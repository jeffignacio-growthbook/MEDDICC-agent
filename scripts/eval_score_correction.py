#!/usr/bin/env python3
"""
Eval: score correction path (FIX_MEDDICC_SCORING_PIPELINE, Part 7).

The first version a rep sees should be one they can argue with. A correction is
captured as structured feedback (component, proposed score, reason) into a
REVIEW QUEUE — it must NEVER auto-adjust a score. Agent proposes, human
disposes.
"""
import sys
import types
import asyncio
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f


class MockSB:
    """Records inserts per table; serves deals (company resolve) + analyses."""
    def __init__(self, deals=None, analyses=None):
        self._deals = deals or []
        self._analyses = analyses or []
        self.inserted = {}          # table -> [rows]
        self._t = None

    def table(self, name):
        self._t = name
        return self

    def select(self, *a, **k):
        return self

    def ilike(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def insert(self, row):
        self.inserted.setdefault(self._t, []).append(row)
        return self

    def execute(self):
        data = {"deals": self._deals, "analyses": self._analyses}.get(self._t, [])
        return types.SimpleNamespace(data=data)


def run():
    from api.handlers import submit_score_correction
    print("=" * 72)
    print("SCORE CORRECTION — review queue, never auto-apply (Part 7)")
    print("=" * 72)
    passed = failed = 0

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1; print(f"  ✓ {name}")
        else:
            failed += 1; print(f"  ❌ {name}")

    deals = [{"deal_id": "62160567676", "company_name": "LiveSport Media"}]
    analyses = [{"deal_id": "62160567676", "champion_score": 5,
                 "analyzed_at": "2026-08-19T00:00:00Z", "passed": True}]

    # 1. Valid correction → logged, captured to score_corrections, NOT applied.
    sb = MockSB(deals, analyses)
    r = asyncio.run(submit_score_correction(
        {"company": "LiveSport", "component": "champion", "proposed_score": 7,
         "correction_reason": "Tomáš is presenting to the CPO next week",
         "submitted_by": "U0AAMMUPSA2"}, sb))
    check("valid correction logged", r.get("logged") is True)
    check("written to score_corrections table",
          len(sb.inserted.get("score_corrections", [])) == 1)
    row = (sb.inserted.get("score_corrections") or [{}])[0]
    check("row carries component/proposed/reason/submitter",
          row.get("component") == "champion" and row.get("proposed_score") == 7
          and row.get("reason") and row.get("submitted_by") == "U0AAMMUPSA2")
    check("captured current score for context (5)", row.get("current_score") == 5)
    check("status is 'proposed' (awaiting human review)",
          row.get("status") == "proposed")
    check("did NOT write to analyses (no auto-apply)",
          "analyses" not in sb.inserted)
    check("reply says it does not auto-change the score",
          "does not change" in (r.get("note") or "").lower()
          or "not change the score automatically" in (r.get("note") or "").lower())

    # 2. Missing proposed_score → clear error, not logged, no raise.
    sb2 = MockSB(deals, analyses)
    r2 = asyncio.run(submit_score_correction(
        {"company": "LiveSport", "component": "champion",
         "correction_reason": "too low"}, sb2))
    check("missing proposed_score → error, not logged",
          r2.get("logged") is False and "error" in r2
          and not sb2.inserted.get("score_corrections"))

    # 3. Unknown component → error.
    r3 = asyncio.run(submit_score_correction(
        {"component": "vibes", "proposed_score": 7, "correction_reason": "x"},
        MockSB()))
    check("unknown component → error, not logged",
          r3.get("logged") is False and "error" in r3)

    # 4. Out-of-range score → error.
    r4 = asyncio.run(submit_score_correction(
        {"component": "champion", "proposed_score": 99,
         "correction_reason": "x"}, MockSB()))
    check("score out of 0-10 → error, not logged",
          r4.get("logged") is False and "error" in r4)

    # 5. Empty params → error, never raises.
    r5 = asyncio.run(submit_score_correction({}, MockSB()))
    check("empty params → error dict, no raise", r5.get("logged") is False)

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
