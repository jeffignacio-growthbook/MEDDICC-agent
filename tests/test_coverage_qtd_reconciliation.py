"""
Three-way reconciliation of the codebase's independent "QTD closed-won
incremental ARR" computations, built for the config-driven-coverage task
(2026-10-03): before wiring a new current-quarter QTD source into
assess_pipeline_coverage, confirm whether the three existing sources
already agree.

They do NOT. This test runs the three REAL functions (not hand-copied
logic) over one shared fixture and documents the exact, deterministic
divergence found — two independent semantic differences, not a flake:

  1. Renewal-pipeline exclusion test.
     - api/handlers.py::query_path_to_target (inline) and
       scripts/loss_concentration.py::assess_loss_concentration both use
       field_semantics.is_incremental_pipeline() — a DOLLAR-based test
       (new_arr > 0 or expansion_arr > 0). A renewal-pipeline deal with
       real expansion ARR still counts.
     - scripts/analytics/forecast_analyses.py::actual_incremental_closed_won
       uses a PIPELINE_ID-based test (excludes pipeline_id == renewal ID
       outright, expansion or not).
  2. Outcome source.
     - query_path_to_target / assess_loss_concentration trust the
       `deal_status` field (== "won").
     - actual_incremental_closed_won ignores deal_status entirely and
       checks is_won(current `stage`) instead — a real divergence
       whenever those two fields disagree (a data-lag/correction
       scenario, not contrived).

Both differences are demonstrated independently in the fixture below, so
a future fix to either one doesn't mask the other.

THIS TEST DOCUMENTS A KNOWN, UNRESOLVED DIVERGENCE — it is NOT yet a
"they must agree" regression test. See the 2026-10-03 session report for
the recommended resolution (generalize actual_incremental_closed_won's
filter to match the other two, since assess_pipeline_coverage's own
qualified-pipeline population filter already uses deal_status=="won" +
is_incremental_pipeline() in the same file). Once that lands, this file's
assertions must flip from "documents the gap" to "proves the gap is
closed" — do not delete it, update it.
"""
import sys
import asyncio
from pathlib import Path
from datetime import date
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "tests", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

from strict_supabase import StrictSupabase  # noqa: E402
from utils import get_fiscal_quarter  # noqa: E402
import api.handlers as handlers  # noqa: E402
from loss_concentration import assess_loss_concentration  # noqa: E402
from forecast_analyses import actual_incremental_closed_won  # noqa: E402

RENEWAL_ID = "866608541"


def _fixture_window():
    """Real current-quarter boundaries (not a fixed/patched date) — the
    fixture's close_date values are derived from whatever quarter the
    real fiscal-calendar code resolves "today" into, so this test stays
    correct as real time passes rather than drifting stale."""
    q_start, q_end, label = get_fiscal_quarter(date.today())
    mid = (q_start + (q_end - q_start) / 2).isoformat()
    return q_start.isoformat(), q_end.isoformat(), label, mid


def _build_fixture_sb():
    q_start_iso, q_end_iso, label, mid = _fixture_window()
    deals = [
        # Agreed by all three: ordinary new-business win, no edge case.
        {"deal_id": "normal_win", "pipeline_id": "default", "deal_status": "won",
         "stage": "closedwon", "close_date": mid, "new_arr": 100000, "expansion_arr": 0,
         "renewal_revenue": 0, "create_date": q_start_iso, "owner_email": "a@x.com",
         "segment": "SMB", "highest_stage_order_reached": 6},
        # Divergence #1: renewal-pipeline deal WITH real expansion ARR.
        # is_incremental_pipeline() -> True (expansion_arr > 0): counted by
        # path_to_target/loss_concentration. pipeline_id-based exclusion in
        # actual_incremental_closed_won -> excluded outright.
        {"deal_id": "renewal_with_expansion", "pipeline_id": RENEWAL_ID, "deal_status": "won",
         "stage": "1297321623", "close_date": mid, "new_arr": 0, "expansion_arr": 50000,
         "renewal_revenue": 200000, "create_date": q_start_iso, "owner_email": "a@x.com",
         "segment": "SMB", "highest_stage_order_reached": 4},
        # Divergence #2: deal_status says won, but the CURRENT stage is a
        # non-terminal stage (a lag/correction scenario). path_to_target/
        # loss_concentration trust deal_status -> counted.
        # actual_incremental_closed_won checks is_won(stage) -> excluded.
        {"deal_id": "stage_lag", "pipeline_id": "default", "deal_status": "won",
         "stage": "presentationscheduled", "close_date": mid, "new_arr": 75000,
         "expansion_arr": 0, "renewal_revenue": 0, "create_date": q_start_iso,
         "owner_email": "a@x.com", "segment": "SMB", "highest_stage_order_reached": 3},
        # Sanity control: pure renewal (no expansion) contributes $0 to all
        # three regardless of exclusion mechanism — proves the "coincidental
        # agreement" case the module docstrings assume actually holds.
        {"deal_id": "pure_renewal", "pipeline_id": RENEWAL_ID, "deal_status": "won",
         "stage": "1297321623", "close_date": mid, "new_arr": 0, "expansion_arr": 0,
         "renewal_revenue": 300000, "create_date": q_start_iso, "owner_email": "a@x.com",
         "segment": "SMB", "highest_stage_order_reached": 4},
    ]
    return StrictSupabase({"deals": deals, "rep_targets": []}), q_start_iso, q_end_iso, label


