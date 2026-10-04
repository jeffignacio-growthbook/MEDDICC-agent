"""
Three-way (now four-way-reported) reconciliation of the codebase's
independent "QTD closed-won incremental ARR" computations, built for the
config-driven-coverage task (2026-10-03).

RESOLVED 2026-10-03: scripts/analytics/forecast_analyses.py::
actual_incremental_closed_won's filter was generalized to match
api/handlers.py::query_path_to_target's inline QTD computation and
scripts/loss_concentration.py::assess_loss_concentration's
won_incremental_arr — all three now use is_incremental_pipeline()
(dollar-based: new_arr > 0 or expansion_arr > 0, pipeline_id-agnostic) +
deal_status == "won". Before the fix, this fixture showed a real,
deterministic $125,000 divergence ($225,000 vs $100,000) driven by two
independent semantic differences:
  1. Renewal-pipeline exclusion test: dollar-based (is_incremental_
     pipeline) vs. pipeline_id-based (excludes a renewal deal outright,
     even with real expansion ARR).
  2. Outcome source: deal_status == "won" vs. is_won(current `stage`)
     (a real divergence whenever those two fields disagree — a data-lag
     /correction scenario, not contrived).
This file now asserts the three agree, and will fail loudly again if
that drifts apart in the future — do not weaken these assertions without
re-running the real-data audit (scripts/audit_qtd_filter_change.py).

RESOLVED 2026-10-03 (attainment PR): a FOURTH source,
api/handlers.py::query_rep_attainment's own won-ARR total
(team_summary.closed_won_qtd), was found to have the SAME now-abandoned
pipeline_id-based renewal exclusion the OLD actual_incremental_closed_won
used, plus an independent bug: a won deal with a missing or unmapped
owner_email was silently dropped from the team total entirely (not just
from per-rep attribution). On the fixture below (pre-fix) this totaled
$175,000 against the other three sources' $225,000 — a $50,000 gap from
the renewal-pipeline exclusion alone, confirmed live against real FY2027
Q3 data as a $13,285 gap ($506,775/11 deals vs. $520,060/12 deals) by
scripts/audit_qtd_filter_change.py (branch audit/attainment-reconciliation,
commit 0850788b).

query_rep_attainment is now fixed to source team_summary.closed_won_qtd
directly from forecast_analyses.actual_incremental_closed_won() (the same
function and window the pipeline-coverage handler's qtd_won uses) and to
classify renewal exclusion via is_incremental_pipeline(), matching the
other three sources exactly. A won deal with a missing or unmapped
owner_email is never dropped: it is counted in the team total and
aggregated into a single "no quota assigned" line in reps[] instead of
being attributed to a named rep who never owned it, or disappearing.
test_query_rep_attainment_matches_other_sources (below) is the proof —
it now asserts agreement instead of documenting the gap. A unification of
query_path_to_target's and assess_loss_concentration's own, separate
copies of this same filter is still tracked as a separate follow-up, not
done here (per the original task's explicit instruction to leave those
two alone).

NOT consolidated in this change (deliberately, to keep this change
reviewable): query_path_to_target's inline QTD computation and
assess_loss_concentration's won_incremental_arr keep their own, separate
implementations of the same now-matching filter definition. Filed as a
follow-up, not done in this PR.
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
        # Agreed by all sources: ordinary new-business win, no edge case.
        {"deal_id": "normal_win", "pipeline_id": "default", "deal_status": "won",
         "stage": "closedwon", "close_date": mid, "new_arr": 100000, "expansion_arr": 0,
         "renewal_revenue": 0, "create_date": q_start_iso, "owner_email": "a@x.com",
         "segment": "SMB", "highest_stage_order_reached": 6},
        # Renewal-pipeline deal WITH real expansion ARR.
        # is_incremental_pipeline() -> True (expansion_arr > 0): counted
        # by path_to_target/loss_concentration/actual_incremental_closed_won
        # (post-fix). query_rep_attainment's OWN pipeline_id-based
        # exclusion still drops it — that is the reported 4th-source gap.
        {"deal_id": "renewal_with_expansion", "pipeline_id": RENEWAL_ID, "deal_status": "won",
         "stage": "1297321623", "close_date": mid, "new_arr": 0, "expansion_arr": 50000,
         "renewal_revenue": 200000, "create_date": q_start_iso, "owner_email": "a@x.com",
         "segment": "SMB", "highest_stage_order_reached": 4},
        # deal_status says won, but the CURRENT stage is a non-terminal
        # stage (a lag/correction scenario). All four sources here trust
        # deal_status, not stage -> counted by all.
        {"deal_id": "stage_lag", "pipeline_id": "default", "deal_status": "won",
         "stage": "presentationscheduled", "close_date": mid, "new_arr": 75000,
         "expansion_arr": 0, "renewal_revenue": 0, "create_date": q_start_iso,
         "owner_email": "a@x.com", "segment": "SMB", "highest_stage_order_reached": 3},
        # Sanity control: pure renewal (no expansion) contributes $0 to
        # every source regardless of exclusion mechanism.
        {"deal_id": "pure_renewal", "pipeline_id": RENEWAL_ID, "deal_status": "won",
         "stage": "1297321623", "close_date": mid, "new_arr": 0, "expansion_arr": 0,
         "renewal_revenue": 300000, "create_date": q_start_iso, "owner_email": "a@x.com",
         "segment": "SMB", "highest_stage_order_reached": 4},
        # Roster-gap case 1: missing owner_email entirely. Must count in
        # query_rep_attainment's team total (closed_won_qtd) and in its
        # "no quota assigned" aggregate line — never silently dropped.
        {"deal_id": "missing_owner", "pipeline_id": "default", "deal_status": "won",
         "stage": "closedwon", "close_date": mid, "new_arr": 30000, "expansion_arr": 0,
         "renewal_revenue": 0, "create_date": q_start_iso, "owner_email": None,
         "segment": "SMB", "highest_stage_order_reached": 6},
        # Roster-gap case 2: a real owner_email with no rep_targets row, no
        # non_quota_roles entry, and no user_personas row (e.g. a rep hired
        # mid-quarter, quota not yet seeded). Same requirement as above.
        {"deal_id": "unmapped_owner", "pipeline_id": "default", "deal_status": "won",
         "stage": "closedwon", "close_date": mid, "new_arr": 20000, "expansion_arr": 0,
         "renewal_revenue": 0, "create_date": q_start_iso, "owner_email": "ghost@nowhere.example",
         "segment": "SMB", "highest_stage_order_reached": 6},
    ]
    rep_targets = [{"entity_email": "a@x.com", "period": label.replace(" ", "_"),
                    "level": "rep", "role": "ae", "metric": "quota", "target_value": 500000}]
    user_personas = [{"email": "a@x.com", "display_name": "A", "name": "A", "role": "ae"}]
    sb = StrictSupabase({"deals": deals, "rep_targets": rep_targets,
                        "user_personas": user_personas})
    return sb, q_start_iso, q_end_iso, label


def test_pure_renewal_agrees_across_all_sources():
    """Sanity control: a renewal deal with zero incremental ARR must
    contribute $0 under every source's exclusion mechanism."""
    print("\n[TEST] pure-renewal-only deal: $0 under every source")
    sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
    solo_sb = StrictSupabase({"deals": [d for d in sb.tables["deals"]
                                        if d["deal_id"] == "pure_renewal"],
                              "rep_targets": [], "user_personas": []})

    solo_total, _ = actual_incremental_closed_won(solo_sb, q_start_iso, q_end_iso)
    solo_lc = assess_loss_concentration(solo_sb, time_window={"start": q_start_iso,
                                                              "end": q_end_iso, "label": label})
    assert solo_total == 0.0
    assert solo_lc.get("won_incremental_arr") == 0.0
    print("  ✓ pure_renewal contributes $0 under every source's exclusion mechanism")


