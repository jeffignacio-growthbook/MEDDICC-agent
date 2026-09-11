"""
Deterministic point-in-time snapshot diffing.

2026-09-11 (round 5): three consecutive live-test failures all asked the
model to compute a two-snapshot stage-change diff in free text, and the
model failed each time in a different way — shipping an unfinished
scratchpad table, narrating twice instead of tool-calling and exhausting
the retry budget, or (once those were fixed) losing its own enrichment
lookup because the finalize shortcut never showed it the data. Three
different failure MECHANISMS, one root cause: diffing two row sets by
deal_id is a deterministic set operation, not a reasoning task an LLM
should ever be asked to perform in prose.

diff_snapshots() does that computation in code, exactly and instantly.
Wired into api/router.py's dynamic_query_loop._finalize_from_data(), it
turns the model's job from "compute the diff yourself" into "write a
clean answer from an already-computed structured result" — a synthesis
task, not a reasoning task, and one that can never partially fail into
scratchpad narration because there is nothing left for the model to
compute.
"""
from typing import Optional


def _stage_changed(prior_row: dict, current_row: dict) -> bool:
    """A deal counts as stage-changed if its stage_order differs between
    snapshots. Falls back to stage_id when either row's stage_order is
    missing (a backfill gap should not silently hide a real stage
    change just because the numeric order wasn't captured)."""
    prior_order = prior_row.get("stage_order")
    current_order = current_row.get("stage_order")
    if prior_order is not None and current_order is not None:
        return prior_order != current_order
    return prior_row.get("stage_id") != current_row.get("stage_id")


def _direction(prior_row: dict, current_row: dict) -> str:
    """'advanced' | 'regressed' | 'unknown' (stage_order missing on
    either side, so direction can't be determined even though the
    stage_id itself differs)."""
    prior_order = prior_row.get("stage_order")
    current_order = current_row.get("stage_order")
    if prior_order is None or current_order is None:
        return "unknown"
    if current_order > prior_order:
        return "advanced"
    if current_order < prior_order:
        return "regressed"
    return "unknown"  # stage_id differs but stage_order tied/equal — data oddity, not a direction


def diff_snapshots(current_rows: list, prior_rows: list) -> dict:
    """
    Deterministically diff two point-in-time deals_snapshot row sets.

    Args:
        current_rows: rows from the CURRENT (more recent) snapshot_date.
        prior_rows: rows from the PRIOR (earlier) snapshot_date.
        Each row should carry `deal_id`; `stage_id`/`stage_order` and
        `owner_email` are used when present but their absence never
        raises — see _stage_changed()/_direction() above.

    Returns:
        {
            "stage_changes": [
                {
                    "deal_id": str,
                    "prior_stage_id": ..., "prior_stage_order": int | None,
                    "current_stage_id": ..., "current_stage_order": int | None,
                    "direction": "advanced" | "regressed" | "unknown",
                    "current_row": {...},  # full current row (region/segment/owner_email/deal_value/etc.)
                    "prior_row": {...},
                },
                ...
            ],
            "population_entries": [ {..full current row..}, ... ],  # deal_id in current, not prior
            "population_exits":   [ {..full prior row..}, ... ],    # deal_id in prior, not current
            "owner_changes": [
                {"deal_id": str, "prior_owner_email": ..., "current_owner_email": ...,
                 "stage_id": ...},
                ...
            ],  # present in both, SAME stage, different owner_email — real information,
                # but out of scope for "changed stage" itself; surfaced as its own list
                # rather than folded into stage_changes or silently dropped.
            "unchanged_deal_ids": [...],  # present in both, same stage, same owner
            "current_count": int,
            "prior_count": int,
            "skipped_missing_deal_id": int,  # rows on either side with no deal_id — can't be diffed
        }

    Pure and side-effect-free: no DB access, no LLM calls. Safe to call
    with any two row lists, including empty ones.
    """
    current_by_id = {}
    prior_by_id = {}
    skipped = 0

    for row in current_rows or []:
        did = row.get("deal_id") if isinstance(row, dict) else None
        if did is None:
            skipped += 1
            continue
        current_by_id[str(did)] = row

    for row in prior_rows or []:
        did = row.get("deal_id") if isinstance(row, dict) else None
        if did is None:
            skipped += 1
            continue
        prior_by_id[str(did)] = row

    current_ids = set(current_by_id)
    prior_ids = set(prior_by_id)
    both_ids = current_ids & prior_ids

    stage_changes = []
    owner_changes = []
    unchanged_deal_ids = []

    for deal_id in sorted(both_ids):
        current_row = current_by_id[deal_id]
        prior_row = prior_by_id[deal_id]

        if _stage_changed(prior_row, current_row):
            stage_changes.append({
                "deal_id": deal_id,
                "prior_stage_id": prior_row.get("stage_id"),
                "prior_stage_order": prior_row.get("stage_order"),
                "current_stage_id": current_row.get("stage_id"),
                "current_stage_order": current_row.get("stage_order"),
                "direction": _direction(prior_row, current_row),
                "current_row": current_row,
                "prior_row": prior_row,
            })
            continue

        prior_owner = prior_row.get("owner_email")
        current_owner = current_row.get("owner_email")
        if prior_owner is not None and current_owner is not None and prior_owner != current_owner:
            owner_changes.append({
                "deal_id": deal_id,
                "prior_owner_email": prior_owner,
                "current_owner_email": current_owner,
                "stage_id": current_row.get("stage_id"),
                # Identifying context beyond a bare deal_id — see
                # attach_company_names()'s docstring for why company_name
                # itself isn't computed here (deals_snapshot doesn't carry
                # it; it's backfilled by the router after this function
                # returns).
                "segment": current_row.get("segment"),
                "pipeline_id": current_row.get("pipeline_id"),
                "deal_value": current_row.get("deal_value"),
            })
            continue

        unchanged_deal_ids.append(deal_id)

    population_entries = [current_by_id[d] for d in sorted(current_ids - prior_ids)]
    population_exits = [prior_by_id[d] for d in sorted(prior_ids - current_ids)]

    return {
        "stage_changes": stage_changes,
        "population_entries": population_entries,
        "population_exits": population_exits,
        "owner_changes": owner_changes,
        "unchanged_deal_ids": unchanged_deal_ids,
        "current_count": len(current_rows or []),
        "prior_count": len(prior_rows or []),
        "skipped_missing_deal_id": skipped,
    }


