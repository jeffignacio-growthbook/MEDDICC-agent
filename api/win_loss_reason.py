"""
Shared win/loss reason-authority logic — the single source of truth for
"surface a populated lost_reason/stated_reason authoritatively."

Background (PENDING_WORK "DATA BUG", fixed 2026-09-25): deals.lost_reason and
its verbatim copy win_loss_narratives.stated_reason are populated now (an ETL
fetch gap, since fixed and backfilled). A populated reason is the deal's OWN
stated close reason from HubSpot and is the authoritative answer to "why did
we win/lose this deal". The absence of a narrative, call transcripts, or
MEDDICC scores is a SEPARATE data-capture gap — context only, never grounds to
hedge, contradict, or override a real stated reason.

This module exists because that logic was independently reimplemented in
query_win_loss (#72) and generate_win_loss (#73) — two copies that had to
change together. It is now called by those two plus query_deal (the third
entry point that can answer "why did we lose <named deal>", found in the
2026-09-26 audit). Any change to how a stated reason is retrieved or how the
synthesis note reads happens HERE, once, and every entry point inherits it.

Both functions are pure and unit-tested (tests/test_win_loss_reason_shared.py).
"""


def stated_close_reason(deal: dict = None, narrative: dict = None) -> str:
    """The deal's authoritative stated close reason as a clean string ("" if
    none). Prefers the narrative's stated_reason (a verbatim copy of
    deals.lost_reason) and falls back to deals.lost_reason — so a pre-backfill
    narrative row with an empty stated_reason still resolves to the now-
    populated lost_reason.
    """
    reason = ((narrative or {}).get("stated_reason") or "").strip()
    if not reason:
        reason = ((deal or {}).get("lost_reason") or "").strip()
    return reason


def reason_synthesis_note(reason: str = "") -> str:
    """The authoritative `_synthesis_note` the router's synthesis prompt is
    told to ALWAYS follow. Pass the specific reason for a single deal so the
    note names it; pass "" for the bulk case (several losses, each with its
    own reason) to get the generic form.
    """
    lead = (
        f'The deal\'s stated close reason is "{reason}". '
        if reason else
        "A populated lost_reason (its verbatim copy stated_reason) is the "
        "deal's own stated close reason from HubSpot. "
    )
    return (
        lead +
        "Treat it as the PRIMARY, TRUSTED, authoritative answer to why that "
        "deal was won/lost — state it directly and plainly. Do NOT frame a "
        "deal that has a stated reason as 'we don't know' or 'unclear'. A "
        "missing AI narrative, call transcripts, or MEDDICC scores is a "
        "SEPARATE data-capture gap you may note as context, but it must NEVER "
        "be used to hedge, contradict, or override the stated reason. When "
        "several losses each carry a reason, give each deal its own reason."
    )