def test_three_sources_now_agree():
    """THE FIX'S PROOF. path_to_target (inline), assess_loss_concentration,
    and actual_incremental_closed_won must now all agree at $275,000 on
    this fixture — the renewal-with-expansion ($50K) and stage_lag ($75K)
    deals that used to be excluded by actual_incremental_closed_won's old
    filter are now counted, matching the other two, and the two
    roster-gap deals (missing_owner $30K, unmapped_owner $20K) are real
    incremental wins none of these three sources ever filtered by owner,
    so they were always included here."""
    print("\n[TEST] path_to_target / loss_concentration / actual_incremental_closed_won agree")
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

    assert ptt_total == lc_total == actual_total == 275000.0, (
        f"REGRESSION: expected all three to agree at $275,000 "
        f"(normal_win $100K + renewal_with_expansion $50K + stage_lag $75K + "
        f"missing_owner $30K + unmapped_owner $20K), got "
        f"path_to_target={ptt_total} loss_concentration={lc_total} "
        f"actual_incremental_closed_won={actual_total} — the 2026-10-03 filter "
        f"generalization may have regressed, or one of the three independent "
        f"implementations changed without the others. Re-run scripts/"
        f"audit_qtd_filter_change.py against real data before changing these "
        f"assertions.")
    assert actual_n == 5
    print(f"  ✓ all three agree: ${ptt_total:,.0f}")