def rows_for_snapshot_date(accumulated_data: dict, snapshot_date: Optional[str]) -> list:
    """All rows across accumulated_data's `_raw` steps whose snapshot_date
    matches, deduplicated by deal_id (a later step's row wins over an
    earlier one for the same id). Used to hand diff_snapshots() the two
    snapshot row sets directly from code — accumulated_data is what the
    loop actually stored, not something reconstructed from the model's
    own (unreliable) narration of what it queried.
    """
    if not snapshot_date:
        return []
    by_deal_id = {}
    for key in sorted(k for k in accumulated_data if k.endswith("_raw")):
        step_data = accumulated_data.get(key) or {}
        for row in step_data.get("rows", []) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("snapshot_date")) != str(snapshot_date):
                continue
            did = row.get("deal_id")
            if did is not None:
                by_deal_id[str(did)] = row
    return list(by_deal_id.values())


def collect_diff_deal_ids(diff_result: dict) -> set:
    """Every deal_id appearing anywhere in a diff_snapshots() result —
    stage_changes, population_entries, population_exits, and
    owner_changes — the full set of deals a synthesized answer will
    need to name.

    2026-09-11 (round 6): a live answer named some deals ("Boylesports",
    "Technogym") and left others as bare deal_ids ("60069831015") in the
    SAME answer. Root cause: the id_scoped_enrichment_lookup shortcut's
    deal_id list is chosen entirely by the MODEL (see
    _is_id_scoped_enrichment_call's docstring — "the model already
    picked the exact deal_ids it wants"), before diff_snapshots() has
    even run. Nothing ever guaranteed that the model's guess covered
    every deal_id the deterministic diff actually surfaces — it happened
    to cover the obviously-dropped deals but missed several stage-
    changed and newly-entered ones from the same run. This function is
    the router's way of asking "which deal_ids does the diff ACTUALLY
    need named" — deterministically, after the diff is computed, not
    before — so it can force one more lookup for whatever the model's
    earlier guess missed, rather than leaving those deals nameless.
    """
    ids = set()
    for entry in diff_result.get("stage_changes", []):
        if entry.get("deal_id") is not None:
            ids.add(str(entry["deal_id"]))
    for row in diff_result.get("population_entries", []):
        if isinstance(row, dict) and row.get("deal_id") is not None:
            ids.add(str(row["deal_id"]))
    for row in diff_result.get("population_exits", []):
        if isinstance(row, dict) and row.get("deal_id") is not None:
            ids.add(str(row["deal_id"]))
    for entry in diff_result.get("owner_changes", []):
        if entry.get("deal_id") is not None:
            ids.add(str(entry["deal_id"]))
    return ids


def attach_company_names(diff_result: dict, company_names: dict) -> dict:
    """Attach a `company_name` field to every entry/row in a
    diff_snapshots() result, from an already-resolved
    {deal_id: company_name} map, so a synthesis step reads a field
    directly instead of having to correlate deal_ids against a separate
    enrichment tool result by hand (the manual-correlation step that
    silently failed for whichever deal_ids the earlier lookup missed —
    see collect_diff_deal_ids()'s docstring for the incident).
    `company_names.get(deal_id)` is used as-is, including None when a
    deal_id genuinely has no name in the map (either never looked up, or
    looked up and NULL in the source table) — the caller decides how to
    render that; this function doesn't guess or invent a name. Mutates
    and returns diff_result.
    """
    def _name_for(deal_id):
        return company_names.get(str(deal_id)) if deal_id is not None else None

    for entry in diff_result.get("stage_changes", []):
        entry["company_name"] = _name_for(entry.get("deal_id"))
    for row in diff_result.get("population_entries", []):
        if isinstance(row, dict):
            row["company_name"] = _name_for(row.get("deal_id"))
    for row in diff_result.get("population_exits", []):
        if isinstance(row, dict):
            row["company_name"] = _name_for(row.get("deal_id"))
    for entry in diff_result.get("owner_changes", []):
        entry["company_name"] = _name_for(entry.get("deal_id"))
    return diff_result
