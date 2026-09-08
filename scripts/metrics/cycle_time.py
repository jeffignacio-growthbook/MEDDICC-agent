#!/usr/bin/env python3
"""
Parameterized cycle_time metric.

Computes median days from create_date to close_date for won deals,
with configurable period filtering and hygiene rules.
"""

import os
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.db import get_supabase
from api.field_semantics import is_won, is_renewal_base


def is_valid_cycle_deal(deal: dict) -> bool:
    """
    Check if deal has valid cycle time (non-negative).

    Excludes deals where (close_date - create_date) < 0.
    Such deals indicate CRM backfill or data entry errors.

    Args:
        deal: Deal record with create_date and close_date

    Returns:
        True if cycle is valid (>= 0 days), False otherwise
    """
    create_date = deal.get('create_date')
    close_date = deal.get('close_date')

    if not create_date or not close_date:
        return False

    try:
        create_dt = datetime.fromisoformat(create_date.replace('Z', '+00:00'))
        close_dt = datetime.fromisoformat(close_date.replace('Z', '+00:00'))
        days = (close_dt - create_dt).days
        return days >= 0
    except:
        return False


def cycle_time(
    period: Optional[dict] = None,
    pipeline_id: str = "default",
    exclude_renewals: bool = True,
    exclude_invalid_cycles: bool = True,
    aggregation: str = "median"
) -> dict:
    """
    Compute sales cycle time for won deals in a given period.

    Args:
        period: Date range {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                If None or {"start": None, "end": None}, computes all_time
        pipeline_id: Which pipeline to analyze (default: "default")
        exclude_renewals: Apply is_renewal_base hygiene rule (default: True)
        exclude_invalid_cycles: Apply is_valid_cycle_deal hygiene rule (default: True)
        aggregation: "median" or "mean" (default: median)

    Returns:
        {
            "days": float,  # median or mean cycle time
            "sample_size": int,  # deals in calculation
            "period": {"start": date, "end": date},
            "distribution": {"p25": float, "p50": float, "p75": float},
            "exclusions": {"renewals": int, "invalid_cycles": int}
        }
    """
    supabase = get_supabase()

    # Normalize period (None → all_time)
    if period is None:
        period = {"start": None, "end": None}

    # Fetch all deals from specified pipeline (with pagination)
    all_deals = []
    page_size = 1000
    offset = 0

    while True:
        query = supabase.table('deals').select(
            'deal_id, company_name, create_date, close_date, stage, pipeline_id, '
            'renewal_revenue, new_arr, expansion_arr, deal_status'
        ).range(offset, offset + page_size - 1).eq('pipeline_id', pipeline_id)

        result = query.execute()
        batch = result.data

        if not batch:
            break

        all_deals.extend(batch)
        offset += page_size

        # If we got fewer than page_size, we're done
        if len(batch) < page_size:
            break

    print(f"Fetched {len(all_deals)} total deals")

    # Filter to won deals only
    won_deals = [d for d in all_deals if is_won(d.get('stage'))]
    print(f"Won deals: {len(won_deals)}")

    # Apply hygiene rules
    exclusions = {"renewals": 0, "invalid_cycles": 0}

    clean_deals = []
    for deal in won_deals:
        # Hygiene rule 1: Exclude renewals
        if exclude_renewals and is_renewal_base(deal):
            exclusions["renewals"] += 1
            continue

        # Hygiene rule 2: Exclude invalid cycles
        if exclude_invalid_cycles and not is_valid_cycle_deal(deal):
            exclusions["invalid_cycles"] += 1
            continue

        clean_deals.append(deal)

    print(f"After hygiene rules: {len(clean_deals)} deals")
    print(f"  Excluded renewals: {exclusions['renewals']}")
    print(f"  Excluded invalid cycles: {exclusions['invalid_cycles']}")

    # Apply period filter (date boundary)
    period_filtered_deals = []
    for deal in clean_deals:
        close_date = deal.get('close_date')
        if not close_date:
            continue

        close_dt = datetime.fromisoformat(close_date.replace('Z', '+00:00'))
        close_date_str = close_dt.strftime("%Y-%m-%d")

        # Check period boundaries
        if period.get("start") and close_date_str < period["start"]:
            continue
        if period.get("end") and close_date_str > period["end"]:
            continue

        period_filtered_deals.append(deal)

    print(f"After period filter: {len(period_filtered_deals)} deals")

    # Compute cycle times
    cycle_times = []
    for deal in period_filtered_deals:
        create_date = deal.get('create_date')
        close_date = deal.get('close_date')

        if not create_date or not close_date:
            continue

        create_dt = datetime.fromisoformat(create_date.replace('Z', '+00:00'))
        close_dt = datetime.fromisoformat(close_date.replace('Z', '+00:00'))
        days = (close_dt - create_dt).days

        # Should already be filtered by is_valid_cycle_deal, but double-check
        if days >= 0:
            cycle_times.append(days)

    # Handle empty result
    if not cycle_times:
        return {
            "days": None,
            "sample_size": 0,
            "period": period,
            "distribution": {"p25": None, "p50": None, "p75": None},
            "exclusions": exclusions,
            "error": "No deals found matching filters"
        }

    # Compute aggregation
    cycle_times.sort()
    n = len(cycle_times)

    if aggregation == "median":
        if n % 2 == 0:
            result_value = (cycle_times[n // 2 - 1] + cycle_times[n // 2]) / 2
        else:
            result_value = cycle_times[n // 2]
    elif aggregation == "mean":
        result_value = sum(cycle_times) / len(cycle_times)
    else:
        raise ValueError(f"Unknown aggregation: {aggregation}")

    # Compute distribution (percentiles)
    def percentile(data, p):
        k = (len(data) - 1) * p
        f = int(k)
        c = k - f
        if f + 1 < len(data):
            return data[f] * (1 - c) + data[f + 1] * c
        else:
            return data[f]

    distribution = {
        "p25": percentile(cycle_times, 0.25),
        "p50": percentile(cycle_times, 0.50),
        "p75": percentile(cycle_times, 0.75),
    }

    return {
        "days": round(result_value, 1),
        "sample_size": n,
        "period": period,
        "distribution": {
            "p25": round(distribution["p25"], 1),
            "p50": round(distribution["p50"], 1),
            "p75": round(distribution["p75"], 1),
        },
        "exclusions": exclusions
    }


if __name__ == "__main__":
    from scripts.metrics.period_utils import period_all_time, period_quarter, format_period

    print("=" * 80)
    print("CYCLE TIME - PARAMETERIZED")
    print("=" * 80)
    print()

    # Test 1: All-time
    print("Test 1: All-time (should match verified 52 days)")
    result = cycle_time(period=None)
    print(f"  Days: {result['days']}")
    print(f"  Sample size: {result['sample_size']}")
    print(f"  Period: {format_period(result['period'])}")
    print(f"  Distribution: p25={result['distribution']['p25']}, "
          f"p50={result['distribution']['p50']}, "
          f"p75={result['distribution']['p75']}")
    print(f"  Exclusions: {result['exclusions']}")
    print()

    # Test 2: Q1 2026
    print("Test 2: Q1 2026")
    result = cycle_time(period=period_quarter("Q1 2026"))
    print(f"  Days: {result['days']}")
    print(f"  Sample size: {result['sample_size']}")
    print(f"  Period: {format_period(result['period'])}")
    print(f"  Distribution: p25={result['distribution']['p25']}, "
          f"p50={result['distribution']['p50']}, "
          f"p75={result['distribution']['p75']}")
    print()

    # Test 3: Q2 2026
    print("Test 3: Q2 2026")
    result = cycle_time(period=period_quarter("Q2 2026"))
    print(f"  Days: {result['days']}")
    print(f"  Sample size: {result['sample_size']}")
    print(f"  Period: {format_period(result['period'])}")
    print(f"  Distribution: p25={result['distribution']['p25']}, "
          f"p50={result['distribution']['p50']}, "
          f"p75={result['distribution']['p75']}")
    print()
