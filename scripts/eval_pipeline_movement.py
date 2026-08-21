#!/usr/bin/env python3
"""
Eval: query_pipeline_movement handler (reads deals_snapshot, counts only).

Guards the non-negotiable rules from PIPELINE_MOVEMENT_HANDLER_SPEC.md:
  - analytics scope applied at read time AND reported in the output
  - counts only — deal_value is never summed, averaged, or returned
  - null-stage rows counted as 'unknown', never dropped
  - backfill_confidence mix reported per week
  - the two weekday grids (backfilled Monday vs forward) never silently mixed
  - missing snapshot returns null-with-reason, never a zero that reads as empty

Supabase is mocked the way eval_ae_handlers.py does it — by patching
handlers.select_all — so no live DB is required.
"""

import sys
import types
import inspect
import asyncio
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

# Offline import shim: handlers -> supabase_client -> supabase (not installed
# in the eval env). We patch select_all in every test, so the stub is never
# actually called.
if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

import handlers  # noqa: E402
from handlers import query_pipeline_movement  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────

def _row(deal_id, date, stage_id, *, pipeline_id="default", order=None,
         source="backfilled", confidence="exact", owner="ae@co.com",
         fq="FY2027 Q2", woq=1):
    return {
        "deal_id": str(deal_id),
        "snapshot_date": date,
        "pipeline_id": pipeline_id,
        "stage_id": stage_id,
        "stage_order": order,
        "close_date": None,
        "owner_email": owner,
        "deal_status": "active",
        "snapshot_source": source,
        "backfill_confidence": confidence,
        "fiscal_quarter": fq,
        "week_of_quarter": woq,
    }


def _make_select_all(rows):
    """Fake select_all that honors the eq filters the handler passes."""
    def _fake(sb, table, columns="*", filters=None, page_size=1000):
        assert table == "deals_snapshot", f"unexpected table {table}"
        out = list(rows)
        for f in (filters or []):
            if f[0] == "eq":
                col, val = f[1], f[2]
                out = [r for r in out if str(r.get(col)) == str(val)]
        return out
    return _fake


def _run(rows, params):
    with patch.object(handlers, "select_all", _make_select_all(rows)):
        return asyncio.run(query_pipeline_movement(params, sb=object()))


# ── tests ────────────────────────────────────────────────────────────────

def test_scoping_applied_and_reported():
    """Excluded stages and pipeline scope are applied at read time, and the
    scope used is present in the output."""
    print("\n[TEST] scoping applied at read time and reported")
    # Two Monday snapshots. In-scope: Discovery + Scoping. Out of scope:
    # a Meeting Set (order 0, excluded), a Closed Won (terminal), and a
    # renewal-pipeline deal.
    rows = []
    for d, woq in (("2026-07-13", 1), ("2026-07-20", 2)):
        rows += [
            _row("d1", d, "appointmentscheduled", order=1, woq=woq),   # Discovery
            _row("d2", d, "qualifiedtobuy", order=2, woq=woq),         # Scoping
            _row("d3", d, "79653122", order=0, woq=woq),               # Meeting Set (excluded)
            _row("d4", d, "closedwon", order=6, woq=woq),              # Closed Won (terminal)
            _row("d5", d, "1297321618", pipeline_id="866608541",
                 order=0, woq=woq),                                    # renewal (excluded pipeline)
        ]
    result = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q2"})

    stages = {s["stage"]: s for s in result["by_stage"]}
    assert set(stages) == {"Discovery", "Scoping"}, \
        f"only in-scope stages should appear, got {set(stages)}"
    assert result["totals"]["current"] == 2, \
        f"2 in-scope deals expected, got {result['totals']['current']}"
    assert "Meeting Set" not in stages and "Closed Won (default)" not in stages
    # scope reported
    assert "scope" in result and "excluded_stages" in result["scope"]
    assert "866608541" in result["scope"]["excluded_pipelines"]
    print("  ✓ Meeting Set, Closed Won, and renewal pipeline excluded; scope reported")


