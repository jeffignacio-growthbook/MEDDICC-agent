"""
Cross-Quarter Qualification Week Lookup

Handles deals created in one quarter but closed in another (carry-over deals).

Example:
  - Deal created Aug 9, 2025 (FY2026 Q2)
  - Deal closed Nov 7, 2025 (FY2026 Q3)
  - Qualification happened in Q2, but Q3 metrics shouldn't exclude it

Solution: When computing qualification_week for a deal, check prior quarters
if create_date < quarter_start.
"""

from typing import Optional, Tuple, List
from datetime import datetime
from collections import defaultdict


def get_fiscal_quarter_for_date(date_str: str) -> Optional[str]:
    """
    Map a date to its fiscal quarter.

    Args:
        date_str: ISO date string (YYYY-MM-DD)

    Returns:
        Fiscal quarter ID (e.g., 'FY2026 Q3') or None if before tracking started
    """
    # Fiscal quarters mapping
    QUARTERS = [
        ('FY2026 Q2', '2025-08-01', '2025-10-31'),
        ('FY2026 Q3', '2025-11-01', '2026-01-31'),
        ('FY2026 Q4', '2026-02-01', '2026-04-30'),
        ('FY2027 Q1', '2026-05-01', '2026-07-31'),
    ]

    try:
        date = datetime.fromisoformat(date_str[:10])
    except:
        return None

    for quarter_id, start_str, end_str in QUARTERS:
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)
        if start <= date <= end:
            return quarter_id

    return None


def get_quarters_to_check(create_date: str, close_quarter: str) -> List[str]:
    """
    Determine which quarters to search for qualification snapshots.

    Args:
        create_date: Deal create_date (YYYY-MM-DD)
        close_quarter: Fiscal quarter where deal closed (e.g., 'FY2026 Q3')

    Returns:
        List of quarters to check, in order (earliest first)

    Example:
        Deal created in Q2, closed in Q3 → ['FY2026 Q2', 'FY2026 Q3']
        Deal created in Q3, closed in Q3 → ['FY2026 Q3']
    """
    create_quarter = get_fiscal_quarter_for_date(create_date)

    if not create_quarter or create_quarter == close_quarter:
        # Deal created and closed in same quarter, only check close quarter
        return [close_quarter]

    # Deal spans quarters - check all quarters from create to close
    QUARTER_ORDER = [
        'FY2026 Q2',
        'FY2026 Q3',
        'FY2026 Q4',
        'FY2027 Q1',
    ]

    try:
        create_idx = QUARTER_ORDER.index(create_quarter)
        close_idx = QUARTER_ORDER.index(close_quarter)

        if create_idx <= close_idx:
            return QUARTER_ORDER[create_idx:close_idx + 1]
        else:
            # Shouldn't happen (deal closed before created), but handle gracefully
            return [close_quarter]
    except ValueError:
        # Quarter not in tracking period
        return [close_quarter]


def find_qualification_week_cross_quarter(
    supabase,
    deal_id: str,
    create_date: str,
    close_date: str,
    close_quarter: str,
    excluded_pipelines: set,
    stage_cfg: dict
) -> Optional[Tuple[int, str]]:
    """
    Find first qualification week for a deal, checking prior quarters if needed.

    Args:
        supabase: Supabase client
        deal_id: Deal ID to search for
        create_date: Deal create_date
        close_date: Deal close_date
        close_quarter: Quarter where deal closed
        excluded_pipelines: Set of excluded pipeline IDs
        stage_cfg: Stage configuration from load_scope_config()

    Returns:
        Tuple of (week_of_quarter, fiscal_quarter) or None if never qualified

    Example:
        Deal created Aug 9 (Q2), closed Nov 7 (Q3)
        - Checks Q2 snapshots first
        - Finds qualification in Q2 week 3
        - Returns (3, 'FY2026 Q2')
        - Q3 metrics now include this deal with correct qualification_week
    """
    from scripts.analytics.point_in_time import is_deal_in_analytics_scope
    from scripts.utils.pagination import fetch_all_rows_by_filters

    quarters_to_check = get_quarters_to_check(create_date, close_quarter)

    for quarter in quarters_to_check:
        # Get all snapshots for this deal in this quarter
        snapshots = fetch_all_rows_by_filters(
            supabase,
            'deals_snapshot',
            'deal_id, week_of_quarter, stage_id, pipeline_id',
            eq={'fiscal_quarter': quarter, 'deal_id': deal_id}
        )

        if not snapshots:
            continue

        # Sort by week and find first qualified snapshot
        snapshots.sort(key=lambda x: x.get('week_of_quarter', 99))

        for snap in snapshots:
            if is_deal_in_analytics_scope(
                stage_at_date=snap.get('stage_id'),
                pipeline_id=snap.get('pipeline_id'),
                excluded_pipelines=excluded_pipelines,
                stage_cfg=stage_cfg
            ):
                return (snap.get('week_of_quarter'), quarter)

    # Never qualified in any checked quarter
    return None


def test_carry_over_deals():
    """
    Test function to verify the 3 known carry-over deals are captured.
    """
    import os
    import sys
    from pathlib import Path
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent.parent / '.env'
    load_dotenv(env_path)
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from api.db import get_supabase
    from scripts.analytics.point_in_time import load_scope_config

    supabase = get_supabase()
    excluded_pipelines, stage_cfg = load_scope_config()

    # The 3 known carry-over deals
    CARRY_OVER_DEALS = [
        {
            'company': 'Fellow',
            'deal_id': 'TBD',  # Need to lookup
            'create_date': '2025-08-09',
            'close_date': '2025-11-07',
            'close_quarter': 'FY2026 Q3',
            'expected_create_quarter': 'FY2026 Q2'
        },
        {
            'company': 'Yeet!',
            'deal_id': 'TBD',
            'create_date': '2026-01-27',
            'close_date': '2026-03-02',
            'close_quarter': 'FY2026 Q4',
            'expected_create_quarter': 'FY2026 Q3'
        },
        {
            'company': 'Wellhub',
            'deal_id': 'TBD',
            'create_date': '2026-04-30',
            'close_date': '2026-05-23',
            'close_quarter': 'FY2027 Q1',
            'expected_create_quarter': 'FY2027 Q1'  # Actually boundary case
        },
    ]

    print("=" * 80)
    print("CROSS-QUARTER QUALIFICATION TEST")
    print("=" * 80)
    print()

    for test_case in CARRY_OVER_DEALS:
        print(f"Testing: {test_case['company']}")
        print(f"  Created: {test_case['create_date']} (expected {test_case['expected_create_quarter']})")
        print(f"  Closed: {test_case['close_date']} ({test_case['close_quarter']})")

        quarters = get_quarters_to_check(test_case['create_date'], test_case['close_quarter'])
        print(f"  Quarters to check: {quarters}")

        # TODO: Add actual deal_id lookup and qualification check
        # result = find_qualification_week_cross_quarter(...)
        # print(f"  Result: {result}")

        print()


if __name__ == '__main__':
    test_carry_over_deals()
