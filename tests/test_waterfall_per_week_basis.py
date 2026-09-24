#!/usr/bin/env python3
"""
query_waterfall: each week states its own basis.

waterfall_weekly weeks before 2026-09-11 are valued on deal_value, later
ones on incremental_arr, so one weekly table can mix bases. Until
2026-09-24 the basis reached the model as one table-wide note it had to
apply week by week. Now:
  1. every week row carries basis_label, derived from that week's stored
     value_basis, and the note says to state it per week;
  2. those per-row labels reach the synthesis input on both paths;
  3. api/plausibility.check_answer_week_basis checks the ANSWER: every week
     line must carry its own row's basis (a table-wide statement counts
     for unlabeled lines). It runs in dynamic_query_loop's wrapper and on
     route_question's path. A mismatch appends a caveat and, in the loop,
     sets its own query_cost_log outcome.

The model's answer can only be checked live. Offline, (3) is exercised on
scripted answers: correct ones pass, planted wrong ones are flagged.
"""
import copy
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.handlers as handlers  # noqa: E402
import api.router as router  # noqa: E402
from api.plausibility import check_answer_week_basis, answer_caveat  # noqa: E402
import test_waterfall_basis_and_disclosure as wf  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402

LABELS = getattr(handlers, "WATERFALL_BASIS_LABELS", {})  # {} on pre-fix code: tests fail, not the import


def _stored_basis_by_week():
    """Straight from the fixture's waterfall_weekly slices, not the handler:
    NULL value_basis = deal_value; renewal-pipeline slices excluded."""
    out = {}
    for s in wf.SLICES:
        if s["pipeline_id"] == wf.RENEWAL:
            continue
        out.setdefault(s["week_ending"], set()).add(s["value_basis"] or "deal_value")
    return {w: (b.pop() if len(b) == 1 else "mixed") for w, b in out.items()}


def _week_segments(text):
    """week_ending -> the synthesis-input text from that week's row to the next."""
    hits = [(m.start(), m.group(1)) for m in re.finditer(r'"week_ending": ?"(\d{4}-\d{2}-\d{2})"', text)]
    return {w: text[a:(hits[i + 1][0] if i + 1 < len(hits) else len(text))]
            for i, (a, w) in enumerate(hits)}


def test_every_week_row_carries_its_stored_basis():
    r = wf._run_handler()
    stored = _stored_basis_by_week()
    assert stored == {"2026-09-14": "deal_value", "2026-09-21": "incremental_arr"}, stored
    rows = {w["week_ending"]: w for w in r["waterfall"]}
    assert set(rows) == set(stored)
    for week, basis in stored.items():
        assert rows[week]["value_basis"] == basis, (week, rows[week]["value_basis"])
        assert rows[week]["basis_label"] == LABELS[basis], (week, rows[week]["basis_label"])
    note = r["_synthesis_note"]
    assert "State EACH week's own basis_label" in note and "Never state one basis for the whole" in note
    print("✓ real handler: each week row's basis_label matches its stored basis "
          "(09-14 deal value, 09-21 Incremental ARR); the note says to state it per week")


def test_per_week_labels_reach_both_synthesis_paths():
    r = wf._run_handler()
    stored = _stored_basis_by_week()
    classifier = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(r)), router.SYNTH_PAYLOAD_CHARS)
    loop = run_canary_case("show me this quarter's pipeline waterfall", "query_waterfall",
                           {}, r, time_window=wf.TW)["synthesis_text"]
    for name, text in (("classifier", classifier), ("dynamic loop", loop)):
        segs = _week_segments(text)
        for week, basis in stored.items():
            assert week in segs, (name, week)
            found = re.findall(r'"basis_label": ?"([^"]*)"', segs[week])
            assert found == [LABELS[basis]], (name, week, found)
    print("✓ both synthesis paths: each week's row carries its own basis_label, "
          "never another week's")


MIXED = {"waterfall": [
    {"week_ending": "2026-09-07", "value_basis": "deal_value", "by_slice": []},
    {"week_ending": "2026-09-14", "value_basis": "deal_value", "by_slice": []},
    {"week_ending": "2026-09-21", "value_basis": "incremental_arr", "by_slice": []},
]}
UNIFORM = {"waterfall": [
    {"week_ending": "2026-09-14", "value_basis": "incremental_arr", "by_slice": []},
    {"week_ending": "2026-09-21", "value_basis": "incremental_arr", "by_slice": []},
]}

