#!/usr/bin/env python3
"""
Audit-only script: reliability quantification for the Apollo-specific
exact-ID identity bridge (Criterion C rep-coaching primitive), SCOPED TO
APOLLO CALLS ONLY, per the explicit requirement that this mechanism's
own reliability be re-quantified before it is trusted — same discipline
as the earlier owner-name (76.7%/81.5%, FAILED) and email-anchored
(re-measured, also below bar on the full mixed population) attempts.

This does NOT reuse either of those name-based mechanisms. It measures
the ACTUAL mechanism now wired into transcript_store.py:
_extract_apollo_participant_identities(), which reads Apollo's
conversation-DETAIL `participants` field and keys identities by
participant `id` — the SAME id already used as the speaker key in
call_transcripts.talk_time_seconds/question_count/speakers. No name-
matching anywhere in this script or in the mechanism it measures.

Population: call_scores.text_source='transcript' AND
call_transcripts.source='apollo' (the ~376 Apollo calls previously
identified as transcript-scored and Apollo-sourced).

For each eligible call: LIVE-fetch ApolloClient.get_conversation(call_id)
(read-only GET, no writes anywhere — migration 065 does not need to be
applied for this script to run, since it measures the mechanism
directly against a fresh live fetch plus the already-stored
call_transcripts speaker keys, not the new column). Extract
participant_identities via the real, production
_extract_apollo_participant_identities() function (not a
reimplementation). Check exact-ID overlap against the keys already
present in that call's stored talk_time_seconds.

Reports match rate two ways — by SPEAKER COUNT and by SPEECH-SECONDS
(talk-time-weighted) — against the same 90% bar used throughout this
session. Bot/notetaker artifacts (is_bot=True) are excluded from both
the numerator and denominator: never scored as a match or a miss,
because they are not people this primitive should ever attribute talk
time to.

Reports the REAL number. Does not assume near-100% just because the
mechanism is exact-ID-based rather than name-based.

READ-ONLY. No writes. No primitive design decision is made here.
"""
import sys
import time
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from db import get_supabase
from supabase_client import select_all

RELIABILITY_BAR = 0.90


def main():
    sb = get_supabase()

    call_scores_rows = select_all(sb, "call_scores", columns="call_id,deal_id,text_source")
    transcript_scored_ids = {r["call_id"] for r in call_scores_rows
                             if r.get("text_source") == "transcript" and r.get("deal_id")}
    print(f"call_scores with text_source='transcript' and a deal_id: {len(transcript_scored_ids)}")

    transcripts = select_all(sb, "call_transcripts",
        columns="call_id,source,speakers,talk_time_seconds,question_count,total_speech_seconds")
    apollo_transcripts = {t["call_id"]: t for t in transcripts if t.get("source") == "apollo"}
    print(f"call_transcripts rows with source='apollo': {len(apollo_transcripts)}")

    eligible = []
    for call_id in transcript_scored_ids:
        t = apollo_transcripts.get(call_id)
        if not t:
            continue
        if not (t.get("speakers") and t.get("talk_time_seconds")):
            continue
        eligible.append((call_id, t))

    print(f"\nFull eligible population (transcript-scored, deal-linked, "
          f"Apollo-sourced, has speakers AND talk_time_seconds): {len(eligible)} calls")
    print("(Running the FULL population, not a subsample.)\n")

    if not eligible:
        print("No eligible Apollo calls found — nothing to measure. DONE")
        return

    from apollo_client import ApolloClient
    from transcript_store import _extract_apollo_participant_identities

    client = ApolloClient()

    matched_speakers = 0
    unmatched_speakers = 0
    excluded_bot_speakers = 0
    matched_seconds = 0.0
    unmatched_seconds = 0.0
    fetch_errors = []
    no_participants_field = 0
    unmatched_examples = []

    total = len(eligible)
    for i, (call_id, t) in enumerate(eligible, 1):
        try:
            convo = client.get_conversation(call_id)
        except Exception as e:
            fetch_errors.append((call_id, f"{type(e).__name__}: {str(e)[:120]}"))
            continue

        identities = _extract_apollo_participant_identities(convo)
        if not identities:
            no_participants_field += 1

        talk = t.get("talk_time_seconds") or {}
        speakers = t.get("speakers") or {}

        for key, seconds in talk.items():
            seconds = seconds or 0
            ident = identities.get(key)
            if ident and ident.get("is_bot"):
                excluded_bot_speakers += 1
                continue
            if ident:
                matched_speakers += 1
                matched_seconds += seconds
            else:
                unmatched_speakers += 1
                unmatched_seconds += seconds
                if len(unmatched_examples) < 15:
                    unmatched_examples.append(
                        (call_id, key, speakers.get(key), sorted(identities.keys())))

        if i % 25 == 0 or i == total:
            print(f"  ...{i}/{total} calls fetched "
                  f"(matched={matched_speakers} unmatched={unmatched_speakers} "
                  f"errors={len(fetch_errors)})")
        time.sleep(0.0)  # Apollo detail fetches ran clean with no throttle earlier this session

    total_speakers = matched_speakers + unmatched_speakers
    total_speech = matched_seconds + unmatched_seconds

    print("\n" + "=" * 100)
    print("FETCH HEALTH")
    print("=" * 100)
    print(f"Calls attempted: {total}")
    print(f"Fetch errors: {len(fetch_errors)}")
    for call_id, err in fetch_errors[:15]:
        print(f"  call_id={call_id}  {err}")
    print(f"Calls whose live conversation carried NO 'participants' dict at all: "
          f"{no_participants_field}")

    print("\n" + "=" * 100)
    print("EXCLUSIONS (never scored as match or miss)")
    print("=" * 100)
    print(f"Bot/notetaker speakers excluded: {excluded_bot_speakers}")

    print("\n" + "=" * 100)
    print("MATCH RATE — by speaker count")
    print("=" * 100)
    print(f"Eligible (non-excluded) speakers: {total_speakers}")
    print(f"  Matched:   {matched_speakers}")
    print(f"  Unmatched: {unmatched_speakers}")
    if total_speakers:
        rate = matched_speakers / total_speakers
        print(f"  MATCH RATE: {rate:.1%}  "
              f"({'CLEARS' if rate >= RELIABILITY_BAR else 'DOES NOT CLEAR'} "
              f"the {RELIABILITY_BAR:.0%} bar)")
    else:
        print("  No eligible speakers — cannot compute a rate.")

    print("\n" + "=" * 100)
    print("MATCH RATE — by speech-seconds (talk-time-weighted)")
    print("=" * 100)
    print(f"Total attributable speech-seconds: {total_speech:,.0f}")
    print(f"  Matched seconds:   {matched_seconds:,.0f}")
    print(f"  Unmatched seconds: {unmatched_seconds:,.0f}")
    if total_speech:
        time_rate = matched_seconds / total_speech
        print(f"  MATCH RATE (time-weighted): {time_rate:.1%}  "
              f"({'CLEARS' if time_rate >= RELIABILITY_BAR else 'DOES NOT CLEAR'} "
              f"the {RELIABILITY_BAR:.0%} bar)")
    else:
        print("  No attributable speech-seconds — cannot compute a rate.")

    print("\n" + "=" * 100)
    print(f"UNMATCHED EXAMPLES (up to 15, of {unmatched_speakers} total)")
    print("=" * 100)
    for call_id, key, disp_name, ident_keys in unmatched_examples:
        print(f"  call_id={call_id}  speaker_key={key!r}  name={disp_name!r}  "
              f"live participant_identities keys={ident_keys}")

    print("\nDONE")


if __name__ == "__main__":
    main()
