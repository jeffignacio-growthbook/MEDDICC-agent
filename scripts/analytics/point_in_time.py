"""
Point-in-time field reconstruction for historical pipeline snapshots.

Shared reconstruction logic used by both Method 1 (prospective snapshots)
and Method 2 (historical backfill). This module is the single source of truth
for point-in-time lookups - both snapshot_deals.py and backfill_snapshots.py
import from here to ensure they cannot diverge.

Strictly backward-looking: a history entry after the snapshot date must
never be selected. No history before the snapshot date means null, never
forward-fill, never a default.

BEFORE ADDING A FILTER THAT NARROWS A SHARED WRITE PATH, ask what else reads
the table for a different purpose. deals_snapshot looked like it served
pipeline-conversion analysis alone, so scoping the write to the analytics
population looked free. It is not: config/client.yaml marks the renewal
pipeline `analyze: false  # MEDDICC agent skips; analytics INCLUDES for
GRR/NRR`, and that one comment is the only thing recording that GRR/NRR reads
the same rows. Scoping the write would have dropped 221 of 376 rows and broken
a consumer nobody was thinking about, unrecoverably without a refetch. Scope
on read, never on write — and check the consumers before narrowing anything
shared.

Confidence labels reflect history coverage:
- 'exact': Field history exists and covers this date (change at or before it)
- 'cleared': An entry at or before this date exists but its value is null —
  the field was actively cleared. Distinct from 'pre_history': the deal WAS
  staged and then unstaged, versus never staged at all. Both read as open,
  but they are different facts and the inclusion rule may want to separate
  them later, so they are recorded separately rather than merged.
- 'pre_history': Deal existed but no field history at or before this date
  (null, not guessed)
- 'no_history': No field history available for this deal at all
"""
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'api'))

from field_semantics import OUTCOME_BUCKETS, stage_bucket


class UnclassifiableStageError(ValueError):
    """
    Raised when a stage id has no classification in field_semantics.

    Reconstruction must never guess at a stage it cannot classify. The
    graceful path (field_semantics.is_open treats an unknown stage as open)
    is correct for the CRO agent, which degrades rather than crashes on a
    live query. It is wrong here: reaching back to 2023 means meeting stage
    ids that have since been retired, and failing open silently promotes
    them into the open-pipeline denominator, producing plausible wrong
    numbers instead of an error.
    """


