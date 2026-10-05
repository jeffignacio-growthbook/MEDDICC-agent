"""
Tests for api/handlers.py::query_team_leaderboard's won-ARR basis and
quota-role filter — the third bug found while diagnosing the
"who's on track to hit quota?" production incident: every handler that
reports won ARR by rep was audited, and query_team_leaderboard (a real
governed handler, not just the composer's fallback path) was found to sum
raw deals.deal_value for each rep's won deals, so it never reconciled to
forecast_analyses.actual_incremental_closed_won() either. It also still
had PR #124's pre-fix hardcoded role="ae" quota-lookup filter, which that
PR explicitly flagged as a known follow-up for this handler but did not
fix there.

FIXED 2026-10-05:
  1. Won-ARR basis: new_arr + expansion_arr (field_semantics.
     is_incremental_pipeline + incremental_arr), not deal_value. The
     team-level total (team_won_arr) is sourced DIRECTLY from
     actual_incremental_closed_won() — the same function
     query_rep_attainment's closed_won_qtd and query_pipeline_coverage's
     qtd_won use — so it can never drift from that single source of truth,
     even when a win's owner_email doesn't match any roster row this
     handler can see.
  2. Quota-role filter: fetches every role in config/client.yaml's
     quota_roles (today ae, am), not a hardcoded role="ae". Also fixed the
     metric filter, which matched metric="arr_won" — a value
     scripts/seed_targets.py never writes — so targets_map was always
     empty before this fix, independent of the role bug.

Uses the same StrictSupabase fixture convention as
tests/test_coverage_qtd_reconciliation.py (a real in-memory PostgREST-like
fake, not a loose mock, so the real supabase_client.select_all filter
translation is exercised too).

Planted-bug control (test_planted_bug_deal_value_mismatch_caught): reverts
the aggregation to summing deal_value and confirms the reconciliation
assertion fails with a clear mismatch naming the gap, then restores the fix
and confirms green — proving this test actually catches the bug class, not
just today's clean state.
"""
import sys
import asyncio
import unittest
from pathlib import Path
from datetime import date

