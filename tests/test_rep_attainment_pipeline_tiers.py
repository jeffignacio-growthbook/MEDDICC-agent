"""
Tests for the per-rep "on track to hit quota" tiers added to
api/handlers.py::query_rep_attainment (2026-10-06).

Before this change, query_rep_attainment computed won_arr/quota/stretch/
deals_won per rep but had NO per-rep weighted open pipeline figure at all
— the only weighted-pipeline figure anywhere in this codebase was the
TEAM-WIDE one in scripts/pipeline_coverage.py::assess_pipeline_coverage().
A prior read-only reconciliation (against live production data, now
discarded — no production numbers are reused here) proved that grouping
assess_pipeline_coverage()'s exact qualifying-deal population by
owner_email and summing incremental_arr(deal) * win_rate per owner
reproduces the team total to the penny, including an off-roster bucket.
This file proves that same claim against an invented fixture, and tests
the new per-rep fields built on top of it: weighted_pipeline, projected,
tier, on_track, quota_met, no_wins_yet, open_renewal_expansion.

Design notes baked into the fixture:
  - Two gated stage_orders (2 and 4) and one UNGATED stage_order (3,
    win_rate=None) — the ungated one is the planted-bug control for the
    rate-exclusion requirement: its deals must be excluded from
    weighted_pipeline/projected, tracked in unweighted_pipeline instead,
    and NEVER defaulted to a win_rate of 1.0 or 0.
  - AE and AM reps (r1-r5 ae, r6-r9 am) get the IDENTICAL weighted-
    pipeline computation — no special-casing, per config/targets.yaml's
    "both roles are measured on the SAME metric" comment.
  - A renewal-pipeline deal with real expansion ARR (r6) feeds
    open_renewal_expansion (unweighted, supplementary color), never
    weighted_pipeline/projected.
  - An off-roster open deal (ghost@nowhere.com) and an off-roster win
    (owner_email=None) prove roster-gap pipeline is folded into the same
    "No quota assigned" reps[] row the existing roster-gap WINS logic
    already uses, not a new/parallel mechanism.

Uses the same StrictSupabase + real-handler convention as
tests/test_rep_attainment_deals_won.py and tests/test_rep_attainment_
display_name_fallback.py — no mocking of query_rep_attainment itself.
query_stage_close_rate is patched exactly the way tests/
test_pipeline_coverage_stage_key.py patches it (same import point,
forecast_analyses.query_stage_close_rate), so the real
assess_pipeline_coverage() can be called against the identical fixture
for the reconciliation test's independent cross-check.
"""
import sys
import asyncio
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
for p in ("", "tests", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

from strict_supabase import StrictSupabase  # noqa: E402
from utils import get_fiscal_quarter  # noqa: E402
import api.handlers as handlers  # noqa: E402

SALES_PIPELINE = "default"
RENEWAL_PIPELINE = "866608541"

# Gated stage_order 2 (qualifiedtobuy / Scoping) at 25%, gated stage_order
# 4 ("24682892" / Negotiating) at 50%, stage_order 3
# (presentationscheduled / Technical Evaluation) UNGATED (win_rate=None,
# below min_evidence_count) — the planted-bug control stage.
RATES = {
    "by_stage_order": {
        "2": {"win_rate": 0.25, "n_observed": 40, "classified": 40, "won": 10,
              "lost": 30, "slipped": 0, "unclassified": 0},
        "3": {"win_rate": None, "n_observed": 3, "classified": 3, "won": 1,
              "lost": 2, "slipped": 0, "unclassified": 0,
              "reason": "3 classified < min_evidence 30"},
        "4": {"win_rate": 0.50, "n_observed": 50, "classified": 50, "won": 25,
              "lost": 25, "slipped": 0, "unclassified": 0},
    },
    "quarters_analyzed": 4, "complete_quarters": [], "min_evidence_count": 30,
    "scope": "New+Expansion only (renewal pipeline excluded)", "note": "test fixture",
}


def _fixture_window():
    q_start, q_end, label = get_fiscal_quarter(date.today())
    mid = (q_start + (q_end - q_start) / 2).isoformat()
    return q_start.isoformat(), q_end.isoformat(), label, mid


def _won(deal_id, owner_email, new_arr, mid, q_start_iso):
    return {
        "deal_id": deal_id, "pipeline_id": SALES_PIPELINE, "deal_status": "won",
        "stage": "closedwon", "close_date": mid, "new_arr": new_arr,
        "expansion_arr": 0, "renewal_revenue": 0, "deal_value": new_arr,
        "create_date": q_start_iso, "owner_email": owner_email, "segment": "SMB",
    }


def _open(deal_id, owner_email, stage, new_arr, mid, pipeline_id=SALES_PIPELINE,
          expansion_arr=0):
    return {
        "deal_id": deal_id, "pipeline_id": pipeline_id, "deal_status": "active",
        "stage": stage, "close_date": mid, "new_arr": new_arr,
        "expansion_arr": expansion_arr, "owner_email": owner_email,
    }


def _target(email, period, role, quota):
    return {"entity_email": email, "period": period, "level": "rep",
            "role": role, "metric": "incremental_arr", "target_value": quota}


def _persona(email, name):
    return {"email": email, "display_name": name, "name": name}


# ---------------------------------------------------------------------------
# Fixture 1: tier-boundary / quota_met / no_wins_yet / renewal-expansion cases
# ---------------------------------------------------------------------------
def _build_boundary_fixture():
    q_start_iso, q_end_iso, label, mid = _fixture_window()
    period = label.replace(" ", "_")

    deals = []
    # rep2: won short of quota, pipeline pushes it to on_track (quota_met
    # False, tier on_track — proves the two fields are independent).
    deals.append(_won("r2_win", "r2@x.com", 90000, mid, q_start_iso))
    deals.append(_open("r2_open", "r2@x.com", "24682892", 50000, mid))  # *0.50 = 25000 -> projected 115000

    # rep3: won == quota exactly, zero pipeline. Boundary: ratio == 1.00
    # exactly -> on_track. quota_met True too (same ratio drives both here,
    # but computed from separate fields).
    deals.append(_won("r3_win", "r3@x.com", 100000, mid, q_start_iso))

    # rep5: won 75000 of 100000 quota, zero pipeline -> ratio == 0.75
    # exactly -> within_reach boundary.
    deals.append(_won("r5_win", "r5@x.com", 75000, mid, q_start_iso))

    # rep6: won 74000 of 100000 quota -> ratio 0.74, just below the 0.75
    # boundary -> behind.
    deals.append(_won("r6_win", "r6@x.com", 74000, mid, q_start_iso))

    # rep4: no wins at all (no_wins_yet True), pipeline alone gives ratio
    # 0.6 -> behind. Confirms no_wins_yet doesn't change the tier math.
    deals.append(_open("r4_open", "r4@x.com", "qualifiedtobuy", 240000, mid))  # *0.25=60000/100000

    # rep10: no wins at all (no_wins_yet True) but pipeline alone reaches
    # exactly quota -> on_track. Confirms no_wins_yet never DOWNGRADES a
    # tier a rep's pipeline earned.
    deals.append(_open("r10_open", "r10@x.com", "24682892", 60000, mid))  # *0.50=30000==quota

    # rep8 (AM): won 10000 of 50000 quota, a renewal-pipeline deal with
    # real expansion ARR (open_renewal_expansion), no Sales-pipeline open
    # deal. Confirms AM gets the identical weighted_pipeline computation
    # (just happens to be 0 here) and open_renewal_expansion is tracked
    # separately, unweighted.
    deals.append(_won("r8_win", "r8@x.com", 10000, mid, q_start_iso))
    deals.append(_open("r8_renewal", "r8@x.com", "decisionmakerboughtin", 0, mid,
                        pipeline_id=RENEWAL_PIPELINE, expansion_arr=30000))

    # rep1: zero renewal-pipeline deals -> open_renewal_expansion must be
    # exactly 0, not missing/None.
    deals.append(_won("r1_win", "r1@x.com", 20000, mid, q_start_iso))

    rep_targets = [
        _target("r1@x.com", period, "ae", 100000),
        _target("r2@x.com", period, "ae", 100000),
        _target("r3@x.com", period, "ae", 100000),
        _target("r4@x.com", period, "ae", 100000),
        _target("r5@x.com", period, "ae", 100000),
        _target("r6@x.com", period, "ae", 100000),
        _target("r8@x.com", period, "am", 50000),
        _target("r10@x.com", period, "ae", 30000),
    ]
    personas = [_persona(e, e.split("@")[0]) for e in
                ("r1@x.com", "r2@x.com", "r3@x.com", "r4@x.com", "r5@x.com",
                 "r6@x.com", "r8@x.com", "r10@x.com")]

    sb = StrictSupabase({"deals": deals, "rep_targets": rep_targets,
                        "user_personas": personas})
    return sb, {"start": q_start_iso, "end": q_end_iso, "label": label}


def _run_boundary(sb, tw):
    with patch("forecast_analyses.query_stage_close_rate") as sr:
        sr.return_value = RATES
        return asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))


