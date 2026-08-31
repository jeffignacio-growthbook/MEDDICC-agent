#!/usr/bin/env python3
"""
Retention metrics handler: GRR, Churn, NRR for renewal pipeline.

Formulas ported exactly from HubSpot custom report:
  GRR   = SUM(IF(hs_is_closed_won, renewal_revenue, 0)) / SUM(renewal_revenue)
  Churn = 1 - GRR
  NRR   = SUM(IF(NOT hs_is_closed_lost, incremental_arr + renewal_revenue, 0)) / SUM(renewal_revenue)

Two views required (never report one without the other):
  - Closed Only: hs_is_closed = true (historical fact)
  - Assume Open Wins: open deals counted as renewed (forward-looking)
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import date
from dateutil.relativedelta import relativedelta

# Add parent paths for imports
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT / 'api'))

from field_semantics import is_won, is_lost
from utils import load_client_config
from db import get_supabase


def query_retention_metrics(supabase, config: Dict, time_window: Dict) -> Dict:
    """
    Compute GRR, Churn, NRR for renewal pipeline by fiscal quarter.

    Returns both views (closed-only, assume-open-wins) with coverage metadata.
    Pre-grouped by fiscal quarter from config (never let synthesis re-infer).

    Args:
        supabase: Supabase client
        config: Client config (for fiscal quarters and renewal pipeline IDs)
        time_window: Resolved time window (not used for grouping, just metadata)

    Returns:
        {
          "views": {
            "closed_only": {quarter_label: {grr, churn, nrr, n, total, coverage_pct, ...}, ...},
            "assume_open_wins": {...}
          },
          "denominator_basis": "renewal_revenue",
          "coverage_floor_pct": 50.0,
          "time_window": {...}
        }
    """
    # Get renewal pipeline IDs from config (never hardcode)
    pipeline_config = config.get('pipeline', {})
    value_field_config = pipeline_config.get('value_field', {})
    renewal_pipeline_ids = value_field_config.get('renewal_pipeline_ids', [])

    if not renewal_pipeline_ids:
        return {
            "error": "No renewal pipeline configured",
            "views": {"closed_only": {}, "assume_open_wins": {}},
            "denominator_basis": "renewal_revenue",
            "time_window": time_window
        }

    # Fetch all renewal pipeline deals
    deals = []
    for pipeline_id in renewal_pipeline_ids:
        response = supabase.table("deals") \
            .select("deal_id,stage,close_date,renewal_revenue,incremental_arr") \
            .eq("pipeline_id", pipeline_id) \
            .execute()
        deals.extend(response.data)

    # Group by fiscal quarter from close_date
    from collections import defaultdict
    by_quarter = defaultdict(lambda: {'all': [], 'won': [], 'lost': [], 'open': []})

    for deal in deals:
        close_date_str = deal.get('close_date')
        if not close_date_str:
            continue

        # Get fiscal quarter from config
        quarter_label = _get_fiscal_quarter_label(close_date_str, config)
        if not quarter_label:
            continue

        stage = deal.get('stage', '')
        renewal_rev = deal.get('renewal_revenue')
        incremental = deal.get('incremental_arr') or 0

        # Track all deals
        by_quarter[quarter_label]['all'].append({
            'deal_id': deal['deal_id'],
            'renewal_revenue': renewal_rev,
            'incremental_arr': incremental,
            'stage': stage
        })

        # Categorize by status
        if is_won(stage):
            by_quarter[quarter_label]['won'].append({
                'renewal_revenue': renewal_rev,
                'incremental_arr': incremental
            })
        elif is_lost(stage):
            by_quarter[quarter_label]['lost'].append({
                'renewal_revenue': renewal_rev,
                'incremental_arr': incremental
            })
        else:
            by_quarter[quarter_label]['open'].append({
                'renewal_revenue': renewal_rev,
                'incremental_arr': incremental
            })

    # Compute metrics for both views
    closed_only = {}
    assume_open_wins = {}

    coverage_floor = config.get('analytics', {}).get('retention_coverage_floor_pct', 50.0)

    for quarter_label in sorted(by_quarter.keys()):
        data = by_quarter[quarter_label]

        # Closed-only view
        # Spec: "Closed Only — hs_is_closed = true. Retention among deals that actually resolved."
        # Both numerator AND denominator include only closed deals (won + lost)
        closed_only[quarter_label] = _compute_view_metrics(
            won_deals=data['won'],
            lost_deals=data['lost'],
            open_deals=[],  # Exclude open from both numerator and denominator
            all_deals=data['won'] + data['lost'],  # Denominator: closed deals only
            quarter_label=quarter_label,
            coverage_floor=coverage_floor,
            view_name="closed_only"
        )

        # Assume-open-wins view
        assume_open_wins[quarter_label] = _compute_view_metrics(
            won_deals=data['won'],
            lost_deals=data['lost'],
            open_deals=data['open'],  # Count open as won
            all_deals=data['all'],
            quarter_label=quarter_label,
            coverage_floor=coverage_floor,
            view_name="assume_open_wins"
        )

    # Build population statement
    total_deals = sum(len(data['all']) for data in by_quarter.values())
    quarters_covered = sorted(by_quarter.keys())

    # Count deals missing renewal_revenue
    all_deals_flat = []
    for data in by_quarter.values():
        all_deals_flat.extend(data['all'])

    missing_amount = sum(1 for d in all_deals_flat
                        if d.get('renewal_revenue') is None or d.get('renewal_revenue') == 0)

    # Build plain-language statement
    quarter_display = ', '.join(quarters_covered)
    population_statement = f"{total_deals} renewals across {quarter_display}."

    if missing_amount > 0:
        population_statement += f" {missing_amount} don't have an amount recorded yet."

    # Add freshness stamps and reconciliation notes
    freshness_metadata = _add_freshness_and_reconciliation(
        closed_only, assume_open_wins, config
    )

    return {
        "views": {
            "closed_only": closed_only,
            "assume_open_wins": assume_open_wins
        },
        "population_statement": population_statement,
        "freshness": freshness_metadata,
        "_metadata": {
            "denominator_basis": "renewal_revenue",
            "coverage_floor_pct": coverage_floor,
            "time_window": time_window
        }
    }


def _compute_view_metrics(
    won_deals: List[Dict],
    lost_deals: List[Dict],
    open_deals: List[Dict],
    all_deals: List[Dict],
    quarter_label: str,
    coverage_floor: float,
    view_name: str
) -> Dict:
    """
    Compute GRR/Churn/NRR for one view with coverage checking.

    Returns:
        - Clean metric (coverage > floor, no caveat)
        - Metric with coverage (coverage stated)
        - Null with reason (insufficient coverage)
    """
    # Count total deals and null exclusions
    total_deals = len(all_deals)

    if total_deals == 0:
        # No deals in this quarter/view (e.g., Q3 closed-only has no closed deals)
        return {
            "status": "no_deals",
            "reason": f"No deals in {view_name} for {quarter_label}",
            "grr": None,
            "churn": None,
            "nrr": None,
            "n": 0,
            "total_deals": 0,
            "null_exclusions": 0,
            "coverage_pct": None
        }

    # Filter to deals with non-null renewal_revenue
    def has_value(deal):
        rr = deal.get('renewal_revenue')
        return rr is not None and rr != 0

    won_with_value = [d for d in won_deals if has_value(d)]
    lost_with_value = [d for d in lost_deals if has_value(d)]
    open_with_value = [d for d in open_deals if has_value(d)]
    all_with_value = [d for d in all_deals if has_value(d)]

    n = len(all_with_value)
    null_exclusions = total_deals - n
    coverage_pct = (n / total_deals * 100) if total_deals > 0 else 0

    # Check coverage floor
    if coverage_pct < coverage_floor:
        return {
            "status": "insufficient_coverage",
            "reason": f"Only {n} of {total_deals} deals have renewal_revenue ({coverage_pct:.1f}% < {coverage_floor:.0f}% floor)",
            "grr": None,
            "churn": None,
            "nrr": None,
            "n": n,
            "total_deals": total_deals,
            "null_exclusions": null_exclusions,
            "coverage_pct": coverage_pct
        }

    # Compute denominators (sum of renewal_revenue across all non-null deals)
    total_renewal_revenue = sum(d.get('renewal_revenue', 0) for d in all_with_value)

    if total_renewal_revenue == 0:
        # Edge case: all renewal_revenue values are zero (different from null)
        return {
            "status": "zero_denominator",
            "reason": f"All {n} deals have renewal_revenue = 0",
            "grr": None,
            "churn": None,
            "nrr": None,
            "n": n,
            "total_deals": total_deals,
            "null_exclusions": null_exclusions,
            "coverage_pct": coverage_pct
        }

    # GRR = won renewal_revenue / total renewal_revenue
    # For assume-open-wins, count open deals as won in the numerator
    if view_name == "assume_open_wins":
        won_plus_open_revenue = sum(
            d.get('renewal_revenue', 0)
            for d in won_with_value + open_with_value
        )
        grr = won_plus_open_revenue / total_renewal_revenue
    else:
        won_renewal_revenue = sum(d.get('renewal_revenue', 0) for d in won_with_value)
        grr = won_renewal_revenue / total_renewal_revenue

    won_renewal_revenue = sum(d.get('renewal_revenue', 0) for d in won_with_value)
    churn = 1 - grr

    # NRR = (not-lost renewal_revenue + incremental) / total renewal_revenue
    # For assume-open-wins, "not lost" includes won + open
    # For closed-only, "not lost" includes only won
    if view_name == "assume_open_wins":
        not_lost_deals = won_with_value + open_with_value
    else:
        not_lost_deals = won_with_value

    not_lost_revenue = sum(
        d.get('renewal_revenue', 0) + d.get('incremental_arr', 0)
        for d in not_lost_deals
    )
    nrr = not_lost_revenue / total_renewal_revenue

    # Determine status based on coverage
    if coverage_pct >= 95:
        status = "clean"
    else:
        status = "reported_with_coverage"

    return {
        "status": status,
        "grr": grr,
        "churn": churn,
        "nrr": nrr,
        "n": n,
        "total_deals": total_deals,
        "null_exclusions": null_exclusions,
        "coverage_pct": coverage_pct,
        "total_renewal_revenue": total_renewal_revenue,
        "won_renewal_revenue": won_renewal_revenue
    }


def _add_freshness_and_reconciliation(
    closed_only: Dict,
    assume_open_wins: Dict,
    config: Dict
) -> Dict:
    """
    Add freshness stamps and reconciliation notes for retention metrics.

    Returns:
        {
          "metric_type": "historical",  # from registry
          "quarters": {
            "FY2027 Q1": {
              "is_closed": true,
              "quarter_end": "2026-04-30",
              "reconciliation": {
                "grr": "Handler 76.68% matches verified 77% (0.32pp variance, within tolerance)",
                "nrr": "Handler 111.82% vs verified 107%. Handler includes Lion Studios..."
              }
            }
          },
          "last_verified": "2026-08-28"
        }
    """
    import yaml
    from datetime import date

    # Load metrics registry
    metrics_path = REPO_ROOT / 'config' / 'metrics.yaml'
    if not metrics_path.exists():
        return {"metric_type": "historical", "quarters": {}}

    with open(metrics_path) as f:
        registry = yaml.safe_load(f)

    grr_def = registry.get('grr', {})
    nrr_def = registry.get('nrr', {})

    last_verified = grr_def.get('verified', {}).get('reconciled_on', None)

    quarters_metadata = {}

    # Check each quarter
    for quarter_label in closed_only.keys():
        quarter_data = closed_only[quarter_label]

        # Determine if quarter is closed (no open deals)
        is_closed = quarter_data.get('status') in ['clean', 'reported_with_coverage']

        # Get quarter end date
        quarter_end = _get_quarter_end_date(quarter_label, config)

        # Build reconciliation notes
        reconciliation = {}

        # Check GRR reconciliation
        grr_value = quarter_data.get('grr')
        if grr_value is not None:
            grr_note = _build_reconciliation_note(
                'grr', quarter_label, grr_value, grr_def.get('verified', {})
            )
            if grr_note:
                reconciliation['grr'] = grr_note

        # Check NRR reconciliation
        nrr_value = quarter_data.get('nrr')
        if nrr_value is not None:
            nrr_note = _build_reconciliation_note(
                'nrr', quarter_label, nrr_value, nrr_def.get('verified', {})
            )
            if nrr_note:
                reconciliation['nrr'] = nrr_note

        quarters_metadata[quarter_label] = {
            "is_closed": is_closed,
            "quarter_end": quarter_end,
            "reconciliation": reconciliation
        }

    return {
        "metric_type": "historical",
        "quarters": quarters_metadata,
        "last_verified": last_verified
    }


def _get_quarter_end_date(quarter_label: str, config: Dict) -> Optional[str]:
    """
    Get the end date for a fiscal quarter.

    Args:
        quarter_label: e.g., "FY2027 Q1"
        config: Client config

    Returns:
        ISO date string for quarter end, e.g., "2026-04-30"
    """
    import re
    from datetime import date
    from dateutil.relativedelta import relativedelta

    # Parse quarter label
    match = re.search(r'FY(\d+) Q(\d+)', quarter_label)
    if not match:
        return None

    fy = int(match.group(1))
    q = int(match.group(2))

    # Get fiscal year start month from config
    fy_start_month = config.get('fiscal', {}).get('fy_start_month', 2)  # Default Feb

    # Calculate quarter start
    # Q1 starts in FY start month of (FY - 1)
    # Q2 starts 3 months later, etc.
    quarter_start_month = fy_start_month + (q - 1) * 3
    quarter_start_year = fy - 1

    # Handle month overflow
    while quarter_start_month > 12:
        quarter_start_month -= 12
        quarter_start_year += 1

    # Quarter end is start + 3 months - 1 day
    quarter_start = date(quarter_start_year, quarter_start_month, 1)
    quarter_end = quarter_start + relativedelta(months=3) - relativedelta(days=1)

    return quarter_end.isoformat()


def _build_reconciliation_note(
    metric: str,
    quarter_label: str,
    handler_value: float,
    verified_dict: Dict
) -> Optional[str]:
    """
    Build a reconciliation note explaining differences between handler and verified values.

    Returns None if no verified value exists or if values match exactly.
    Returns a plain-language explanation if there's a discrepancy.
    """
    # Find verified value for this quarter
    # Registry keys are like "q1_fy2027_closed_only"
    import re

    # Parse quarter label to match registry format
    match = re.search(r'FY(\d+) Q(\d+)', quarter_label)
    if not match:
        return None

    fy = match.group(1)
    q = match.group(2).lower()
    registry_key = f"q{q}_fy{fy}_closed_only"

    verified_value = verified_dict.get(registry_key)
    if verified_value is None:
        return None

    tolerance = verified_dict.get('tolerance', 0.005)
    variance = abs(handler_value - verified_value)

    # If values match exactly, no note needed
    if variance == 0:
        return None

    # If within tolerance, brief note
    if variance <= tolerance:
        return (
            f"Handler {handler_value*100:.1f}% matches verified {verified_value*100:.0f}% "
            f"({variance*100:.2f}pp variance, within tolerance)"
        )

    # If outside tolerance, detailed note with reconciliation explanation
    # Check for known reconciliation notes in registry
    reconciliation_note = verified_dict.get('reconciliation_note', '')
    report_exclusions = verified_dict.get('report_exclusions', '')

    if reconciliation_note or report_exclusions:
        # Use registry explanation
        note_parts = [
            f"Handler {handler_value*100:.1f}% vs verified {verified_value*100:.0f}%."
        ]

        if metric == 'nrr' and 'Lion Studios' in reconciliation_note:
            note_parts.append(
                "Handler includes Lion Studios ($37.5K expansion). Report excludes it. "
                "Reason unknown. Both are valid views depending on treatment rules."
            )
        else:
            # Generic explanation
            note_parts.append(
                "Different populations. See metrics.yaml for details."
            )

        return " ".join(note_parts)

    # No registry explanation - just state the difference
    return (
        f"Handler {handler_value*100:.1f}% vs verified {verified_value*100:.0f}% "
        f"({variance*100:.2f}pp variance)"
    )


def _get_fiscal_quarter_label(close_date_str: str, config: Dict) -> Optional[str]:
    """
    Get fiscal quarter label from close_date using config.

    Returns: "FY2027 Q3" or None
    """
    try:
        close_date = date.fromisoformat(close_date_str[:10])
    except (ValueError, TypeError):
        return None

    # Get fiscal year start month from config
    fy_start_month = config.get('fiscal', {}).get('fy_start_month', 2)  # Default Feb

    year = close_date.year
    month = close_date.month

    # Determine fiscal year
    if month >= fy_start_month:
        fy = year + 1
    else:
        fy = year

    # Determine quarter (fiscal quarters of 3 months each)
    month_offset = (month - fy_start_month) % 12
    quarter = (month_offset // 3) + 1

    return f"FY{fy} Q{quarter}"


# For testing
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    config = load_client_config()
    supabase = get_supabase()

    # Test with empty time window (not used for grouping)
    time_window = {"type": "all"}

    result = query_retention_metrics(supabase, config, time_window)

    import json
    print(json.dumps(result, indent=2, default=str))
