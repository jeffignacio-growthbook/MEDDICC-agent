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

    for quarter in complete_quarters:
        # Get week 3 snapshot (all deals in week 3)
        week3_result = sb.table('deals_snapshot').select(
            'deal_id, deal_value'
        ).eq('fiscal_quarter', quarter).eq('week_of_quarter', 3).execute()

        week3_pipeline_count = len(week3_result.data)
        week3_pipeline_value = sum(r.get('deal_value', 0) or 0 for r in week3_result.data)

        # CRITICAL: Return NULL if sample size below evidence threshold
        # A coverage target computed from 15 deals is worse than no answer
        if week3_pipeline_count < min_evidence:
            return {
                'error': f'Insufficient week-3 pipeline data in quarter {quarter}',
                'week3_pipeline_count': week3_pipeline_count,
                'min_evidence_required': min_evidence,
                'quarters_analyzed': 0,
                'coverage_note': f'Week-3 snapshot has only {week3_pipeline_count} deals (need {min_evidence}+). Run full backfill.'
            }

        # NUMERATOR (defect 1): deals that TRANSITIONED to won DURING the
        # quarter, counted by terminal won stage with an in-quarter close_date
        # — never "won as of quarter end" (which cumulatively re-counted every
        # deal ever won). Independent of the week-3 membership: a deal created
        # and closed mid-quarter counts in the numerator without being in the
        # week-3 denominator (the intentional asymmetry, defect 3).
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        won_by_pipeline = _in_quarter_won_by_pipeline(sb, q_start_iso, q_end_iso)
        closed_won_count = sum(won_by_pipeline.values())  # Phase 1: pooled

        # Dollar basis deferred to Phase 4 (null-propagation over the ledger);
        # basis stays 'count' meanwhile.
        rate_count = closed_won_count / week3_pipeline_count if week3_pipeline_count > 0 else 0

        per_quarter[quarter] = {
            'rate_count': rate_count,
            'closed_won_count': closed_won_count,
            'closed_won_by_pipeline': won_by_pipeline,
            'week3_pipeline_count': week3_pipeline_count,
            'quarter_window': [q_start_iso, q_end_iso],
        }

    # Calculate trailing average
    basis = config.get('basis', 'count')
    rate_key = f'rate_{basis}'

    rates = [q[rate_key] for q in per_quarter.values() if rate_key in q]
    trailing_average = sum(rates) / len(rates) if rates else None

    # Implied coverage target (1 / rate)
    implied_coverage = (1 / trailing_average) if trailing_average and trailing_average > 0 else None

    return {
        'per_quarter': per_quarter,
        'trailing_average': trailing_average,
        'implied_coverage_target': implied_coverage,
        'basis': basis,
        'quarters_analyzed': len(complete_quarters),
        'coverage_note': f'{len(complete_quarters)} complete quarters available (85% category coverage)',
        'complete_quarters': complete_quarters
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
            print(f"Trailing average: {result['trailing_average']:.1%}" if result['trailing_average'] else "N/A")
            print(f"Implied coverage target: {result['implied_coverage_target']:.2f}x" if result['implied_coverage_target'] else "N/A")
            print(f"\n{result.get('coverage_note', '')}")

            print("\nPer-quarter breakdown:")
            for quarter, stats in result.get('per_quarter', {}).items():
                print(f"  {quarter}: {stats['rate_count']:.1%} ({stats['closed_won_count']}/{stats['week3_pipeline_count']})")

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