def _rep(result, email):
    for r in result["reps"]:
        if r["owner_email"] == email:
            return r
    raise AssertionError(f"{email} not found in reps[]: {result['reps']}")


class TestTierBoundaries(unittest.TestCase):
    def test_on_track_boundary_exactly_1_00(self):
        """projected/quota == 1.00 exactly -> on_track (ratio >= on_track_ratio)."""
        sb, tw = _build_boundary_fixture()
        r = _rep(_run_boundary(sb, tw), "r3@x.com")
        self.assertEqual(r["projected"], 100000)
        self.assertEqual(r["tier"], "on_track")
        self.assertTrue(r["on_track"])
        print("✓ projected/quota == 1.00 exactly classifies as on_track")

    def test_within_reach_boundary_exactly_0_75(self):
        """projected/quota == 0.75 exactly -> within_reach (>= within_reach_ratio,
        < on_track_ratio)."""
        sb, tw = _build_boundary_fixture()
        r = _rep(_run_boundary(sb, tw), "r5@x.com")
        self.assertEqual(r["projected"], 75000)
        self.assertEqual(r["tier"], "within_reach")
        self.assertFalse(r["on_track"])
        print("✓ projected/quota == 0.75 exactly classifies as within_reach")

    def test_just_below_within_reach_boundary_is_behind(self):
        """projected/quota == 0.74 -> behind."""
        sb, tw = _build_boundary_fixture()
        r = _rep(_run_boundary(sb, tw), "r6@x.com")
        self.assertEqual(r["projected"], 74000)
        self.assertEqual(r["tier"], "behind")
        self.assertFalse(r["on_track"])
        print("✓ projected/quota == 0.74 (just below 0.75) classifies as behind")

    def test_pipeline_only_can_reach_behind_or_on_track(self):
        sb, tw = _build_boundary_fixture()
        result = _run_boundary(sb, tw)
        r4 = _rep(result, "r4@x.com")
        self.assertEqual(r4["won_arr"], 0)
        self.assertEqual(r4["weighted_pipeline"], 60000)
        self.assertEqual(r4["projected"], 60000)
        self.assertEqual(r4["tier"], "behind")
        r10 = _rep(result, "r10@x.com")
        self.assertEqual(r10["weighted_pipeline"], 30000)
        self.assertEqual(r10["projected"], 30000)
        self.assertEqual(r10["tier"], "on_track")
        print("✓ pipeline-only projection correctly classifies both behind and on_track")


