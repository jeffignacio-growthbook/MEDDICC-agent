#!/usr/bin/env python3
"""
Forecast Analysis Handlers — Phase 3
Kellogg-method commit calibration and week-3 conversion analyses.

IMPORTANT: These are read-only analyses. No proposals, no config mutations.
Build as independently useful handlers first. Proposal writers (Phase 4) will
call these same functions — never duplicate the math.

Data requirements:
- Complete quarters: 13 weeks of snapshot data
- Populated forecast_category field
- Fiscal quarter and week_of_quarter fields

Coverage caveats:
- Currently 2 complete quarters (FY2027 Q1, Q2) at 85% coverage
- Limited historical depth — analyses return null on insufficient data
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client


def _load_config() -> Dict:
    """Load forecast analysis configuration."""
    config_path = Path(__file__).parent.parent.parent / 'config' / 'client.yaml'
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path) as f:
        full_config = yaml.safe_load(f)

    # Merge forecast_analysis and proposal_engine configs
    forecast_config = full_config.get('forecast_analysis', {
        'trailing_quarters_window': 9,
        'anchor_week': None,
        'claimed_commit_accuracy': 0.90,
        'basis': 'count',
        'segmentation_keys': ['motion']
    })

    # Add min_evidence_count from proposal_engine
    proposal_config = full_config.get('proposal_engine', {})
    forecast_config['min_evidence_count'] = proposal_config.get('min_evidence_count', 30)

    return forecast_config


def _get_complete_quarters(sb) -> List[str]:
    """
    Return list of fiscal quarters with 13 complete weeks of snapshot data.

    A quarter is complete if it has snapshots for all weeks 1-13.
    """
    # MUST paginate: deals_snapshot has 24k+ rows and PostgREST silently caps
    # an unpaginated .execute() at 1,000. The old direct call saw only the
    # first 1,000 rows, never observed all 13 weeks of any quarter, and so
    # reported "no complete quarters" — dead-ending every analysis. select_all
    # pages through the whole table.
    from supabase_client import select_all
    rows = select_all(
        sb, 'deals_snapshot',
        columns='fiscal_quarter,week_of_quarter',
        filters=[('__not_null__', 'fiscal_quarter')])

    # Group by quarter, collect unique weeks
    quarters = defaultdict(set)
    for row in rows:
        quarter = row.get('fiscal_quarter')
        week = row.get('week_of_quarter')
        if quarter and week:
            quarters[quarter].add(week)

    # Filter to complete quarters (13 weeks)
    complete = sorted([
        q for q, weeks in quarters.items()
        if len(weeks) == 13
    ])

    return complete


def _classify_deal_outcome(
    deal_id: str,
    q_start_iso: str,
    q_end_iso: str,
    deals_by_id: Dict[str, Dict],
) -> Optional[str]:
    """
    Classify a deal that was COMMIT at the anchor week: Won / Slipped / Lost.

    Returns:
        'WON' — terminally won AND close_date within the committed quarter
        'LOST' — terminally lost AND closed on/before quarter end
        'SLIPPED' — still open past quarter end, or a close_date pushed beyond
                    it (this includes a won/lost deal whose close_date falls
                    OUTSIDE the committed quarter — it did not resolve in-quarter)
        None — deal not found in the deals table

    OUTCOME-READ (defect 5): the outcome comes from the TERMINAL state in the
    current `deals` table (is_won / is_lost + close_date), NOT the last snapshot
    row. The Method-2 backfilled quarters hold only OPEN snapshot rows (terminal
    stages are excluded), so a deal that won would read 'active' in its last
    in-quarter snapshot and be misclassified SLIPPED — the same open-rows
    artifact the week-3 numerator fix addressed, which would fabricate a ~0%
    hit rate with everything slipped. The COMMIT-at-anchor cohort IS point-in-
    time (from the snapshot); the outcome has no point-in-time equivalent.

    CRITICAL: Slipped vs Lost must be separate. A deal open past quarter end
    with a pushed close date is SLIPPED, never LOST. This is the exact error
    Kellogg critiques.
    """
    from field_semantics import is_won, is_lost
    d = deals_by_id.get(str(deal_id))
    if not d:
        return None
    stage = d.get('stage')
    close = str(d.get('close_date'))[:10] if d.get('close_date') else None
    try:
        won = is_won(str(stage)) if stage else False
        lost = is_lost(str(stage)) if stage else False
    except Exception:
        won = lost = False
    in_quarter = bool(close and q_start_iso <= close <= q_end_iso)
    if won and in_quarter:
        return 'WON'
    if lost and close and close <= q_end_iso:
        return 'LOST'
    # open, or resolved outside the committed quarter → slipped
    return 'SLIPPED'


def _quarter_window_iso(sb, quarter: str) -> Tuple[Optional[str], Optional[str]]:
    """(q_start_iso, q_end_iso) for a fiscal-quarter label, from the fiscal
    calendar applied to any snapshot date in the quarter."""
    from utils import get_fiscal_quarter
    from datetime import date as _date
    r = sb.table('deals_snapshot').select('snapshot_date').eq(
        'fiscal_quarter', quarter).limit(1).execute()
    if not r.data:
        return None, None
    d = _date.fromisoformat(r.data[0]['snapshot_date'])
    q_start, q_end, _ = get_fiscal_quarter(d)
    return q_start.isoformat(), q_end.isoformat()


def _in_quarter_won_by_pipeline(sb, q_start_iso: str, q_end_iso: str) -> Dict[str, int]:
    """
    Per-pipeline count of deals that TRANSITIONED to won during the quarter —
    i.e. terminally won (deals.is_won(stage)) with a close_date inside the
    quarter window (defect 1).

    Why terminal outcome, not a snapshot read: the Method-2 backfilled quarters
    (the complete ones the analysis reads) contain ONLY open rows — get_deal_status
    marks 'won' only for won stages, which the open-row reconstruction excludes.
    So deals_snapshot has zero won rows in those quarters (verified: 0 per
    quarter), and an in-quarter win is only observable as a terminal won stage
    with an in-quarter close_date. Counting close-date-in-quarter counts the
    transition INTO won during the quarter, never cumulative won-as-of-a-date
    (the bug: every deal ever won appeared in every later quarter).
    """
    from supabase_client import select_all
    from field_semantics import is_won
    # OUTCOME-READ (defect 5): this reads `stage` from the current `deals` table
    # to determine the TERMINAL WON OUTCOME (is_won) and attribute it to a
    # pipeline — an outcome/event, NOT a point-in-time stage exclusion. The
    # backfilled complete quarters hold zero won rows in deals_snapshot, so a
    # won transition has no point-in-time snapshot equivalent; close_date bounds
    # it to the quarter. Stage EXCLUSIONS (the denominator scope) read the
    # snapshot's point-in-time stage_id, never this table.
    deals = select_all(sb, 'deals',
                       columns='deal_id,stage,close_date,pipeline_id')
    by_pipe: Dict[str, int] = defaultdict(int)
    for d in deals:
        stage, close_date = d.get('stage'), d.get('close_date')
        if not stage or not close_date:
            continue
        try:
            if not is_won(str(stage)):
                continue
        except Exception:
            continue
        if q_start_iso <= str(close_date)[:10] <= q_end_iso:
            by_pipe[str(d.get('pipeline_id'))] += 1
    return dict(by_pipe)


def query_week3_conversion(
    sb=None,
    trailing_quarters: Optional[int] = None
) -> Dict:
    """
    Calculate week-3 pipeline conversion rate (Kellogg's method).

    Formula:
        week-3 conversion rate = new ARR closed in quarter
                                / week-3 starting pipeline snapshot

    Args:
        sb: Supabase client (if None, creates one)
        trailing_quarters: Number of trailing quarters (default from config)

    Returns:
        {
            'per_quarter': {quarter: {'rate': float, 'closed': int, 'week3_pipeline': int}},
            'trailing_average': float,
            'implied_coverage_target': float,  # 1 / trailing_average
            'current_quarter_coverage': float,
            'basis': 'count',
            'quarters_analyzed': int,
            'coverage_note': str,  # Caveat about limited history
            'error': str  # If insufficient data
        }

    Note: Returns null fields on insufficient data, never fabricates.
    """
    if sb is None:
        sb = create_client(
            os.environ['SUPABASE_URL'],
            os.environ['SUPABASE_SERVICE_KEY']
        )

    config = _load_config()
    if trailing_quarters is None:
        trailing_quarters = config.get('trailing_quarters_window', 9)

    # Get complete quarters
    complete_quarters = _get_complete_quarters(sb)

    if not complete_quarters:
        return {
            'error': 'No complete quarters available',
            'quarters_analyzed': 0,
            'coverage_note': 'Insufficient historical data — forecast_category backfill incomplete'
        }

    # Limit to trailing window
    complete_quarters = complete_quarters[-trailing_quarters:]

    if len(complete_quarters) < 2:
        return {
            'error': f'Insufficient quarters: {len(complete_quarters)} found, need 2+ for meaningful analysis',
            'quarters_analyzed': len(complete_quarters),
            'coverage_note': f'Only {len(complete_quarters)} complete quarters available (FY2027 Q1, Q2 at 85% coverage)'
        }

    per_quarter = {}
    min_evidence = config.get('min_evidence_count', 30)

    # Shared scope (defect 2): numerator and denominator draw from the SAME
    # pipeline population, and conversion is computed PER PIPELINE (new business
    # and renewal are different motions — pooling describes neither). Sourced
    # from the shared rule, never reimplemented.
    from analytics.point_in_time import (
        load_scope_config, is_deal_in_analytics_scope)
    from supabase_client import select_all
    excl_pipelines, stage_cfg = load_scope_config()

    def _qualified_in_own_pipeline(stage_id, pipeline_id):
        # The shared stage rule (qualified order, not an excluded stage),
        # with the pooled pipeline-exclusion NEUTRALISED (empty set) so each
        # pipeline is scored on its own stages. A null stage is not qualified
        # and so is not in a starting-pipeline denominator.
        if stage_id is None or not str(stage_id).strip():
            return False
        return is_deal_in_analytics_scope(
            str(stage_id), pipeline_id, set(), stage_cfg)

    for quarter in complete_quarters:
        # Week-3 snapshot. DENOMINATOR (defect 3): deals open (the snapshot is
        # already terminal-stage-excluded) AND qualified in analytics scope at
        # the week-3 snapshot. NO close-date filter — the whole qualified open
        # pipeline competes for the quarter.
        week3_rows = select_all(
            sb, 'deals_snapshot',
            columns='deal_id,stage_id,pipeline_id,deal_value',
            filters=[('eq', 'fiscal_quarter', quarter),
                     ('eq', 'week_of_quarter', 3)])

        denom_by_pipeline = defaultdict(int)
        for r in week3_rows:
            if _qualified_in_own_pipeline(r.get('stage_id'), r.get('pipeline_id')):
                denom_by_pipeline[str(r.get('pipeline_id'))] += 1

        # NUMERATOR (defect 1): in-quarter terminal wins, per pipeline.
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        won_by_pipeline = _in_quarter_won_by_pipeline(sb, q_start_iso, q_end_iso)

        # Per-pipeline conversion. min_evidence gate applied PER PIPELINE:
        # a pipeline whose scoped week-3 denominator is below the threshold
        # returns null with a reason (gate unchanged, applied at the right
        # granularity for a per-pipeline number).
        pipelines = {}
        for pid in sorted(set(denom_by_pipeline) | set(won_by_pipeline)):
            denom = denom_by_pipeline.get(pid, 0)
            won = won_by_pipeline.get(pid, 0)
            if denom < min_evidence:
                pipelines[pid] = {
                    'rate_count': None,
                    'closed_won_count': won,
                    'week3_scoped_denominator': denom,
                    'reason': f'denominator {denom} < min_evidence {min_evidence}',
                }
            else:
                pipelines[pid] = {
                    'rate_count': won / denom,
                    'closed_won_count': won,
                    'week3_scoped_denominator': denom,
                }

        per_quarter[quarter] = {
            'by_pipeline': pipelines,
            'quarter_window': [q_start_iso, q_end_iso],
        }

    # Trailing average per pipeline (each motion has its own conversion).
    basis = config.get('basis', 'count')
    rate_key = f'rate_{basis}'
    trailing_by_pipeline = {}
    all_pids = sorted({pid for q in per_quarter.values()
                       for pid in q['by_pipeline']})
    for pid in all_pids:
        rates = [q['by_pipeline'][pid][rate_key]
                 for q in per_quarter.values()
                 if pid in q['by_pipeline']
                 and q['by_pipeline'][pid].get(rate_key) is not None]
        avg = sum(rates) / len(rates) if rates else None
        trailing_by_pipeline[pid] = {
            'trailing_average': avg,
            'implied_coverage_target': (1 / avg) if avg and avg > 0 else None,
            'quarters_with_rate': len(rates),
        }

    return {
        'per_quarter': per_quarter,
        'trailing_by_pipeline': trailing_by_pipeline,
        'basis': basis,
        'quarters_analyzed': len(complete_quarters),
        'scope': {
            'source': 'point_in_time.is_deal_in_analytics_scope / load_scope_config',
            'per_pipeline': True,
            'excluded_stages': 'Meeting Set, Disqualified, Closed Won, Closed Lost',
            'close_date_filter': 'none (whole qualified open pipeline)',
            'pooled_excluded_pipelines_in_default_view': sorted(excl_pipelines),
        },
        'coverage_note': f'{len(complete_quarters)} complete quarters available (85% category coverage)',
        'complete_quarters': complete_quarters,
    }


def query_commit_outcome_by_week(sb=None) -> Dict:
    """
    Of deals tagged COMMIT at each week_of_quarter, what ACTUALLY happened to
    them — Won / Lost / Slipped from TERMINAL outcome, not tag survival.

    Replaces the former "category churn" retention metric, which measured
    whether a COMMIT tag was STILL present at week 13. That was wrong: a deal
    tagged COMMIT that CLOSES WON leaves the open backfilled snapshot (terminal
    stages are excluded), so under retention it read as the tag "failing to
    survive" — penalising the exact outcome it should reward, and penalising
    early weeks hardest (a week-1 commit has twelve weeks to win and vanish).
    The monotonic 38%→100% climb and the tautological 100% at week 13 were
    artifacts of that.

    Correct measure: cohort membership is point-in-time (deals tagged COMMIT at
    (quarter, week) from deals_snapshot — already right); the OUTCOME comes from
    _classify_deal_outcome against the `deals` terminal state (the same source
    commit calibration uses — no second classifier). Won requires the close_date
    to land inside the committed quarter; a deal committed in Q1 that closes won
    in Q2 is SLIPPED (it missed the quarter it was committed for), never Won.

    Reports, pooled across complete quarters, per commit-week: n_committed
    (volume), classified, won, lost, slipped, and win_rate = won/classified —
    GATED: a week whose classified cohort is below min_evidence_count returns
    win_rate null with a reason (counts still shown). Volume is always reported;
    it distinguishes a conservative commit culture (few early commits, high
    win rate) from an optimistic one (many early commits that fall out). Per
    quarter is included, gated the same way.
    """
    if sb is None:
        sb = create_client(
            os.environ['SUPABASE_URL'],
            os.environ['SUPABASE_SERVICE_KEY']
        )

    config = _load_config()
    min_evidence = config.get('min_evidence_count', 30)

    complete_quarters = _get_complete_quarters(sb)
    if not complete_quarters:
        return {
            'error': 'No complete quarters available',
            'coverage_note': 'Insufficient historical data'
        }

    # Terminal outcome source (OUTCOME-READ, defect 5): the backfilled snapshot
    # has no won/lost rows, so the outcome of a committed deal must be read from
    # the deal's terminal state, never from tag survival across snapshots.
    from supabase_client import select_all
    deals_rows = select_all(sb, 'deals', columns='deal_id,stage,close_date')
    deals_by_id = {str(d['deal_id']): d for d in deals_rows}

    def _blank():
        return {'n_committed': 0, 'won': 0, 'lost': 0, 'slipped': 0,
                'unclassified': 0}

    pooled_by_week = defaultdict(_blank)
    per_quarter_week = defaultdict(lambda: defaultdict(_blank))

    for quarter in complete_quarters:
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        for week in range(1, 14):
            res = sb.table('deals_snapshot').select('deal_id').eq(
                'fiscal_quarter', quarter).eq(
                'week_of_quarter', week).eq(
                'forecast_category', 'COMMIT').execute()
            for r in res.data:
                did = r['deal_id']
                outcome = _classify_deal_outcome(
                    did, q_start_iso, q_end_iso, deals_by_id)
                for agg in (pooled_by_week[week], per_quarter_week[quarter][week]):
                    agg['n_committed'] += 1
                    if outcome == 'WON':
                        agg['won'] += 1
                    elif outcome == 'LOST':
                        agg['lost'] += 1
                    elif outcome == 'SLIPPED':
                        agg['slipped'] += 1
                    else:  # deal absent from deals table — cannot classify
                        agg['unclassified'] += 1

    def _finish(agg):
        classified = agg['won'] + agg['lost'] + agg['slipped']
        gated = classified >= min_evidence
        return {
            'n_committed': agg['n_committed'],
            'classified': classified,
            'unclassified': agg['unclassified'],
            'won': agg['won'], 'lost': agg['lost'], 'slipped': agg['slipped'],
            'win_rate': (agg['won'] / classified) if gated and classified else None,
            'reason': (None if gated
                       else f'{classified} classified < min_evidence {min_evidence}'),
        }

    by_week = {w: _finish(pooled_by_week[w]) for w in sorted(pooled_by_week)}
    per_quarter = {
        q: {w: _finish(per_quarter_week[q][w]) for w in sorted(per_quarter_week[q])}
        for q in per_quarter_week
    }
    volume_by_week = {w: by_week[w]['n_committed'] for w in by_week}

    return {
        'by_week': by_week,
        'per_quarter': per_quarter,
        'volume_by_week': volume_by_week,
        'quarters_analyzed': len(complete_quarters),
        'min_evidence_count': min_evidence,
        'coverage_note': f'{len(complete_quarters)} complete quarters at 85% coverage',
        'complete_quarters': complete_quarters,
        'note': ('Outcome is terminal (deals table), not tag survival. '
                 'Won requires close_date inside the committed quarter; '
                 'won-in-a-later-quarter is slipped.'),
    }


def query_commit_calibration(
    sb=None,
    anchor_week: Optional[int] = None
) -> Dict:
    """
    Measure actual commit hit rate vs claimed accuracy.

    Cohort: deals with forecast_category = 'COMMIT' as of anchor week.
    Track each forward to quarter end. Classify as Won/Slipped/Lost.

    Args:
        sb: Supabase client
        anchor_week: Week to measure COMMIT status (default from config or measured)

    Returns:
        {
            'actual_hit_rate': float,  # Won / (Won + Slipped + Lost)
            'claimed_hit_rate': float,  # From config
            'calibration_delta': float,  # actual - claimed
            'breakdown': {'won': int, 'slipped': int, 'lost': int},
            'kellogg_benchmark': {'won': 0.33, 'lost': 0.33, 'slipped': 0.33},
            'by_quarter': {...},
            'by_rep': {...},
            'quarters_analyzed': int,
            'anchor_week': int,
            'coverage_note': str
        }

    CRITICAL: Won/Slipped/Lost are three distinct outcomes, never two.
    A deal open past quarter end is SLIPPED, not LOST.
    """
    if sb is None:
        sb = create_client(
            os.environ['SUPABASE_URL'],
            os.environ['SUPABASE_SERVICE_KEY']
        )

    config = _load_config()

    # Determine anchor week. The former churn-retention anchor was an artifact
    # (see query_commit_outcome_by_week); anchor now = the EARLIEST commit-week
    # whose pooled cohort clears min_evidence_count — the earliest week we can
    # compute a rate at, a statistical-validity criterion, not a tuned target.
    if anchor_week is None:
        anchor_week = config.get('anchor_week')
        if anchor_week is None:
            obw = query_commit_outcome_by_week(sb)
            gate_weeks = [w for w, s in sorted(obw.get('by_week', {}).items())
                          if s.get('win_rate') is not None]
            anchor_week = gate_weeks[0] if gate_weeks else None
            if anchor_week is None:
                return {
                    'error': 'No commit-week cohort clears min_evidence_count — '
                             'cannot compute a calibrated hit rate',
                    'coverage_note': 'See query_commit_outcome_by_week for the '
                                     'per-week volumes and null reasons',
                }

    complete_quarters = _get_complete_quarters(sb)

    if not complete_quarters:
        return {
            'error': 'No complete quarters available',
            'coverage_note': 'Insufficient historical data'
        }

    min_evidence = config.get('min_evidence_count', 30)

    # Terminal outcome comes from the current deals table (OUTCOME-READ, defect
    # 5): the backfilled snapshot has no won/lost rows, so outcome must be read
    # from the deal's terminal state, not a snapshot row. Load once; owner_email
    # drives the by-rep slice (deals_snapshot has no owner column — the earlier
    # deal_owner select was a latent bug, surfaced once churn produced an anchor).
    from supabase_client import select_all
    deals_rows = select_all(sb, 'deals',
                            columns='deal_id,stage,close_date,owner_email')
    deals_by_id = {str(d['deal_id']): d for d in deals_rows}

    # Track outcomes across all quarters, plus per-quarter and per-rep slices.
    total_won = total_slipped = total_lost = 0
    by_quarter = {}
    by_rep = defaultdict(lambda: {'won': 0, 'slipped': 0, 'lost': 0})

    for quarter in complete_quarters:
        # COMMIT cohort at the anchor week (point-in-time, from the snapshot).
        anchor_result = sb.table('deals_snapshot').select(
            'deal_id'
        ).eq('fiscal_quarter', quarter).eq(
            'week_of_quarter', anchor_week
        ).eq('forecast_category', 'COMMIT').execute()
        deal_ids = [r['deal_id'] for r in anchor_result.data]
        if not deal_ids:
            continue

        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        won = slipped = lost = 0
        for deal_id in deal_ids:
            outcome = _classify_deal_outcome(
                deal_id, q_start_iso, q_end_iso, deals_by_id)
            owner = (deals_by_id.get(str(deal_id)) or {}).get(
                'owner_email') or 'unknown'
            if outcome == 'WON':
                won += 1; by_rep[owner]['won'] += 1
            elif outcome == 'SLIPPED':
                slipped += 1; by_rep[owner]['slipped'] += 1
            elif outcome == 'LOST':
                lost += 1; by_rep[owner]['lost'] += 1

        total_won += won
        total_slipped += slipped
        total_lost += lost
        q_total = won + slipped + lost
        # Per-quarter gate: below min_evidence returns null-with-reason, never a
        # fabricated rate (gate unchanged).
        by_quarter[quarter] = {
            'won': won, 'slipped': slipped, 'lost': lost,
            'total_commit': len(deal_ids), 'classified': q_total,
            'hit_rate': (won / q_total) if q_total >= min_evidence else None,
            'reason': (None if q_total >= min_evidence
                       else f'{q_total} classified < min_evidence {min_evidence}'),
        }

    # Pooled hit rate across quarters at the anchor week. Same gate, applied to
    # the pooled cohort.
    total_outcomes = total_won + total_slipped + total_lost
    pooled_ok = total_outcomes >= min_evidence
    actual_hit_rate = (total_won / total_outcomes) if (pooled_ok and total_outcomes) else None
    claimed_hit_rate = config.get('claimed_commit_accuracy', 0.90)
    calibration_delta = (actual_hit_rate - claimed_hit_rate) if actual_hit_rate is not None else None

    # by-rep hit rate, gated per rep too.
    by_rep_out = {}
    for owner, c in by_rep.items():
        n = c['won'] + c['slipped'] + c['lost']
        by_rep_out[owner] = {
            **c, 'classified': n,
            'hit_rate': (c['won'] / n) if n >= min_evidence else None,
            'reason': (None if n >= min_evidence
                       else f'{n} classified < min_evidence {min_evidence}'),
        }

    return {
        'actual_hit_rate': actual_hit_rate,
        'claimed_hit_rate': claimed_hit_rate,
        'calibration_delta': calibration_delta,
        'pooled_below_gate': (not pooled_ok),
        'pooled_reason': (None if pooled_ok
                          else f'{total_outcomes} classified < min_evidence {min_evidence}'),
        'breakdown': {
            'won': total_won, 'slipped': total_slipped,
            'lost': total_lost, 'total': total_outcomes,
        },
        'kellogg_benchmark': {
            'won': 0.33, 'lost': 0.33, 'slipped': 0.33,
            'note': "Kellogg's heuristic for two-horse market orientation, not a target"
        },
        'by_quarter': by_quarter,
        'by_rep': by_rep_out,
        'quarters_analyzed': len(complete_quarters),
        'anchor_week': anchor_week,
        'min_evidence_count': min_evidence,
        'coverage_note': f'{len(complete_quarters)} complete quarters at 85% coverage',
        'note': ('Outcome is terminal (deals table), not a snapshot row; the '
                 'COMMIT cohort is point-in-time at the anchor week.'),
    }


def main():
    """CLI for testing analyses."""
    import argparse

    parser = argparse.ArgumentParser(description='Run forecast analyses')
    parser.add_argument('analysis',
                        choices=['week3', 'outcome', 'calibration', 'all'])
    args = parser.parse_args()

    sb = create_client(
        os.environ['SUPABASE_URL'],
        os.environ['SUPABASE_SERVICE_KEY']
    )

    if args.analysis in ['week3', 'all']:
        print("\n" + "=" * 70)
        print("WEEK-3 CONVERSION (Kellogg's Method)")
        print("=" * 70)
        result = query_week3_conversion(sb)

        if 'error' in result:
            print(f"\n⚠️  {result['error']}")
            print(f"Coverage: {result.get('coverage_note', 'N/A')}")
        else:
            print(f"\nQuarters analyzed: {result['quarters_analyzed']}")
            print(f"Basis: {result['basis']}")
            print(f"Scope: {result['scope']}")

            print("\nTrailing average by pipeline:")
            for pid, t in result.get('trailing_by_pipeline', {}).items():
                avg = t['trailing_average']
                cov = t['implied_coverage_target']
                avg_s = f"{avg:.1%}" if avg is not None else "N/A"
                cov_s = f"{cov:.2f}x" if cov is not None else "N/A"
                print(f"  {pid}: {avg_s}  implied coverage {cov_s}  "
                      f"({t['quarters_with_rate']} quarters)")

            print("\nPer-quarter / per-pipeline conversion "
                  "(won / scoped week-3 denominator):")
            for quarter, qd in result.get('per_quarter', {}).items():
                for pid, s in qd['by_pipeline'].items():
                    rate = s.get('rate_count')
                    if rate is None:
                        rate_s = f"null ({s.get('reason', 'n/a')})"
                    else:
                        rate_s = f"{rate:.1%}"
                    print(f"  {quarter} / {pid}: {rate_s}  "
                          f"({s['closed_won_count']}/{s['week3_scoped_denominator']})")

    if args.analysis in ['outcome', 'all']:
        print("\n" + "=" * 70)
        print("COMMIT OUTCOME BY WEEK (terminal outcome, not tag retention)")
        print("=" * 70)
        result = query_commit_outcome_by_week(sb)

        if 'error' in result:
            print(f"\n⚠️  {result['error']}")
        else:
            print(f"\nQuarters analyzed: {result['quarters_analyzed']}  "
                  f"(min_evidence_count={result.get('min_evidence_count')})")
            print(f"{result.get('coverage_note', '')}")
            print("\nPooled across quarters, by commit-week:")
            print(f"  {'wk':>2}  {'n':>3}  {'won':>3} {'lost':>4} {'slip':>4}  win_rate")
            for week in sorted(result['by_week'].keys()):
                s = result['by_week'][week]
                wr = (f"{s['win_rate']:.1%}" if s['win_rate'] is not None
                      else f"null ({s['reason']})")
                print(f"  {week:>2}  {s['n_committed']:>3}  {s['won']:>3} "
                      f"{s['lost']:>4} {s['slipped']:>4}  {wr}")
            print("\nVolume curve (deals tagged COMMIT at each week): "
                  + " ".join(f"w{w}:{n}" for w, n in
                             sorted(result['volume_by_week'].items())))
            print(f"\n{result.get('note', '')}")

    if args.analysis in ['calibration', 'all']:
        print("\n" + "=" * 70)
        print("COMMIT CALIBRATION")
        print("=" * 70)
        result = query_commit_calibration(sb)

        if 'error' in result:
            print(f"\n⚠️  {result['error']}")
        else:
            print(f"\nAnchor week: {result['anchor_week']}  "
                  f"(min_evidence_count={result.get('min_evidence_count')})")
            print(f"Quarters analyzed: {result['quarters_analyzed']}")

            if result.get('pooled_below_gate'):
                print(f"\nPooled hit rate: null ({result.get('pooled_reason')})")
            else:
                hr = result['actual_hit_rate']
                print(f"\nPooled actual hit rate: {hr:.1%}"
                      if hr is not None else "\nPooled actual hit rate: N/A")
            print(f"Claimed hit rate: {result['claimed_hit_rate']:.1%}")
            if result.get('calibration_delta') is not None:
                print(f"Delta vs claim: {result['calibration_delta']:+.1%}")

            breakdown = result['breakdown']
            t = breakdown['total']
            print(f"\nPooled outcome breakdown (n={t}):")
            if t > 0:
                print(f"  Won: {breakdown['won']} ({breakdown['won']/t:.1%})")
                print(f"  Slipped: {breakdown['slipped']} ({breakdown['slipped']/t:.1%})")
                print(f"  Lost: {breakdown['lost']} ({breakdown['lost']/t:.1%})")

            print("\nBy quarter (gated per quarter):")
            for q, qd in result.get('by_quarter', {}).items():
                if qd['hit_rate'] is None:
                    print(f"  {q}: null ({qd['reason']})  "
                          f"[W{qd['won']}/S{qd['slipped']}/L{qd['lost']}, "
                          f"n={qd['classified']}]")
                else:
                    print(f"  {q}: {qd['hit_rate']:.1%}  "
                          f"[W{qd['won']}/S{qd['slipped']}/L{qd['lost']}, "
                          f"n={qd['classified']}]")

            print("\nBy rep (gated per rep):")
            for rep, rd in sorted(result.get('by_rep', {}).items(),
                                  key=lambda kv: -(kv[1]['classified'])):
                if rd['hit_rate'] is None:
                    print(f"  {rep}: null ({rd['reason']})  "
                          f"[W{rd['won']}/S{rd['slipped']}/L{rd['lost']}]")
                else:
                    print(f"  {rep}: {rd['hit_rate']:.1%}  "
                          f"[W{rd['won']}/S{rd['slipped']}/L{rd['lost']}, "
                          f"n={rd['classified']}]")

            bench = result['kellogg_benchmark']
            print(f"\nKellogg's benchmark (orientation only):")
            print(f"  {bench['won']:.0%} won / {bench['lost']:.0%} lost / {bench['slipped']:.0%} slipped")
            print(f"  {bench['note']}")
            print(f"\n{result.get('note', '')}")


if __name__ == '__main__':
    main()