def test_never_aggregates_deal_value():
    """Static check: the handler does not sum, avg, or return deal_value.
    Dollar aggregation is blocked until the null-coalescing ledger is worked
    off."""
    print("\n[TEST] handler never touches deal_value (counts only)")
    # deal_value must not even be selected.
    assert "deal_value" not in handlers._PM_SNAPSHOT_COLUMNS, \
        "deal_value must not be in the selected columns"
    # No pipeline-movement function may reference deal_value in actual CODE.
    # Ignore comments and string literals (a comment may legitimately explain
    # *why* deal_value is never used) — only a real name/attribute reference
    # is a violation.
    import io
    import tokenize as _tok

    def _code_mentions_deal_value(src):
        toks = _tok.generate_tokens(io.StringIO(src).readline)
        for t in toks:
            if t.type in (_tok.COMMENT, _tok.STRING):
                continue
            if t.type == _tok.NAME and t.string == "deal_value":
                return True
        return False

    offenders = []
    for name, obj in vars(handlers).items():
        if (name == "query_pipeline_movement" or name.startswith("_pm_")) \
                and inspect.isfunction(obj):
            if _code_mentions_deal_value(inspect.getsource(obj)):
                offenders.append(name)
    assert not offenders, f"deal_value referenced in code of: {offenders}"
    # basis is explicitly 'count'
    rows = [_row("d1", "2026-07-13", "appointmentscheduled", order=1),
            _row("d1", "2026-07-20", "appointmentscheduled", order=1)]
    result = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q2"})
    assert result["basis"] == "count"
    print("  ✓ deal_value never selected/summed; basis=count")


def test_null_stage_rows_counted_as_unknown_not_dropped():
    """A no_history deal appears as stage 'unknown', not absent. Dropping it
    understates population."""
    print("\n[TEST] null-stage rows counted as 'unknown', not dropped")
    rows = []
    for d in ("2026-07-13", "2026-07-20"):
        rows += [
            _row("d1", d, "appointmentscheduled", order=1),
            # no_history deal: stage_id is None, genuinely open, unknown stage
            _row("nh", d, None, order=None, source="backfilled",
                 confidence="no_history"),
        ]
    result = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q2"})
    stages = {s["stage"]: s for s in result["by_stage"]}
    assert "unknown" in stages, f"null-stage deal must show as 'unknown', got {set(stages)}"
    assert stages["unknown"]["current"] == 1
    assert result["totals"]["current"] == 2, "null-stage deal must be counted in the total"
    print("  ✓ no_history deal counted as stage 'unknown' and in the total")


def test_confidence_mix_reported_per_week():
    """Output carries the exact/pre_history/no_history split so thin weeks can
    be caveated."""
    print("\n[TEST] confidence mix reported per week")
    rows = [
        _row("a", "2026-07-13", "appointmentscheduled", order=1, confidence="exact", woq=1),
        _row("b", "2026-07-13", "qualifiedtobuy", order=2, confidence="pre_history", woq=1),
        _row("a", "2026-07-20", "appointmentscheduled", order=1, confidence="exact", woq=2),
        _row("b", "2026-07-20", "qualifiedtobuy", order=2, confidence="no_history", woq=2),
    ]
    comp = _run(rows, {"view": "composition", "fiscal_quarter": "FY2027 Q2", "weeks": 4})
    for wk in comp["weeks"]:
        assert set(_PM := ("exact", "pre_history", "no_history")).issubset(wk["confidence"]), \
            f"each week must carry the confidence split, got {wk['confidence']}"
    last = comp["weeks"][-1]["confidence"]
    assert last["no_history"] == 1 and last["exact"] == 1, \
        f"week confidence mix wrong: {last}"
    # movement view also reports confidence
    mv = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q2"})
    assert set(("exact", "pre_history", "no_history")).issubset(mv["confidence"])
    print("  ✓ per-week confidence split present in composition and movement")


def test_grid_mismatch_surfaces_as_data_gap():
    """A query spanning backfilled (Monday) and prospective (other weekday)
    rows either restricts to one source or reports the dates used. It never
    silently mixes grids."""
    print("\n[TEST] grid mismatch surfaces as data_gap, never silently mixed")
    rows = [
        # backfilled Monday grid (2 dates → the dominant grid)
        _row("a", "2026-07-13", "appointmentscheduled", order=1, source="backfilled"),
        _row("a", "2026-07-20", "appointmentscheduled", order=1, source="backfilled"),
        # a stray forward-grid row on a Wednesday
        _row("b", "2026-07-22", "qualifiedtobuy", order=2, source="prospective"),
    ]
    result = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q2"})
    assert result["snapshot_source"] == "backfilled", \
        "should pick the dominant (backfilled) grid"
    assert result["snapshot_dates"] == ["2026-07-13", "2026-07-20"], \
        "must not mix the Wednesday prospective date into the Monday grid"
    assert any("grid" in g.lower() for g in result["data_gaps"]), \
        f"grid mismatch must be surfaced as a data_gap, got {result['data_gaps']}"
    print("  ✓ dominant grid chosen; other grid reported as data_gap, not mixed")