class TestQuotaMetIndependentOfTier(unittest.TestCase):
    def test_quota_met_false_while_tier_is_on_track(self):
        """rep2 has NOT yet won quota (90000 < 100000) but pipeline pushes
        tier to on_track — quota_met and tier/on_track are distinct signals,
        never conflated."""
        sb, tw = _build_boundary_fixture()
        r = _rep(_run_boundary(sb, tw), "r2@x.com")
        self.assertEqual(r["won_arr"], 90000)
        self.assertEqual(r["weighted_pipeline"], 25000)
        self.assertEqual(r["projected"], 115000)
        self.assertEqual(r["tier"], "on_track")
        self.assertTrue(r["on_track"])
        self.assertFalse(r["quota_met"], "quota_met must be won_arr>=quota, not tied to tier")
        print("✓ quota_met=False and tier=on_track coexist correctly (independent signals)")

    def test_quota_met_true_when_won_arr_at_or_above_quota(self):
        sb, tw = _build_boundary_fixture()
        r = _rep(_run_boundary(sb, tw), "r3@x.com")
        self.assertTrue(r["quota_met"])
        print("✓ quota_met=True when won_arr >= quota")

    def test_quota_met_none_for_data_gap_rep(self):
        """A rep with no quota this period must get quota_met=None (and
        tier=None), never a fabricated value."""
        sb, tw = _build_boundary_fixture()
        q_start_iso, q_end_iso, label, mid = _fixture_window()
        period = label.replace(" ", "_")
        sb.tables["deals"].append(_won("r9_win", "r9@x.com", 5000, mid, q_start_iso))
        sb.tables["user_personas"].append(_persona("r9@x.com", "Rep Nine"))
        r = _rep(_run_boundary(sb, tw), "r9@x.com")
        self.assertIsNone(r["quota"])
        self.assertIsNone(r["quota_met"])
        self.assertIsNone(r["tier"])
        self.assertIsNone(r["on_track"])
        self.assertTrue(r["data_gap"])
        print("✓ data-gap rep (no quota this period) gets quota_met/tier/on_track=None, never fabricated")


