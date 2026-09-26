"""
generate_win_loss reason-authority fix (2026-09-26).

Sibling to tests/test_win_loss_reason_authority.py. `generate_win_loss`
(api/handlers.py) is a genuinely separate handler from `query_win_loss`
(own function, own router entry "full narrative for a specific closed deal",
own evaluator STRUCTURED_HANDLERS entry ["narrative"]) — NOT a routing alias.
"Why did we lose <named deal>" overlaps both handlers and the live ask routed
HERE, so this handler needs the same fix query_win_loss already got.

Before the fix:
  - Path A (a win_loss_narratives row exists — Paradigm's case): the handler
    returned {"narrative": row}. stated_reason was IN the payload but nothing
    directed the model to trust it, and there was no `_synthesis_note` (the
    field the router's synthesis prompt is told to ALWAYS follow).
  - Path B (no narrative row): the handler queried `deals` WITHOUT selecting
    lost_reason and returned a stale note "No narrative generated yet — runs
    Sunday after close." — a data-quality caveat that invites "we don't know"
    even when the deal carries a real stated close reason.

The fix surfaces the deal's stated close reason (stated_reason on the
narrative, or deals.lost_reason as fallback / on the no-narrative path) via an
authoritative `_synthesis_note`, and reframes the stale no-narrative note so a
populated reason is never drowned by the absence of a narrative.

Paradigm's real pinned values (captured read-only 2026-09-25 via Supabase MCP,
project htgvkqycrwesdysustxd): deal 58867845224, stated_reason / lost_reason
"Not a good fit (FF only)", and it HAS a narrative row (Path A).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.handlers as handlers_module

REASON = "Not a good fit (FF only)"

PARADIGM_NARRATIVE = {
    "company_name": "Paradigm Technology", "outcome": "lost",
    "stated_reason": REASON, "competitor_mentioned": None,
    "key_factors": None, "narrative": None, "generated_at": "2026-08-22",
}
PARADIGM_DEAL = {
    "deal_id": "58867845224", "company_name": "Paradigm Technology",
    "deal_status": "lost", "close_date": "2026-08-21", "lost_reason": REASON,
}
DEAL_NO_REASON = {
    "deal_id": "999", "company_name": "Blankco", "deal_status": "lost",
    "close_date": "2026-09-02", "lost_reason": None,
}


def _run(coro):
    return asyncio.run(coro)


def _project(rows, columns):
    """Mimic select_all's column projection: only the requested columns come
    back (unless '*'). This is what makes the 'handler forgot to select
    lost_reason' regression catchable — a fake that returns full rows
    regardless would hide it."""
    if not columns or columns == "*":
        return [dict(r) for r in rows]
    cols = [c.strip() for c in columns.split(",")]
    return [{c: r.get(c) for c in cols} for r in rows]


def _make_fake_select_all(narratives, deals, analyses=None):
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "win_loss_narratives":
            return _project(narratives, columns)
        if table == "deals":
            return _project(deals, columns)
        if table == "analyses":
            return _project(analyses or [], columns)
        return []
    return fake_select_all


def _call(narratives, deals, analyses=None, company="Paradigm"):
    orig = handlers_module.select_all
    handlers_module.select_all = _make_fake_select_all(narratives, deals, analyses)
    try:
        return _run(handlers_module.generate_win_loss({"company": company}, object()))
    finally:
        handlers_module.select_all = orig


def _assert_authoritative(note):
    assert note, "expected a non-empty `_synthesis_note`"
    low = note.lower()
    assert "primary" in low or "authoritative" in low or "trusted" in low, note
    assert "meddicc" in low, note
    assert ("override" in low or "contradict" in low or "hedge" in low), note
    # any 'we don't know'/'unclear' must be under a prohibition, not affirmative
    if "we don't know" in low or "unclear" in low:
        assert "do not" in low or "never" in low, note


def test_path_a_narrative_exists_emits_authoritative_note():
    """Paradigm's real case: a narrative row exists carrying the stated reason.
    The handler must still return the narrative AND now attach an authoritative
    `_synthesis_note` naming the reason as the primary trusted answer."""
    result = _call([PARADIGM_NARRATIVE], [PARADIGM_DEAL])
    assert "narrative" in result, "path A must still return the narrative row"
    assert result["narrative"]["stated_reason"] == REASON
    _assert_authoritative(result.get("_synthesis_note"))
    assert REASON in result["_synthesis_note"], (
        "the note should name the actual stated reason so synthesis anchors on it"
    )


def test_path_a_empty_stated_reason_falls_back_to_deal_lost_reason():
    """A pre-backfill narrative row with an empty stated_reason must fall back
    to the (now populated) deals.lost_reason rather than emitting nothing."""
    stale_narr = dict(PARADIGM_NARRATIVE, stated_reason=None)
    result = _call([stale_narr], [PARADIGM_DEAL])
    assert "narrative" in result
    _assert_authoritative(result.get("_synthesis_note"))
    assert REASON in result["_synthesis_note"]


def test_path_b_no_narrative_surfaces_deal_lost_reason():
    """No narrative row, but the deal carries a stated lost_reason: the handler
    must now select lost_reason, emit an authoritative `_synthesis_note`, and
    NOT return the bare stale 'No narrative generated yet' note as the whole
    story."""
    result = _call([], [PARADIGM_DEAL], analyses=[{"overall_score": 5}])
    _assert_authoritative(result.get("_synthesis_note"))
    assert REASON in result["_synthesis_note"]
    note = (result.get("note") or "").lower()
    # the note must be reframed (not the bare "No narrative generated yet")
    # so a real reason isn't drowned by the absence of a narrative — it frames
    # the missing narrative as a SEPARATE data-capture gap.
    assert "separate" in note, (
        f"the no-narrative note must be reframed so a real reason isn't "
        f"drowned by 'no narrative yet' — got: {result.get('note')!r}"
    )


def test_path_b_no_reason_keeps_honest_no_data_note_and_no_false_authority():
    """No narrative AND no lost_reason: nothing to trust, so NO authoritative
    note, and the honest 'no narrative yet' note stays."""
    result = _call([], [DEAL_NO_REASON], analyses=[], company="Blankco")
    assert not result.get("_synthesis_note"), (
        "no reason anywhere -> no authoritative-reason note"
    )
    assert result.get("note"), "should still explain no narrative exists yet"


if __name__ == "__main__":
    test_path_a_narrative_exists_emits_authoritative_note()
    test_path_a_empty_stated_reason_falls_back_to_deal_lost_reason()
    test_path_b_no_narrative_surfaces_deal_lost_reason()
    test_path_b_no_reason_keeps_honest_no_data_note_and_no_false_authority()
    print("\n✅ All tests passed")
