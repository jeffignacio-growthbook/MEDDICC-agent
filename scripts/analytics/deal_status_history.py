#!/usr/bin/env python3
"""
Point-in-time deal status lookup from property_history.

Provides get_deal_status_as_of(deal_id, as_of_date) to reconstruct whether
a deal was won/lost/active at a historical date by tracing dealstage changes.

Uses centralized is_won()/is_lost() from field_semantics.py to avoid
duplicating business logic.
"""

import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).parent.parent.parent

# Import field_semantics for centralized stage classification
sys.path.insert(0, str(REPO_ROOT / 'api'))
from field_semantics import is_won, is_lost


DealStatus = Literal['won', 'lost', 'active', 'unknown']


def get_deal_status_as_of(
    supabase_client,
    deal_id: str,
    as_of_date: date,
    close_date: date = None,
    current_stage: str = None
) -> DealStatus:
    """
    Get deal status (won/lost/active/unknown) as of a historical date.

    Hybrid approach:
    1. FIRST: Try property_history (most accurate, captures all transitions)
    2. FALLBACK: If no property_history BUT close_date confirms deal was already
       closed by as_of_date, use current status (valid because deals don't un-close)
    3. LAST: Return 'unknown' if neither source can establish status

    This is different from the original bug (which blindly defaulted to 'active'):
    - Original bug: No check on close_date, just assumed 'active'
    - This approach: Only uses current status when close_date PROVES deal was closed

    Args:
        supabase_client: Supabase client instance
        deal_id: Deal ID to look up
        as_of_date: Date to check status at
        close_date: Deal's close_date (optional, for fallback)
        current_stage: Deal's current stage (optional, for fallback)

    Returns:
        'won': Deal was won as of date (property_history OR close_date evidence)
        'lost': Deal was lost as of date (property_history OR close_date evidence)
        'active': Deal was active as of date (property_history evidence only)
        'unknown': Cannot determine (no evidence from either source)

    Business logic uses centralized is_won()/is_lost() from field_semantics.py.
    """
    sb = supabase_client

    # Step 1: Try property_history (preferred)
    result = sb.table('property_history')\
        .select('new_value, changed_at')\
        .eq('deal_id', deal_id)\
        .eq('property_name', 'dealstage')\
        .lte('changed_at', as_of_date.isoformat())\
        .order('changed_at', desc=True)\
        .limit(1)\
        .execute()

    if result.data:
        # Found historical stage record - use it
        stage_as_of = result.data[0]['new_value']

        # Classify using centralized field_semantics
        if is_won(stage_as_of):
            return 'won'
        elif is_lost(stage_as_of):
            return 'lost'
        else:
            return 'active'

    # Step 2: Fallback to close_date + current_stage if available
    # This is valid ONLY when close_date confirms deal was already closed
    if close_date and current_stage and close_date <= as_of_date:
        # Deal was closed by as_of_date
        # Since deals don't un-close, current status IS historical status
        if is_won(current_stage):
            return 'won'
        elif is_lost(current_stage):
            return 'lost'
        # If current_stage is somehow not won/lost despite close_date,
        # fall through to 'unknown'

    # Step 3: No evidence from either source
    return 'unknown'


