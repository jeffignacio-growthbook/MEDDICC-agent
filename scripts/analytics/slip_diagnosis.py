#!/usr/bin/env python3
"""
Why do committed deals slip? — diagnosis on already-correct data.

Follows the commit-outcome-by-week finding: win rate is flat ~50% across commit
weeks and the misses are SLIPS, not losses (lost shrinks, slipped grows). Plain
reading: good deal judgment, poor date discipline. This asks WHY, four ways.

Everything is point-in-time and reuses the shared helpers — no second
implementation of scoping, outcome classification, or field reconstruction:
  * cohort membership: deals tagged COMMIT in a complete quarter (the same
    unscoped COMMIT population the finding came from), keyed to the EARLIEST
    week they were committed (the "commit moment").
  * outcome: analytics.forecast_analyses._classify_deal_outcome (terminal state
    from `deals`; won requires close inside the committed quarter; else slipped).
  * point-in-time stage / close_date: from the deal's weekly deals_snapshot rows.
  * MEDDICC as of the commit date: the most recent `analyses` row with
    analyzed_at <= the commit-week snapshot date (the backward-looking rule used
    everywhere else).

Counts only. Gates unchanged: a cohort below min_evidence_count returns null
with a reason — never pooled or tuned to force a number.

Analyses 1-3 here are data-ready; analysis 4 (calls) lives in slip_calls.py.
"""
import os
import sys
from pathlib import Path
from datetime import date
from collections import defaultdict, Counter

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))

from supabase import create_client
from supabase_client import select_all
from analytics.forecast_analyses import (
    _get_complete_quarters, _quarter_window_iso, _classify_deal_outcome,
    _load_config)
from analytics.point_in_time import load_scope_config

COMPONENTS = [
    ('metrics_score', 'Metrics'),
    ('economic_buyer_score', 'Economic Buyer'),
    ('decision_criteria_score', 'Decision Criteria'),
    ('decision_process_score', 'Decision Process'),
    ('pain_score', 'Identified Pain'),
    ('champion_score', 'Champion'),
    ('competition_score', 'Competition'),
]