def test_query_rep_attainment_matches_other_sources():
    """THE ATTAINMENT FIX'S PROOF (2026-10-03, attainment PR):
    query_rep_attainment.team_summary.closed_won_qtd must now equal the
    other three sources' $275,000 on this fixture — it previously used its
    own pipeline_id-based renewal exclusion (like the OLD, now-abandoned
    actual_incremental_closed_won) and silently dropped roster-gap wins
    from the team total. Now it sources closed_won_qtd directly from
    actual_incremental_closed_won(), and the two roster-gap deals
    (missing_owner, unmapped_owner) must both still count in the team
    total and be aggregated into a single 'no quota assigned' reps[] line,
    not dropped and not misattributed to the real rep (a@x.com)."""
    print("\n[TEST] query_rep_attainment: closed_won_qtd now matches the other three sources")
    sb, q_start_iso, q_end_iso, label = _build_fixture_sb()

    actual_total, _ = actual_incremental_closed_won(sb, q_start_iso, q_end_iso)

    with patch("api.handlers._resolve_owner_email", return_value=(None, None)):
        ra = asyncio.run(handlers.query_rep_attainment({}, sb))
    team_summary = ra.get("team_summary") or {}
    ra_total = team_summary.get("closed_won_qtd")

    assert ra_total == actual_total == 275000.0, (
        f"query_rep_attainment.team_summary.closed_won_qtd={ra_total}, expected "
        f"it to equal actual_incremental_closed_won's ${actual_total:,.0f} "
        f"(normal_win $100K + renewal_with_expansion $50K + stage_lag $75K + "
        f"missing_owner $30K + unmapped_owner $20K) — if these disagree again, "
        f"the attainment fix has regressed: query_rep_attainment must source "
        f"closed_won_qtd from actual_incremental_closed_won(), not a separate "
        f"pipeline_id-based re-sum. Re-run scripts/audit_qtd_filter_change.py "
        f"against real data before changing these assertions.")

    reps = ra.get("reps") or []
    unattributed_rows = [r for r in reps if r.get("unattributed")]
    assert len(unattributed_rows) == 1, (
        f"expected exactly one 'no quota assigned' aggregate row for the "
        f"missing_owner + unmapped_owner deals, got {len(unattributed_rows)}: "
        f"{unattributed_rows}")
    unattributed = unattributed_rows[0]
    assert unattributed.get("owner_email") is None
    assert unattributed.get("won_arr") == 50000.0, (
        f"expected the 'no quota assigned' line to total $50,000 "
        f"(missing_owner $30K + unmapped_owner $20K), got "
        f"{unattributed.get('won_arr')}")
    assert unattributed.get("deals_won") == 2
    assert unattributed.get("data_gap") is True

    a_rep = next((r for r in reps if r.get("owner_email") == "a@x.com"), None)
    assert a_rep is not None, "a@x.com (the only named rep) must still appear"
    assert a_rep.get("won_arr") == 225000.0, (
        f"a@x.com's own won_arr must stay at $225,000 (normal_win + "
        f"renewal_with_expansion + stage_lag) — missing_owner and "
        f"unmapped_owner must NEVER be misattributed to a named rep, got "
        f"{a_rep.get('won_arr')}")

    print(f"  query_rep_attainment: ${ra_total:,.0f}, matching the other three "
          f"sources (was $175,000 before this fix)")
    print(f"  'no quota assigned' line: ${unattributed.get('won_arr'):,.0f} "
          f"across {unattributed.get('deals_won')} deals (missing_owner + "
          f"unmapped_owner) — counted in the team total, never dropped")
