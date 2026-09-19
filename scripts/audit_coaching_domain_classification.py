#!/usr/bin/env python3
"""
Audit-only script: verify whether participant_domains/is_internal (the E.3
Fireflies/Apollo call-resolution work) actually provides a PER-SPEAKER
internal/external classification usable for Criterion C's redesign, before
wiring it into anything. Do not assume it's reliable just because it exists.

THE STRUCTURAL QUESTION THIS CHECKS: call_transcripts.talk_time_seconds/
question_count are keyed by a per-utterance speaker_key (Fireflies: display
name string: Apollo: participant_id). calls.participant_domains/
participant_emails/is_internal are CALL-LEVEL aggregates computed once by
resolve_calls.py / apollo_participants.py for DEAL-RESOLUTION purposes —
confirmed by reading that code, there is no call_participants join table
and no per-speaker email/domain field stored anywhere. So the real
question is not "is is_internal accurate" (it may well be, for its own
original purpose) but "can it be joined to a specific speaker_key at all,
without reintroducing name-matching."

READ-ONLY. No writes. No primitive is designed or built here.
"""
import sys
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from db import get_supabase
from supabase_client import select_all


def _looks_like_email_localpart_name(key: str) -> bool:
    """Fireflies speaker keys are free-text display names; Apollo speaker
    keys are participant_id hashes. Neither carries an email or domain."""
    return True  # placeholder; real check happens via inspection below


def main():
    sb = get_supabase()

    call_scores_rows = select_all(sb, "call_scores",
        columns="call_id,deal_id,text_source")
    transcript_calls = {r["call_id"]: r for r in call_scores_rows
                        if r.get("text_source") == "transcript" and r.get("deal_id")}

    calls = select_all(sb, "calls",
        columns="call_id,deal_id,source,participant_emails,"
                "participant_domains,is_internal")
    call_by_id = {c["call_id"]: c for c in calls}

    transcripts = select_all(sb, "call_transcripts",
        columns="call_id,source,speakers,talk_time_seconds,"
                "question_count,total_speech_seconds")
    transcript_by_call = {t["call_id"]: t for t in transcripts}

    print("=" * 100)
    print("STEP 1: Does a per-speaker email/domain field exist ANYWHERE in "
          "call_transcripts or calls?")
    print("=" * 100)
    print("call_transcripts.speakers is {speaker_key: display_name} — checked "
          "schema (migration 042): no email/domain column per speaker.")
    print("calls.participant_emails/participant_domains are flat, UNKEYED "
          "arrays — the whole call's roster, not attributable to a specific "
          "speaker_key. No call_participants join table exists in migrations/.")
    print()

    print("=" * 100)
    print("STEP 2: Live spot-check — 10 real transcript-scored, deal-linked "
          "calls, calls.source split fireflies vs apollo")
    print("=" * 100)

    sample = []
    for call_id in transcript_calls:
        call = call_by_id.get(call_id)
        t = transcript_by_call.get(call_id)
        if not call or not t:
            continue
        if not (t.get("speakers") and call.get("participant_emails")):
            continue
        sample.append((call_id, call, t))

    by_source = Counter(c.get("source") for _, c, _ in sample)
    print(f"Eligible calls (transcript-scored, deal-linked, has BOTH speakers "
          f"AND participant_emails): {len(sample)}")
    print(f"  by calls.source: {dict(by_source)}\n")

    # Take up to 5 fireflies + 5 apollo for a mixed spot-check
    fireflies_sample = [s for s in sample if s[1].get("source") == "fireflies"][:5]
    apollo_sample = [s for s in sample if s[1].get("source") == "apollo"][:5]
    spot = fireflies_sample + apollo_sample
    if not spot:
        spot = sample[:10]

    joinable_count = 0
    for call_id, call, t in spot:
        speakers = t.get("speakers") or {}
        pemails = call.get("participant_emails") or []
        pdomains = call.get("participant_domains") or []
        print(f"call_id={call_id}  calls.source={call.get('source')}  "
              f"is_internal={call.get('is_internal')}")
        print(f"  transcript speaker keys/names: {speakers}")
        print(f"  calls.participant_emails (call-level roster): {pemails}")
        print(f"  calls.participant_domains: {pdomains}")

        # Attempt a DIRECT (non-fuzzy) join: does any speaker_key or speaker
        # display name literally equal, or contain, an email local-part from
        # participant_emails? This is the most generous possible test of
        # "can these be joined without inventing a name-matching heuristic."
        direct_hits = []
        for key, disp_name in speakers.items():
            for email in pemails:
                local = email.split("@")[0].lower()
                if local and (local in (disp_name or "").lower().replace(" ", "")
                              or local in str(key).lower()):
                    direct_hits.append((key, disp_name, email))
        if direct_hits:
            joinable_count += 1
            print(f"  DIRECT (non-fuzzy) join found: {direct_hits}")
        else:
            print(f"  DIRECT (non-fuzzy) join found: NONE — no speaker key/name "
                  f"literally contains any participant email's local-part")
        print()

    print(f"Direct, non-fuzzy joinability across spot-check: "
          f"{joinable_count}/{len(spot)} calls")

    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)
    print("participant_domains/is_internal are real and were built for a "
          "different, working purpose (deal resolution) — that purpose is "
          "not in question. But they are CALL-LEVEL aggregates with no "
          "stored link to call_transcripts' per-utterance speaker_key. "
          "Attributing talk_time_seconds/question_count per speaker to "
          "'internal' vs 'external' would require matching each speaker_key "
          "against the call's participant_emails/participant_domains by "
          "NAME — the same class of heuristic that just failed the Piece 1 "
          "spot-check, not a structurally different, more reliable path.")

    print("\nDONE")


if __name__ == "__main__":
    main()