def test_pure_renewal_agrees_across_all_three():
    """Sanity control: a renewal deal with zero incremental ARR must
    contribute $0 under every source's exclusion mechanism — proves the
    divergence below is about the edge cases, not a wholesale disagreement."""
    print("\n[TEST] pure-renewal-only deal: $0 under all three sources")
    sb, q_start_iso, q_end_iso, label = _build_fixture_sb()

    total, _n = actual_incremental_closed_won(sb, q_start_iso, q_end_iso)
    lc = assess_loss_concentration(sb, time_window={"start": q_start_iso, "end": q_end_iso,
                                                     "label": label})
    # Isolate pure_renewal's own contribution by re-running with just that row.
    solo_sb = StrictSupabase({"deals": [d for d in sb.tables["deals"]
                                        if d["deal_id"] == "pure_renewal"],
                              "rep_targets": []})
    solo_total, _ = actual_incremental_closed_won(solo_sb, q_start_iso, q_end_iso)
    solo_lc = assess_loss_concentration(solo_sb, time_window={"start": q_start_iso,
                                                              "end": q_end_iso, "label": label})
    assert solo_total == 0.0
    assert solo_lc.get("won_incremental_arr") == 0.0
    print("  ✓ pure_renewal contributes $0 under both exclusion mechanisms")


def test_known_divergence_renewal_with_expansion_and_stage_lag():
    """THE FINDING. Documents the current, real divergence between the
    three QTD sources on the SAME fixture — $225,000 (path_to_target,
    loss_concentration) vs $100,000 (actual_incremental_closed_won),
    driven by the two semantic differences named in this module's
    docstring. This is reported, not silently wired around (per the
    2026-10-03 task's explicit instruction)."""
    print("\n[TEST] known divergence across the three QTD sources (reporting, not asserting agreement)")
    sb, q_start_iso, q_end_iso, label = _build_fixture_sb()

    actual_total, actual_n = actual_incremental_closed_won(sb, q_start_iso, q_end_iso)
    lc = assess_loss_concentration(sb, time_window={"start": q_start_iso, "end": q_end_iso,
                                                     "label": label})
    lc_total = lc.get("won_incremental_arr")

    stub_cov = {
        "status": "ok", "fiscal_quarter": label,
        "qualified_pipeline": {"raw_value": 0.0, "deal_count": 0},
        "stage_weighting": {"weighted_value": 0.0},
        "real_target": {"quota": None, "stretch": None},
    }
    with patch("pipeline_coverage.assess_pipeline_coverage", return_value=stub_cov):
        ptt_result = asyncio.run(handlers.query_path_to_target({}, sb))
    ptt_total = ptt_result.get("qtd_closed_won")

    assert ptt_result.get("error") is None, f"query_path_to_target errored: {ptt_result}"

    # The two deal_status-trusting, dollar-based-exclusion sources agree
    # with EACH OTHER (this part is NOT broken):
    assert ptt_total == lc_total == 225000.0, (
        f"path_to_target={ptt_total} loss_concentration={lc_total} — expected both "
        f"to agree at $225,000 (normal_win $100K + renewal_with_expansion $50K + "
        f"stage_lag $75K); if this no longer holds, one of THOSE two has changed, "
        f"which is a separate regression from the known divergence below")

    # actual_incremental_closed_won disagrees with both, by exactly the two
    # excluded deals' combined value ($50K + $75K = $125K):
    assert actual_total == 100000.0, (
        f"actual_incremental_closed_won={actual_total}, expected $100,000 "
        f"(normal_win only) — if this changed, the known divergence below may "
        f"have narrowed or widened; update this test's numbers and its module "
        f"docstring, do not just raise the assertion")
    assert actual_n == 1

    divergence = (ptt_total or 0) - actual_total
    assert divergence == 125000.0, (
        f"divergence={divergence}, expected exactly $125,000 "
        f"($50K renewal_with_expansion + $75K stage_lag)")

    print(f"  path_to_target / loss_concentration: ${ptt_total:,.0f}")
    print(f"  actual_incremental_closed_won:       ${actual_total:,.0f}")
    print(f"  KNOWN DIVERGENCE:                    ${divergence:,.0f} "
          f"(unresolved as of this commit — see module docstring)")
