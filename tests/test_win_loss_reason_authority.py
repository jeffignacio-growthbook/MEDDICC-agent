"""
query_win_loss reason-authority fix (2026-09-25).

Background: deals.lost_reason / win_loss_narratives.stated_reason are now
populated (the ETL fetch-gap fix + fleet backfill — see PENDING_WORK's
"DATA BUG" entry, now ✅ FIXED). Before this fix, query_win_loss handed the
model the reason as an ordinary field with NO instruction that it is the
authoritative answer to "why did we lose this deal". The model would then
hedge a real, stated close reason against the (separate) absence of call
transcripts or MEDDICC scores and answer with "we don't really know why we
lost" framing — a self-contradiction: the deal literally carries its own
stated reason.

The fix adds a `_synthesis_note` (the field the router's synthesis prompt is
told to ALWAYS follow — see api/router.py's "HANDLER SYNTHESIS NOTES" /
"OPERATOR METADATA" blocks) that directs the model to treat a populated
lost_reason/stated_reason as the PRIMARY, TRUSTED answer, and to treat
missing calls/MEDDICC as context only — never as grounds to override or
contradict a real stated reason. It also scopes the stale `data_quality_note`
(which used to claim "Lost reasons are blank for most deals") to the specific
deals that actually lack a reason, and only when any do.

The live Paradigm re-ask (step 5 of the task) is the end-to-end confirmation;
this file is the offline proof that the handler now DIRECTS the reason
authoritatively. Paradigm's real production values are pinned here (captured
read-only 2026-09-25 via Supabase MCP, project htgvkqycrwesdysustxd):
deal 58867845224, lost_reason "Not a good fit (FF only)".
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.handlers as handlers_module


def _run(coro):
    return asyncio.run(coro)


# Paradigm's real production row (deals), pinned read-only 2026-09-25.
PARADIGM_LOSS = {
    "deal_id": "58867845224", "company_name": "Paradigm Technology",
    "deal_value": 75000.0, "deal_status": "lost", "close_date": "2026-08-21",
    "lost_reason": "Not a good fit (FF only)",
    "owner_email": "christian@growthbook.io", "segment": "Mid-Market",
}
# Its real narrative row (win_loss_narratives): stated_reason is the verbatim
# copy of deals.lost_reason.
PARADIGM_NARRATIVE = {
    "company_name": "Paradigm Technology", "outcome": "lost",
    "stated_reason": "Not a good fit (FF only)", "competitor_mentioned": None,
    "key_factors": None, "narrative": None, "generated_at": "2026-08-22",
}
LOSS_NO_REASON = {
    "deal_id": "999", "company_name": "Blankco", "deal_value": 40000.0,
    "deal_status": "lost", "close_date": "2026-09-02", "lost_reason": None,
    "owner_email": "rep@growthbook.io", "segment": "SMB",
}


def _make_fake_select_all(deals, narratives=None, analyses=None):
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "deals":
            return deals
        if table == "win_loss_narratives":
            return narratives or []
        if table == "analyses":
            return analyses or []
        return []
    return fake_select_all


def _call(deals, narratives=None, analyses=None, params=None):
    orig = handlers_module.select_all
    handlers_module.select_all = _make_fake_select_all(deals, narratives, analyses)
    try:
        return _run(handlers_module.query_win_loss(params or {}, object()))
    finally:
        handlers_module.select_all = orig


def test_populated_reason_emits_authoritative_synthesis_note():
    """A loss with a populated lost_reason must carry a `_synthesis_note`
    (the field synthesis is told to ALWAYS follow) directing the model to
    treat the stated reason as the primary, trusted answer."""
    result = _call([PARADIGM_LOSS], narratives=[PARADIGM_NARRATIVE])

    note = result.get("_synthesis_note")
    assert note, (
        "query_win_loss must return a non-empty `_synthesis_note` when a "
        "closed-lost deal carries a populated lost_reason — that is the "
        "hook the synthesis prompt is told to ALWAYS follow. Without it the "
        "model has no instruction to trust the stated reason and hedges it."
    )
    low = note.lower()
    assert "lost_reason" in low or "stated reason" in low or "stated_reason" in low
    assert "primary" in low or "authoritative" in low or "trusted" in low, (
        f"the note must direct the reason as the primary/trusted answer — got: {note!r}"
    )
    # It must explicitly forbid using missing calls/MEDDICC to override the reason.
    assert "meddicc" in low, note
    assert ("override" in low or "contradict" in low or "hedge" in low), (
        f"the note must forbid overriding/contradicting/hedging the stated "
        f"reason on the basis of missing data — got: {note!r}"
    )


def test_paradigm_reason_is_present_and_not_framed_as_unknown():
    """Paradigm specifically: the loss row carries its exact stated reason,
    and NOTHING the handler returns invites a 'we don't know' answer."""
    result = _call([PARADIGM_LOSS], narratives=[PARADIGM_NARRATIVE])

    losses = result["losses"]
    assert len(losses) == 1
    assert losses[0]["lost_reason"] == "Not a good fit (FF only)"
    assert result["narratives"][0]["stated_reason"] == "Not a good fit (FF only)"

    # The stale "blank for most deals" data_quality_note must NOT fire when
    # the (only) loss has a reason — that wording is what produced the
    # self-contradiction.
    dq = result.get("data_quality_note")
    assert not dq, (
        f"data_quality_note must be empty when every loss has a reason — "
        f"got: {dq!r}"
    )
    # And the authoritative note must PROHIBIT (not merely lack) the
    # "we don't know" framing — where that phrasing appears, it must be under
    # an explicit prohibition, never as an affirmative hedge.
    note = (result.get("_synthesis_note") or "").lower()
    if "we don't know" in note or "unclear" in note:
        assert "do not" in note or "never" in note, (
            f"any 'we don't know'/'unclear' wording in the note must be a "
            f"prohibition, not an affirmative hedge — got: {note!r}"
        )


