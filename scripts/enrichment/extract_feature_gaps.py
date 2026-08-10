#!/usr/bin/env python3
"""
Extract structured feature gaps from call transcripts already
in memory/calls/*.json. Runs against calls not yet scanned
(feature_gaps_scanned_at IS NULL in Supabase).

Usage:
  python scripts/enrichment/extract_feature_gaps.py
  python scripts/enrichment/extract_feature_gaps.py --dry-run
  python scripts/enrichment/extract_feature_gaps.py --limit 50 --yes
"""

import os
import json
import argparse
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent.parent.parent

PROMPT = """Read this sales call summary and identify any moments
where the prospect asked for a capability GrowthBook doesn't
have, compared unfavorably to a competitor's feature, or
described a workaround they'd need.

Call summary:
{call_summary}

For each gap found, return an object with:
  feature_description: what they asked for or found missing,
                        in plain language (not a quote)
  category: one of reporting, integration,
            permissions_security, pricing_packaging,
            platform_capability, other
  competitor_mentioned: name if they cited a competitor
                        having this, else null
  severity: blocker (they said this could stop the deal),
            nice_to_have, or workaround_exists (rep offered
            a workaround and they accepted it)

Return a JSON array. Empty array if none. No prose outside
the JSON."""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=50)
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
    import sys
    sys.path.insert(0, str(REPO_ROOT / 'scripts'))
    from supabase_client import select_all

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get unscanned calls
    unscanned = select_all(
        sb, 'calls',
        columns='call_id,company_name,company_slug,deal_id,stage_when_captured',
        filters=[('is_', 'feature_gaps_scanned_at', 'null')]
    )
    to_process = unscanned[:args.limit]

    if not to_process:
        print("No unscanned calls found.")
        return

    est_cost = len(to_process) * 0.02  # Haiku, small prompt
    print(f"{len(to_process)} calls to scan, "
          f"estimated cost: ${est_cost:.2f}")

    if len(to_process) >= 20 and not args.yes and not args.dry_run:
        if input("Proceed? (y/N): ").lower() != 'y':
            print("Aborted.")
            return

    if args.dry_run:
        for c in to_process[:10]:
            print(f"  Would scan: {c.get('company_name')} / "
                  f"call {c.get('call_id')}")
        return

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    from token_tracker import TokenTracker
    tracker = TokenTracker(REPO_ROOT / 'memory')

    written, scanned = 0, 0
    for call in to_process:
        call_id = call['call_id']
        company = call.get('company_name', '')
        deal_id = call.get('deal_id')
        slug = call.get('company_slug', company.lower().replace(' ', '-'))
        cache_path = REPO_ROOT / 'memory' / 'calls' / f'{slug}.json'
        summary = ''

        if cache_path.exists():
            cache = json.load(open(cache_path))
            for c in cache.get('calls', []):
                if c.get('id') == call_id:
                    summary = c.get('formatted_summary') or c.get('summary', '')
                    break

        if not summary or len(summary) < 100:
            # stamp scanned anyway — nothing to extract, but
            # don't rescan a call with no usable content
            sb.table('calls').update(
                {'feature_gaps_scanned_at': datetime.utcnow().isoformat()}
            ).eq('call_id', call_id).execute()
            scanned += 1
            continue

        prompt = PROMPT.format(call_summary=summary[:4000])

        try:
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=500,
                messages=[{'role': 'user', 'content': prompt}]
            )
            tracker.record(resp, 'claude-haiku-4-5-20251001',
                           'feature_gap_extraction', company)

            # Parse JSON response
            feature_gaps = json.loads(resp.content[0].text.strip())

            for gap in feature_gaps:
                sb.table('feature_gaps').insert({
                    'deal_id': deal_id,
                    'company_name': company,
                    'call_id': call_id,
                    'feature_description': gap.get('feature_description', ''),
                    'category': gap.get('category', 'other'),
                    'competitor_mentioned': gap.get('competitor_mentioned'),
                    'stage_when_raised': call.get('stage_when_captured'),
                    'severity': gap.get('severity', 'nice_to_have'),
                    'extracted_at': datetime.utcnow().isoformat(),
                }).execute()
                written += 1

            sb.table('calls').update(
                {'feature_gaps_scanned_at': datetime.utcnow().isoformat()}
            ).eq('call_id', call_id).execute()
            scanned += 1
            print(f"  ✓ {company}: {len(feature_gaps)} feature gap(s)")

        except Exception as e:
            print(f"  ✗ {company} ({call_id}): {e}")

    summary_stats = tracker.save()
    tracker.print_summary(summary_stats, scanned)
    print(f"\n✓ Scanned {scanned} calls, {written} feature gaps written")


if __name__ == '__main__':
    main()
