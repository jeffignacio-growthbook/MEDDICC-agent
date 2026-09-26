#!/usr/bin/env python3
"""
Stage-vs-call-content lag detector (Direction 1) — tests first.

Flags OPEN deals recorded at a pre-commercial stage (Discovery/Scoping) whose
call evidence (MEDDICC Economic Buyer + Decision Process scores) says they are
commercially further along than the stage records. A REVIEW list only — never
an automatic stage/forecast change.

Gating rules under test:
  - Substance gate: a deal with no scoreable call (no MEDDICC analysis carrying
    real signal) is EXCLUDED entirely — counted as excluded_no_scoreable_call,
    never silently treated as "no mismatch".
  - Signal: Economic Buyer >= 6 AND Decision Process >= 6 (BOTH), on cumulative
    call evidence at ANY point in the deal's history (peak), not just the latest
    analysis — stage_at_analysis is not populated to support a near-stage check.

Real pinned data (captured read-only 2026-09-26 via Supabase MCP, project
htgvkqycrwesdysustxd; FY2027-Q3 open Sales/default deals):
  Flagged (6): Livesport 7/8, Box 6/8, Felt 7/7, Aircall 6/7, CFI Global 7/6,
               Stone 6/7 — all at Discovery/Scoping.
  Below-threshold open (AND-gate proof): shiftkey EB5/DP9, The Wellness Company
               EB7/DP5 — one score high, the other below 6 → NOT flagged.
  No scoreable call open: Luminus, Ryzon (no analysis row).
  Negative controls (closed, from tonight's investigation): RedCore EB0/DP0
               (null-input → no_scoreable_call), Paradigm EB0/DP5
               (below-threshold).
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

from stage_call_lag import (
    classify_deal, detect_stage_call_lag, PRECOMMERCIAL_STAGES_DEFAULT,
)

# Discovery/Scoping stage ids (buckets discovery+scoping), real config values.
PRECOMMERCIAL = ("79653122", "appointmentscheduled", "qualifiedtobuy")


def _an(eb, dp):
    return {"economic_buyer_score": eb, "decision_process_score": dp}


# Real flagged candidates: (deal_id, company, stage, peak_eb, peak_dp)
FLAGGED = [
    ("62160567676", "Livesport", "qualifiedtobuy", 7, 8),
    ("62622458398", "Box", "qualifiedtobuy", 6, 8),
    ("62354816397", "Felt", "79653122", 7, 7),
    ("57553904779", "Aircall", "qualifiedtobuy", 6, 7),
    ("61024408734", "CFI Global", "appointmentscheduled", 7, 6),
    ("53500422798", "Stone", "qualifiedtobuy", 6, 7),
]


def _real_open_pool():
    """deals + analyses_by_deal for the real open pre-commercial pool."""
    deals = []
    abd = {}
    for did, co, stage, eb, dp in FLAGGED:
        deals.append({"deal_id": did, "company_name": co, "stage": stage,
                      "deal_status": "active"})
        abd[did] = [_an(eb, dp)]
    # below-threshold (AND-gate): one score high, the other below 6
    deals += [
        {"deal_id": "60355159912", "company_name": "shiftkey",
         "stage": "appointmentscheduled", "deal_status": "active"},
        {"deal_id": "60036684928", "company_name": "The Wellness Company",
         "stage": "qualifiedtobuy", "deal_status": "active"},
    ]
    abd["60355159912"] = [_an(5, 9)]
    abd["60036684928"] = [_an(7, 5)]
    # no scoreable call: no analysis row at all
    deals += [
        {"deal_id": "65168396726", "company_name": "Luminus",
         "stage": "appointmentscheduled", "deal_status": "active"},
        {"deal_id": "64624160587", "company_name": "Ryzon",
         "stage": "appointmentscheduled", "deal_status": "active"},
    ]
    return deals, abd


# ---- classify_deal ------------------------------------------------------

def test_classify_flag_below_and_null():
    assert classify_deal([_an(7, 8)])["status"] == "flag"
    assert classify_deal([_an(6, 6)])["status"] == "flag"          # boundary: >= both
    assert classify_deal([_an(5, 9)])["status"] == "below_threshold"  # EB below
    assert classify_deal([_an(7, 5)])["status"] == "below_threshold"  # DP below
    assert classify_deal([_an(0, 0)])["status"] == "no_scoreable_call"  # null-input
    assert classify_deal([])["status"] == "no_scoreable_call"          # no calls


def test_classify_uses_cumulative_peak_not_latest():
    """An earlier commercial-ready call must flag even if the latest analysis
    fell back — cumulative evidence at ANY point, not the latest row."""
    hist = [_an(6, 8), _an(2, 2)]  # peaked 6/8, latest 2/2
    r = classify_deal(hist)
    assert r["status"] == "flag"
    assert r["peak_eb"] == 6 and r["peak_dp"] == 8


def test_null_input_vs_below_threshold_controls():
    """The two negative controls, classified from their real scores."""
    redcore = classify_deal([_an(0, 0)])          # RedCore
    paradigm = classify_deal([_an(0, 5), _an(0, 5)])  # Paradigm
    assert redcore["status"] == "no_scoreable_call", "RedCore is the null-input case"
    assert paradigm["status"] == "below_threshold", "Paradigm has real signal but below threshold"


# ---- detect_stage_call_lag ----------------------------------------------

def test_flags_exactly_the_six_real_candidates():
    deals, abd = _real_open_pool()
    res = detect_stage_call_lag(deals, abd, precommercial_stages=PRECOMMERCIAL)
    flagged_ids = {f["deal_id"] for f in res["flagged"]}
    assert flagged_ids == {d for d, *_ in FLAGGED}, flagged_ids
    assert len(res["flagged"]) == 6
    # shiftkey / Wellness excluded (AND gate), counted as below_threshold
    assert res["below_threshold_count"] == 2
    # Luminus / Ryzon excluded as no scoreable call — NOT silently "no mismatch"
    assert res["excluded_no_scoreable_call"] == 2


def test_and_gate_not_or():
    """shiftkey (5/9) and Wellness (7/5) must NOT flag — both scores must clear."""
    deals, abd = _real_open_pool()
    res = detect_stage_call_lag(deals, abd, precommercial_stages=PRECOMMERCIAL)
    flagged_ids = {f["deal_id"] for f in res["flagged"]}
    assert "60355159912" not in flagged_ids and "60036684928" not in flagged_ids


def test_closed_and_out_of_stage_deals_are_not_flagged():
    """Controls are closed; and an open deal past the pre-commercial stages is
    out of scope even with strong scores."""
    deals = [
        {"deal_id": "58867845224", "company_name": "Paradigm Technology",
         "stage": "closedlost", "deal_status": "lost"},
        {"deal_id": "62921497713", "company_name": "RedCore Group",
         "stage": "closedlost", "deal_status": "lost"},
        {"deal_id": "999", "company_name": "LateStageCo",
         "stage": "43449439", "deal_status": "active"},  # commercial stage
    ]
    abd = {"58867845224": [_an(0, 5)], "62921497713": [_an(0, 0)],
           "999": [_an(9, 9)]}
    res = detect_stage_call_lag(deals, abd, precommercial_stages=PRECOMMERCIAL)
    assert res["flagged"] == []
    assert res["considered"] == 0  # none were open AND pre-commercial


def test_output_is_review_only_with_caveats():
    deals, abd = _real_open_pool()
    res = detect_stage_call_lag(deals, abd, precommercial_stages=PRECOMMERCIAL)
    for f in res["flagged"]:
        assert set(f) >= {"deal_id", "company_name", "current_stage",
                          "economic_buyer_score", "decision_process_score",
                          "evidence", "suggested_review"}
        # never an automatic change: no field that mutates stage/forecast
        assert "new_stage" not in f and "forecast_category" not in f and "action" not in f
        assert "review" in f["suggested_review"].lower()
    # step 3: recency limitation stated in the tool's own output
    assert "recency_caveat" in res and "stage_at_analysis" in res["recency_caveat"]
    assert "not" in res["recency_caveat"].lower()
    # step 4: thin-pool caveat stated in the output
    assert "thin_pool_note" in res and "review list" in res["thin_pool_note"].lower()


def test_default_precommercial_stages_are_discovery_scoping():
    assert set(PRECOMMERCIAL_STAGES_DEFAULT) == set(PRECOMMERCIAL)


if __name__ == "__main__":
    import inspect
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            fn(); print(f"✓ {name}")
    print("\n✅ All tests passed")
