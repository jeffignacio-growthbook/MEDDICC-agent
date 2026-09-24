#!/usr/bin/env python3
"""
$0-ARR deals: counted and flagged, never silently dropped, by both
query_pipeline and query_waterfall.

Before 2026-09-24 the two disagreed. query_waterfall counted a qualified $0
deal closing in the period and flagged it in needs_attention.
query_pipeline's is_incremental_pipeline() scope (ARR > 0, since
2026-09-22) dropped the same deal from total_deals, and its zero_arr_deals
branch for non-renewal stages could never fire (it tested $0 on deals
already filtered to > $0). Live: 19 active qualified-stage $0 deals were
missing from the pipeline count.

The rule both handlers now apply to a non-renewal deal past Meeting Set
with no incremental ARR: count it at $0 and flag it as a hygiene issue.
$0 Meeting Set deals (expected unsized) are reported as
meeting_set_unsized, not counted. Pure renewals are neither.

Runs both REAL handlers against one fake deals table.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import test_query_pipeline_note_and_entities as qp  # noqa: E402
import test_waterfall_basis_and_disclosure as wf  # noqa: E402

RENEWAL = "866608541"
MEETING_SET = "79653122"


def _deal(deal_id, stage, pipeline_id="default", new=None, exp=None, renewal=None,
          close="2026-09-30"):
    return {"deal_id": deal_id, "company_name": f"Co{deal_id}", "stage": stage,
            "pipeline_id": pipeline_id, "deal_status": "active", "close_date": close,
            "owner_email": "rep@example.com", "new_arr": new, "expansion_arr": exp,
            "renewal_revenue": renewal, "deal_value": (new or 0) + (exp or 0) + (renewal or 0) or 15000,
            "arr_usd": (new or 0) + (exp or 0)}


DEALS = [
    _deal("A", "presentationscheduled", new=120000),                 # counted
    _deal("Z", "presentationscheduled"),                             # $0, qualified: counted + flagged
    _deal("M0", MEETING_SET),                                        # $0 Meeting Set: unsized, not counted
    _deal("M1", MEETING_SET, new=30000),                             # Meeting Set with ARR: counted
    _deal("R0", "1297321619", pipeline_id=RENEWAL, renewal=100000),  # pure renewal: neither
    _deal("R1", "1297321620", pipeline_id=RENEWAL, exp=30000, renewal=90000),  # expansion: counted
]


def _query_pipeline(params=None):
    return qp._run(params, DEALS)       # strict fake: real select_all, real filters


def _query_waterfall():
    saved = wf.DEALS
    wf.DEALS = DEALS
    try:
        return wf._run_handler()
    finally:
        wf.DEALS = saved


def test_query_pipeline_counts_and_flags_the_zero_arr_deal():
    r = _query_pipeline()
    assert r["total_deals"] == 4, r["total_deals"]                     # A, Z, M1, R1
    assert r["total_pipeline"] == 180000, r["total_pipeline"]          # $0 adds $0
    z = r["zero_arr_deals"]
    assert z["count"] == 1 and [d["deal_id"] for d in z["deals"]] == ["Z"], z
    assert r["meeting_set_unsized"]["count"] == 1, r["meeting_set_unsized"]
    assert sum(s["count"] for s in r["by_stage"].values()) == r["total_deals"], r["by_stage"]
    assert "They ARE included in total_deals (4) at $0" in r["_synthesis_note"], r["_synthesis_note"]
    print("✓ query_pipeline: 4 deals / $180,000 (the $0 qualified deal counted at $0 and flagged; "
          "$0 Meeting Set reported unsized, not counted; pure renewal excluded)")


def test_both_handlers_count_and_flag_the_same_zero_arr_deals():
    p = _query_pipeline()
    w = _query_waterfall()
    ps = w["pipeline_summary"]
    wf_flagged = ps["needs_attention"]["no_arr_count"]
    assert ps["total_open_count"] == 2 and wf_flagged == 1, (ps["total_open_count"], wf_flagged)  # A, Z
    qp_zero = {d["deal_id"] for d in p["zero_arr_deals"]["deals"]}
    assert qp_zero == {"Z"} and wf_flagged == len(qp_zero)
    assert "INCLUDES 1 deal(s) with no ARR entered" in w["_synthesis_note"], w["_synthesis_note"][:400]
    print("✓ query_pipeline and query_waterfall both count deal Z at $0 and flag it "
          "(waterfall: 2 qualified deals closing in Q3, 1 with no ARR; the note says it's in the count)")


def test_flags_describe_the_same_population_as_the_count():
    """Before: flags were collected before the quarter filter. A renewal-stage
    deal with expansion but $0 renewal_revenue (flagged) closing outside the
    quarter stayed flagged while the count dropped it."""
    saved = list(DEALS)
    DEALS.append(_deal("RE", "1297321619", pipeline_id=RENEWAL, exp=20000, renewal=0,
                       close="2026-09-30"))   # Renewal Engaged, $0 renewal_revenue: flagged
    try:
        full = _query_pipeline()
        assert full["zero_arr_deals"]["count"] == 2, full["zero_arr_deals"]      # Z and RE
        q4 = _query_pipeline({"resolved_quarter_filter": {"start": "2026-10-01", "end": "2026-12-31"}})
    finally:
        DEALS[:] = saved
    assert q4["total_deals"] == 0 and q4["zero_arr_deals"]["count"] == 0, (q4["total_deals"], q4["zero_arr_deals"])
    print("✓ zero_arr_deals is collected after the quarter filter: a flagged deal outside "
          "the quarter leaves the flags with the count (was: 0 deals, 1 flag)")


if __name__ == "__main__":
    test_query_pipeline_counts_and_flags_the_zero_arr_deal()
    test_both_handlers_count_and_flag_the_same_zero_arr_deals()
    test_flags_describe_the_same_population_as_the_count()
    print("\n✅ All tests passed")