GOOD_ANSWERS = {
    "Basis column": (MIXED, "| Week | New | Basis |\n|---|---|---|\n"
                            "| 2026-09-07 | $12K | deal value (pre-2026-09-11 basis) |\n"
                            "| 2026-09-14 | $25K | deal value (pre-2026-09-11 basis) |\n"
                            "| 2026-09-21 | $7K | Incremental ARR |"),
    "per-line, Sep 14 style": (MIXED, "• Sep 7: +$12K new (deal value)\n• Sept. 14: +$25K new (deal value)\n"
                                      "• September 21st: +$7K new (Incremental ARR)"),
    "slash dates": (MIXED, "9/7 $12K deal value\n9/14 $25K deal value\n9/21 $7K Incremental ARR"),
    "uniform weeks, one header": (UNIFORM, "All weekly figures are Incremental ARR.\n"
                                           "• Sep 14: +$25K\n• Sep 21: +$7K"),
    "no weeks mentioned": (MIXED, "Pipeline is $4.6M in Incremental ARR closing this quarter."),
}

BAD_ANSWERS = {
    # the failure a single table-wide note invites: one basis applied to all rows
    "one header over mixed weeks": (MIXED, "All weekly figures are Incremental ARR.\n"
                                           "• Sep 7: +$12K\n• Sep 14: +$25K\n• Sep 21: +$7K",
                                    ["2026-09-07", "2026-09-14"]),
    "wrong label on a line": (MIXED, "• Sep 7: +$12K (deal value)\n• Sep 14: +$25K (Incremental ARR)\n"
                                     "• Sep 21: +$7K (Incremental ARR)", ["2026-09-14"]),
    "no basis at all, mixed weeks": (MIXED, "• Sep 14: +$25K\n• Sep 21: +$7K", None),
    "uniform table labeled deal value": (UNIFORM, "Weekly flows (deal value):\n• 9/14 $25K\n• 9/21 $7K",
                                         ["2026-09-14", "2026-09-21"]),
}


def test_answer_check_passes_correct_answers():
    for name, (data, answer) in GOOD_ANSWERS.items():
        v = check_answer_week_basis(answer, data)
        assert not v, (name, v)
    print(f"✓ answer check: {len(GOOD_ANSWERS)} correct answers pass "
          "(Basis column, per-line labels, Sep/Sept/September and 9/14 dates, uniform header)")


def test_answer_check_flags_planted_wrong_bases():
    for name, (data, answer, wrong_weeks) in BAD_ANSWERS.items():
        v = check_answer_week_basis(answer, data)
        assert v and all(x.check == "answer_week_basis" for x in v), (name, v)
        if wrong_weeks is not None:
            flagged = sorted(w["week_ending"] for x in v for w in x.context.get("wrong", []))
            assert flagged == wrong_weeks, (name, flagged)
        else:
            assert v[0].context.get("unlabeled"), (name, v)
    print(f"✓ answer check: {len(BAD_ANSWERS)} planted wrong answers flagged, naming exactly "
          "the misstated weeks (one header over mixed weeks flags 09-07 and 09-14, not 09-21)")


def _loop(answer_text):
    r = wf._run_handler()
    seen = {}
    saved = router._log_query_cost

    def capture(sb, question, cost_state, result, exc):
        seen["outcome"] = router._compute_query_cost_outcome(result, cost_state, exc)
    router._log_query_cost = capture
    try:
        rep = run_canary_case("show me this quarter's pipeline waterfall", "query_waterfall",
                              {}, r, answer_text=answer_text, time_window=wf.TW)
    finally:
        router._log_query_cost = saved
    return rep, seen["outcome"]


def test_dynamic_loop_caveats_and_logs_a_wrong_basis():
    bad = "All weekly figures are Incremental ARR.\n• Sep 14: +$25K new\n• Sep 21: +$7K new"
    rep, outcome = _loop(bad)
    caveat = answer_caveat(check_answer_week_basis(bad, {"waterfall": wf._run_handler()["waterfall"]}))
    assert caveat and rep["answer"].endswith(caveat), rep["answer"]
    assert outcome == "answered_with_week_basis_mismatch", outcome
    assert rep["result"]["plausibility_violations"][0]["check"] == "answer_week_basis"

    good = "• Sep 14: +$25K new (deal value)\n• Sep 21: +$7K new (Incremental ARR)"
    rep, outcome = _loop(good)
    assert rep["answer"] == good and outcome == "answered_cleanly", (rep["answer"], outcome)
    print("✓ dynamic loop: a one-basis answer over mixed weeks ships with the caveat and "
          "outcome answered_with_week_basis_mismatch; a per-week answer ships unchanged")


if __name__ == "__main__":
    test_every_week_row_carries_its_stored_basis()
    test_per_week_labels_reach_both_synthesis_paths()
    test_answer_check_passes_correct_answers()
    test_answer_check_flags_planted_wrong_bases()
    test_dynamic_loop_caveats_and_logs_a_wrong_basis()
    print("\n✅ All tests passed")
