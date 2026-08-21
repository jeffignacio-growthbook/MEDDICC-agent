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
    committed_quarter: str,
    sb
) -> Optional[str]:
    """
    Classify a deal that was COMMIT in a given quarter.

    Returns:
        'WON' — closed won in the committed quarter
        'SLIPPED' — still open past quarter end OR close date pushed out
        'LOST' — closed lost before/during quarter end
        None — insufficient data to classify

    CRITICAL: Slipped vs Lost must be separate. A deal open past quarter end
    with a pushed close date is SLIPPED, never LOST. This is the exact error
    Kellogg critiques.
    """
    # Get quarter end date from fiscal calendar
    # Parse committed_quarter (e.g., 'FY2027 Q1')
    # For now, we'll need to get the last snapshot in that quarter

    # Get all snapshots for this deal in this quarter
    result = sb.table('deals_snapshot').select(
        'snapshot_date, deal_status, stage_id, forecast_category, close_date'
    ).eq('deal_id', deal_id).eq('fiscal_quarter', committed_quarter).order(
        'snapshot_date', desc=True
    ).execute()

    if not result.data:
        return None

    # Get the last snapshot in the quarter
    last_snap = result.data[0]

    # Check final status/stage
    status = (last_snap.get('deal_status') or '').lower()
    stage_id = (last_snap.get('stage_id') or '').lower()

    if 'won' in status or 'closedwon' in stage_id:
        return 'WON'
    elif 'lost' in status or 'closedlost' in stage_id:
        return 'LOST'
    else:
        # Deal was still open at quarter end = SLIPPED
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


