#!/usr/bin/env python3
"""
query_pipeline_movement: exited deals are split into won / lost / still open
but out of scope, before the answer interprets them.

"Exited" only means a deal is in the prior snapshot's scope and not in the
current one. Live on 2026-09-24 ("how has pipeline moved this quarter?"), the
answer called 8 Negotiating exits a close-date-slippage risk. The handler
couldn't tell it whether any of them were wins.

Now summary.exited_breakdown classifies every exited deal by its current
`deals` row, and the _synthesis_note states the split and says to read exits
only through it.

Two layers: the REAL handler (fake deals_snapshot + deals), then its exact
result through both synthesis paths.
"""
import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.handlers as handlers  # noqa: E402
import api.router as router  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402
import test_pipeline_movement_synthesis_note as pm  # noqa: E402

PRIOR, CURRENT = "2026-09-14", "2026-09-21"
EXITED = ["W", "L", "Q4", "MS", "GONE"]
ROWS = ([pm._snap(i, PRIOR) for i in ["K"] + EXITED]
        + [pm._snap("K", CURRENT), pm._snap("N1", CURRENT)])

DEALS = {   # current `deals` rows
    "K":  {"deal_status": "active", "stage": "presentationscheduled", "close_date": "2026-10-30", "new_arr": 1},
    "N1": {"deal_status": "active", "stage": "presentationscheduled", "close_date": "2026-10-30", "new_arr": 90000},
    "W":  {"deal_status": "won", "stage": "closedwon", "close_date": "2026-09-18", "new_arr": 50000},
    "L":  {"deal_status": "lost", "stage": "closedlost", "close_date": "2026-09-16", "new_arr": 20000},
    "Q4": {"deal_status": "active", "stage": "presentationscheduled", "close_date": "2026-12-15", "new_arr": 30000},
    "MS": {"deal_status": "active", "stage": "79653122", "close_date": "2026-10-20", "expansion_arr": 10000},
    # GONE: deleted from deals
}


def _run():
    """Strict fake (tests/strict_supabase.py): real select_all, only selected
    columns, every filter applied. GONE has no deals row."""
    deals = [{"deal_id": i, "company_name": f"Co {i}", "pipeline_id": "default",
              "new_arr": None, "expansion_arr": None, **DEALS[i]} for i in DEALS]
    return pm._run_handler({"view": "movement", "fiscal_quarter": "FY2027 Q3"},
                           pm._sb(rows=ROWS, deals=deals))


def test_exits_are_split_by_outcome():
    r = _run()
    s = r["summary"]
    assert (s["added_arr_total"], s["exited_arr_total"]) == (90000, 110000), s
    b = s.get("exited_breakdown")
    assert b, "exited deals are not split by outcome"
    ids = {k: [d["deal_id"] for d in b[k]["deals"]]
           for k in ("won", "lost", "still_open_out_of_scope", "not_found")}
    assert ids == {"won": ["W"], "lost": ["L"], "still_open_out_of_scope": ["MS", "Q4"],
                   "not_found": ["GONE"]}, ids
    assert (b["won"]["incremental_arr"], b["lost"]["incremental_arr"],
            b["still_open_out_of_scope"]["incremental_arr"]) == (50000, 20000, 40000)
    assert b["still_open_out_of_scope"]["reasons"] == {
        "close_date_moved_out_of_quarter": 1, "stage_now_out_of_scope": 1}, b["still_open_out_of_scope"]
    assert sum(b[k]["count"] for k in ids) == len(EXITED)
    assert "today" in b["status_as_of"]
    print("✓ real handler: 5 exits split into 1 won ($50,000), 1 lost ($20,000), 2 still open "
          "out of scope ($40,000: close date moved out, stage now Meeting Set), 1 not in deals")


def test_note_states_the_split_and_forbids_reading_exits_as_losses():
    note = _run()["_synthesis_note"]
    for part in ("EXITS ARE NOT LOSSES", "1 closed won ($50,000)", "1 closed lost ($20,000)",
                 "2 are still open but out of this quarter's scope ($40,000",
                 "1 close date moved out of quarter", "1 stage now out of scope",
                 "1 no longer in deals", "a won exit is good news"):
        assert part in note, (part, note)
    for part in ("added $90,000", "exited $110,000", "net $-20,000"):
        assert part in note, (part, note)
    print("✓ note: the three dollar figures plus the won / lost / still-open split and "
          "the instruction to interpret exits only through it")


def test_split_reaches_both_synthesis_paths():
    r = _run()
    note = json.dumps(r["_synthesis_note"])[1:-1]
    classifier = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(r)), router.SYNTH_PAYLOAD_CHARS)
    loop = run_canary_case("how has pipeline moved this quarter?", "query_pipeline_movement",
                           {"view": "movement", "fiscal_quarter": "FY2027 Q3"}, r)["synthesis_text"]
    for name, text in (("classifier", classifier), ("dynamic loop", loop)):
        assert note in text, name
        assert '"exited_breakdown"' in text, name
    print("✓ the note and exited_breakdown reach the synthesis input on both paths")


def test_status_alone_classifies_an_exit_when_the_stage_is_unmapped():
    """deal_status is read from the exited-deals lookup, not just the stage:
    a deal marked won whose stage id isn't a mapped won stage is still won.
    Needs the strict fake (only selected columns come back) to mean anything."""
    rows = [pm._snap(i, PRIOR) for i in ("K", "WS")] + [pm._snap("K", CURRENT)]
    deals = [{"deal_id": "K", "company_name": "Co K", "pipeline_id": "default", "new_arr": 1,
              "expansion_arr": None, "deal_status": "active", "stage": "presentationscheduled",
              "close_date": "2026-10-30"},
             {"deal_id": "WS", "company_name": "Co WS", "pipeline_id": "default", "new_arr": 15000,
              "expansion_arr": None, "deal_status": "won", "stage": "999999999",
              "close_date": "2026-09-17"}]
    r = pm._run_handler({"view": "movement", "fiscal_quarter": "FY2027 Q3"}, pm._sb(rows=rows, deals=deals))
    b = r["summary"]["exited_breakdown"]
    assert [d["deal_id"] for d in b["won"]["deals"]] == ["WS"], b
    print("✓ an exited deal with deal_status 'won' and an unmapped stage id is classified won")


if __name__ == "__main__":
    test_exits_are_split_by_outcome()
    test_note_states_the_split_and_forbids_reading_exits_as_losses()
    test_split_reaches_both_synthesis_paths()
    test_status_alone_classifies_an_exit_when_the_stage_is_unmapped()
    print("\n✅ All tests passed")
