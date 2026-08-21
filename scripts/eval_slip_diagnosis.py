#!/usr/bin/env python3
"""
Offline tests for slip_diagnosis (analyses 1-3). Synthetic cohorts exercise the
pure analysis functions; analyze_meddicc's analyses read is stubbed. Locks:
slip≠loss, point-in-time (no-lookahead) MEDDICC selection, the close-date
pushed-vs-lapsed split, and the gate (null-with-reason below min_evidence).
"""
import sys
import types
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
for p in ("scripts", "scripts/analytics", "api", "."):
    sys.path.insert(0, str(REPO / p))

if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f

import slip_diagnosis as sd  # noqa: E402

STAGE_CFG = {
    "disco": {"name": "Discovery", "order": 2},
    "te": {"name": "Technical Evaluation", "order": 4},
    "neg": {"name": "Negotiating", "order": 5},
}


def _member(deal_id, outcome, commit_stage, commit_date, q_end,
            closes, end_stage=None):
    """closes: list of close_date per week from commit week onward."""
    trail = []
    for i, c in enumerate(closes):
        stage = end_stage if (end_stage and i == len(closes) - 1) else commit_stage
        trail.append({"week_of_quarter": 4 + i, "stage_id": stage, "close_date": c})
    return {"deal_id": deal_id, "outcome": outcome, "quarter": "FY2027 Q1",
            "q_start": "2026-02-01", "q_end": q_end, "commit_week": 4,
            "commit_date": commit_date, "commit_stage": commit_stage,
            "commit_close": closes[0] if closes else None, "trail": trail}


def _cohort(members, min_evidence=3):
    return {"members": members, "stage_cfg": STAGE_CFG,
            "min_evidence": min_evidence, "quarters": ["FY2027 Q1"]}


def test_close_date_pushed_vs_lapsed_split():
    print("\n[TEST] close-date: repeatedly-pushed vs never-moved-and-lapsed")
    members = [
        # pushed: close_date changes across weeks
        _member("p1", "SLIPPED", "neg", "2026-03-01", "2026-04-30",
                ["2026-04-15", "2026-05-10", "2026-06-01"]),
        _member("p2", "SLIPPED", "neg", "2026-03-01", "2026-04-30",
                ["2026-04-20", "2026-05-20"]),
        # never moved, date lapsed inside the quarter
        _member("f1", "SLIPPED", "neg", "2026-03-01", "2026-04-30",
                ["2026-04-10", "2026-04-10", "2026-04-10"]),
        _member("f2", "SLIPPED", "neg", "2026-03-01", "2026-04-30",
                ["2026-04-05", "2026-04-05"]),
    ]
    r = sd.analyze_close_date_movement(_cohort(members, min_evidence=3))
    assert r["repeatedly_pushed"] == 2, r
    assert r["never_moved_date_passed"] == 2, r
    assert r["days_past_original_close"]["n"] == 4
    print("  ✓ 2 pushed (judgment) vs 2 lapsed (hygiene); days-past distributed")


def test_close_date_gate_below_min_evidence():
    print("\n[TEST] close-date analysis nulls below min_evidence")
    members = [_member("s1", "SLIPPED", "neg", "2026-03-01", "2026-04-30",
                       ["2026-04-10"])]
    r = sd.analyze_close_date_movement(_cohort(members, min_evidence=30))
    assert "reason" in r and r["n_slipped"] == 1, r
    assert "repeatedly_pushed" not in r
    print("  ✓ 1 slipped < 30 → null with reason, no fabricated split")


def test_stall_stage_commit_distribution_won_vs_slipped():
    print("\n[TEST] stall stage: commit-stage distribution won vs slipped")
    members = (
        [_member(f"w{i}", "WON", "disco", "2026-03-01", "2026-04-30",
                 ["2026-03-20"]) for i in range(3)]
        + [_member(f"s{i}", "SLIPPED", "te", "2026-03-01", "2026-04-30",
                   ["2026-04-10", "2026-04-10"]) for i in range(3)]
    )
    r = sd.analyze_stall_stage(_cohort(members, min_evidence=3))
    assert r["WON"]["commit_stage_distribution"] == {"Discovery": 3}, r
    assert r["SLIPPED"]["commit_stage_distribution"] == {"Technical Evaluation": 3}, r
    assert r["slipped_non_advancers"]["count"] == 3, r
    print("  ✓ won commit from Discovery; slipped stall in Technical Evaluation")