def test_returns_null_not_zero_when_no_snapshot_for_week():
    """A week with no snapshot row returns null with a reason, not a zero
    count that reads as an empty pipeline."""
    print("\n[TEST] missing snapshot → null with reason, not zero")
    # Only ONE snapshot date → movement (which needs two) must return null.
    rows = [_row("a", "2026-07-13", "appointmentscheduled", order=1)]
    result = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q2"})
    assert result["totals"]["current"] is None and result["totals"]["net"] is None, \
        f"totals must be null, not zero, got {result['totals']}"
    assert result["by_stage"] == [], "no fabricated stage rows"
    assert any("null" in g.lower() or "two snapshot" in g.lower()
               for g in result["data_gaps"]), \
        f"must explain the null, got {result['data_gaps']}"
    # And an entirely absent quarter → null result + reason, never zero.
    empty = _run([], {"view": "movement", "fiscal_quarter": "FY2099 Q1"})
    assert empty["result"] is None and empty["data_gaps"], \
        "absent quarter must return null with a reason"
    print("  ✓ single-date movement and absent quarter both return null-with-reason")


def test_all_four_views_run():
    """Sanity: each of the four views returns its expected shape."""
    print("\n[TEST] all four views produce their shape")
    rows = []
    for d, woq in (("2026-07-06", 1), ("2026-07-13", 2), ("2026-07-20", 3)):
        rows += [
            _row("d1", d, "appointmentscheduled", order=1, woq=woq),
            _row("d2", d, "qualifiedtobuy", order=2, woq=woq),
        ]
    # deal_changes: move d2 forward on the last date
    rows.append(_row("d2", "2026-07-20", "presentationscheduled", order=3, woq=3))
    # (the later row for d2 on 2026-07-20 overrides via _pm_latest_row_per_deal)

    mv = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q2"})
    assert "by_stage" in mv and "totals" in mv

    comp = _run(rows, {"view": "composition", "fiscal_quarter": "FY2027 Q2", "weeks": 3})
    assert "weeks" in comp and len(comp["weeks"]) == 3

    dc = _run(rows, {"view": "deal_changes", "fiscal_quarter": "FY2027 Q2"})
    assert "changes" in dc and "summary" in dc

    cv = _run(rows, {"view": "curve", "fiscal_quarter": "FY2027 Q2"})
    assert "curve" in cv and all("week_of_quarter" in c for c in cv["curve"])
    print("  ✓ movement / composition / deal_changes / curve all return their shape")


def test_views_emit_entity_bearing_rows_for_thread_context():
    """Every view returns a `rows` list whose items carry deal_id, so
    extract_entity_context saves entities and follow-up drill-downs have
    context. This is the regression guard for the reported break: the
    movement view used to return pure counts, save_thread stored zero
    entities, and 'which deals are in Discovery?' fell through with no IDs."""
    print("\n[TEST] every view emits entity-bearing rows (deal_id present)")
    rows = []
    for d in ("2026-07-13", "2026-07-20"):
        rows += [
            _row("d1", d, "appointmentscheduled", order=1),
            _row("d2", d, "qualifiedtobuy", order=2),
        ]
    rows.append(_row("d2", "2026-07-20", "presentationscheduled", order=3))

    for view in ("movement", "composition", "curve", "deal_changes"):
        res = _run(rows, {"view": view, "fiscal_quarter": "FY2027 Q2"})
        assert "rows" in res, f"{view} must return a rows list"
        assert res["rows"], f"{view} rows must be non-empty"
        assert all("deal_id" in r for r in res["rows"]), \
            f"{view} rows must each carry deal_id for entity extraction"
    print("  ✓ movement/composition/curve/deal_changes all carry deal_id rows")


def test_movement_by_stage_carries_drillable_deal_ids():
    """by_stage entries carry deal_ids (current members) so the counts are
    drillable, and the ids line up with the counts."""
    print("\n[TEST] movement by_stage carries deal_ids matching the counts")
    rows = []
    for d in ("2026-07-13", "2026-07-20"):
        rows += [
            _row("d1", d, "appointmentscheduled", order=1),
            _row("d2", d, "appointmentscheduled", order=1),
            _row("d3", d, "qualifiedtobuy", order=2),
        ]
    res = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q2"})
    disc = next(s for s in res["by_stage"] if s["stage"] == "Discovery")
    assert disc["deal_ids"] == ["d1", "d2"], f"got {disc['deal_ids']}"
    assert len(disc["deal_ids"]) == disc["current"], "deal_ids must match current count"
    print("  ✓ by_stage.deal_ids present and consistent with the counts")


