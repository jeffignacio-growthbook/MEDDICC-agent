"""
Test H1 fix: in-memory _pm_in_scope() no longer strips explicitly-requested pipeline deals.

Bug: When pipeline_filter='renewal' set pipeline_id to the renewal pipeline,
the DB correctly loaded those deals, but _pm_in_scope() was stripping them
back out because excluded_pipelines contains that ID.

Fix: Removed redundant pipeline exclusion check from _pm_in_scope() since
pipeline scoping is already handled server-side at query construction.
"""
from api.handlers import _pm_in_scope


def test_renewal_pipeline_deals_no_longer_filtered_out():
    """After H1 fix, renewal deals should pass _pm_in_scope() check."""
    excluded_pipelines = ['866608541']  # Renewal pipeline ID from config
    stage_cfg = {}
    is_in_scope_mock = lambda *args: True  # Mock stage scoping function

    # Before H1 fix: this returned False (incorrectly filtered out)
    # After H1 fix: this should return True (pipeline scope handled at query level)
    renewal_row = {
        'pipeline_id': '866608541',
        'stage_id': '12345',
        'deal_id': 'test_renewal'
    }

    result = _pm_in_scope(renewal_row, excluded_pipelines, stage_cfg, is_in_scope_mock)

    assert result is True, (
        "H1 fix failed: renewal pipeline deal was filtered out by _pm_in_scope(). "
        "Pipeline exclusions should be handled at query level, not in-memory."
    )


def test_regular_pipeline_deals_still_pass():
    """Regular pipeline deals should continue to pass scoping check."""
    excluded_pipelines = ['866608541']
    stage_cfg = {}
    is_in_scope_mock = lambda *args: True

    regular_row = {
        'pipeline_id': 'default',
        'stage_id': '12345',
        'deal_id': 'test_regular'
    }

    result = _pm_in_scope(regular_row, excluded_pipelines, stage_cfg, is_in_scope_mock)
    assert result is True


def test_closed_won_deals_still_filtered():
    """Stage-level filtering should still work (won/lost stages excluded)."""
    from api.handlers import is_won

    excluded_pipelines = []
    stage_cfg = {}
    is_in_scope_mock = lambda *args: True

    # Mock a Closed Won stage ID (this is environment-specific, but the logic should work)
    # We'll use a real stage ID if available, else skip
    try:
        # Try to get actual won stage IDs
        from field_semantics import _STAGE_WON
        if not _STAGE_WON:
            return  # Skip if no won stages configured
        won_stage_id = list(_STAGE_WON)[0]
    except (ImportError, IndexError):
        return  # Skip if can't import

    closed_won_row = {
        'pipeline_id': 'default',
        'stage_id': str(won_stage_id),
        'deal_id': 'test_won'
    }

    result = _pm_in_scope(closed_won_row, excluded_pipelines, stage_cfg, is_in_scope_mock)
    assert result is False, "Closed Won deals should still be filtered out"


def test_null_stage_deals_still_counted():
    """Null-stage rows should still count (treated as 'unknown')."""
    excluded_pipelines = []
    stage_cfg = {}
    is_in_scope_mock = lambda *args: True

    null_stage_row = {
        'pipeline_id': 'default',
        'stage_id': None,
        'deal_id': 'test_null_stage'
    }

    result = _pm_in_scope(null_stage_row, excluded_pipelines, stage_cfg, is_in_scope_mock)
    assert result is True, "Null-stage deals should count as 'unknown'"
