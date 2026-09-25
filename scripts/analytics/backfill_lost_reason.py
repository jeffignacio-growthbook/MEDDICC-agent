#!/usr/bin/env python3
"""
One-time backfill for the close-reason ETL fetch gap (2026-09-25).

deals.lost_reason was 0% populated because DEAL_SYNC_PROPERTIES never fetched
HubSpot's closed_lost_reason (see PENDING_WORK "DATA BUG (confirmed
2026-09-25)"). The ETL fix makes new syncs correct going forward; this script
fills EXISTING rows now instead of waiting for a full re-sync:

  1. deals: pull closed_lost_reason / closed_lost_from / dq_reason /
     closed_won_reason from HubSpot for every closed deal and write them into
     deals (lost_reason + the three enrichment columns). Only a non-empty new
     value that differs from the stored one is written — a backfill never
     clobbers a real value with an empty one.

  2. win_loss_narratives.stated_reason: a verbatim copy of deals.lost_reason
     (generate_win_loss.py:117). generate_win_loss.py SKIPS any deal that
     already has a narrative row, so a plain re-run would leave every existing
     narrative's stated_reason empty forever. This is the TARGETED update that
     fills exactly those rows from the now-populated deals.lost_reason.

The pure helpers below are unit-tested (tests/test_deal_close_reasons.py);
main() wires them to a live HubSpot + Supabase and is what the nightly or an
operator runs. The 2026-09-25 fleet backfill itself was executed row-for-row
with this same logic.
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# HubSpot deal property -> deals column
HS_TO_COL = {
    "closed_lost_reason": "lost_reason",
    "closed_lost_from": "closed_lost_from",
    "dq_reason": "dq_reason",
    "closed_won_reason": "closed_won_reason",
}


def _clean(v) -> str:
    return (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v).strip())


def reason_values(props: Dict[str, Any]) -> Dict[str, str]:
    """{deals-column: value} for the reason columns from a HubSpot deal's
    properties. Empty string (never None) when HubSpot has no value."""
    return {col: _clean(props.get(hs)) for hs, col in HS_TO_COL.items()}


def deals_needing_update(hs_by_id: Dict[str, dict],
                         current_by_id: Dict[str, dict]) -> List[Tuple[str, Dict[str, str]]]:
    """[(deal_id, {column: value})] for deals whose reason columns would change.

    Only a NON-EMPTY new value that DIFFERS from the currently stored value is
    written: a backfill never overwrites a real stored value with an empty one
    (HubSpot returning '' for an inapplicable reason must not blank a column),
    and never rewrites a value that already matches.
    """
    out: List[Tuple[str, Dict[str, str]]] = []
    for did, props in hs_by_id.items():
        did = str(did)
        cur = current_by_id.get(did, {})
        changed = {col: val for col, val in reason_values(props).items()
                   if val and val != _clean(cur.get(col))}
        if changed:
            out.append((did, changed))
    return out


def stated_reason_updates(narrative_rows: List[dict],
                          lost_reason_by_deal: Dict[str, str]) -> List[Tuple[str, str]]:
    """The targeted win_loss_narratives backfill.

    For narrative rows that ALREADY EXIST (the ones generate_win_loss.py skips
    via its skip-if-narrative-exists filter), set stated_reason from the
    now-populated deals.lost_reason where stated_reason is still empty. This is
    exactly the set a plain generator re-run would never touch.
    """
    out: List[Tuple[str, str]] = []
    for r in narrative_rows:
        did = str(r.get("deal_id"))
        if _clean(r.get("stated_reason")):
            continue  # already has a reason — leave it
        lr = _clean(lost_reason_by_deal.get(did))
        if lr:
            out.append((did, lr))
    return out


def _fetch_hubspot_reasons(hubspot, deal_ids: List[str]) -> Dict[str, dict]:  # pragma: no cover
    """{deal_id: {closed_lost_reason, closed_lost_from, dq_reason,
    closed_won_reason}} for the given ids, via the HubSpot batch read."""
    out: Dict[str, dict] = {}
    props = list(HS_TO_COL.keys())
    for i in range(0, len(deal_ids), 100):
        for d in hubspot.batch_get_deals(deal_ids[i:i + 100], properties=props):
            out[str(d.get("id") or d.get("deal_id"))] = d.get("properties", {})
    return out


def main():  # pragma: no cover - live wiring, exercised via MCP for the one-time run
    import os
    from supabase_client import select_all, SupabaseWriter
    from hubspot_deals import get_hubspot_deals_client

    sb = SupabaseWriter()
    closed = select_all(sb.client, "deals",
                        "deal_id," + ",".join(sorted(set(HS_TO_COL.values()))),
                        filters=[("in_", "deal_status", ["won", "lost"])])
    current_by_id = {str(d["deal_id"]): d for d in closed}
    hubspot = get_hubspot_deals_client(api_key=os.environ["HUBSPOT_API_KEY"])
    hs_by_id = _fetch_hubspot_reasons(hubspot, list(current_by_id))

    deal_updates = deals_needing_update(hs_by_id, current_by_id)
    for did, changed in deal_updates:
        sb.client.table("deals").update(changed).eq("deal_id", did).execute()
    print(f"deals: {len(deal_updates)} rows updated")

    narratives = select_all(sb.client, "win_loss_narratives", "deal_id,stated_reason")
    lost_by_deal = {str(d["deal_id"]): d.get("lost_reason") for d in closed}
    sr_updates = stated_reason_updates(narratives, lost_by_deal)
    for did, reason in sr_updates:
        sb.client.table("win_loss_narratives").update(
            {"stated_reason": reason}).eq("deal_id", did).execute()
    print(f"win_loss_narratives.stated_reason: {len(sr_updates)} rows updated")


if __name__ == "__main__":
    main()
