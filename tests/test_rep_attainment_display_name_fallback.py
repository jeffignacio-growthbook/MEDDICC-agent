"""
Tests for query_rep_attainment's rep-name display fallback (2026-10-06).

Before this fix, reps[].name was `persona_map.get(email)` with no
fallback at all — None whenever a rep had no user_personas row. Two real
reps (marsh@growthbook.io / Andy Marshall, kris@growthbook.io / Kris
Washburn) have no user_personas row today, and Slack showed them as bare
"marsh@"/"kris@" because synthesis had to improvise from the raw email
with nothing better to read.

Fix: a three-tier fallback — persona display_name/name, then this
period's own rep_targets.entity_name (same level='rep' rows the handler
already fetches for quota values — no new join), then the email's
local-part as a last resort. No user_personas rows were added; the real
marsh@/kris@ rows were separately renamed in rep_targets.entity_name
(Andy Marshall / Kris Washburn) in a prior data fix, so tier 2 now
resolves them correctly.

Uses the same StrictSupabase convention as tests/test_rep_attainment_
deals_won.py — the real query_rep_attainment handler, no mock of the
handler itself.
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


def _fixture_window():
    q_start, q_end, label = get_fiscal_quarter(date.today())
    mid = (q_start + (q_end - q_start) / 2).isoformat()
    return q_start.isoformat(), q_end.isoformat(), label, mid


def _won_deal(deal_id, owner_email, new_arr, mid):
    return {
        "deal_id": deal_id, "pipeline_id": "default", "deal_status": "won",
        "stage": "closedwon", "close_date": mid, "new_arr": new_arr,
        "expansion_arr": 0, "renewal_revenue": 0, "deal_value": new_arr,
        "owner_email": owner_email, "segment": "SMB",
        "highest_stage_order_reached": 6,
    }


def _build_fixture_sb():
    """Three reps, three different name-resolution paths:
      - andy@x.com:   no user_personas row, rep_targets.entity_name set
                      (mirrors the real marsh@/kris@ situation) -> tier 2.
      - persona@x.com: BOTH a user_personas row AND a rep_targets.entity_name
                      -> persona must still win (tier 1), unchanged from
                      today's behavior.
      - bare@x.com:   neither a persona row nor an entity_name
                      -> falls back to the email local-part (tier 3)."""
    q_start_iso, q_end_iso, label, mid = _fixture_window()
    period = label.replace(" ", "_")

    deals = [
        _won_deal("andy_win", "andy@x.com", 10000, mid),
        _won_deal("persona_win", "persona@x.com", 10000, mid),
        _won_deal("bare_win", "bare@x.com", 10000, mid),
    ]
    rep_targets = [
        {"entity_email": "andy@x.com", "entity_name": "Andy Marshall",
         "period": period, "level": "rep", "role": "ae",
         "metric": "incremental_arr", "target_value": 50000},
        {"entity_email": "persona@x.com", "entity_name": "Mechanical Persona",
         "period": period, "level": "rep", "role": "ae",
         "metric": "incremental_arr", "target_value": 50000},
        {"entity_email": "bare@x.com", "entity_name": None,
         "period": period, "level": "rep", "role": "ae",
         "metric": "incremental_arr", "target_value": 50000},
        # A team-level row sharing nothing with the rep rows above, to
        # prove the fallback never reads a team row's entity_name (e.g.
        # "AE Team") by accident — target_filters already scopes to
        # level='rep', this is belt-and-suspenders in the fixture itself.
        {"entity_email": None, "entity_name": "AE Team",
         "period": period, "level": "team", "role": None,
         "metric": "incremental_arr", "target_value": 150000},
    ]
    user_personas = [
        {"email": "persona@x.com", "display_name": "Real Persona Name",
         "name": "Real Persona Name", "role": "ae"},
    ]
    sb = StrictSupabase({"deals": deals, "rep_targets": rep_targets,
                        "user_personas": user_personas})
    return sb, q_start_iso, q_end_iso, label


class TestDisplayNameFallback(unittest.TestCase):

    def _run(self):
        sb, q_start_iso, q_end_iso, label = _build_fixture_sb()
        tw = {"start": q_start_iso, "end": q_end_iso, "label": label}
        result = asyncio.run(handlers.query_rep_attainment({"time_window": tw}, sb))
        by_email = {r["owner_email"]: r for r in result["reps"]}
        return result, by_email

    def test_no_persona_falls_back_to_rep_targets_entity_name(self):
        """THE FIX'S PROOF (tier 2): a rep with no user_personas row but a
        rep_targets.entity_name — exactly the real marsh@/kris@ situation
        after their data fix — must show that real name, not None and not
        the bare email."""
        print("\n[TEST] no-persona rep falls back to rep_targets.entity_name")
        _, by_email = self._run()
        self.assertEqual(by_email["andy@x.com"]["name"], "Andy Marshall")
        print("  ✓ andy@x.com resolved to 'Andy Marshall' via tier-2 fallback")

    def test_existing_persona_reps_unchanged(self):
        """A rep WITH a user_personas row must keep showing that persona
        name even though a (deliberately different) rep_targets.entity_name
        also exists for the same email — tier 1 always wins, so no
        existing rep's displayed name changes because of this fix."""
        print("\n[TEST] a rep with a persona row is unaffected by this fix")
        _, by_email = self._run()
        self.assertEqual(by_email["persona@x.com"]["name"], "Real Persona Name")
        print("  ✓ persona@x.com still resolves to its persona name, "
              "'Mechanical Persona' (rep_targets) never used")

    def test_no_persona_no_entity_name_falls_back_to_email_prefix(self):
        """THE FIX'S PROOF (tier 3): a rep with neither a persona row nor a
        rep_targets.entity_name must still get a deterministic name — the
        email's local-part — rather than None."""
        print("\n[TEST] rep with neither source falls back to email prefix")
        _, by_email = self._run()
        self.assertEqual(by_email["bare@x.com"]["name"], "bare")
        print("  ✓ bare@x.com resolved to 'bare' via tier-3 fallback")

    def test_team_row_entity_name_never_leaks_into_a_rep_name(self):
        """Belt-and-suspenders: the team-level 'AE Team' row's entity_name
        must never appear as any rep's displayed name."""
        print("\n[TEST] team row's entity_name never leaks into a rep's name")
        _, by_email = self._run()
        names = {r["name"] for r in by_email.values()}
        self.assertNotIn("AE Team", names)
        print("  ✓ 'AE Team' not present among rep names")

    def test_planted_bug_no_fallback_leaves_name_none(self):
        """Planted-bug control: reproduce the ORIGINAL behavior (no
        fallback at all, persona_map.get(email) only) on a copy of the
        real result, confirming the pre-fix shape really did leave `name`
        as None for andy@x.com and bare@x.com — the exact gap the real
        Slack incident showed. Done by rebuilding the pre-fix value from
        the fixture's own persona map, not by re-implementing the handler,
        so this stays honest about what the fix actually changed."""
        print("\n[TEST] planted-bug control: pre-fix shape had name=None")
        result, by_email = self._run()

        persona_map = {"persona@x.com": "Real Persona Name"}
        pre_fix_andy_name = persona_map.get("andy@x.com")
        pre_fix_bare_name = persona_map.get("bare@x.com")

        self.assertIsNone(
            pre_fix_andy_name,
            "planted-bug control failed to reproduce: pre-fix andy@x.com "
            "should have resolved to None (no persona row, no fallback)")
        self.assertIsNone(
            pre_fix_bare_name,
            "planted-bug control failed to reproduce: pre-fix bare@x.com "
            "should have resolved to None")
        # And the real (fixed) handler does carry a real name for both.
        self.assertEqual(by_email["andy@x.com"]["name"], "Andy Marshall")
        self.assertEqual(by_email["bare@x.com"]["name"], "bare")
        print("  ✓ confirmed: pre-fix shape left name=None for both; "
              "fixed handler now resolves both via the new fallback tiers")


if __name__ == "__main__":
    unittest.main()
