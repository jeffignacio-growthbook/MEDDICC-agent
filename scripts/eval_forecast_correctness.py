#!/usr/bin/env python3
"""
Analysis-correctness tests for forecast_analyses.py (and the ledger).

Offline: forecast_analyses imports supabase at module load, so we stub it;
every test patches the data-access seam it needs.
"""
import sys
import types
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
for p in ("scripts", "scripts/analytics", "api", "."):
    sys.path.insert(0, str(REPO / p))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

import supabase_client  # noqa: E402
from analytics import forecast_analyses as fa  # noqa: E402


def _deal(deal_id, stage, close_date, pipeline_id="default"):
    return {"deal_id": str(deal_id), "stage": stage,
            "close_date": close_date, "pipeline_id": pipeline_id}


# ── Phase 1 — numerator ────────────────────────────────────────────────

def test_numerator_counts_in_quarter_transitions_not_terminal_status():
    """A deal won in Q1 must not appear in Q2's numerator. Cumulative counting
    overstated wins; the numerator counts a deal only in the quarter its
    close_date falls in."""
    print("\n[TEST] numerator counts in-quarter wins, not cumulative")
    deals = [
        _deal("q1a", "closedwon", "2026-02-15"),  # FY2027 Q1
        _deal("q1b", "closedwon", "2026-04-30"),  # FY2027 Q1 (edge)
        _deal("q2a", "closedwon", "2026-05-01"),  # FY2027 Q2 (edge)
        _deal("q2b", "closedwon", "2026-07-10"),  # FY2027 Q2
        _deal("open", "appointmentscheduled", "2026-06-01"),  # not won
        _deal("nodate", "closedwon", None),       # no close date → excluded
    ]
    with patch.object(supabase_client, "select_all", return_value=deals):
        q1 = fa._in_quarter_won_by_pipeline(None, "2026-02-01", "2026-04-30")
        q2 = fa._in_quarter_won_by_pipeline(None, "2026-05-01", "2026-07-31")
    assert sum(q1.values()) == 2, f"Q1 should have 2 in-quarter wins, got {q1}"
    assert sum(q2.values()) == 2, f"Q2 should have 2 in-quarter wins, got {q2}"
    # The decisive assertion: a Q1 win does NOT leak into Q2 (cumulative bug).
    total_all = sum(q1.values()) + sum(q2.values())
    assert total_all == 4, "no deal is counted in more than one quarter"
    print("  ✓ each won deal counts only in its close-date quarter (no cumulation)")


def main():
    print("=" * 70)
    print("FORECAST CORRECTNESS TESTS")
    print("=" * 70)
    tests = [
        test_numerator_counts_in_quarter_transitions_not_terminal_status,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n❌ FAILED: {t.__name__}\n   {e}")
        except Exception as e:
            failed += 1
            print(f"\n❌ ERROR in {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
