#!/usr/bin/env python3
"""
query_pipeline's this-quarter figure must not depend on a rep_targets row.

Until 2026-09-24 the close-date-scoped total (q3_scoped_pipeline /
q3_scoped_deals) was computed only inside the branch that found a team
incremental_arr target for the current quarter. rep_targets holds one such
row (FY2027_Q3), so from 2026-11-01 the answer would silently lose its
this-quarter figure. The quarter's dates also came from
resolve_time_window({"time_window": label}), a shape the resolver ignores:
it fell back to today's quarter and never parsed the label.

Now:
  - the this-quarter total is computed whenever the quarter resolves, and its
    dates come from the label itself;
  - coverage still needs a target: without one, coverage_ratio is None and
    coverage_omitted_reason says why, and the note tells the model to say so.

Runs the real handler against a fake Supabase, with the current quarter
pinned (no waiting for Nov 1).
"""
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.handlers as handlers  # noqa: E402
import time_resolver  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import api.router as router  # noqa: E402
from canary_harness import run_canary_case  # noqa: E402


def _deal(deal_id, close, arr):
    return {"deal_id": deal_id, "company_name": f"Co{deal_id}", "deal_value": arr,
            "stage": "presentationscheduled", "close_date": close, "owner_email": "a@x.com",
            "pipeline_id": "default", "new_arr": arr, "expansion_arr": None, "renewal_revenue": None}


DEALS = [
    _deal("Q3a", "2026-09-30", 100000),   # FY2027 Q3 (Aug-Oct)
    _deal("Q4a", "2026-11-15", 40000),    # FY2027 Q4 (Nov-Jan)
    _deal("Q4b", "2027-01-20", 60000),    # FY2027 Q4
    _deal("Q1a", "2027-03-01", 25000),    # FY2028 Q1
]


class _SB:
    """rep_targets holds only what `targets` says: {period: value}."""

    def __init__(self, targets):
        self.targets = targets

    def table(self, name):
        sb = self

        class _Q:
            def __init__(self):
                self.period = None

            def select(self, *a, **k):
                return self

            def eq(self, col, val):
                if col == "period":
                    self.period = val
                return self

            def __getattr__(self, _):
                return lambda *a, **k: self

            def execute(self):
                data = []
                if name == "rep_targets" and self.period in sb.targets:
                    data = [{"target_value": sb.targets[self.period]}]
                return type("R", (), {"data": data})()
        return _Q()


def _run(quarter, targets):
    saved = (handlers.select_all, time_resolver.current_quarter_label)
    handlers.select_all = lambda sb, table, columns="*", filters=None, **kw: [dict(d) for d in DEALS]
    time_resolver.current_quarter_label = lambda *a, **k: quarter
    try:
        return asyncio.run(handlers.query_pipeline({}, _SB(targets)))
    finally:
        handlers.select_all, time_resolver.current_quarter_label = saved


def test_no_target_row_keeps_the_quarter_total_and_states_why_coverage_is_missing():
    r = _run("FY2027_Q4", {"FY2027_Q3": 1_550_000})          # the live table on 2026-09-24
    assert (r["q3_scoped_pipeline"], r["q3_scoped_deals"]) == (100000, 2), \
        (r["q3_scoped_pipeline"], r["q3_scoped_deals"])        # Q4a + Q4b
    assert r["this_quarter"] == {"label": "FY2027 Q4", "start": "2026-11-01", "end": "2027-01-31"}, \
        r["this_quarter"]
    assert r["coverage_ratio"] is None and r["quarterly_target"] is None
    assert r["coverage_omitted_reason"] == "No FY2027 Q4 team incremental_arr target loaded yet", \
        r["coverage_omitted_reason"]
    note = r["_synthesis_note"]
    assert "$100,000 closing in FY2027 Q4" in note, note[:600]
    assert "No FY2027 Q4 team incremental_arr target loaded yet" in note
    print("✓ no FY2027 Q4 target: the Q4 total ($100,000, 2 deals, Nov 1 - Jan 31) is still "
          "returned; coverage is None with the stated reason, and the note says both")


def test_with_a_target_coverage_is_computed_as_before():
    r = _run("FY2027_Q3", {"FY2027_Q3": 1_550_000})
    assert (r["q3_scoped_pipeline"], r["q3_scoped_deals"]) == (100000, 1)
    assert r["quarterly_target"] == 1_550_000
    assert abs(r["coverage_ratio"] - 100000 / 1_550_000) < 1e-12
    assert r["coverage_omitted_reason"] is None
    print(f"✓ with the FY2027 Q3 target: coverage {r['coverage_ratio']:.4f}x of $1,550,000, no omission reason")


def test_the_quarter_label_is_parsed_not_ignored():
    """The old call resolve_time_window({"time_window": label}) ignored the
    label and returned today's quarter; pinning Q2 must give Q2's dates."""
    r = _run("FY2027_Q2", {})
    assert r["this_quarter"]["start"] == "2026-05-01" and r["this_quarter"]["end"] == "2026-07-31", \
        r["this_quarter"]
    assert r["q3_scoped_deals"] == 0 and r["q3_scoped_pipeline"] == 0
    print("✓ the pinned label drives the dates (FY2027_Q2 -> May 1 - Jul 31), not today's quarter")


def test_the_omission_reaches_both_synthesis_paths():
    r = _run("FY2027_Q4", {"FY2027_Q3": 1_550_000})
    want = "omitted: No FY2027 Q4 team incremental_arr target loaded yet"
    classifier = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(r)), router.SYNTH_PAYLOAD_CHARS)
    loop = run_canary_case("what is our pipeline", "query_pipeline", {}, r)["synthesis_text"]
    for name, text in (("classifier", classifier), ("dynamic loop", loop)):
        assert json.dumps(want)[1:-1] in text, name
        assert '"coverage_omitted_reason"' in text, name
    print("✓ the coverage omission and its reason reach the synthesis input on both paths")


if __name__ == "__main__":
    test_no_target_row_keeps_the_quarter_total_and_states_why_coverage_is_missing()
    test_with_a_target_coverage_is_computed_as_before()
    test_the_quarter_label_is_parsed_not_ignored()
    test_the_omission_reaches_both_synthesis_paths()
    print("\n✅ All tests passed")
