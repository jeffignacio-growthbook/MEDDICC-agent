#!/usr/bin/env python3
"""
Extract sales intelligence from internal sales-team calls
(forecast reviews, pipeline discussions, deal strategy,
win/loss debriefs) — the INTENT_SALES_REVIEW profile.

These calls carry real sales intelligence but no prospect
objections, so they are deliberately routed away from the
objection/feature-gap extractors and into three signal
tables instead.

Usage:
  # As a library, from the enrichment ETL:
  from scripts.enrichment.extract_sales_signals import (
      extract_signals)
  extract_signals(sb, client, call_data, company,
                  deal_id, call_id, slug)

  # Standalone, over calls classified as sales_review:
  python scripts/enrichment/extract_sales_signals.py --dry-run
  python scripts/enrichment/extract_sales_signals.py \
    --limit 50 --yes

Unlike the objection/gap extractors, this one deliberately
scans internal calls — including cache files whose company
slug does not resolve to a deal, which is where forecast and
pipeline calls live. Rows whose deal cannot be resolved are
still written; deal_id is nullable here because the signal is
about the conversation, not a single deal record.

Requires migration 022 (deal_risks, competitive_signals,
pipeline_signals tables).
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

JOB_NAME = 'sales_signals'

SALES_SIGNAL_PROMPT = """Read this internal sales team
call and extract sales intelligence signals.

This is a {call_type} call (forecast review, pipeline
discussion, deal strategy, or competitive debrief).

Call summary:
{call_summary}

Extract:

1. deal_risks: deals mentioned as at-risk, stalled, or
   in trouble. For each:
   - company_name
   - risk_description (what the rep said about the risk)
   - rep_name (who raised it, if mentioned)

2. competitive_signals: competitor mentions or competitive
   situations discussed:
   - competitor_name
   - context (what was said)
   - deal_company (which prospect deal, if mentioned)

3. pipeline_signals: pipeline accuracy or forecast notes:
   - signal_type: commit_risk | upside | slip | pull_in
   - company_name (deal being discussed)
   - description

