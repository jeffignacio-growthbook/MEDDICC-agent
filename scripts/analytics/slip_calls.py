#!/usr/bin/env python3
"""
Why do committed deals slip? — analysis 4: what do the calls say? (qualitative)

Lower priority than 1-3 and it does not scale — but it is what turns a pattern
into a diagnosis: a legitimate slip (budget cycle, champion departure) separates
from rep optimism only in the conversation, not the numbers.

Reuses the slip cohort from slip_diagnosis (no second cohort definition). For a
SAMPLE of committed-and-slipped deals it reads the already-stored call summaries
(calls.summary, joined by deal_id — no live Fireflies dependency) and extracts,
per deal, three signals via the shared LLM client:
  * was a mutual action plan discussed?
  * was a specific close process (procurement / legal / security) identified?
  * what reason was given when the date moved?

Qualitative: counts over the sample, reported as "of N sampled", never a rate.
It runs whenever there are slipped deals, flagged below_evidence_bar when the
cohort is under the gate (the min_evidence gate guards inferential rates, not a
sampled signal read); only an empty slipped cohort returns a bare reason.
"""
import os
import sys
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))

from supabase import create_client
from supabase_client import select_all
from slip_diagnosis import build_slip_cohort

SAMPLE_SIZE = 15
MAX_SUMMARY_CHARS = 6000

EXTRACT_SYSTEM = ("You extract three factual signals from B2B sales call "
                  "summaries. Reply with STRICT JSON only, no prose.")


def build_extraction_prompt(company_summaries: str) -> str:
    return f"""From these call summaries for one deal, answer three questions.
Only mark true when the summaries actually show it — do not infer.

Call summaries:
{company_summaries[:MAX_SUMMARY_CHARS]}

Reply with this JSON exactly:
{{
  "mutual_action_plan": true|false,   // a shared, dated close/mutual plan was discussed
  "close_process_identified": true|false,  // procurement, legal, security review, or signature path named
  "date_move_reason": "<short phrase, or 'none' if no date change/reason appears>"
}}"""


def parse_extraction(text: str) -> dict:
    """Tolerant JSON extraction — grab the first {...} block."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {"mutual_action_plan": None, "close_process_identified": None,
                "date_move_reason": None, "parse_error": True}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"mutual_action_plan": None, "close_process_identified": None,
                "date_move_reason": None, "parse_error": True}
    return {
        "mutual_action_plan": bool(d.get("mutual_action_plan")),
        "close_process_identified": bool(d.get("close_process_identified")),
        "date_move_reason": (str(d.get("date_move_reason") or "none").strip()
                             .lower()),
    }


def analyze_slip_calls(sb, llm=None, sample_size: int = SAMPLE_SIZE,
                       cohort=None) -> dict:
    cohort = cohort or build_slip_cohort(sb)
    me = cohort['min_evidence']
    slipped = [m for m in cohort['members'] if m['outcome'] == 'SLIPPED']
    if not slipped:
        return {'n_slipped': 0, 'reason': 'no slipped deals in cohort'}
    # This analysis is QUALITATIVE — a sample read of call summaries, reported as
    # "of N sampled" counts, never a rate. So it runs whenever there are slipped
    # deals, flagged below_evidence_bar when the cohort is under the gate; the
    # min_evidence gate guards inferential rates, not a sampled signal read.
    below_bar = len(slipped) < me

    # Deterministic sample (stable ordering, no RNG).
    slipped = sorted(slipped, key=lambda m: (str(m['deal_id']), m['quarter']))
    sample = slipped[:sample_size]
    sample_ids = {str(m['deal_id']) for m in sample}

    calls = select_all(sb, 'calls',
                       columns='deal_id,call_date,summary')
    summaries_by_deal = {}
    for c in calls:
        did = str(c['deal_id'])
        if did in sample_ids and (c.get('summary') or '').strip():
            summaries_by_deal.setdefault(did, []).append(c)

    if llm is None:
        from llm_client import LLMClient  # scripts/ is on sys.path
        llm = LLMClient.from_config(role="classifier")

    tally = {'mutual_action_plan': 0, 'close_process_identified': 0}
    reasons, per_deal, with_calls = [], [], 0
    for m in sample:
        did = str(m['deal_id'])
        rows = sorted(summaries_by_deal.get(did, []),
                      key=lambda c: str(c.get('call_date') or ''))
        if not rows:
            per_deal.append({'deal_id': did, 'calls': 0})
            continue
        with_calls += 1
        blob = "\n\n---\n\n".join((c.get('summary') or '') for c in rows)
        resp = llm.complete(
            messages=[{"role": "user", "content": build_extraction_prompt(blob)}],
            system=EXTRACT_SYSTEM, max_tokens=200)
        ext = parse_extraction(getattr(resp, 'text', '') or '')
        if ext.get('mutual_action_plan'):
            tally['mutual_action_plan'] += 1
        if ext.get('close_process_identified'):
            tally['close_process_identified'] += 1
        reason = ext.get('date_move_reason')
        if reason and reason != 'none':
            reasons.append(reason)
        per_deal.append({'deal_id': did, 'calls': len(rows), **ext})

    from collections import Counter
    return {
        'n_slipped_cohort': len(slipped),
        'below_evidence_bar': below_bar,
        'sampled': len(sample),
        'sampled_with_calls': with_calls,
        'counts_over_sampled_with_calls': {
            'mutual_action_plan': tally['mutual_action_plan'],
            'close_process_identified': tally['close_process_identified'],
        },
        'date_move_reasons': dict(Counter(reasons)),
        'note': ('Counts over a small deterministic sample of slipped deals, '
                 'from stored call summaries. Qualitative — read as signal, '
                 'not rate. This separates a legitimate slip from rep optimism.'),
        'per_deal': per_deal,
    }


def main():
    sb = create_client(os.environ['SUPABASE_URL'],
                       os.environ['SUPABASE_SERVICE_KEY'])
    r = analyze_slip_calls(sb)
    print("=" * 72)
    print("WHY DO COMMITTED DEALS SLIP? — analysis 4: what the calls say")
    print("=" * 72)
    print(json.dumps(r, indent=2, default=str))


if __name__ == '__main__':
    main()
