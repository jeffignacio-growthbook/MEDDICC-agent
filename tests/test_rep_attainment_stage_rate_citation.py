"""
Tests for the stage-rate citation fields added to
api/handlers.py::query_rep_attainment's cache_payload (2026-10-06).

Context (PR #129, commit 9baf508b, "Add per-rep weighted-pipeline on-track
tiers"): query_rep_attainment already computed, per rep, a weighted open-
pipeline total using forecast_analyses.query_stage_close_rate()'s team-
pooled, evidence-gated per-stage win rates — but only the final per-rep
SCALAR totals (weighted_pipeline, unweighted_pipeline,
unweighted_pipeline_deal_count) were kept; the per-stage breakdown that
built them was thrown away. A Slack follow-up like "what rates did you
use? or did you use forecast category weights?" (the 2026-10-06 incident
tested in tests/test_correction_detector_method_question.py) had no real
data to cite.

This file proves two new cache_payload fields, populated BEFORE the
`result["cache_payload"] = dict(result)` line so they're retained for
citation:

  - "stage_rates": team-level, scoped to just the stage_orders that
    actually appeared among THIS call's qualifying open deals (not
    query_stage_close_rate()'s entire historical by_stage_order) — each
    entry carries stage_name/win_rate/n_observed, read directly off the
    SAME by_stage_order row the per-rep weighting loop already used (never
    a second query, never reimplemented — reconciled below against a
    direct, UNMOCKED call to query_stage_close_rate() on the identical
    fixture, same discipline as PR #129's own reconciliation test against
    assess_pipeline_coverage()).
  - "pipeline_by_stage" (per rep, inside reps[]): per-stage deal_count +
    weighted_dollars for that rep's own qualifying open deals — aggregates
    only, no deal IDs, no deal-level rows.

Also tests:
  - json.dumps(cache_payload) doesn't raise and stays well under a sane
    size bound (aggregate counts/rates for ~9 reps x a handful of stages
    should be tiny — a few hundred KB at most; a larger payload would mean
    deal-level granularity leaked in).
  - The new EXPLAIN_PRIOR_ANSWER_PROMPT bullet (api/router.py) instructing
    the model to describe a cited stage_rates field as governed historical
    stage win rates, never forecast-category weights or a CRM stage-
    probability field — deterministic (template formatting only, no live
    LLM call).

Fixture conventions reused: StrictSupabase + real-handler convention from
tests/test_rep_attainment_pipeline_tiers.py (same SALES_PIPELINE/
RENEWAL_PIPELINE constants, same stage ids/orders — "qualifiedtobuy"=2,
"24682892"=4 per config/client.yaml).
"""
import json
import sys
import asyncio
import unittest
from pathlib import Path
from datetime import date, timedelta