Return JSON:
{{
  "deal_risks": [...],
  "competitive_signals": [...],
  "pipeline_signals": [...]
}}
Empty arrays if nothing found. No prose outside JSON."""

VALID_PIPELINE_SIGNAL_TYPES = {
    "commit_risk", "upside", "slip", "pull_in",
}


def _parse_json_object(text: str) -> dict | None:
    """
    Parse a JSON object from the model response, tolerating a
    markdown fence the model was told not to emit.
    """
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                parsed = json.loads(block)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
    return None


def _stamp(sb, call_id, job, slug, n):
    """Record scan completion in enrichment_scans ledger."""
    sb.table('enrichment_scans').upsert({
        'call_id': call_id,
        'job': job,
        'company_slug': slug,
        'items_found': n,
        'scanned_at': datetime.utcnow().isoformat(),
    }, on_conflict='call_id,job').execute()


def extract_signals(sb, client, call_data: dict, company: str,
                    deal_id, call_id: str, slug: str) -> dict:
    """
    Extract and persist sales signals for one internal call.

    Args:
        sb: supabase client
        client: anthropic.Anthropic() instance
        call_data: dict carrying at least 'summary' (and
                   optionally 'title')
        company: resolved company name for the call
        deal_id: resolved deal id, or None
        call_id: call identifier
        slug: company slug

    Returns:
        {"deal_risks": n, "competitive_signals": n,
         "pipeline_signals": n, "total": n}
    """
    counts = {"deal_risks": 0, "competitive_signals": 0,
              "pipeline_signals": 0, "total": 0}

    summary = call_data.get("summary") or ""
    if len(summary) < 100:
        return counts

    call_type = call_data.get("title") or "internal sales"

    prompt = SALES_SIGNAL_PROMPT.format(
        call_type=call_type[:80],
        call_summary=summary[:4000],
    )

    resp = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1000,
        system="Respond with valid JSON only.",
        messages=[{'role': 'user', 'content': prompt}],
    )

    parsed = _parse_json_object(resp.content[0].text)
    if not parsed:
        print(f"  ✗ {company}: could not parse signal JSON")
        return counts

    now = datetime.utcnow().isoformat()

    for risk in (parsed.get("deal_risks") or []):
        if not isinstance(risk, dict):
            continue
        description = (risk.get("risk_description") or "").strip()
        if not description:
            continue
        sb.table('deal_risks').insert({
            'call_id': call_id,
            'company_name': risk.get("company_name") or company,
            'deal_id': deal_id,
            'risk_description': description,
            'rep_name': risk.get("rep_name"),
            'source_company': company,
            'extracted_at': now,
        }).execute()
        counts["deal_risks"] += 1

    for sig in (parsed.get("competitive_signals") or []):
        if not isinstance(sig, dict):
            continue
        competitor = (sig.get("competitor_name") or "").strip()
        if not competitor:
            continue
        sb.table('competitive_signals').insert({
            'call_id': call_id,
            'competitor_name': competitor,
            'context': sig.get("context"),
            'deal_company': sig.get("deal_company"),
            'deal_id': deal_id,
            'source_company': company,
            'extracted_at': now,
        }).execute()
        counts["competitive_signals"] += 1

    for sig in (parsed.get("pipeline_signals") or []):
        if not isinstance(sig, dict):
            continue
        signal_type = (sig.get("signal_type") or "").strip().lower()
        if signal_type not in VALID_PIPELINE_SIGNAL_TYPES:
            signal_type = "commit_risk"
        description = (sig.get("description") or "").strip()
        if not description:
            continue
        sb.table('pipeline_signals').insert({
            'call_id': call_id,
            'signal_type': signal_type,
            'company_name': sig.get("company_name") or company,
            'deal_id': deal_id,
            'description': description,
            'source_company': company,
            'extracted_at': now,
        }).execute()
        counts["pipeline_signals"] += 1

    counts["total"] = (counts["deal_risks"]
                       + counts["competitive_signals"]
                       + counts["pipeline_signals"])
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50,
                        help='Max calls to scan')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args()

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    ANTHROPIC_KEY = os.getenv('ANTHROPIC_API_KEY')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Supabase credentials not set")
        return

    from supabase import create_client
    from supabase_client import select_all
    from utils import slugify
    from scripts.enrichment.call_intent_classifier import (
        classify_call, ENRICHMENT_PROFILE,
    )

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    scanned_ledger = {r['call_id'] for r in select_all(
        sb, 'enrichment_scans', columns='call_id,job',
        filters=[('eq', 'job', JOB_NAME)])}

    deals = select_all(sb, 'deals', columns='deal_id,company_name')
    by_slug = {}
    for d in deals:
        by_slug.setdefault(slugify(d.get('company_name') or ''),
                           []).append(d)

    cache_dir = REPO_ROOT / 'memory' / 'calls'
    if not cache_dir.exists():
        print(f"⚠️  Cache directory not found: {cache_dir}")
        return

    # Unlike the objection/gap extractors this scans ALL cache
    # files — internal calls are the point of this job.
    to_process = []
    for cache_file in sorted(cache_dir.glob('*.json')):
        try:
            data = json.load(open(cache_file))
        except Exception:
            continue

        cache_company = (data.get('company')
                         or cache_file.stem.replace('-', ' ').title())
        slug = slugify(cache_company)
        cands = by_slug.get(slug, [])
        deal_id = cands[0]['deal_id'] if len(cands) == 1 else None

        for call in data.get('calls', []):
            call_id = str(call.get('id') or '')
            if not call_id or call_id in scanned_ledger:
                continue

            summary = (call.get('formatted_summary')
                       or call.get('summary', ''))
            classification = classify_call({
                'title':        call.get('title', ''),
                'summary':      summary,
                'participants': call.get('participants', []),
                'company':      cache_company,
                'tags':         call.get('tags', []),
            }, client=None, use_llm=False)

            profile = ENRICHMENT_PROFILE[classification["intent"]]
            if not profile["extract_sales_signals"]:
                continue

            to_process.append({
                'call_id': call_id,
                'slug': slug or 'internal',
                'company': cache_company,
                'title': call.get('title', ''),
                'summary': summary,
                'deal_id': deal_id,
                'reason': classification['reason'],
            })
            if len(to_process) >= args.limit:
                break
        if len(to_process) >= args.limit:
            break

    if not to_process:
        print("No unscanned sales_review calls found.")
        return

    est_cost = len(to_process) * 0.004
    print(f"{len(to_process)} sales_review calls to scan, "
          f"estimated cost: ${est_cost:.2f}")

    if args.dry_run:
        print("\n--dry-run: First 15 calls:")
        for i, c in enumerate(to_process[:15], 1):
            print(f"  {i:2d}. {c['company'][:25]:25s} | "
                  f"{c['title'][:35]:35s} | {c['reason']}")
        return

    if len(to_process) >= 20 and not args.yes:
        if input("Proceed? (y/N): ").lower() != 'y':
            print("Aborted.")
            return

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    scanned, totals = 0, {"deal_risks": 0,
                          "competitive_signals": 0,
                          "pipeline_signals": 0}
    for c in to_process:
        try:
            counts = extract_signals(
                sb, client, c, c['company'], c['deal_id'],
                c['call_id'], c['slug'])
            for k in totals:
                totals[k] += counts[k]
            _stamp(sb, c['call_id'], JOB_NAME, c['slug'],
                   counts["total"])
            scanned += 1
            print(f"  ✓ {c['company']}: {counts['total']} signal(s) "
                  f"({counts['deal_risks']} risk, "
                  f"{counts['competitive_signals']} comp, "
                  f"{counts['pipeline_signals']} pipeline)")
        except Exception as e:
            print(f"  ✗ {c['company']} ({c['call_id'][:20]}): {e}")

    print(f"\n✓ Scanned {scanned} calls")
    print(f"  Deal risks: {totals['deal_risks']}")
    print(f"  Competitive signals: {totals['competitive_signals']}")
    print(f"  Pipeline signals: {totals['pipeline_signals']}")


if __name__ == '__main__':
    main()
