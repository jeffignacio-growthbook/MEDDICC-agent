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


# ── Phase 2 — shared scope + per-pipeline ──────────────────────────────

def _make_select_all(week3_rows, deals_rows):
    def _fake(sb, table, columns="*", filters=None, page_size=1000):
        if table == "deals_snapshot":
            return list(week3_rows)   # only the week-3 query reaches here
        if table == "deals":
            return list(deals_rows)
        return []
    return _fake


def test_numerator_and_denominator_share_scope():
    """Both sides apply the same pipeline+stage scope from the shared rule, and
    conversion is computed per pipeline. Meeting Set / null-stage deals are not
    in the denominator; default and renewal are separate."""
    print("\n[TEST] numerator & denominator share scope; per-pipeline")
    from unittest.mock import Mock
    # week-3 snapshot: 2 qualified default (Discovery/Scoping), 1 Meeting Set
    # (excluded), 1 null-stage (not qualified), 1 qualified renewal.
    week3 = [
        {"deal_id": "d1", "stage_id": "appointmentscheduled", "pipeline_id": "default", "deal_value": 1},
        {"deal_id": "d2", "stage_id": "qualifiedtobuy", "pipeline_id": "default", "deal_value": 1},
        {"deal_id": "m1", "stage_id": "79653122", "pipeline_id": "default", "deal_value": 1},  # Meeting Set
        {"deal_id": "n1", "stage_id": None, "pipeline_id": "default", "deal_value": 1},         # null stage
        {"deal_id": "r1", "stage_id": "1297321618", "pipeline_id": "866608541", "deal_value": 1},  # renewal
    ]
    deals = [
        {"deal_id": "w1", "stage": "closedwon", "close_date": "2026-03-01", "pipeline_id": "default"},
        {"deal_id": "wr", "stage": "1297321623", "close_date": "2026-03-05", "pipeline_id": "866608541"},  # renewal won
    ]
    with patch.object(fa, "_get_complete_quarters",
                      return_value=["FY2026 Q4", "FY2027 Q1"]), \
         patch.object(fa, "_quarter_window_iso",
                      return_value=("2026-02-01", "2026-04-30")), \
         patch.object(supabase_client, "select_all",
                      _make_select_all(week3, deals)):
        result = fa.query_week3_conversion(Mock())

    q = result["per_quarter"]["FY2027 Q1"]["by_pipeline"]
    assert q["default"]["week3_scoped_denominator"] == 2, \
        f"default denom should exclude Meeting Set + null-stage, got {q['default']}"
    assert q["866608541"]["week3_scoped_denominator"] == 1, \
        f"renewal denom should be its own, got {q.get('866608541')}"
    # per-pipeline numerator attribution (renewal won stage is a renewal win)
    assert q["default"]["closed_won_count"] == 1
    assert q["866608541"]["closed_won_count"] == 1
    assert result["scope"]["per_pipeline"] is True
    assert "none" in result["scope"]["close_date_filter"]
    print("  ✓ denom excludes Meeting Set/null; default vs renewal separate; "
          "scope reported")


# ── Phase 3 — denominator rule (no close-date filter) ──────────────────

def test_denominator_has_no_close_date_filter():
    """The week-3 denominator is all open in-scope pipeline. A close-date
    filter collapsed it 213 -> 19 and produced 110% conversion. Deals with
    far-future or null close dates must still count."""
    print("\n[TEST] denominator has no close-date filter")
    from unittest.mock import Mock
    week3 = [
        {"deal_id": f"d{i}", "stage_id": "appointmentscheduled",
         "pipeline_id": "default", "deal_value": 1, "close_date": cd}
        for i, cd in enumerate(
            ["2026-03-01", "2027-01-01", None, "2099-12-31", "2026-04-30",
             "2026-11-15", "2028-06-01"])
    ]
    with patch.object(fa, "_get_complete_quarters",
                      return_value=["FY2026 Q4", "FY2027 Q1"]), \
         patch.object(fa, "_quarter_window_iso",
                      return_value=("2026-02-01", "2026-04-30")), \
         patch.object(supabase_client, "select_all",
                      _make_select_all(week3, [])):
        result = fa.query_week3_conversion(Mock())
    denom = (result["per_quarter"]["FY2027 Q1"]["by_pipeline"]
             ["default"]["week3_scoped_denominator"])
    assert denom == 7, (
        f"all 7 qualified deals must count regardless of close_date "
        f"(far-future/null included); got {denom}")
    assert "none" in result["scope"]["close_date_filter"]
    print("  ✓ every qualified deal counts; close_date never collapses the denom")


# ── Phase 4 — null propagation (defect 4) ──────────────────────────────

def test_null_value_excluded_from_both_sides_and_counted():
    """A deal with unknown value is excluded from the sum and the exclusion is
    counted — never coalesced to 0.0. (Excluded from both sides of a ratio:
    the sum uses only real values.)"""
    print("\n[TEST] null value excluded from the sum and counted, not zero-filled")
    from null_propagation import null_propagate
    r = null_propagate([100.0, 200.0, None, None, 300.0], max_null_pct=50)
    assert r["sum"] == 600.0, f"nulls must be excluded, not 0-filled; got {r['sum']}"
    assert r["null_count"] == 2 and r["valued_count"] == 3 and r["total"] == 5
    # A zero-fill would have produced sum 600 too but total-as-5-with-2-zeros;
    # the distinguishing fact is null_count is surfaced, not swallowed.
    assert r["dollar"] == 600.0  # below 50% threshold → trustworthy
    print("  ✓ sum excludes the 2 unknowns and counts them (no 0-fill)")


def test_dollar_basis_returns_null_above_null_threshold():
    """When null-value deals exceed max_null_value_pct, dollar basis returns
    null with a reason. Count basis (valued_count) is unaffected."""
    print("\n[TEST] dollar basis returns null above the null threshold")
    from null_propagation import null_propagate
    # 5 nulls of 100 = exactly 5% → NOT above 5 → still trustworthy.
    lo = null_propagate([1.0] * 95 + [None] * 5, max_null_pct=5)
    assert lo["basis_null"] is False and lo["dollar"] == 95.0, lo
    # 10% > 5% → dollar basis null with reason.
    hi = null_propagate([1.0] * 90 + [None] * 10, max_null_pct=5)
    assert hi["basis_null"] is True, hi
    assert hi["dollar"] is None and hi["reason"], hi
    assert hi["valued_count"] == 90, "count basis unaffected"
    print("  ✓ >5% null → dollar null with reason; count basis intact")


def main():
    print("=" * 70)
    print("FORECAST CORRECTNESS TESTS")
    print("=" * 70)
    tests = [
        test_numerator_counts_in_quarter_transitions_not_terminal_status,
        test_numerator_and_denominator_share_scope,
        test_denominator_has_no_close_date_filter,
        test_null_value_excluded_from_both_sides_and_counted,
        test_dollar_basis_returns_null_above_null_threshold,
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