def test_data_quality_note_is_scoped_to_deals_actually_missing_a_reason():
    """Mixed case: one loss with a reason, one without. The note must be
    scoped to the count actually missing a reason (not 'most deals'), and the
    authoritative synthesis note must still fire for the one that has one."""
    result = _call([PARADIGM_LOSS, LOSS_NO_REASON],
                   narratives=[PARADIGM_NARRATIVE])

    dq = result.get("data_quality_note") or ""
    assert dq, "with a loss missing its reason, a scoped data_quality_note should fire"
    assert "most" not in dq.lower(), (
        f"the note must not claim 'most' deals are blank — it must be scoped "
        f"to the actual count (1 of 2 here) — got: {dq!r}"
    )
    assert "1 of 2" in dq, f"note should state the real count (1 of 2) — got: {dq!r}"
    assert result.get("_synthesis_note"), (
        "the authoritative note must still fire while ANY loss has a reason"
    )


def test_all_losses_missing_reason_still_scopes_note_and_no_false_authority():
    """When no loss has a reason, the authoritative note must NOT fire (there
    is nothing to trust), and the data_quality_note must be scoped, not the
    stale 'most deals' wording."""
    result = _call([LOSS_NO_REASON])

    assert not result.get("_synthesis_note"), (
        "no populated reason -> no authoritative-reason note"
    )
    dq = result.get("data_quality_note") or ""
    assert dq and "most" not in dq.lower()
    assert "1 of 1" in dq, f"note should state the real count — got: {dq!r}"


def test_loss_concentration_docstring_has_no_false_data_ceiling_claim():
    """The query_loss_concentration docstring must no longer assert the false
    '0% lost_reason fleet-wide' / 'hard data ceiling' claim about
    query_win_loss — lost_reason is populated now."""
    import inspect
    src = inspect.getsource(handlers_module.query_loss_concentration)
    low = src.lower()
    assert "0% lost_reason" not in low, "stale '0% lost_reason' claim still present"
    assert "hard data ceiling" not in low, "stale 'hard data ceiling' claim still present"


def test_router_description_has_no_false_reasoning_ceiling_claim():
    """The router's query_loss_concentration description must no longer call
    query_win_loss's reasoning a 'hard data-quality gap' — that ceiling was
    an ETL fetch bug, now fixed."""
    import api.router as router
    desc = router.HANDLER_DESCRIPTIONS["query_loss_concentration"].lower() \
        if hasattr(router, "HANDLER_DESCRIPTIONS") else ""
    if not desc:
        # fall back to scanning the module source for the phrase
        full = open(router.__file__).read().lower()
        assert "reasoning ceiling is a hard data-quality gap" not in full, (
            "stale 'reasoning ceiling is a hard data-quality gap' phrase "
            "still present in router.py"
        )
    else:
        assert "hard data-quality gap" not in desc


if __name__ == "__main__":
    test_populated_reason_emits_authoritative_synthesis_note()
    test_paradigm_reason_is_present_and_not_framed_as_unknown()
    test_data_quality_note_is_scoped_to_deals_actually_missing_a_reason()
    test_all_losses_missing_reason_still_scopes_note_and_no_false_authority()
    test_loss_concentration_docstring_has_no_false_data_ceiling_claim()
    test_router_description_has_no_false_reasoning_ceiling_claim()
    print("\n✅ All tests passed")