def test_meddicc_gap_and_backward_looking_selection():
    print("\n[TEST] MEDDICC: gap won>slipped, and score is as-of commit (no lookahead)")
    won = [_member(f"w{i}", "WON", "neg", "2026-03-15", "2026-04-30",
                   ["2026-04-10"]) for i in range(3)]
    slip = [_member(f"s{i}", "SLIPPED", "neg", "2026-03-15", "2026-04-30",
                    ["2026-04-10"]) for i in range(3)]
    # analyses: each deal has a LOW score before commit and a HIGH score AFTER.
    # Backward-looking selection must pick the pre-commit (LOW) row for everyone;
    # won deals get a higher pre-commit decision_process than slipped.
    rows = []
    for i in range(3):
        rows += [
            {"deal_id": f"w{i}", "analyzed_at": "2026-03-01T00:00:00Z",
             "decision_process_score": 8, "economic_buyer_score": 7,
             "overall_score": 70},
            {"deal_id": f"w{i}", "analyzed_at": "2026-04-20T00:00:00Z",  # future
             "decision_process_score": 1, "economic_buyer_score": 1,
             "overall_score": 10},
            {"deal_id": f"s{i}", "analyzed_at": "2026-03-01T00:00:00Z",
             "decision_process_score": 4, "economic_buyer_score": 5,
             "overall_score": 55},
            {"deal_id": f"s{i}", "analyzed_at": "2026-04-20T00:00:00Z",  # future
             "decision_process_score": 9, "economic_buyer_score": 9,
             "overall_score": 90},
        ]
    with patch.object(sd, "select_all", return_value=rows):
        r = sd.analyze_meddicc(_cohort(won + slip, min_evidence=3), sb=None)
    assert r["matched"] == {"WON": 3, "SLIPPED": 3}, r
    dp = r["per_component"]["Decision Process"]
    # pre-commit means: won 8, slipped 4 → gap +4 (NOT the post-commit values)
    assert dp["won_mean"] == 8.0 and dp["slipped_mean"] == 4.0, dp
    assert dp["gap_won_minus_slipped"] == 4.0, dp
    assert r["largest_gaps"][0][0] in ("Decision Process", "Economic Buyer")
    print("  ✓ picks pre-commit score (no lookahead); Decision Process gap surfaces")


def test_meddicc_gate_below_min_evidence():
    print("\n[TEST] MEDDICC nulls when a group is below min_evidence")
    won = [_member(f"w{i}", "WON", "neg", "2026-03-15", "2026-04-30",
                   ["2026-04-10"]) for i in range(3)]
    slip = [_member("s0", "SLIPPED", "neg", "2026-03-15", "2026-04-30",
                    ["2026-04-10"])]
    rows = [{"deal_id": m["deal_id"], "analyzed_at": "2026-03-01T00:00:00Z",
             "decision_process_score": 5} for m in won + slip]
    with patch.object(sd, "select_all", return_value=rows):
        r = sd.analyze_meddicc(_cohort(won + slip, min_evidence=3), sb=None)
    assert "reason" in r and "per_component" not in r, r
    print("  ✓ slipped=1 < 3 → null with reason, no gap reported")


def test_lost_excluded_from_slip_analyses():
    print("\n[TEST] LOST deals are not counted as slipped")
    members = [
        _member("l1", "LOST", "neg", "2026-03-01", "2026-04-30", ["2026-04-10"]),
        _member("s1", "SLIPPED", "neg", "2026-03-01", "2026-04-30", ["2026-04-10"]),
    ]
    r = sd.analyze_close_date_movement(_cohort(members, min_evidence=1))
    assert r["n_slipped"] == 1, "LOST must not be counted in the slipped cohort"
    print("  ✓ slip cohort excludes losses")


# ── Analysis 4 — calls (qualitative) ───────────────────────────────────

class _FakeLLM:
    """Returns a canned JSON extraction per call, cycling through scripted
    responses so the aggregation can be asserted deterministically."""
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = 0

    def complete(self, messages, system=None, max_tokens=1000):
        i = min(self.calls, len(self._scripted) - 1)
        self.calls += 1
        return types.SimpleNamespace(text=self._scripted[i])