REPO = Path(__file__).resolve().parents[1]
for p in ("", "tests", "scripts", "scripts/analytics", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

from strict_supabase import StrictSupabase  # noqa: E402
from utils import get_fiscal_quarter  # noqa: E402
import api.handlers as handlers  # noqa: E402

SALES_PIPELINE = "default"

# Historical (complete) quarter used ONLY for the deals_snapshot/win-rate
# computation — deliberately a different quarter than the "current" one
# below, same as production (historical rates weight the CURRENT quarter's
# open pipeline).
HIST_START, HIST_END, HIST_LABEL = get_fiscal_quarter(date(2025, 2, 15))


def _hist_week_date(w: int) -> str:
    return (HIST_START + timedelta(days=7 * (w - 1))).isoformat()


def _snapshot_row(deal_id, stage_order, week):
    return {
        "deal_id": deal_id, "stage_order": stage_order, "pipeline_id": SALES_PIPELINE,
        "fiscal_quarter": HIST_LABEL, "week_of_quarter": week,
        "snapshot_date": _hist_week_date(week),
    }


def _historical_deal(deal_id, outcome):
    """outcome: 'won' or 'lost'. close_date inside the historical quarter."""
    stage = "closedwon" if outcome == "won" else "closedlost"
    return {
        "deal_id": deal_id, "stage": stage, "pipeline_id": SALES_PIPELINE,
        "close_date": HIST_START.isoformat(), "deal_status": "closed_won" if outcome == "won" else "closed_lost",
    }


def _open_deal(deal_id, owner_email, stage, new_arr, close_date):
    return {
        "deal_id": deal_id, "pipeline_id": SALES_PIPELINE, "deal_status": "active",
        "stage": stage, "close_date": close_date, "new_arr": new_arr,
        "expansion_arr": 0, "owner_email": owner_email,
    }


def _target(email, period, role, quota):
    return {"entity_email": email, "period": period, "level": "rep",
            "role": role, "metric": "incremental_arr", "target_value": quota}


def _persona(email, name):
    return {"email": email, "display_name": name, "name": name}


def _build_fixture():
    """3 historical deals at stage_order 2 (2 won, 1 lost -> win_rate 2/3),
    3 at stage_order 4 (1 won, 2 lost -> win_rate 1/3), each observed across
    all 13 weeks of the historical quarter (39 deal-week observations per
    stage, clearing min_evidence_count=30). Plus two reps with open
    qualifying deals in the CURRENT quarter at those same two stages."""
    q_start, q_end, label = get_fiscal_quarter(date.today())
    period = label.replace(" ", "_")
    mid = (q_start + (q_end - q_start) / 2).isoformat()

    deals = []
    snapshots = []

    # Stage order 2 ("qualifiedtobuy" / Scoping): 2 won, 1 lost.
    stage2_outcomes = {"h2_win_a": "won", "h2_win_b": "won", "h2_lose_a": "lost"}
    # Stage order 4 ("24682892" / Negotiating): 1 won, 2 lost.
    stage4_outcomes = {"h4_win_a": "won", "h4_lose_a": "lost", "h4_lose_b": "lost"}

    for deal_id, outcome in stage2_outcomes.items():
        deals.append(_historical_deal(deal_id, outcome))
        for w in range(1, 14):
            snapshots.append(_snapshot_row(deal_id, 2, w))
    for deal_id, outcome in stage4_outcomes.items():
        deals.append(_historical_deal(deal_id, outcome))
        for w in range(1, 14):
            snapshots.append(_snapshot_row(deal_id, 4, w))

    # Current-quarter open pipeline: two reps, each with deals at both
    # qualifying stages.
    deals.append(_open_deal("r1_open_s2", "r1@x.com", "qualifiedtobuy", 40000, mid))
    deals.append(_open_deal("r1_open_s4", "r1@x.com", "24682892", 20000, mid))
    deals.append(_open_deal("r2_open_s2", "r2@x.com", "qualifiedtobuy", 30000, mid))

    rep_targets = [
        _target("r1@x.com", period, "ae", 100000),
        _target("r2@x.com", period, "ae", 100000),
    ]
    personas = [_persona("r1@x.com", "R1"), _persona("r2@x.com", "R2")]

    sb = StrictSupabase({
        "deals": deals,
        "deals_snapshot": snapshots,
        "rep_targets": rep_targets,
        "user_personas": personas,
    })
    tw = {"start": q_start.isoformat(), "end": q_end.isoformat(), "label": label}
    return sb, tw


class TestStageRatesReconciliation(unittest.TestCase):
    def test_stage_rates_matches_query_stage_close_rate_exactly(self):
        print("\n[TEST] cache_payload.stage_rates reconciles against a direct, "
              "unmocked query_stage_close_rate() call on the identical fixture")
        from forecast_analyses import query_stage_close_rate, clear_request_cache

        sb, tw = _build_fixture()

        clear_request_cache()
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        clear_request_cache()
        direct_rates = query_stage_close_rate(sb)
        by_stage_order = direct_rates["by_stage_order"]

        stage_rates = result["cache_payload"]["stage_rates"]
        self.assertIn("2", stage_rates)
        self.assertIn("4", stage_rates)

        for so_str, so_int in (("2", 2), ("4", 4)):
            direct_row = by_stage_order.get(so_int) or by_stage_order.get(so_str)
            self.assertIsNotNone(direct_row, f"direct query_stage_close_rate() has no "
                                 f"row for stage_order {so_int}: {by_stage_order}")
            cached_row = stage_rates[so_str]
            self.assertEqual(cached_row["win_rate"], direct_row["win_rate"],
                             f"stage_order {so_int} win_rate must be EXACTLY the same "
                             "object query_stage_close_rate() returned, not recomputed")
            self.assertEqual(cached_row["n_observed"], direct_row["n_observed"],
                             f"stage_order {so_int} n_observed must match exactly")

        self.assertAlmostEqual(stage_rates["2"]["win_rate"], 2 / 3, places=6)
        self.assertAlmostEqual(stage_rates["4"]["win_rate"], 1 / 3, places=6)
        self.assertEqual(stage_rates["2"]["n_observed"], 39)
        self.assertEqual(stage_rates["4"]["n_observed"], 39)

        # stage_name populated and not a raw numeric key.
        self.assertEqual(stage_rates["2"]["stage_name"], "Scoping")
        self.assertEqual(stage_rates["4"]["stage_name"], "Negotiating")
        for so_str in ("2", "4"):
            self.assertFalse(stage_rates[so_str]["stage_name"].isdigit(),
                             "stage_name must be a display name, never a raw numeric key")

        print(f"  ✓ stage_rates[2]={stage_rates['2']}, stage_rates[4]={stage_rates['4']} "
              "— exact match against the direct query_stage_close_rate() call")

    def test_stage_rates_scoped_to_stages_actually_used_not_entire_history(self):
        """stage_rates must NOT dump query_stage_close_rate()'s entire
        historical by_stage_order — only the stage_orders that appeared
        among THIS call's qualifying open deals (here: 2 and 4 only; this
        fixture has no open deal at any other qualifying stage_order)."""
        from forecast_analyses import clear_request_cache
        sb, tw = _build_fixture()
        clear_request_cache()
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))
        stage_rates = result["cache_payload"]["stage_rates"]
        self.assertEqual(set(stage_rates.keys()), {"2", "4"},
                         "stage_rates must be scoped to stages actually used "
                         "when weighting THIS call's open deals, not the full "
                         "historical by_stage_order")
        print("✓ stage_rates scoped to exactly the two stages this call's open deals used")

    def test_stage_rates_not_in_top_level_result_only_in_cache_payload(self):
        """Matches the HEURISTIC-curve pattern: present in cache_payload for
        citation, popped from the top-level result so it never reaches
        synthesis un-framed."""
        from forecast_analyses import clear_request_cache
        sb, tw = _build_fixture()
        clear_request_cache()
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))
        self.assertNotIn("stage_rates", result)
        self.assertIn("stage_rates", result["cache_payload"])
        print("✓ stage_rates absent from top-level result, present in cache_payload")


