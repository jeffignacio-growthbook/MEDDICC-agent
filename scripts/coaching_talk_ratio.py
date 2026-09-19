#!/usr/bin/env python3
"""
Criterion C (rep-coaching primitive) — talk-time / question-share
diagnostic for a single call.

DIAGNOSTIC ONLY, no pass/fail threshold. Ship decision, 2026-09-19: the
first calibration attempt (owner-name matched against a call's own
participant_emails roster) never cleared the 90% reliability bar on the
full 1,383-call population (76.7% by speaker count, 81.5% by
speech-seconds — see PENDING_WORK.md). This module replaces that
approach entirely for Apollo-sourced calls with an EXACT PARTICIPANT-ID
MATCH (no name-matching anywhere) — confirmed live via a three-run
investigation that Apollo's conversation-detail `participants` field
ties a diarized speaker to a real email/account by the same id already
used as call_transcripts' speaker key. That mechanism's OWN reliability
has not yet been re-calibrated into a won/lost threshold, so this
returns plain numbers only — never a judgment.

SOURCE-DEPENDENT BY DESIGN, not a gap to close uniformly: Fireflies has
NO equivalent anywhere in its API (confirmed live — querying `email` on
its Sentence type is rejected by the schema, and its own top-level
speakers{id,name} roster carries a meaningless ordinal id with no
email). A Fireflies-sourced call MUST return insufficient_data/
source_not_supported here, explicitly, every time — never silently
omitted, and never a name-matched approximation reintroduced through
the back door.
"""
from typing import Any, Dict


def assess_call_talk_ratio(call_transcript_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Diagnostic-only Criterion C signal for ONE call_transcripts row.

    Args:
        call_transcript_row: a row (dict) from call_transcripts — must
            carry source, talk_time_seconds, question_count,
            total_speech_seconds, participant_identities (Apollo only,
            migration 065).

    Returns (gated by source and data availability, never fabricated):
        {"status": "insufficient_data", "reason": str, "note": str}
      or:
        {"status": "ok",
         "internal_talk_ratio": float,           # internal speech / total speech
         "internal_question_share": float|None,  # internal Qs / total Qs
         "matched_seconds": float,       # speech attributable to a known,
                                          # non-bot identity
         "total_speech_seconds": float,
         "unmatched_seconds": float,     # speech from an unmatched speaker
                                          # OR a bot artifact — never folded
                                          # into either side of the ratio
         "note": str}                    # permanent diagnostic-only label
    """
    source = (call_transcript_row.get("source") or "").lower()
    if source != "apollo":
        return {
            "status": "insufficient_data",
            "reason": "source_not_supported",
            "note": (
                f"Criterion C requires per-speaker identity data this "
                f"codebase can only capture from Apollo (exact participant-id "
                f"match, confirmed live 2026-09-19). '{source or 'unknown'}' "
                f"has no equivalent anywhere in its API — this is a "
                f"permanent, source-level limitation, not a missing backfill."
            ),
        }

    identities = call_transcript_row.get("participant_identities") or {}
    talk = call_transcript_row.get("talk_time_seconds") or {}
    questions = call_transcript_row.get("question_count") or {}
    total_speech = call_transcript_row.get("total_speech_seconds") or 0.0

    if not identities:
        return {
            "status": "insufficient_data",
            "reason": "no_participant_identities",
            "note": ("This Apollo call has no participant_identities recorded "
                     "(migration 065) — cannot attribute talk time to a "
                     "known identity for this specific call."),
        }
    if not talk or not total_speech:
        return {
            "status": "insufficient_data",
            "reason": "no_speech_data",
            "note": "No talk_time_seconds/total_speech_seconds on this row.",
        }

    internal_seconds = 0.0
    internal_questions = 0
    matched_seconds = 0.0
    total_questions = sum(questions.values())

    for key, seconds in talk.items():
        ident = identities.get(key)
        if not ident or ident.get("is_bot"):
            continue  # unmatched speaker or a bot artifact — never scored
        matched_seconds += seconds
        if ident.get("is_internal"):
            internal_seconds += seconds
            internal_questions += questions.get(key, 0)

    if matched_seconds <= 0:
        return {
            "status": "insufficient_data",
            "reason": "no_matched_speakers",
            "note": ("No speaker on this call matched a participant_identities "
                     "entry (or all matches were bot artifacts) — the "
                     "exact-id bridge found nothing to attribute."),
        }

    return {
        "status": "ok",
        "internal_talk_ratio": round(internal_seconds / total_speech, 4),
        "internal_question_share": (
            round(internal_questions / total_questions, 4)
            if total_questions else None),
        "matched_seconds": round(matched_seconds, 1),
        "total_speech_seconds": round(total_speech, 1),
        "unmatched_seconds": round(total_speech - matched_seconds, 1),
        "note": (
            "DIAGNOSTIC ONLY — plain numbers, no pass/fail judgment. The "
            "won/lost calibration for this exact-ID mechanism has not been "
            "run; never treat any value here as 'good' or 'bad' until that "
            "calibration exists and clears the reliability bar."
        ),
    }