def _pdate(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _stage_name(stage_cfg, sid):
    if sid is None:
        return '(none)'
    return (stage_cfg.get(str(sid)) or {}).get('name', str(sid))


def _stage_order(stage_cfg, sid):
    if sid is None:
        return None
    return (stage_cfg.get(str(sid)) or {}).get('order')


def build_slip_cohort(sb):
    """Committed deal-quarters, classified won/slipped/lost, with each one's
    commit moment (earliest COMMIT week) and its weekly point-in-time trail from
    commit week to quarter end."""
    config = _load_config()
    min_evidence = config.get('min_evidence_count', 30)
    _, stage_cfg = load_scope_config()

    quarters = _get_complete_quarters(sb)
    deals_rows = select_all(sb, 'deals', columns='deal_id,stage,close_date')
    deals_by_id = {str(d['deal_id']): d for d in deals_rows}

    snaps = select_all(
        sb, 'deals_snapshot',
        columns='deal_id,snapshot_date,fiscal_quarter,week_of_quarter,'
                'stage_id,close_date,forecast_category',
        filters=[('eq', 'snapshot_source', 'backfilled')])

    # index: (quarter, deal_id) -> weekly rows sorted by week_of_quarter
    by_qd = defaultdict(list)
    for r in snaps:
        by_qd[(r.get('fiscal_quarter'), str(r['deal_id']))].append(r)

    members = []
    for quarter in quarters:
        q_start, q_end = _quarter_window_iso(sb, quarter)
        for (q, deal_id), rows in by_qd.items():
            if q != quarter:
                continue
            rows = sorted(rows, key=lambda r: (r.get('week_of_quarter') or 0))
            commit_rows = [r for r in rows
                           if r.get('forecast_category') == 'COMMIT']
            if not commit_rows:
                continue
            commit = commit_rows[0]           # earliest committed week
            cwk = commit.get('week_of_quarter')
            trail = [r for r in rows if (r.get('week_of_quarter') or 0) >= (cwk or 0)]
            outcome = _classify_deal_outcome(deal_id, q_start, q_end, deals_by_id)
            members.append({
                'deal_id': deal_id, 'quarter': quarter,
                'q_start': q_start, 'q_end': q_end,
                'commit_week': cwk,
                'commit_date': commit.get('snapshot_date'),
                'commit_stage': commit.get('stage_id'),
                'commit_close': commit.get('close_date'),
                'outcome': outcome,
                'trail': trail,
            })
    return {'members': members, 'stage_cfg': stage_cfg,
            'min_evidence': min_evidence, 'quarters': quarters}


# ── Analysis 1 — do close dates move, or sit past? ─────────────────────

def analyze_close_date_movement(cohort):
    # DESCRIPTIVE split (counts, not a rate): report it whenever there is any
    # slipped deal, flagging when n is below the evidence bar so the reader
    # does not over-read a small sample. The min_evidence gate guards inferential
    # RATES (analysis 3), not a descriptive tally of what happened to N deals.
    members = [m for m in cohort['members'] if m['outcome'] == 'SLIPPED']
    me = cohort['min_evidence']
    n = len(members)
    result = {'n_slipped': n, 'below_evidence_bar': n < me}
    if n == 0:
        result['reason'] = 'no slipped deals in cohort'
        return result
    if n < me:
        result['note'] = (f'{n} slipped < min_evidence {me}: descriptive counts '
                          f'below the evidence bar — read as signal, not a rate')

    repeatedly_pushed = never_moved_date_passed = committed_past_quarter = 0
    days_past = []
    for m in members:
        trail = m['trail']
        closes = [r.get('close_date') for r in trail]
        original = closes[0] if closes else None
        changes = 0
        prev = original
        for c in closes[1:]:
            if c != prev:
                changes += 1
            prev = c
        q_end = _pdate(m['q_end'])
        oc = _pdate(original)
        if oc and q_end:
            days_past.append((q_end - oc).days)
        if changes >= 1:
            repeatedly_pushed += 1        # actively re-forecast, still wrong
        elif oc and q_end and oc <= q_end:
            never_moved_date_passed += 1  # field drifted; date just lapsed
        else:
            committed_past_quarter += 1   # committed with a date already beyond Q

    dp = sorted(days_past)

    def _median(x):
        return x[len(x) // 2] if x else None
    result.update({
        'repeatedly_pushed': repeatedly_pushed,
        'never_moved_date_passed': never_moved_date_passed,
        'committed_past_quarter': committed_past_quarter,
        'days_past_original_close': {
            'n': len(dp),
            'min': dp[0] if dp else None,
            'median': _median(dp),
            'max': dp[-1] if dp else None,
            'buckets': {
                '<=0': sum(1 for d in dp if d <= 0),
                '1-30': sum(1 for d in dp if 1 <= d <= 30),
                '31-60': sum(1 for d in dp if 31 <= d <= 60),
                '60+': sum(1 for d in dp if d > 60),
            },
        },
    })
    return result


# ── Analysis 2 — where do slipped deals stall? ─────────────────────────

def analyze_stall_stage(cohort):
    stage_cfg = cohort['stage_cfg']
    me = cohort['min_evidence']
    groups = {'WON': [m for m in cohort['members'] if m['outcome'] == 'WON'],
              'SLIPPED': [m for m in cohort['members'] if m['outcome'] == 'SLIPPED']}
    out = {'min_evidence': me}
    for label, members in groups.items():
        n = len(members)
        dist = Counter(_stage_name(stage_cfg, m['commit_stage']) for m in members)
        entry = {'n': n, 'commit_stage_distribution': dict(dist)}
        if n < me:
            entry['rate_note'] = f'{n} < min_evidence {me}: distribution shown, no rates'
        out[label] = entry

    # For slipped non-advancers, how long stuck in the end stage. Descriptive
    # (counts + median weeks) — shown whenever there is any slipped deal, with a
    # below-bar flag; not a rate, so the gate does not null it.
    slipped = groups['SLIPPED']
    stalled, stuck_weeks = [], []
    for m in slipped:
        trail = m['trail']
        if not trail:
            continue
        end = trail[-1]
        co = _stage_order(stage_cfg, m['commit_stage'])
        eo = _stage_order(stage_cfg, end.get('stage_id'))
        advanced = (co is not None and eo is not None and eo > co)
        if not advanced:
            w = 0
            for r in reversed(trail):
                if r.get('stage_id') == end.get('stage_id'):
                    w += 1
                else:
                    break
            stuck_weeks.append(w)
            stalled.append(_stage_name(stage_cfg, end.get('stage_id')))
    out['slipped_non_advancers'] = {
        'count': len(stuck_weeks),
        'below_evidence_bar': len(slipped) < me,
        'end_stage_distribution': dict(Counter(stalled)),
        'weeks_stuck_median': (sorted(stuck_weeks)[len(stuck_weeks) // 2]
                               if stuck_weeks else None),
    }
    return out


# ── Analysis 3 — does MEDDICC predict the slip? (highest value) ────────

def analyze_meddicc(cohort, sb):
    me = cohort['min_evidence']
    cols = ('deal_id,analyzed_at,overall_score,' +
            ','.join(c for c, _ in COMPONENTS))
    rows = select_all(sb, 'analyses', columns=cols)
    by_deal = defaultdict(list)
    for r in rows:
        by_deal[str(r['deal_id'])].append(r)
    for d in by_deal:
        by_deal[d].sort(key=lambda r: str(r.get('analyzed_at') or ''))

    def score_at_commit(deal_id, commit_date):
        # most recent analysis at or before the commit-week snapshot date
        best = None
        for r in by_deal.get(str(deal_id), []):
            if str(r.get('analyzed_at') or '')[:10] <= str(commit_date)[:10]:
                best = r
            else:
                break
        return best

    groups = {'WON': defaultdict(list), 'SLIPPED': defaultdict(list)}
    matched = {'WON': 0, 'SLIPPED': 0}
    unmatched = {'WON': 0, 'SLIPPED': 0}
    for m in cohort['members']:
        if m['outcome'] not in groups:
            continue
        a = score_at_commit(m['deal_id'], m['commit_date'])
        if not a:
            unmatched[m['outcome']] += 1
            continue
        matched[m['outcome']] += 1
        for col, _ in COMPONENTS + [('overall_score', 'Overall')]:
            v = a.get(col)
            if v is not None:
                groups[m['outcome']][col].append(float(v))

    # Diagnostic: distinguish "MEDDICC doesn't separate" from "no MEDDICC score
    # existed as of the commit date" (a data-availability gap, not a predictive
    # one). matched=0 with a large unmatched count is the latter — surface why.
    ats = sorted(str(r.get('analyzed_at'))[:10] for r in rows if r.get('analyzed_at'))
    cds = sorted(str(m['commit_date'])[:10] for m in cohort['members']
                 if m.get('commit_date') and m['outcome'] in ('WON', 'SLIPPED'))
    cohort_ids = {str(m['deal_id']) for m in cohort['members']
                  if m['outcome'] in ('WON', 'SLIPPED')}
    with_any_analysis = sum(1 for did in cohort_ids if by_deal.get(did))
    diagnostic = {
        'analyses_rows_total': len(rows),
        'analyzed_at_range': [ats[0] if ats else None, ats[-1] if ats else None],
        'commit_date_range': [cds[0] if cds else None, cds[-1] if cds else None],
        'cohort_deals_with_any_analysis_date_agnostic': with_any_analysis,
        'cohort_deals_total': len(cohort_ids),
        'interpretation': (
            'matched=0 with deals present but no analysis AT OR BEFORE commit '
            'means MEDDICC scoring postdates these historical commit weeks — a '
            'data-availability gap, not evidence that MEDDICC fails to predict '
            'timing. It becomes answerable as scoring history accrues.'),
    }
    result = {'matched': matched, 'unmatched_no_analysis': unmatched,
              'min_evidence': me, 'diagnostic': diagnostic}
    if matched['WON'] < me or matched['SLIPPED'] < me:
        result['reason'] = (f"won={matched['WON']}, slipped={matched['SLIPPED']}; "
                            f"need >= {me} each to compare — null")
        return result

    def _mean(x):
        return round(sum(x) / len(x), 2) if x else None
    per_component = {}
    for col, name in COMPONENTS + [('overall_score', 'Overall')]:
        w = groups['WON'][col]
        s = groups['SLIPPED'][col]
        wm, sm = _mean(w), _mean(s)
        per_component[name] = {
            'won_mean': wm, 'slipped_mean': sm,
            'gap_won_minus_slipped': (round(wm - sm, 2)
                                      if wm is not None and sm is not None else None),
            'won_n': len(w), 'slipped_n': len(s),
        }
    # rank the seven COMPONENTS by how cleanly they separate the groups
    # (largest gap). Overall is derivative — kept in per_component, excluded here.
    component_names = {name for _, name in COMPONENTS}
    ranked = sorted(
        (p for p in per_component.items()
         if p[0] in component_names and p[1]['gap_won_minus_slipped'] is not None),
        key=lambda kv: -kv[1]['gap_won_minus_slipped'])
    result['per_component'] = per_component
    result['largest_gaps'] = [(name, d['gap_won_minus_slipped']) for name, d in ranked[:3]]
    return result


def run(sb):
    cohort = build_slip_cohort(sb)
    outcomes = Counter(m['outcome'] for m in cohort['members'])
    return {
        'cohort_summary': {
            'quarters': cohort['quarters'],
            'committed_deal_quarters': len(cohort['members']),
            'by_outcome': dict(outcomes),
            'min_evidence_count': cohort['min_evidence'],
        },
        'analysis_1_close_date_movement': analyze_close_date_movement(cohort),
        'analysis_2_stall_stage': analyze_stall_stage(cohort),
        'analysis_3_meddicc_predicts_slip': analyze_meddicc(cohort, sb),
    }


def main():
    sb = create_client(os.environ['SUPABASE_URL'],
                       os.environ['SUPABASE_SERVICE_KEY'])
    import json
    r = run(sb)
    print("=" * 72)
    print("WHY DO COMMITTED DEALS SLIP? — analyses 1-3 (counts only)")
    print("=" * 72)
    cs = r['cohort_summary']
    print(f"\nCohort: {cs['committed_deal_quarters']} committed deal-quarters "
          f"across {len(cs['quarters'])} quarters  {cs['by_outcome']}  "
          f"(min_evidence={cs['min_evidence_count']})")

    print("\n── 1. Close dates: move or sit past? ──")
    print(json.dumps(r['analysis_1_close_date_movement'], indent=2, default=str))
    print("\n── 2. Where do slipped deals stall? ──")
    print(json.dumps(r['analysis_2_stall_stage'], indent=2, default=str))
    print("\n── 3. Does MEDDICC predict the slip? ──")
    print(json.dumps(r['analysis_3_meddicc_predicts_slip'], indent=2, default=str))


if __name__ == '__main__':
    main()