def test_slip_calls_extraction_and_scope():
    print("\n[TEST] analysis 4: extracts signals over sampled slipped deals only")
    import slip_calls as sc
    slipped = [_member(f"s{i}", "SLIPPED", "neg", "2026-03-01", "2026-04-30",
                       ["2026-04-10"]) for i in range(3)]
    won = [_member("w0", "WON", "neg", "2026-03-01", "2026-04-30", ["2026-04-10"])]
    cohort = _cohort(slipped + won, min_evidence=3)
    # calls: slipped deals have summaries; the WON deal also has one that must
    # NOT be pulled (scope = sampled slipped only).
    calls = [
        {"deal_id": "s0", "call_date": "2026-03-10", "formatted_summary": "MAP agreed; procurement path clear"},
        {"deal_id": "s1", "call_date": "2026-03-11", "formatted_summary": "date pushed to next quarter"},
        {"deal_id": "s2", "call_date": "2026-03-12", "formatted_summary": "no plan discussed"},
        {"deal_id": "w0", "call_date": "2026-03-13", "formatted_summary": "should not be read"},
    ]
    scripted = [
        '{"mutual_action_plan": true, "close_process_identified": true, "date_move_reason": "none"}',
        '{"mutual_action_plan": false, "close_process_identified": false, "date_move_reason": "budget freeze"}',
        '{"mutual_action_plan": false, "close_process_identified": false, "date_move_reason": "none"}',
    ]
    llm = _FakeLLM(scripted)
    with patch.object(sc, "select_all", return_value=calls):
        r = sc.analyze_slip_calls(sb=None, llm=llm, cohort=cohort)
    assert r["sampled"] == 3 and r["sampled_with_calls"] == 3, r
    assert r["counts_over_sampled_with_calls"]["mutual_action_plan"] == 1, r
    assert r["counts_over_sampled_with_calls"]["close_process_identified"] == 1, r
    assert r["date_move_reasons"] == {"budget freeze": 1}, r
    assert llm.calls == 3, "must not read the WON deal's call (scope leak)"
    print("  ✓ signals extracted; WON deal's call excluded; reasons aggregated")


def test_slip_calls_gate_below_min_evidence():
    print("\n[TEST] analysis 4 nulls when slipped cohort is below min_evidence")
    import slip_calls as sc
    cohort = _cohort([_member("s0", "SLIPPED", "neg", "2026-03-01",
                              "2026-04-30", ["2026-04-10"])], min_evidence=30)
    r = sc.analyze_slip_calls(sb=None, llm=_FakeLLM(["{}"]), cohort=cohort)
    assert "reason" in r and "counts_over_sampled_with_calls" not in r, r
    print("  ✓ 1 slipped < 30 → null with reason, no LLM sampling")


def test_slip_calls_parse_tolerant():
    print("\n[TEST] analysis 4 tolerates noisy LLM JSON")
    import slip_calls as sc
    ext = sc.parse_extraction('sure!\n{"mutual_action_plan": true, '
                              '"close_process_identified": false, '
                              '"date_move_reason": "Legal review"}\ndone')
    assert ext["mutual_action_plan"] is True and ext["date_move_reason"] == "legal review", ext
    bad = sc.parse_extraction("not json at all")
    assert bad.get("parse_error") is True, bad
    print("  ✓ first JSON block parsed; garbage flagged, not crashed")


def main():
    print("=" * 70)
    print("SLIP DIAGNOSIS TESTS (analyses 1-4)")
    print("=" * 70)
    tests = [
        test_close_date_pushed_vs_lapsed_split,
        test_close_date_gate_below_min_evidence,
        test_stall_stage_commit_distribution_won_vs_slipped,
        test_meddicc_gap_and_backward_looking_selection,
        test_meddicc_gate_below_min_evidence,
        test_lost_excluded_from_slip_analyses,
        test_slip_calls_extraction_and_scope,
        test_slip_calls_gate_below_min_evidence,
        test_slip_calls_parse_tolerant,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t(); passed += 1
        except Exception as e:
            failed += 1
            print(f"\n❌ {t.__name__}: {e}")
            import traceback; traceback.print_exc()
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