def query_category_churn(sb=None) -> Dict:
    """
    Measure forecast category stability by week.

    For each week_of_quarter (1-13), of deals tagged COMMIT that week,
    what fraction were still COMMIT at quarter end.

    Returns:
        {
            'churn_curve': {week: {'commit_start': int, 'commit_end': int, 'retention_rate': float}},
            'empirical_anchor_week': int,  # Week where churn drops and stabilizes
            'by_owner': {...},  # Same structure, segmented by owner
            'quarters_analyzed': int,
            'coverage_note': str
        }

    The empirical anchor week replaces the instinctive week-8 hardcode.
    """
    if sb is None:
        sb = create_client(
            os.environ['SUPABASE_URL'],
            os.environ['SUPABASE_SERVICE_KEY']
        )

    complete_quarters = _get_complete_quarters(sb)

    if not complete_quarters:
        return {
            'error': 'No complete quarters available',
            'coverage_note': 'Insufficient historical data'
        }

    # Aggregate across all complete quarters
    churn_by_week = defaultdict(lambda: {'commit_start': 0, 'commit_end': 0})

    for quarter in complete_quarters:
        for week in range(1, 14):  # Weeks 1-13
            # Get deals tagged COMMIT in this week
            week_result = sb.table('deals_snapshot').select(
                'deal_id'
            ).eq('fiscal_quarter', quarter).eq(
                'week_of_quarter', week
            ).eq('forecast_category', 'COMMIT').execute()

            commit_start = len(week_result.data)
            churn_by_week[week]['commit_start'] += commit_start

            if commit_start == 0:
                continue

            deal_ids = [r['deal_id'] for r in week_result.data]

            # Check how many were still COMMIT at week 13 (quarter end)
            end_result = sb.table('deals_snapshot').select(
                'deal_id, forecast_category'
            ).eq('fiscal_quarter', quarter).eq(
                'week_of_quarter', 13
            ).in_('deal_id', deal_ids).execute()

            # Count still COMMIT
            commit_end = sum(
                1 for r in end_result.data
                if r.get('forecast_category') == 'COMMIT'
            )

            churn_by_week[week]['commit_end'] += commit_end

    # Calculate retention rates
    churn_curve = {}
    for week, stats in churn_by_week.items():
        if stats['commit_start'] > 0:
            retention_rate = stats['commit_end'] / stats['commit_start']
        else:
            retention_rate = None

        churn_curve[week] = {
            'commit_start': stats['commit_start'],
            'commit_end': stats['commit_end'],
            'retention_rate': retention_rate,
            'churn_rate': (1 - retention_rate) if retention_rate else None
        }

    # Find empirical anchor week (where retention stabilizes)
    # Simple heuristic: first week where retention >= 0.80 and stays stable
    anchor_week = None
    for week in sorted(churn_curve.keys()):
        rate = churn_curve[week]['retention_rate']
        if rate and rate >= 0.80:
            # Check if next 2 weeks also stable
            next_weeks_stable = True
            for w in range(week + 1, min(week + 3, 14)):
                if w in churn_curve:
                    next_rate = churn_curve[w]['retention_rate']
                    if not next_rate or abs(next_rate - rate) > 0.10:
                        next_weeks_stable = False
                        break

            if next_weeks_stable:
                anchor_week = week
                break

    return {
        'churn_curve': churn_curve,
        'empirical_anchor_week': anchor_week,
        'quarters_analyzed': len(complete_quarters),
        'coverage_note': f'{len(complete_quarters)} complete quarters at 85% coverage',
        'complete_quarters': complete_quarters,
        'note': 'Empirical anchor replaces instinctive week-8 hardcode'
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

    # Determine anchor week
    if anchor_week is None:
        anchor_week = config.get('anchor_week')
        if anchor_week is None:
            # Use measured value from category churn
            churn_data = query_category_churn(sb)
            anchor_week = churn_data.get('empirical_anchor_week')
            if anchor_week is None:
                return {
                    'error': 'Cannot determine anchor week — insufficient data for category churn analysis',
                    'coverage_note': 'Run query_category_churn first to establish empirical anchor'
                }

    complete_quarters = _get_complete_quarters(sb)

    if not complete_quarters:
        return {
            'error': 'No complete quarters available',
            'coverage_note': 'Insufficient historical data'
        }

    # Track outcomes across all quarters
    total_won = 0
    total_slipped = 0
    total_lost = 0
    by_quarter = {}

    for quarter in complete_quarters:
        # Get deals tagged COMMIT at anchor week
        anchor_result = sb.table('deals_snapshot').select(
            'deal_id, deal_owner, deal_value'
        ).eq('fiscal_quarter', quarter).eq(
            'week_of_quarter', anchor_week
        ).eq('forecast_category', 'COMMIT').execute()

        deal_ids = [r['deal_id'] for r in anchor_result.data]

        if not deal_ids:
            continue

        # Classify each deal
        won = 0
        slipped = 0
        lost = 0

        for deal_id in deal_ids:
            outcome = _classify_deal_outcome(deal_id, quarter, sb)
            if outcome == 'WON':
                won += 1
            elif outcome == 'SLIPPED':
                slipped += 1
            elif outcome == 'LOST':
                lost += 1

        total_won += won
        total_slipped += slipped
        total_lost += lost

        by_quarter[quarter] = {
            'won': won,
            'slipped': slipped,
            'lost': lost,
            'total_commit': len(deal_ids)
        }

    # Calculate hit rate
    total_outcomes = total_won + total_slipped + total_lost
    actual_hit_rate = total_won / total_outcomes if total_outcomes > 0 else None

    claimed_hit_rate = config.get('claimed_commit_accuracy', 0.90)
    calibration_delta = (actual_hit_rate - claimed_hit_rate) if actual_hit_rate else None

    return {
        'actual_hit_rate': actual_hit_rate,
        'claimed_hit_rate': claimed_hit_rate,
        'calibration_delta': calibration_delta,
        'breakdown': {
            'won': total_won,
            'slipped': total_slipped,
            'lost': total_lost,
            'total': total_outcomes
        },
        'kellogg_benchmark': {
            'won': 0.33,
            'lost': 0.33,
            'slipped': 0.33,
            'note': "Kellogg's heuristic for two-horse market orientation, not a target"
        },
        'by_quarter': by_quarter,
        'quarters_analyzed': len(complete_quarters),
        'anchor_week': anchor_week,
        'coverage_note': f'{len(complete_quarters)} complete quarters at 85% coverage',
        'note': 'Limited historical depth — 2 quarters vs ideal 4+'
    }


def main():
    """CLI for testing analyses."""
    import argparse

    parser = argparse.ArgumentParser(description='Run forecast analyses')
    parser.add_argument('analysis', choices=['week3', 'churn', 'calibration', 'all'])
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

    if args.analysis in ['churn', 'all']:
        print("\n" + "=" * 70)
        print("CATEGORY CHURN CURVE")
        print("=" * 70)
        result = query_category_churn(sb)

        if 'error' in result:
            print(f"\n⚠️  {result['error']}")
        else:
            print(f"\nEmpirical anchor week: {result.get('empirical_anchor_week', 'N/A')}")
            print(f"Quarters analyzed: {result['quarters_analyzed']}")
            print(f"\n{result.get('coverage_note', '')}")

            print("\nChurn curve by week:")
            for week in sorted(result['churn_curve'].keys()):
                stats = result['churn_curve'][week]
                retention = stats['retention_rate']
                if retention:
                    print(f"  Week {week:2d}: {retention:.1%} retention ({stats['commit_end']}/{stats['commit_start']} still COMMIT)")

    if args.analysis in ['calibration', 'all']:
        print("\n" + "=" * 70)
        print("COMMIT CALIBRATION")
        print("=" * 70)
        result = query_commit_calibration(sb)

        if 'error' in result:
            print(f"\n⚠️  {result['error']}")
        else:
            print(f"\nAnchor week: {result['anchor_week']}")
            print(f"Quarters analyzed: {result['quarters_analyzed']}")
            print(f"\nActual hit rate: {result['actual_hit_rate']:.1%}" if result['actual_hit_rate'] else "N/A")
            print(f"Claimed hit rate: {result['claimed_hit_rate']:.1%}")
            print(f"Delta: {result['calibration_delta']:+.1%}" if result['calibration_delta'] else "N/A")

            breakdown = result['breakdown']
            print(f"\nOutcome breakdown:")
            print(f"  Won: {breakdown['won']} ({breakdown['won']/breakdown['total']:.1%})" if breakdown['total'] > 0 else "N/A")
            print(f"  Slipped: {breakdown['slipped']} ({breakdown['slipped']/breakdown['total']:.1%})" if breakdown['total'] > 0 else "N/A")
            print(f"  Lost: {breakdown['lost']} ({breakdown['lost']/breakdown['total']:.1%})" if breakdown['total'] > 0 else "N/A")

            bench = result['kellogg_benchmark']
            print(f"\nKellogg's benchmark (orientation only):")
            print(f"  {bench['won']:.0%} won / {bench['lost']:.0%} lost / {bench['slipped']:.0%} slipped")
            print(f"  {bench['note']}")

            print(f"\n{result.get('note', '')}")


if __name__ == '__main__':
    main()