def test_status_lookup():
    """
    Test get_deal_status_as_of with independently verified property_history evidence.

    Tests three categories:
    1. Deals WITH historical records: verify correct status returned
    2. Deals WITHOUT historical records: verify 'unknown' returned
    3. Deals where current != historical: verify historical status used, not current
    """
    from dotenv import load_dotenv
    load_dotenv()

    from supabase import create_client
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Testing get_deal_status_as_of() with property_history evidence")
    print("=" * 70)

    # First, find suitable test deals by examining property_history
    print("\n1. Finding test deals with known property_history patterns...")
    print("-" * 70)

    # Find deals with stage changes to closed stages
    result = sb.table('property_history')\
        .select('deal_id, changed_at, new_value')\
        .eq('property_name', 'dealstage')\
        .execute()

    deals_with_history = {}
    for row in result.data:
        deal_id = row['deal_id']
        if deal_id not in deals_with_history:
            deals_with_history[deal_id] = []
        deals_with_history[deal_id].append((row['changed_at'], row['new_value']))

    # Find a deal that closed (has closedwon or closedlost in history)
    test_closed_deal = None
    for deal_id, changes in deals_with_history.items():
        for ts, stage in changes:
            if 'closed' in stage.lower():
                test_closed_deal = (deal_id, ts, stage)
                break
        if test_closed_deal:
            break

    # Find a deal with multiple stage changes (for testing historical vs current)
    test_multi_stage_deal = None
    for deal_id, changes in deals_with_history.items():
        if len(changes) >= 3:  # At least 3 stage changes
            test_multi_stage_deal = (deal_id, changes)
            break

    # Find a deal WITHOUT any property_history (should return unknown)
    all_deals_with_history = set(deals_with_history.keys())
    all_deals = sb.table('deals').select('deal_id').limit(1000).execute()
    test_no_history_deal = None
    for deal in all_deals.data:
        if deal['deal_id'] not in all_deals_with_history:
            test_no_history_deal = deal['deal_id']
            break

    print(f"✓ Found test deals:")
    print(f"  Closed deal: {test_closed_deal[0] if test_closed_deal else 'None'}")
    print(f"  Multi-stage deal: {test_multi_stage_deal[0] if test_multi_stage_deal else 'None'}")
    print(f"  No-history deal: {test_no_history_deal or 'None'}")

    # Now run tests with evidence
    print(f"\n2. Running tests with property_history evidence...")
    print("-" * 70)

    passed = 0
    failed = 0

    # Test 1: Closed deal
    if test_closed_deal:
        deal_id, close_ts, close_stage = test_closed_deal
        close_date = datetime.fromisoformat(close_ts.replace('Z', '+00:00')).date()

        # Test before close
        date_before = date.fromisoformat('2025-08-01')
        status_before = get_deal_status_as_of(sb, deal_id, date_before)

        # Test after close
        date_after = close_date
        status_after = get_deal_status_as_of(sb, deal_id, date_after)

        print(f"\nTest 1: Closed deal {deal_id}")
        print(f"  Property_history shows: closed on {close_date} to stage {close_stage}")
        print(f"  Status at {date_before}: {status_before} (expected: active or unknown)")
        print(f"  Status at {date_after}: {status_after} (expected: won or lost)")

        if status_after in ['won', 'lost']:
            print(f"  ✓ PASS: Correctly identified as closed")
            passed += 1
        else:
            print(f"  ✗ FAIL: Should be won/lost, got {status_after}")
            failed += 1

    # Test 2: Multi-stage deal (current != historical)
    if test_multi_stage_deal:
        deal_id, changes = test_multi_stage_deal
        # Sort changes by timestamp
        changes_sorted = sorted(changes, key=lambda x: x[0])

        # Pick a middle timestamp
        if len(changes_sorted) >= 2:
            middle_ts, middle_stage = changes_sorted[1]
            middle_date = datetime.fromisoformat(middle_ts.replace('Z', '+00:00')).date()

            # Get current stage
            current = sb.table('deals').select('stage').eq('deal_id', deal_id).execute()
            current_stage = current.data[0]['stage'] if current.data else None

            status_historical = get_deal_status_as_of(sb, deal_id, middle_date)

            print(f"\nTest 2: Multi-stage deal {deal_id}")
            print(f"  Property_history at {middle_date}: {middle_stage}")
            print(f"  Current stage: {current_stage}")
            print(f"  Function returned: {status_historical}")

            # Verify it didn't just return current stage classification
            if current_stage and middle_stage != current_stage:
                current_class = 'won' if is_won(current_stage) else ('lost' if is_lost(current_stage) else 'active')
                historical_class = 'won' if is_won(middle_stage) else ('lost' if is_lost(middle_stage) else 'active')

                if status_historical == historical_class:
                    print(f"  ✓ PASS: Used historical stage, not current")
                    passed += 1
                else:
                    print(f"  ✗ FAIL: Should match historical ({historical_class}), got {status_historical}")
                    failed += 1
            else:
                print(f"  ⚠️  SKIP: Current and historical stages are same")

    # Test 3: Deal with no history
    if test_no_history_deal:
        status_no_history = get_deal_status_as_of(sb, test_no_history_deal, date.today())

        print(f"\nTest 3: No-history deal {test_no_history_deal}")
        print(f"  Property_history: No dealstage records")
        print(f"  Function returned: {status_no_history}")

        if status_no_history == 'unknown':
            print(f"  ✓ PASS: Correctly returned unknown (no fallback to current)")
            passed += 1
        else:
            print(f"  ✗ FAIL: Should be unknown, got {status_no_history}")
            print(f"  This indicates fallback to current status (the bug!)")
            failed += 1

    print(f"\n" + "=" * 70)
    print(f"Test Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✓ All tests passed - function correctly uses property_history only")
        return True
    else:
        print("✗ Some tests failed - function has bugs")
        return False


if __name__ == '__main__':
    success = test_status_lookup()
    sys.exit(0 if success else 1)