class TestNoWinsYet(unittest.TestCase):
    def test_no_wins_yet_true_only_when_won_arr_zero(self):
        sb, tw = _build_boundary_fixture()
        result = _run_boundary(sb, tw)
        self.assertTrue(_rep(result, "r4@x.com")["no_wins_yet"])
        self.assertTrue(_rep(result, "r10@x.com")["no_wins_yet"])
        self.assertFalse(_rep(result, "r2@x.com")["no_wins_yet"])
        self.assertFalse(_rep(result, "r3@x.com")["no_wins_yet"])
        print("✓ no_wins_yet is True iff won_arr == 0")

    def test_no_wins_yet_never_downgrades_tier(self):
        """rep10 has no_wins_yet=True but its pipeline alone reaches
        on_track — the flag must not collapse it to behind, and must not
        be reported as if it were its own tier value."""
        sb, tw = _build_boundary_fixture()
        r10 = _rep(_run_boundary(sb, tw), "r10@x.com")
        self.assertTrue(r10["no_wins_yet"])
        self.assertEqual(r10["tier"], "on_track")
        self.assertTrue(r10["on_track"])
        self.assertIn(r10["tier"], ("on_track", "within_reach", "behind"),
                      "tier must only ever be one of the three real tier values")
        print("✓ no_wins_yet=True coexists with tier=on_track — flag never downgrades the tier")


class TestOpenRenewalExpansion(unittest.TestCase):
    def test_renewal_expansion_counted_and_unweighted(self):
        sb, tw = _build_boundary_fixture()
        r8 = _rep(_run_boundary(sb, tw), "r8@x.com")
        self.assertEqual(r8["open_renewal_expansion"], 30000)
        # Not folded into weighted_pipeline/projected (no Sales-pipeline
        # open deal exists for r8 in this fixture, so both are 0).
        self.assertEqual(r8["weighted_pipeline"], 0.0)
        self.assertEqual(r8["projected"], r8["won_arr"])
        print("✓ open_renewal_expansion counted ($30,000) and excluded from weighted_pipeline/projected")

    def test_zero_for_rep_with_no_renewal_deals(self):
        sb, tw = _build_boundary_fixture()
        r1 = _rep(_run_boundary(sb, tw), "r1@x.com")
        self.assertEqual(r1["open_renewal_expansion"], 0.0)
        print("✓ open_renewal_expansion is exactly 0 for a rep with no renewal-pipeline deals")


