"""
Collapse the win-loss-reason duplication into ONE shared helper (2026-09-26).

query_win_loss (#72) and generate_win_loss (#73) each grew their own copy of
"surface a populated lost_reason/stated_reason authoritatively" — retrieval +
an authoritative `_synthesis_note`. Two copies that must change together are a
standing bug risk. This collapses them into api/win_loss_reason.py:
  - stated_close_reason(deal, narrative) -> the authoritative reason string
  - reason_synthesis_note(reason="")     -> the ALWAYS-follow synthesis note

The step-4 audit found a THIRD entry point that can answer "why did we lose X"
for a named closed deal — query_deal ("deep dive on a specific company's
deal") — which previously omitted the reason entirely (never selected
lost_reason, never read narratives). It now routes through the same helper.

Single-instance is enforced here by source inspection: the authoritative note
text lives in exactly one module, and all three handlers call the shared
function rather than re-inlining it.

Paradigm's real pinned value (deal 58867845224, "Not a good fit (FF only)")
is reused as the fixture.
"""
import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.handlers as handlers_module
from api.win_loss_reason import stated_close_reason, reason_synthesis_note

REASON = "Not a good fit (FF only)"


def _run(coro):
    return asyncio.run(coro)


# ---- stated_close_reason -------------------------------------------------

def test_stated_reason_prefers_narrative_then_deal():
    assert stated_close_reason(
        deal={"lost_reason": "Budget"},
        narrative={"stated_reason": REASON}) == REASON, "narrative wins"
    assert stated_close_reason(
        deal={"lost_reason": REASON}, narrative={"stated_reason": None}) == REASON, \
        "falls back to deal.lost_reason when narrative stated_reason empty"
    assert stated_close_reason(deal={"lost_reason": REASON}) == REASON
    assert stated_close_reason(deal={"lost_reason": None}, narrative=None) == ""
    assert stated_close_reason() == ""
    # whitespace is stripped
    assert stated_close_reason(deal={"lost_reason": "  x  "}) == "x"


# ---- reason_synthesis_note ----------------------------------------------

def _assert_authoritative(note):
    low = note.lower()
    assert "primary" in low or "authoritative" in low or "trusted" in low, note
    assert "meddicc" in low, note
    assert ("override" in low or "contradict" in low or "hedge" in low), note
    if "we don't know" in low or "unclear" in low:
        assert "do not" in low or "never" in low, note


def test_note_names_reason_when_given():
    note = reason_synthesis_note(REASON)
    _assert_authoritative(note)
    assert REASON in note, "the note must name the specific reason when given one"


def test_note_generic_when_no_reason_mentions_the_fields():
    note = reason_synthesis_note()
    _assert_authoritative(note)
    low = note.lower()
    assert "lost_reason" in low or "stated_reason" in low or "stated reason" in low


# ---- single-instance enforcement ----------------------------------------

def test_note_text_lives_in_exactly_one_module():
    """The authoritative sentence must exist in api/win_loss_reason.py and NOT
    be re-inlined in api/handlers.py — that inlining is exactly the duplication
    being collapsed."""
    import api.win_loss_reason as wlr
    signature = "PRIMARY, TRUSTED, authoritative"
    handlers_src = inspect.getsource(handlers_module)
    wlr_src = inspect.getsource(wlr)
    assert wlr_src.count(signature) == 1, "note text must live in win_loss_reason.py"
    assert signature not in handlers_src, (
        "the authoritative note text is inlined in handlers.py again — it must "
        "come from reason_synthesis_note() so it changes in one place"
    )


def test_all_three_handlers_call_the_shared_helper():
    for name in ("query_win_loss", "generate_win_loss", "query_deal"):
        src = inspect.getsource(getattr(handlers_module, name))
        assert "reason_synthesis_note" in src, (
            f"{name} must build its authoritative note via the shared "
            f"reason_synthesis_note(), not its own inlined copy"
        )


# ---- query_deal: the third entry point ----------------------------------

def _fake_select_all(deals, analyses=None, objections=None, narratives=None):
    def fake(sb, table, columns=None, filters=None):
        data = {"deals": deals, "analyses": analyses or [],
                "objections": objections or [],
                "win_loss_narratives": narratives or []}.get(table, [])
        if not columns or columns == "*":
            return [dict(r) for r in data]
        cols = [c.strip() for c in columns.split(",")]
        return [{c: r.get(c) for c in cols} for r in data]
    return fake


def _call_query_deal(deals, analyses=None, company="Paradigm"):
    orig = handlers_module.select_all
    handlers_module.select_all = _fake_select_all(deals, analyses)
    try:
        return _run(handlers_module.query_deal({"company": company}, object()))
    finally:
        handlers_module.select_all = orig


PARADIGM_LOST = {
    "deal_id": "58867845224", "company_name": "Paradigm Technology",
    "deal_value": 75000.0, "stage": "Closed Lost", "deal_status": "lost",
    "close_date": "2026-08-21", "owner_email": "christian@growthbook.io",
    "highest_stage_order_reached": 5, "forecast_category": "CLOSED_LOST",
    "lost_reason": REASON,
}
OPEN_DEAL = dict(PARADIGM_LOST, deal_id="1", company_name="Openco",
                 deal_status="open", stage="Scoping", lost_reason=None)


def test_query_deal_closed_lost_surfaces_authoritative_reason():
    """A closed-lost deep dive must now surface the stated reason via the
    shared authoritative note — previously query_deal omitted it entirely."""
    result = _call_query_deal([PARADIGM_LOST])
    assert result["deal"].get("lost_reason") == REASON, (
        "query_deal must now select lost_reason for the deal"
    )
    note = result.get("_synthesis_note")
    assert note, "closed-lost deep dive must carry the authoritative reason note"
    _assert_authoritative(note)
    assert REASON in note


def test_query_deal_open_deal_no_reason_note():
    """An open deal has no close reason — no authoritative note is attached."""
    result = _call_query_deal([OPEN_DEAL], company="Openco")
    assert not result.get("_synthesis_note")


if __name__ == "__main__":
    test_stated_reason_prefers_narrative_then_deal()
    test_note_names_reason_when_given()
    test_note_generic_when_no_reason_mentions_the_fields()
    test_note_text_lives_in_exactly_one_module()
    test_all_three_handlers_call_the_shared_helper()
    test_query_deal_closed_lost_surfaces_authoritative_reason()
    test_query_deal_open_deal_no_reason_note()
    print("\n✅ All tests passed")
