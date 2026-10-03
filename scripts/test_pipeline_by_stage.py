#!/usr/bin/env python3
"""
Tests for scripts/pipeline_coverage.py's current-pipeline-by-stage
breakdown (2026-10-03, follow-up to #120).

Context: a real live Slack answer said "most deals are sitting in
Discovery and Scoping" (api/handlers.py::query_pipeline_coverage) — an
unsupported model inference, since assess_pipeline_coverage() never
actually broke qualified pipeline out by stage. This adds
qualified_pipeline.by_stage_order — {stage_order: {"deal_count": int,
"value": float}} — aggregates ONLY (no deal ids, no deal-level detail),
built from qualified_deals (already computed for raw_pipeline_total/
raw_deal_count), not a new query.

Reuses scripts/test_pipeline_coverage.py's mock scaffolding (_run,
_base_deals, RENEWAL_PIPELINE_ID) rather than re-deriving it — same
deals, same mocks, this file only asserts on the new field.

Covers:
1. Aggregation: the two base deals (order 1 $100k, order 2 $50k) each
   produce their own stage_order row with the correct deal_count/value.
2. Multiple deals at the SAME stage_order aggregate (sum value, increment
   deal_count) rather than the last one overwriting the row.
3. Renewal-pipeline and sub-qualified-stage deals (excluded from
   qualified_pipeline itself) must not appear in by_stage_order either —
   same scope, no separate exclusion to get wrong.
4. PLANTED-BUG control (documented, not re-executed here): reverting the
   accumulation in pipeline_coverage.py from `row["deal_count"] += 1` /
   `row["value"] += ...` to a plain overwrite (`row = {"deal_count": 1,
   "value": ...}` on every iteration) makes test 2 fail — confirmed by
   hand during development (revert, run, see the expected failure,
   restore, confirm green again); see this module's test 2 docstring.
"""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "analytics"))
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from test_pipeline_coverage import _run, _base_deals, RENEWAL_PIPELINE_ID  # noqa: E402


def test_by_stage_order_aggregates_count_and_value_per_stage():
    """The two base deals land in two different stage_order rows, each
    with the correct deal_count and dollar value — not lumped into one
    bucket, not dropped."""
    print("\n[TEST] qualified_pipeline.by_stage_order: one row per stage, correct count/value")

    result = _run(_base_deals())
    bso = result["qualified_pipeline"]["by_stage_order"]

    if bso.get(1) != {"deal_count": 1, "value": 100000.0}:
        raise AssertionError(f"Expected stage order 1 row {{'deal_count': 1, "
                             f"'value': 100000.0}}, got {bso.get(1)!r}")
    if bso.get(2) != {"deal_count": 1, "value": 50000.0}:
        raise AssertionError(f"Expected stage order 2 row {{'deal_count': 1, "
                             f"'value': 50000.0}}, got {bso.get(2)!r}")
    print("  ✓ stage order 1 ($100k, 1 deal) and stage order 2 ($50k, 1 deal) both correct")


def test_multiple_deals_same_stage_aggregate_not_overwrite():
    """A second deal at the SAME stage_order (1) must be SUMMED into that
    stage's row (deal_count=2, value=100000+75000), not overwrite the
    first deal's contribution. This is the test a plain `row = {...}`
    assignment (instead of `+=`) would fail — confirmed by hand: reverting
    the real += accumulation to an overwrite and re-running this test
    produces deal_count=1/value=75000 instead, failing the assertion
    below; restoring the real code makes it pass again."""
    print("\n[TEST] second deal at the same stage_order aggregates, does not overwrite")

    extra = [{"deal_id": "gated2", "pipeline_id": "default", "expansion_arr": 0,
              "new_arr": 75000, "stage": "appointmentscheduled",
              "highest_stage_order_reached": 1,
              "close_date": "2026-09-22", "deal_status": "active"}]
    result = _run(_base_deals(extra))
    bso = result["qualified_pipeline"]["by_stage_order"]

    if bso[1]["deal_count"] != 2:
        raise AssertionError(f"Expected stage order 1 deal_count=2 (two deals "
                             f"aggregated), got {bso[1]['deal_count']!r}")
    if bso[1]["value"] != 175000.0:
        raise AssertionError(f"Expected stage order 1 value=175000.0 "
                             f"(100000 + 75000, summed not overwritten), "
                             f"got {bso[1]['value']!r}")
    print("  ✓ stage order 1 row sums both deals: deal_count=2, value=$175,000")


def test_renewal_and_subqualified_deals_excluded_from_by_stage_order():
    """A renewal-pipeline deal and a sub-qualified-stage deal are already
    excluded from qualified_pipeline itself (scripts/test_pipeline_
    coverage.py's own scope test) — this confirms the SAME exclusion
    applies to by_stage_order, since it's built from the same
    qualified_deals list, not a separate query that could silently
    diverge in scope."""
    print("\n[TEST] renewal + sub-qualified deals excluded from by_stage_order too")

    extra = [
        {"deal_id": "renewal1", "pipeline_id": RENEWAL_PIPELINE_ID,
         "expansion_arr": 0, "new_arr": 0, "renewal_revenue": 999999,
         "stage": "presentationscheduled", "highest_stage_order_reached": 3,
         "close_date": "2026-09-10", "deal_status": "active"},
        {"deal_id": "subqual1", "pipeline_id": "default", "expansion_arr": 0,
         "new_arr": 777777, "stage": "79653122", "highest_stage_order_reached": 0,
         "close_date": "2026-09-10", "deal_status": "active"},
    ]
    result = _run(_base_deals(extra))
    bso = result["qualified_pipeline"]["by_stage_order"]

    total_deal_count = sum(row["deal_count"] for row in bso.values())
    total_value = sum(row["value"] for row in bso.values())
    if total_deal_count != 2:
        raise AssertionError(f"Expected only the 2 qualified deals across all "
                             f"by_stage_order rows, got total deal_count="
                             f"{total_deal_count} (rows: {bso!r})")
    if total_value != 150000.0:
        raise AssertionError(f"Expected total by_stage_order value=150000.0 "
                             f"(renewal/sub-qualified excluded), got {total_value!r}")
    print("  ✓ by_stage_order totals match qualified_pipeline exactly (2 deals, $150,000)")


def main():
    tests = [
        test_by_stage_order_aggregates_count_and_value_per_stage,
        test_multiple_deals_same_stage_aggregate_not_overwrite,
        test_renewal_and_subqualified_deals_excluded_from_by_stage_order,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1

    print("\n✅ All qualified_pipeline.by_stage_order tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