# ---------------------------------------------------------------------------
# Fixture 2: nine reps + off-roster owners, for the reconciliation test and
# the rate-exclusion planted-bug control.
# ---------------------------------------------------------------------------
def _build_reconciliation_fixture():
    q_start_iso, q_end_iso, label, mid = _fixture_window()
    period = label.replace(" ", "_")

    reps = [
        # (email, role, quota, won_arr, open_stage_or_None, open_value)
        ("a1@x.com", "ae", 80000, 10000, "qualifiedtobuy", 40000),      # *0.25=10000
        ("a2@x.com", "ae", 80000, 10000, "24682892", 60000),            # *0.50=30000
        ("a3@x.com", "ae", 80000, 10000, "qualifiedtobuy", 20000),      # *0.25=5000
        ("a4@x.com", "ae", 80000, 10000, "24682892", 10000),            # *0.50=5000
        ("a5@x.com", "ae", 80000, 10000, "presentationscheduled", 70000),  # UNGATED -> unweighted
        ("a6@x.com", "am", 50000, 5000, "qualifiedtobuy", 16000),       # *0.25=4000
        ("a7@x.com", "am", 50000, 5000, "24682892", 20000),             # *0.50=10000
        ("a8@x.com", "am", 50000, 5000, "qualifiedtobuy", 8000),        # *0.25=2000
        ("a9@x.com", "am", 50000, 5000, None, 0),                      # no open deal
    ]
    expected_weighted_by_email = {
        "a1@x.com": 10000, "a2@x.com": 30000, "a3@x.com": 5000,
        "a4@x.com": 5000, "a5@x.com": 0, "a6@x.com": 4000,
        "a7@x.com": 10000, "a8@x.com": 2000, "a9@x.com": 0,
    }

    deals = []
    rep_targets = []
    personas = []
    for email, role, quota, won, stage, val in reps:
        deals.append(_won(f"{email}_win", email, won, mid, q_start_iso))
        if stage:
            deals.append(_open(f"{email}_open", email, stage, val, mid))
        rep_targets.append(_target(email, period, role, quota))
        personas.append(_persona(email, email.split("@")[0]))

    # a6 also carries a renewal-pipeline expansion deal — supplementary
    # color only, must not affect the reconciliation.
    deals.append(_open("a6_renewal", "a6@x.com", "decisionmakerboughtin", 0, mid,
                        pipeline_id=RENEWAL_PIPELINE, expansion_arr=20000))

    # Off-roster: an open qualifying deal from an owner not on the roster
    # at all, plus an off-roster win (owner_email=None) — both must be
    # folded into the single "No quota assigned" reps[] row, never
    # dropped, never misattributed to a named rep.
    deals.append(_open("ghost_open", "ghost@nowhere.com", "24682892", 30000, mid))  # *0.50=15000
    deals.append(_won("unowned_win", None, 5000, mid, q_start_iso))

    sb = StrictSupabase({"deals": deals, "rep_targets": rep_targets,
                        "user_personas": personas})
    tw = {"start": q_start_iso, "end": q_end_iso, "label": label}
    return sb, tw, expected_weighted_by_email