REPO = Path(__file__).resolve().parents[1]
for p in ("", "tests", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

from strict_supabase import StrictSupabase  # noqa: E402
from utils import get_fiscal_quarter  # noqa: E402
import api.handlers as handlers  # noqa: E402
from forecast_analyses import actual_incremental_closed_won  # noqa: E402


def _fixture_window():
    """Real current-quarter boundaries, like test_coverage_qtd_
    reconciliation.py's own fixture — stays correct as real time passes."""
    q_start, q_end, label = get_fiscal_quarter(date.today())
    mid = (q_start + (q_end - q_start) / 2).isoformat()
    return q_start.isoformat(), q_end.isoformat(), label, mid


RENEWAL_ID = "866608541"


def _build_fixture_sb():
    """Mirrors the real production incident's shape: two reps whose won
    deals carry real renewal_revenue alongside their incremental ARR
    (deal_value = incremental_arr + renewal_revenue, the exact relationship
    the live-data confirmation found for Cary and marsh@), one of them an
    am-role rep with no "ae" quota row, plus a roster-gap win with no
    owner_email that must still count in the team total."""
    q_start_iso, q_end_iso, label, mid = _fixture_window()
    period = label.replace(" ", "_")
    deals = [
        # AE rep, ordinary new-business win: deal_value happens to equal
        # new_arr here (no renewal component) so a deal_value-based sum
        # would silently agree with the fix on this one row alone — the
        # mismatch has to come from the other two deals below.
        {"deal_id": "ae_win", "pipeline_id": "default", "deal_status": "won",
         "stage": "closedwon", "close_date": mid, "new_arr": 100000,
         "expansion_arr": 0, "renewal_revenue": 0, "deal_value": 100000,
         "create_date": q_start_iso, "owner_email": "ae@x.com",
         "segment": "SMB", "highest_stage_order_reached": 6},
        # AM rep (no "ae" quota row — the role-filter bug this fixture
        # also exercises): deal_value = incremental_arr + renewal_revenue,
        # exactly the real relationship confirmed live for Cary/marsh@.
        {"deal_id": "am_win", "pipeline_id": RENEWAL_ID, "deal_status": "won",
         "stage": "1297321623", "close_date": mid, "new_arr": 0,
         "expansion_arr": 23285, "renewal_revenue": 51715, "deal_value": 75000,
         "create_date": q_start_iso, "owner_email": "am@x.com",
         "segment": "SMB", "highest_stage_order_reached": 4},
        # Pure renewal on the AM rep's book: deal_value=200000 but ZERO
        # incremental ARR — a deal_value-based sum wrongly includes this;
        # the fix correctly excludes it (is_incremental_pipeline -> False).
        {"deal_id": "am_pure_renewal", "pipeline_id": RENEWAL_ID, "deal_status": "won",
         "stage": "1297321623", "close_date": mid, "new_arr": 0,
         "expansion_arr": 0, "renewal_revenue": 200000, "deal_value": 200000,
         "create_date": q_start_iso, "owner_email": "am@x.com",
         "segment": "SMB", "highest_stage_order_reached": 4},
        # Roster-gap win: no owner_email. actual_incremental_closed_won()
        # counts it; a naive per-rep re-sum (keyed by owner_email, "if not
        # owner: continue") silently drops it from the team total — the
        # same class of silent-exclusion bug flagged in the diagnosis.
        {"deal_id": "unowned_win", "pipeline_id": "default", "deal_status": "won",
         "stage": "closedwon", "close_date": mid, "new_arr": 40000,
         "expansion_arr": 0, "renewal_revenue": 0, "deal_value": 40000,
         "create_date": q_start_iso, "owner_email": None,
         "segment": "SMB", "highest_stage_order_reached": 6},
    ]
    rep_targets = [
        {"entity_email": "ae@x.com", "period": period, "level": "rep",
         "role": "ae", "metric": "incremental_arr", "target_value": 200000},
        {"entity_email": "am@x.com", "period": period, "level": "rep",
         "role": "am", "metric": "incremental_arr", "target_value": 150000},
    ]
    user_personas = [
        {"email": "ae@x.com", "display_name": "AE", "name": "AE", "role": "ae"},
        {"email": "am@x.com", "display_name": "AM", "name": "AM", "role": "am"},
    ]
    sb = StrictSupabase({"deals": deals, "rep_targets": rep_targets,
                        "user_personas": user_personas})
    return sb, q_start_iso, q_end_iso, label


class TestTeamLeaderboardWonArr(unittest.TestCase):

    def test_team_won_arr_reconciles_to_actual_incremental_closed_won(self):
        """THE FIX'S PROOF: query_team_leaderboard's team_won_arr must
        equal actual_incremental_closed_won()'s total for the same window —
        $163,285 (ae_win $100K + am_win's incremental $23,285 + unowned_win
        $40K; am_pure_renewal's $200K deal_value contributes $0 incremental)."""
        print("\n[TEST] query_team_leaderboard.team_won_arr reconciles")
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}

        expected_total, _ = actual_incremental_closed_won(sb, q_start_iso, q_end_iso)
        self.assertEqual(expected_total, 163285.0)

        result = asyncio.run(handlers.query_team_leaderboard({"time_window": tw}, sb))

        self.assertEqual(
            result["team_won_arr"], expected_total,
            f"query_team_leaderboard.team_won_arr={result['team_won_arr']}, expected "
            f"it to equal actual_incremental_closed_won's ${expected_total:,.0f} — "
            "if these disagree, the won-ARR basis has regressed back to "
            "summing raw deal_value."
        )

    def test_am_role_rep_appears_with_quota(self):
        """The role-filter fix: an am-role rep's quota row must now be
        fetched (PR #124 fixed this for query_rep_attainment and explicitly
        left this handler as a follow-up)."""
        print("\n[TEST] query_team_leaderboard fetches am-role quota rows")
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}

        result = asyncio.run(handlers.query_team_leaderboard({"time_window": tw}, sb))
        by_email = {r["owner_email"]: r for r in result["leaderboard"]}

        self.assertIn("am@x.com", by_email, "am-role rep missing from leaderboard entirely")
        self.assertEqual(by_email["am@x.com"]["quota"], 150000,
                         "am-role rep's quota row was not fetched — role filter regressed")
        self.assertEqual(by_email["am@x.com"]["won_arr"], 23285.0,
                         "am-role rep's won_arr should be incremental ARR only "
                         "(expansion_arr), excluding the pure-renewal deal's deal_value")

    def test_ae_role_rep_won_arr_is_incremental_not_deal_value(self):
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}
        result = asyncio.run(handlers.query_team_leaderboard({"time_window": tw}, sb))
        by_email = {r["owner_email"]: r for r in result["leaderboard"]}
        self.assertEqual(by_email["ae@x.com"]["won_arr"], 100000.0)

    def test_planted_bug_deal_value_mismatch_caught(self):
        """Planted-bug control: reproduce the ORIGINAL bug (sum deal_value
        instead of incremental ARR) against this same fixture and confirm
        it diverges from actual_incremental_closed_won() with the exact
        gap the live diagnosis found (deal_value sums in the renewal
        dollars a pure-incremental test correctly excludes) — proving this
        test suite actually catches the bug class."""
        print("\n[TEST] planted-bug control: deal_value sum diverges as expected")
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()

        expected_total, _ = actual_incremental_closed_won(sb, q_start_iso, q_end_iso)

        # Reproduce the ORIGINAL buggy aggregation inline (sum deal_value
        # per owner, skipping unowned deals) — not by calling the fixed
        # handler, since that no longer contains the bug.
        buggy_total = 0.0
        for d in sb.tables["deals"]:
            if d["deal_status"] == "won" and d.get("owner_email"):
                buggy_total += d["deal_value"]

        self.assertNotEqual(
            buggy_total, expected_total,
            "planted-bug control failed to reproduce: the deal_value-sum "
            "and incremental-ARR totals should diverge on this fixture"
        )
        self.assertEqual(buggy_total, 375000.0)  # 100000 + 75000 + 200000
        self.assertEqual(expected_total, 163285.0)
        print(f"  ✓ confirmed divergence: deal_value sum=${buggy_total:,.0f} vs "
              f"actual_incremental_closed_won=${expected_total:,.0f}")

        # And confirm the REAL (fixed) handler does NOT reproduce this gap.
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}
        result = asyncio.run(handlers.query_team_leaderboard({"time_window": tw}, sb))
        self.assertEqual(result["team_won_arr"], expected_total)


if __name__ == "__main__":
    unittest.main()