def test_stage_deals_view_lists_deals_in_a_stage():
    """The stage_deals view answers 'which deals are in Discovery?' directly —
    a stage-filtered deal list at the latest snapshot."""
    print("\n[TEST] stage_deals view filters to one stage")
    rows = []
    for d in ("2026-07-13", "2026-07-20"):
        rows += [
            _row("d1", d, "appointmentscheduled", order=1),   # Discovery
            _row("d2", d, "appointmentscheduled", order=1),   # Discovery
            _row("d3", d, "qualifiedtobuy", order=2),         # Scoping
        ]
    res = _run(rows, {"view": "stage_deals", "fiscal_quarter": "FY2027 Q2",
                      "stage": "Discovery"})
    assert res["count"] == 2, f"expected 2 Discovery deals, got {res['count']}"
    assert {r["deal_id"] for r in res["rows"]} == {"d1", "d2"}
    assert all(r["stage"] == "Discovery" for r in res["rows"])
    # unknown stage → empty with a helpful data_gap, not a crash
    miss = _run(rows, {"view": "stage_deals", "fiscal_quarter": "FY2027 Q2",
                       "stage": "Nonexistent"})
    assert miss["count"] == 0 and miss["data_gaps"]
    print("  ✓ stage_deals returns the filtered deal list; unknown stage → data_gap")


def test_stage_copied_source_caveats_movement():
    """backfill_current_quarter stamps the current stage on every week, so
    stage exits are structurally zero. The movement/deal_changes views must
    say so — otherwise a structural zero reads as a real 'nothing moved'."""
    print("\n[TEST] stage-copied source caveated on movement/deal_changes")
    # Same stage per deal across both weeks (as backfill_current_quarter does),
    # plus one deal that entered on the second date.
    rows = [
        _row("a", "2026-08-10", "appointmentscheduled", order=1,
             source="backfill_current_quarter", fq="FY2027 Q3", woq=1),
        _row("b", "2026-08-10", "qualifiedtobuy", order=2,
             source="backfill_current_quarter", fq="FY2027 Q3", woq=1),
        _row("a", "2026-08-17", "appointmentscheduled", order=1,
             source="backfill_current_quarter", fq="FY2027 Q3", woq=2),
        _row("b", "2026-08-17", "qualifiedtobuy", order=2,
             source="backfill_current_quarter", fq="FY2027 Q3", woq=2),
        _row("c", "2026-08-17", "appointmentscheduled", order=1,
             source="backfill_current_quarter", fq="FY2027 Q3", woq=2),  # entered
    ]
    mv = _run(rows, {"view": "movement", "fiscal_quarter": "FY2027 Q3"})
    # structural: every stage shows 0 exits
    assert all(s["exited"] == 0 for s in mv["by_stage"]), \
        "stage-copied source yields structurally zero exits"
    assert any("point-in-time" in g or "stamps each deal" in g
               for g in mv["data_gaps"]), \
        f"movement must caveat the stage-copied source, got {mv['data_gaps']}"
    # composition (a pure count) is valid on the same source → no such caveat
    comp = _run(rows, {"view": "composition", "fiscal_quarter": "FY2027 Q3"})
    assert not any("stamps each deal" in g for g in comp["data_gaps"]), \
        "composition is a valid point-in-time count; should not carry the caveat"
    print("  ✓ movement caveats stage-copied source; composition does not")


def main():
    print("=" * 70)
    print("PIPELINE MOVEMENT HANDLER TESTS")
    print("=" * 70)
    tests = [
        test_scoping_applied_and_reported,
        test_never_aggregates_deal_value,
        test_null_stage_rows_counted_as_unknown_not_dropped,
        test_confidence_mix_reported_per_week,
        test_grid_mismatch_surfaces_as_data_gap,
        test_returns_null_not_zero_when_no_snapshot_for_week,
        test_all_four_views_run,
        test_views_emit_entity_bearing_rows_for_thread_context,
        test_movement_by_stage_carries_drillable_deal_ids,
        test_stage_deals_view_lists_deals_in_a_stage,
        test_stage_copied_source_caveats_movement,
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