def is_terminal_stage(stage_id: Optional[str]) -> bool:
    """
    Strict terminal (won/lost) test for point-in-time reconstruction.

    Returns False for None: that is the 'pre_history' case, where the deal
    existed but history does not reach back to this date. The caller
    distinguishes it via the confidence label; it is not a stage value.

    Raises:
        UnclassifiableStageError: the stage id is not in field_semantics.
            Add it to config/field_semantics.yaml with its correct bucket
            and regenerate, or mark it excluded — never let it default.
    """
    if stage_id is None:
        return False

    bucket = stage_bucket(stage_id)
    if bucket == 'unknown':
        raise UnclassifiableStageError(
            f"Stage id {stage_id!r} has no classification in "
            f"config/field_semantics.yaml. Reconstruction refuses to treat "
            f"it as open. Add it with its correct bucket and re-run "
            f"scripts/generate_field_semantics.py, or mark it excluded."
        )
    return bucket in OUTCOME_BUCKETS['won'] or bucket in OUTCOME_BUCKETS['lost']


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
        - confidence: 'exact', 'cleared', 'pre_history', 'no_history'
        - has_history: True if property history exists

    Confidence definitions:
    - 'exact': Stage history exists and covers this date (change occurred at or before it)
    - 'cleared': An entry at or before this date exists but carries a null value —
      the stage was actively cleared. Not the same fact as 'pre_history'.
    - 'pre_history': Deal existed but had no stage entry at or before this date (null, not guessed)
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
    # Whether any entry at all fell at or before the snapshot date. Without
    # this, a cleared stage (entry present, value null) is indistinguishable
    # from history that starts later — both leave current_stage as None.
    entry_covers_date = False

    for entry in sorted_history:
        entry_ts = entry['timestamp']

        if entry_ts <= snapshot_ts:
            current_stage = entry['value']
            entry_covers_date = True
        else:
            # We've passed the snapshot date (strictly backward-looking)
            break

    if current_stage is None:
        if entry_covers_date:
            # An entry covers this date but its value is null: the stage was
            # actively cleared. Reads as open, same as pre_history, but it is
            # a different fact and is labelled as one.
            return None, 'cleared', True
        # No stage entry at or before this snapshot date
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
        - confidence: 'exact', 'cleared', 'pre_history', 'no_history'

    Same backward-looking logic as stage reconstruction, including the
    cleared-versus-never-set distinction.
    """
    if deal_id not in field_history:
        return None, 'no_history'

    history = field_history[deal_id]['history']

    if not history:
        return None, 'no_history'

    sorted_history = sorted(history, key=lambda x: x['timestamp'])
    snapshot_ts = snapshot_date.isoformat()
    current_value = None
    entry_covers_date = False

    for entry in sorted_history:
        if entry['timestamp'] <= snapshot_ts:
            current_value = entry['value']
            entry_covers_date = True
        else:
            # Strictly backward-looking
            break

    if current_value is None:
        return None, ('cleared' if entry_covers_date else 'pre_history')

    return current_value, 'exact'


def is_deal_open_at_date(
    deal_create_date: datetime,
    deal_stage_at_date: Optional[str],
    snapshot_date: datetime,
    is_terminal_stage_func=is_terminal_stage
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
        is_terminal_stage_func: Function(stage_id) -> bool (checks if stage is
            won/lost). Defaults to the strict is_terminal_stage above, which
            raises on a stage id field_semantics cannot classify.

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


def load_scope_config(config=None):
    """
    Analytics scoping from config/client.yaml, shared so no caller reinvents it.

    Returns (excluded_pipeline_ids, {stage_id: {...}}).
    """
    if config is None:
        import yaml
        config_path = Path(__file__).parent.parent.parent / 'config' / 'client.yaml'
        config = yaml.safe_load(config_path.read_text())

    excluded_pipelines = {str(p['id'])
                          for p in config.get('pipelines', {}).get('excluded', [])}
    default_qso = config['pipeline'].get('qualified_stage_order', 1)
    stages = {}
    for pipeline in config['pipeline']['pipelines']:
        qso = pipeline.get('qualified_stage_order', default_qso)
        for stage in pipeline['stages']:
            stages[str(stage['id'])] = {
                'name': stage['name'],
                'order': stage['order'],
                'excluded': bool(stage.get('exclude_from_analysis')),
                'qualified_stage_order': qso,
            }
    return excluded_pipelines, stages


def is_deal_in_analytics_scope(
    stage_at_date: Optional[str],
    pipeline_id: Optional[str],
    excluded_pipelines=None,
    stage_cfg=None,
) -> bool:
    """
    Whether a deal belongs in a pipeline-conversion population at some date.

    Scoping is NOT the inclusion rule and must never gate what gets WRITTEN.
    Method 1 writes every pipeline and stage on purpose: the renewal pipeline
    carries `analyze: false  # MEDDICC agent skips; analytics INCLUDES for
    GRR/NRR`, so dropping renewals from deals_snapshot would destroy the rows
    GRR/NRR reads. Scope on the way out, never on the way in.

    Excluded by: a pipeline in pipelines.excluded; a stage flagged
    exclude_from_analysis (Meeting Set, Disqualified); a stage below its
    pipeline's qualified_stage_order.

    A None stage cannot be scoped — there is no stage to judge — so it returns
    False and the caller should count it rather than assume either way.
    """
    if excluded_pipelines is None or stage_cfg is None:
        excluded_pipelines, stage_cfg = load_scope_config()

    if pipeline_id is not None and str(pipeline_id) in excluded_pipelines:
        return False
    if stage_at_date is None:
        return False
    cfg = stage_cfg.get(str(stage_at_date))
    if cfg is None or cfg['excluded']:
        return False
    return cfg['order'] >= cfg['qualified_stage_order']