class TestReconciliation(unittest.TestCase):
    def test_nine_reps_plus_off_roster_equals_team_weighted_figure(self):
        sb, tw, expected_by_email = _build_reconciliation_fixture()
        with patch("forecast_analyses.query_stage_close_rate") as sr:
            sr.return_value = RATES
            result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        named_reps = [r for r in result["reps"] if not r.get("unattributed")]
        self.assertEqual(len(named_reps), 9, f"expected nine reps, got {len(named_reps)}: {result['reps']}")

        for r in named_reps:
            self.assertAlmostEqual(
                r["weighted_pipeline"], expected_by_email[r["owner_email"]], places=6,
                msg=f"{r['owner_email']} weighted_pipeline mismatch: {r}")

        off_roster_row = next(r for r in result["reps"] if r.get("unattributed"))
        self.assertAlmostEqual(off_roster_row["weighted_pipeline"], 15000, places=6)

        reps_sum = sum(r["weighted_pipeline"] for r in result["reps"])
        self.assertAlmostEqual(
            result["team_summary"]["weighted_pipeline"], reps_sum, places=6,
            msg="team_summary.weighted_pipeline must equal sum(reps[].weighted_pipeline) "
                "(named reps + off-roster row) to the cent")
        self.assertAlmostEqual(result["team_summary"]["weighted_pipeline"], 81000.0, places=6)

        # Independent cross-check: assess_pipeline_coverage() governs the
        # TEAM-WIDE weighted-pipeline figure. Calling it directly against
        # the identical fixture/rates proves the per-rep breakdown is
        # provably a partition of the SAME qualifying population, not a
        # parallel reimplementation that happens to agree today.
        from pipeline_coverage import assess_pipeline_coverage
        with patch("utils.get_fiscal_quarter") as gfq, \
             patch("snapshot_deals.get_week_of_quarter") as gw, \
             patch("time_resolver.current_quarter_label") as cql, \
             patch("forecast_analyses.query_stage_close_rate") as sr2, \
             patch("forecast_analyses.query_coverage_proxy_target_by_week") as curve:
            from datetime import date as _date
            q_start = _date.fromisoformat(tw["start"])
            q_end = _date.fromisoformat(tw["end"])
            gfq.return_value = (q_start, q_end, tw["label"])
            gw.return_value = 1
            cql.return_value = tw["label"].replace(" ", "_")
            sr2.return_value = RATES
            curve.return_value = {"by_week": {}}
            coverage = assess_pipeline_coverage(sb, as_of=q_start)

        self.assertAlmostEqual(
            coverage["stage_weighting"]["weighted_value"],
            result["team_summary"]["weighted_pipeline"], places=6,
            msg="query_rep_attainment's team_summary.weighted_pipeline must equal "
                "assess_pipeline_coverage()'s own weighted_value for the identical "
                "qualifying population — a partition, not a parallel computation")
        print(f"✓ nine reps (${reps_sum - 15000:,.0f}) + off-roster ($15,000) == team_summary.weighted_pipeline "
              f"(${result['team_summary']['weighted_pipeline']:,.0f}), reconciled against "
              f"assess_pipeline_coverage()'s own ${coverage['stage_weighting']['weighted_value']:,.0f} "
              "to the cent")


class TestRateExclusionPlantedBugControl(unittest.TestCase):
    """a5's open deal sits in an UNGATED stage (win_rate=None, below
    min_evidence_count). The correct behavior: excluded from
    weighted_pipeline/projected, tracked in unweighted_pipeline/
    unweighted_pipeline_deal_count. Planted-bug control: a rate-defaulting
    implementation (None -> 1.0, the exact anti-pattern the spec forbids)
    would instead weight it at the full $70,000 — this test proves the
    real result is NOT that value, i.e. it would catch the regression."""

    def test_ungated_stage_deal_excluded_from_weighted_not_defaulted(self):
        sb, tw, _ = _build_reconciliation_fixture()
        with patch("forecast_analyses.query_stage_close_rate") as sr:
            sr.return_value = RATES
            result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))
        a5 = _rep(result, "a5@x.com")

        BUGGY_DEFAULT_TO_1 = 70000 * 1.0  # what a "missing rate -> 1.0" bug would produce
        BUGGY_DEFAULT_TO_0_WIN_RATE_ZERO = 70000 * 0.0  # a "missing rate -> 0" bug (silently correct-looking here)

        self.assertEqual(a5["weighted_pipeline"], 0.0)
        self.assertNotEqual(a5["weighted_pipeline"], BUGGY_DEFAULT_TO_1,
                            "a missing stage win_rate must never be defaulted to 1.0")
        self.assertEqual(a5["unweighted_pipeline"], 70000)
        self.assertEqual(a5["unweighted_pipeline_deal_count"], 1)
        self.assertEqual(a5["projected"], a5["won_arr"],
                         "unweighted_pipeline must be excluded from projected")

        team = result["team_summary"]
        self.assertEqual(team["unweighted_pipeline"], 70000)
        self.assertEqual(team["unweighted_pipeline_deal_count"], 1)
        # And the team weighted figure must NOT silently include it either.
        self.assertNotIn(70000, [team["weighted_pipeline"]])
        print("✓ ungated-stage deal ($70,000) surfaced via unweighted_pipeline, "
              "never defaulted into weighted_pipeline at rate 1.0 or 0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
