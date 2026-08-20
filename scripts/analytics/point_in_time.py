"""
Point-in-time field reconstruction for historical pipeline snapshots.

Shared reconstruction logic used by both Method 1 (prospective snapshots)
and Method 2 (historical backfill). This module is the single source of truth
for point-in-time lookups - both snapshot_deals.py and backfill_snapshots.py
import from here to ensure they cannot diverge.

Strictly backward-looking: a history entry after the snapshot date must
never be selected. No history before the snapshot date means null, never
forward-fill, never a default.

Confidence labels reflect history coverage:
- 'exact': Field history exists and covers this date (change at or before it)
- 'pre_history': Deal existed but no field history before this date (null, not guessed)
- 'no_history': No field history available for this deal at all
"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def get_stage_at_date(
    property_history: Dict,
    deal_id: str,
    snapshot_date: datetime
) -> Tuple[Optional[str], str, bool]:
    """
    Get stage ID for a deal at a specific snapshot date.

    Args:
        property_history: Dict mapping deal_id to {'history': [{'timestamp': str, 'value': str}]}
        deal_id: Deal identifier
        snapshot_date: Point-in-time date for reconstruction

    Returns:
        (stage_id, confidence, has_history)
        - stage_id: The stage at snapshot_date (or None)
        - confidence: 'exact', 'pre_history', 'no_history'
        - has_history: True if property history exists

    Confidence definitions:
    - 'exact': Stage history exists and covers this date (change occurred at or before it)
    - 'pre_history': Deal existed but had no stage change at or before this date (null, not guessed)
    - 'no_history': No stage history available for this deal at all
    """
    if deal_id not in property_history:
        # No property history available
        return None, 'no_history', False

    history = property_history[deal_id]['history']

    if not history:
        # Deal exists but has no stage history
        return None, 'no_history', False

    # Sort history by timestamp (oldest first)
    sorted_history = sorted(history, key=lambda x: x['timestamp'])

    # Find the most recent stage change before or at snapshot_date
    # Strictly backward-looking: entries after snapshot_date are never selected
    snapshot_ts = snapshot_date.isoformat()
    current_stage = None

    for entry in sorted_history:
        entry_ts = entry['timestamp']

        if entry_ts <= snapshot_ts:
            current_stage = entry['value']
        else:
            # We've passed the snapshot date (strictly backward-looking)
            break

    if current_stage is None:
        # No stage change before this snapshot date
        # Deal existed but history doesn't cover this early date
        return None, 'pre_history', True

    # We have a stage from history that covers this date
    # This is 'exact' regardless of whether the change landed on the exact same day
    # (The old definition marked almost everything 'interpolated' and made correct data look unreliable)
    confidence = 'exact'

    return current_stage, confidence, True


def get_field_at_date(
    field_history: Dict,
    deal_id: str,
    snapshot_date: datetime
) -> Tuple[Optional[str], str]:
    """
    Generic point-in-time field lookup (amount, closedate, etc).

    Args:
        field_history: Dict mapping deal_id to {'history': [{'timestamp': str, 'value': any}]}
        deal_id: Deal identifier
        snapshot_date: Point-in-time date for reconstruction

    Returns:
        (value, confidence)
        - value: Field value at snapshot_date (or None)
        - confidence: 'exact', 'pre_history', 'no_history'

    Same backward-looking logic as stage reconstruction.
    """
    if deal_id not in field_history:
        return None, 'no_history'

    history = field_history[deal_id]['history']

    if not history:
        return None, 'no_history'

    sorted_history = sorted(history, key=lambda x: x['timestamp'])
    snapshot_ts = snapshot_date.isoformat()
    current_value = None

    for entry in sorted_history:
        if entry['timestamp'] <= snapshot_ts:
            current_value = entry['value']
        else:
            # Strictly backward-looking
            break

    if current_value is None:
        return None, 'pre_history'

    return current_value, 'exact'


def is_deal_open_at_date(
    deal_create_date: datetime,
    deal_stage_at_date: Optional[str],
    snapshot_date: datetime,
    is_terminal_stage_func
) -> bool:
    """
    Inclusion rule for pipeline snapshots (shared by Method 1 and Method 2).

    A deal belongs in the snapshot for date D if:
    - create_date <= D, AND
    - deal had not reached a terminal stage as of D

    Args:
        deal_create_date: Date deal was created
        deal_stage_at_date: Stage of deal at snapshot_date (or None if no history)
        snapshot_date: Snapshot date
        is_terminal_stage_func: Function(stage_id) -> bool (checks if stage is won/lost)

    Returns:
        True if deal should be in snapshot, False otherwise

    This is the single source of truth for inclusion logic - both snapshot_deals.py
    and backfill_snapshots.py import this function so they cannot diverge.
    """
    # Must be created before or on snapshot date
    if deal_create_date > snapshot_date:
        return False

    # If we have no stage history at this date, deal is open (hasn't progressed to terminal)
    if deal_stage_at_date is None:
        return True

    # If stage is not terminal (won/lost), deal is open
    if not is_terminal_stage_func(deal_stage_at_date):
        return True

    # Deal is in terminal stage, not open
    return False
