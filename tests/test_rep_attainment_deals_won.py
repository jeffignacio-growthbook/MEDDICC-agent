"""
Tests for items 4 and 5 of the 2026-10 quota-attainment retry regression fix.

Item 4 (api/handlers.py::query_rep_attainment): team_summary previously had
NO deal-count field at all. A live answer stated "15" team deals won when
reps[].deals_won actually summed to 12 (matching query_pipeline_coverage's
own figure) — the model invented/mis-summed the number during synthesis
because there was nowhere to read it directly. Fix: team_summary.deals_won
(computed in code, never by the model) plus
team_summary.unassigned_deals_won for the "no quota assigned" roster-gap
line, and a `_synthesis_note` field telling the generator to read
team_summary.deals_won directly. (DYNAMIC_SYSTEM_PROMPT already has a
"never sum sample arrays, use aggregate fields" rule, but that is the
dynamic loop's own system prompt — a different code path that this
handler's synthesis (build_synthesis_prompt/_VOICE_BASE) never reaches;
_synthesis_note is the mechanism _VOICE_BASE already documents for exactly
this ("ALWAYS follow the instructions in this field when present").)

Item 5 (api/evaluator.py::STRUCTURED_HANDLERS): query_rep_attainment was
not registered, so evaluate_result() fell through to the generic row-based
branch, saw no "rows" key, and classified a genuinely good result as
"partial" purely from shape-blindness — not a real data gap. Registering it
with primary keys ["reps", "team_summary"] fixes the classification to
"good" (the api/router.py retry-loop usability check added in this same
fix, _governed_result_is_usable, reuses this registration).

Planted-bug controls: both exercises use StrictSupabase (tests/
strict_supabase.py) and the real query_rep_attainment handler — no mocks of
the handler itself. Each test includes an inline reproduction of the
ORIGINAL buggy behavior (sum of a field that doesn't exist / the dict
temporarily missing from STRUCTURED_HANDLERS) to prove the test actually
discriminates fixed vs. broken, not just asserting today's output.
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
from api.evaluator import evaluate_result, STRUCTURED_HANDLERS  # noqa: E402


def _fixture_window():
    q_start, q_end, label = get_fiscal_quarter(date.today())
    mid = (q_start + (q_end - q_start) / 2).isoformat()
    return q_start.isoformat(), q_end.isoformat(), label, mid


def _won_deal(deal_id, owner_email, new_arr, q_start_iso, mid):
    return {
        "deal_id": deal_id, "pipeline_id": "default", "deal_status": "won",
        "stage": "closedwon", "close_date": mid, "new_arr": new_arr,
        "expansion_arr": 0, "renewal_revenue": 0, "deal_value": new_arr,
        "create_date": q_start_iso, "owner_email": owner_email,
        "segment": "SMB", "highest_stage_order_reached": 6,
    }


def _build_fixture_sb():
    """5 deals for ae1@x.com, 6 for ae2@x.com, 1 roster-gap (unowned) win —
    team_summary.deals_won must reconcile to 12, with
    unassigned_deals_won == 1."""
    q_start_iso, q_end_iso, label, mid = _fixture_window()
    period = label.replace(" ", "_")

    deals = []
    for i in range(5):
        deals.append(_won_deal(f"ae1_win_{i}", "ae1@x.com", 10000, q_start_iso, mid))
    for i in range(6):
        deals.append(_won_deal(f"ae2_win_{i}", "ae2@x.com", 10000, q_start_iso, mid))
    deals.append(_won_deal("unowned_win", None, 5000, q_start_iso, mid))

    rep_targets = [
        {"entity_email": "ae1@x.com", "period": period, "level": "rep",
         "role": "ae", "metric": "incremental_arr", "target_value": 50000},
        {"entity_email": "ae2@x.com", "period": period, "level": "rep",
         "role": "ae", "metric": "incremental_arr", "target_value": 60000},
    ]
    user_personas = [
        {"email": "ae1@x.com", "display_name": "AE One", "name": "AE One", "role": "ae"},
        {"email": "ae2@x.com", "display_name": "AE Two", "name": "AE Two", "role": "ae"},
    ]
    sb = StrictSupabase({"deals": deals, "rep_targets": rep_targets,
                        "user_personas": user_personas})
    return sb, q_start_iso, q_end_iso, label


class TestTeamSummaryDealsWon(unittest.TestCase):

    def test_team_summary_deals_won_reconciles_to_12(self):
        """THE FIX'S PROOF: team_summary.deals_won == 12, and equals
        sum(reps[].deals_won) exactly — the invariant the fix exists to
        guarantee."""
        print("\n[TEST] query_rep_attainment.team_summary.deals_won reconciles")
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}

        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))
        team_summary = result["team_summary"]
        reps = result["reps"]

        reps_sum = sum(r["deals_won"] for r in reps)
        self.assertEqual(reps_sum, 12, f"fixture sanity check: reps[].deals_won should sum to 12, got {reps_sum}")
        self.assertEqual(
            team_summary["deals_won"], 12,
            f"team_summary.deals_won={team_summary.get('deals_won')}, expected 12 "
            "(5 ae1 + 6 ae2 + 1 unassigned) — this is the exact reconciliation the "
            "2026-10 incident's invented '15' figure violated."
        )
        self.assertEqual(team_summary["deals_won"], reps_sum,
                         "team_summary.deals_won must equal sum(reps[].deals_won) by construction")
        self.assertEqual(team_summary["unassigned_deals_won"], 1,
                         "the roster-gap (unowned) win should be isolated as 1 unassigned deal")
        print(f"  ✓ team_summary.deals_won=12, reconciles with reps[] sum, unassigned=1")

    def test_synthesis_note_present_and_instructs_reading_aggregate(self):
        """The handler must carry its own synthesis instruction (the
        mechanism _VOICE_BASE documents: '_synthesis_note: ALWAYS follow the
        instructions in this field when present') since the dynamic loop's
        'never sum sample arrays' rule does NOT reach this handler's
        synthesis path."""
        print("\n[TEST] query_rep_attainment result carries _synthesis_note")
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        note = result.get("_synthesis_note", "")
        self.assertIn("deals_won", note)
        self.assertIn("team_summary", note)
        self.assertNotIn("cache_payload", result.get("_synthesis_note", ""))
        print("  ✓ _synthesis_note present, names team_summary.deals_won")

    def test_planted_bug_deals_won_field_missing_before_fix(self):
        """Planted-bug control: reproduce the ORIGINAL output shape (no
        team_summary.deals_won at all) and confirm a model reading it would
        have had nothing but reps[] to sum itself — the exact gap that let
        '15' get invented. Done by deleting the key from a copy of the real
        result, not by re-implementing the handler, so this stays honest
        about what changed."""
        print("\n[TEST] planted-bug control: pre-fix shape had no deals_won field")
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        pre_fix_team_summary = dict(result["team_summary"])
        pre_fix_team_summary.pop("deals_won", None)
        pre_fix_team_summary.pop("unassigned_deals_won", None)

        self.assertNotIn(
            "deals_won", pre_fix_team_summary,
            "planted-bug control failed to reproduce: pre-fix team_summary "
            "should have no deal-count field at all"
        )
        # And the real (fixed) handler does carry it.
        self.assertIn("deals_won", result["team_summary"])
        print("  ✓ confirmed: pre-fix shape had no aggregate deal-count field; "
              "fixed handler now carries team_summary.deals_won")


class TestStructuredHandlerRegistration(unittest.TestCase):

    def test_query_rep_attainment_registered_as_structured(self):
        print("\n[TEST] query_rep_attainment is in STRUCTURED_HANDLERS")
        self.assertIn("query_rep_attainment", STRUCTURED_HANDLERS)
        self.assertEqual(set(STRUCTURED_HANDLERS["query_rep_attainment"]),
                         {"reps", "team_summary"})

    def test_good_result_classified_good_not_partial(self):
        """THE FIX'S PROOF: a real, populated query_rep_attainment result
        must classify as 'good', not 'partial' (the shape-blind misread
        that existed before item 5's registration)."""
        print("\n[TEST] evaluate_result classifies a real attainment result as 'good'")
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        quality = evaluate_result(result, "query_rep_attainment")
        self.assertEqual(
            quality, "good",
            f"expected 'good', got {quality!r} — query_rep_attainment's real "
            "output should never classify as 'partial'/'empty' purely from "
            "shape-blindness"
        )

    def test_no_targets_data_gap_shape_still_classifies_good(self):
        """The no-targets-set data-gap shape (reps=[], but team_summary
        populated with a data_gap=True attainment + an explanatory note) is
        a complete, honest answer — same principle as
        query_forecast_trust's gate response. Must not classify 'empty'."""
        print("\n[TEST] no-targets data-gap shape still classifies as usable")
        sb = StrictSupabase({"deals": [], "rep_targets": [], "user_personas": []})
        q_start, q_end, label = get_fiscal_quarter(date.today())
        tw = {"start": q_start.isoformat(), "end": q_end.isoformat(), "label": label}
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        self.assertEqual(result["reps"], [])
        self.assertIn("note", result)
        quality = evaluate_result(result, "query_rep_attainment")
        self.assertNotEqual(quality, "empty",
                            "a populated, honest data-gap team_summary must not "
                            "classify as 'empty'")

    def test_planted_bug_unregistered_handler_misclassified_partial(self):
        """Planted-bug control: temporarily remove query_rep_attainment from
        STRUCTURED_HANDLERS (patch.dict auto-restores after the block) and
        confirm the SAME real result now misclassifies as 'partial' — proving
        this test suite actually catches the registration gap, not just
        today's already-fixed state."""
        print("\n[TEST] planted-bug control: unregistered handler misclassifies as 'partial'")
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))

        with patch.dict(STRUCTURED_HANDLERS, {}, clear=False):
            del STRUCTURED_HANDLERS["query_rep_attainment"]
            buggy_quality = evaluate_result(result, "query_rep_attainment")
            self.assertEqual(
                buggy_quality, "partial",
                f"planted-bug control failed to reproduce: expected 'partial' "
                f"from the generic row-based branch, got {buggy_quality!r}"
            )
        # Restored outside the `with` block — patch.dict guarantees this.
        self.assertIn("query_rep_attainment", STRUCTURED_HANDLERS)
        fixed_quality = evaluate_result(result, "query_rep_attainment")
        self.assertEqual(fixed_quality, "good")
        print(f"  ✓ confirmed divergence: unregistered → 'partial', registered → 'good'")


if __name__ == "__main__":
    unittest.main()