class TestPerRepPipelineByStage(unittest.TestCase):
    def test_pipeline_by_stage_deal_count_and_weighted_dollars(self):
        from forecast_analyses import clear_request_cache
        sb, tw = _build_fixture()
        clear_request_cache()
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        r1 = next(r for r in result["reps"] if r["owner_email"] == "r1@x.com")
        r2 = next(r for r in result["reps"] if r["owner_email"] == "r2@x.com")

        # r1: one deal at stage 2 ($40,000 * 2/3), one at stage 4 ($20,000 * 1/3).
        self.assertEqual(r1["pipeline_by_stage"]["2"]["deal_count"], 1)
        self.assertAlmostEqual(r1["pipeline_by_stage"]["2"]["weighted_dollars"],
                               40000 * (2 / 3), places=4)
        self.assertEqual(r1["pipeline_by_stage"]["4"]["deal_count"], 1)
        self.assertAlmostEqual(r1["pipeline_by_stage"]["4"]["weighted_dollars"],
                               20000 * (1 / 3), places=4)

        # r2: one deal at stage 2 only.
        self.assertEqual(r2["pipeline_by_stage"]["2"]["deal_count"], 1)
        self.assertAlmostEqual(r2["pipeline_by_stage"]["2"]["weighted_dollars"],
                               30000 * (2 / 3), places=4)
        self.assertNotIn("4", r2["pipeline_by_stage"])
        print("✓ pipeline_by_stage deal_count/weighted_dollars correct per rep per stage")

    def test_pipeline_by_stage_has_no_deal_ids(self):
        """Aggregates only — no deal IDs, no deal-level rows."""
        from forecast_analyses import clear_request_cache
        sb, tw = _build_fixture()
        clear_request_cache()
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))
        for r in result["reps"]:
            for stage_entry in r["pipeline_by_stage"].values():
                self.assertEqual(set(stage_entry.keys()), {"deal_count", "weighted_dollars"})
        print("✓ pipeline_by_stage entries carry only deal_count/weighted_dollars — no deal IDs")


class TestCachePayloadSerialization(unittest.TestCase):
    def test_json_dumps_does_not_raise_and_stays_small(self):
        """A few hundred KB is a generous bound: this payload is aggregate
        counts/rates for a handful of reps x a handful of stages, not
        deal-level data. A size this fixture produces far under 100KB;
        anything near the bound would be a sign deal-level granularity
        leaked in."""
        from forecast_analyses import clear_request_cache
        sb, tw = _build_fixture()
        clear_request_cache()
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        serialized = json.dumps(result["cache_payload"])
        size_kb = len(serialized) / 1024
        self.assertLess(size_kb, 200,
                        f"cache_payload serialized to {size_kb:.1f}KB — unexpectedly "
                        "large for aggregate-only data; check for leaked deal-level rows")
        print(f"✓ json.dumps(cache_payload) succeeded, size={size_kb:.2f}KB (bound: 200KB)")


class TestExplainPriorAnswerPromptBullet(unittest.TestCase):
    def test_stage_rates_bullet_present_and_correctly_worded(self):
        """Deterministic (no live LLM): format the template and check the
        new bullet's text is present, instructing the model to describe a
        cited stage_rates field as governed historical stage win rates,
        never forecast-category weights or a CRM stage-probability field."""
        import api.router as router
        formatted = router.EXPLAIN_PRIOR_ANSWER_PROMPT.format(
            prior_answer="Team weighted pipeline is $400,000.",
            question="What weighted rates did you use for each stage? or did "
                     "you use forecast category weights?",
            cached_fields_section="",
        )
        normalized = " ".join(formatted.split())
        self.assertIn("stage_rates", normalized)
        self.assertIn("governed historical stage win rates", normalized)
        self.assertIn("pooled across the team from closed deals in complete quarters",
                      normalized)
        self.assertIn("NOT forecast-category weights", normalized)
        self.assertIn("NOT a CRM deal-stage probability field", normalized)
        print("✓ EXPLAIN_PRIOR_ANSWER_PROMPT's new stage_rates bullet is present "
              "and correctly worded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
