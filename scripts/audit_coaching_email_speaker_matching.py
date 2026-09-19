#!/usr/bin/env python3
"""
Audit-only script: reliability quantification for the email-anchored
speaker-matching bridge discovered in the domain-classification audit
(matching call_transcripts.speakers against THIS call's own
calls.participant_emails, NOT the deal owner's inferred name — the
mechanism that scored 9/10 on a 10-call spot-check, unlike the earlier
owner-name heuristic that failed).

Fixes the two known gaps found in that spot-check BEFORE measuring at
scale (not patched ad hoc afterward):
  1. Dotted/underscored/hyphenated local-parts (scott.keller@ ->
     scottkeller, matched against "Scott Keller").
  2. First-initial+lastname conventions (jtaylor@ -> matched against
     "Jack Taylor" via first-initial+lastname, and the symmetric
     firstname+last-initial form).

Excludes generic/alias addresses (everyone@, sales@, ...) and
non-human "speakers" (conference-room systems, bracketed/numbered
placeholder names) from the eligible pool explicitly — never scored as
a match OR a miss, because they are not people this ratio should ever
attribute talk time to.

Runs over the FULL eligible population (1,383 calls, confirmed in the
prior audit) rather than a subsample of a few hundred — strictly more
evidence at effectively the same cost, not a deviation from what was
asked.

Reports:
  - match rate two ways: by SPEAKER COUNT and by SPEECH-SECONDS
    (talk-time-weighted) — a single unmatched dominant talker matters
    more than an unmatched wallflower, and count-based and time-based
    rates can diverge.
  - failure breakdown by rule that fired (exact_concat / substring /
    initial_lastname / firstname_initial) for matches, so the
    contribution of the two NEW rules (beyond plain substring) is
    visible, not just the aggregate.
  - genuinely-unmatchable examples for manual inspection.

Does NOT re-run the won/lost calibration — that is a separate, later
step, deliberately sequential so a matching-rule change never gets
silently baked into a calibration number before being verified on its
own.

READ-ONLY. No writes. No primitive is designed or built here.
"""
import re
import sys
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from db import get_supabase
from supabase_client import select_all

# Reliability bar: Piece 1's failed heuristic used 70% (exploratory, guessed
# against an unrelated field). This mechanism is anchored to the call's own
# confirmed roster, not guessed — a materially higher bar is fair. Proposed:
# 90%, on BOTH the speaker-count and speech-seconds-weighted measures.
RELIABILITY_BAR = 0.90

GENERIC_LOCAL_PARTS = {
    "everyone", "sales", "support", "info", "noreply", "no-reply", "admin",
    "team", "hello", "contact", "help", "office", "reception", "frontdesk",
    "booking", "meetings", "calendar", "scheduling", "enterprise",
    "marketing", "hr", "jobs", "careers", "press", "media", "billing",
    "accounts", "finance", "legal", "security", "general", "welcome",
}


def is_generic_alias(email: str) -> bool:
    local = email.split("@")[0].lower()
    return local in GENERIC_LOCAL_PARTS


def is_non_human_speaker(display_name: str) -> bool:
    """Conference-room systems / placeholder names: contain digits or
    bracket/paren markers (e.g. 'RAV4 [Capacity 7]', 'GTP-1-05 (6)'),
    or are explicitly a non-name placeholder."""
    d = (display_name or "").strip()
    if not d:
        return True
    if any(ch.isdigit() for ch in d):
        return True
    if "[" in d or "(" in d:
        return True
    if d.lower() in {"unknown", "guest"}:
        return True
    return False


def _normalize_tokens(display_name: str):
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", display_name or "")
    return [t.lower() for t in cleaned.split() if t]


def match_email_to_speaker(email: str, display_name: str):
    """Deterministic rule set, checked in priority order (most specific
    first). Returns the rule name that matched, or None.

    local_stripped: the email local-part with '.', '_', '-' removed
    (fixes the dotted-local-part gap: scott.keller -> scottkeller).
    A length guard (>=3 chars) avoids spurious matches on very short
    local-parts.
    """
    local = email.split("@")[0].lower()
    local_stripped = re.sub(r"[._\-]", "", local)
    if len(local_stripped) < 3:
        return None

    tokens = _normalize_tokens(display_name)
    if not tokens:
        return None
    concat = "".join(tokens)

    if local_stripped == concat:
        return "exact_concat"
    if local_stripped in concat:
        return "substring"
    if len(tokens) >= 2:
        first, last = tokens[0], tokens[-1]
        if local_stripped == first[0] + last:
            return "initial_lastname"     # jtaylor = j + taylor
        if local_stripped == first + last[0]:
            return "firstname_initial"    # taylorj = taylor + j
    return None


def best_match(pemails_people, display_name):
    """Try every candidate email against this speaker; keep the most
    specific rule that fires (priority order below)."""
    priority = {"exact_concat": 0, "substring": 1,
                "initial_lastname": 2, "firstname_initial": 2}
    best = None  # (email, rule)
    for email in pemails_people:
        rule = match_email_to_speaker(email, display_name)
        if rule and (best is None or priority[rule] < priority[best[1]]):
            best = (email, rule)
    return best


def main():
    sb = get_supabase()

    call_scores_rows = select_all(sb, "call_scores",
        columns="call_id,deal_id,text_source")
    transcript_calls = {r["call_id"]: r for r in call_scores_rows
                        if r.get("text_source") == "transcript" and r.get("deal_id")}

    calls = select_all(sb, "calls",
        columns="call_id,deal_id,source,participant_emails,participant_domains")
    call_by_id = {c["call_id"]: c for c in calls}

    transcripts = select_all(sb, "call_transcripts",
        columns="call_id,source,speakers,talk_time_seconds,total_speech_seconds")
    transcript_by_call = {t["call_id"]: t for t in transcripts}

    eligible = []
    for call_id in transcript_calls:
        call = call_by_id.get(call_id)
        t = transcript_by_call.get(call_id)
        if not call or not t:
            continue
        if not (t.get("speakers") and call.get("participant_emails")):
            continue
        eligible.append((call_id, call, t))

    print(f"Full eligible population (transcript-scored, deal-linked, has "
          f"BOTH speakers AND participant_emails): {len(eligible)} calls")
    print(f"(Running the FULL population, not a subsample — strictly more "
          f"evidence at the same cost.)\n")

    matched_speakers = 0
    unmatched_speakers = 0
    excluded_non_human_speakers = 0
    excluded_generic_emails_total = 0
    matched_speech_seconds = 0.0
    unmatched_speech_seconds = 0.0
    rule_counts = Counter()
    unmatched_examples = []

    for call_id, call, t in eligible:
        pemails = call.get("participant_emails") or []
        pemails_people = [e for e in pemails if not is_generic_alias(e)]
        excluded_generic_emails_total += (len(pemails) - len(pemails_people))
        if not pemails_people:
            continue

        speakers = t.get("speakers") or {}
        talk = t.get("talk_time_seconds") or {}

        for key, disp_name in speakers.items():
            if is_non_human_speaker(disp_name):
                excluded_non_human_speakers += 1
                continue

            match = best_match(pemails_people, disp_name)
            seconds = talk.get(key, 0) or 0
            if match:
                matched_speakers += 1
                matched_speech_seconds += seconds
                rule_counts[match[1]] += 1
            else:
                unmatched_speakers += 1
                unmatched_speech_seconds += seconds
                if len(unmatched_examples) < 15:
                    unmatched_examples.append(
                        (call_id, disp_name, pemails_people))

    total_speakers = matched_speakers + unmatched_speakers
    total_speech = matched_speech_seconds + unmatched_speech_seconds

    print("=" * 100)
    print("EXCLUSIONS (never scored as match or miss)")
    print("=" * 100)
    print(f"Generic/alias participant_emails excluded: {excluded_generic_emails_total}")
    print(f"Non-human speakers excluded (digits/brackets/placeholders): "
          f"{excluded_non_human_speakers}\n")

    print("=" * 100)
    print("MATCH RATE — by speaker count")
    print("=" * 100)
    print(f"Eligible (non-excluded) speakers: {total_speakers}")
    print(f"  Matched:   {matched_speakers}")
    print(f"  Unmatched: {unmatched_speakers}")
    if total_speakers:
        rate = matched_speakers / total_speakers
        print(f"  MATCH RATE: {rate:.1%}  "
              f"({'CLEARS' if rate >= RELIABILITY_BAR else 'DOES NOT CLEAR'} "
              f"the proposed {RELIABILITY_BAR:.0%} bar)")

    print("\n" + "=" * 100)
    print("MATCH RATE — by speech-seconds (talk-time-weighted)")
    print("=" * 100)
    print(f"Total attributable speech-seconds: {total_speech:,.0f}")
    print(f"  Matched seconds:   {matched_speech_seconds:,.0f}")
    print(f"  Unmatched seconds: {unmatched_speech_seconds:,.0f}")
    if total_speech:
        time_rate = matched_speech_seconds / total_speech
        print(f"  MATCH RATE (time-weighted): {time_rate:.1%}  "
              f"({'CLEARS' if time_rate >= RELIABILITY_BAR else 'DOES NOT CLEAR'} "
              f"the proposed {RELIABILITY_BAR:.0%} bar)")

    print("\n" + "=" * 100)
    print("MATCH BREAKDOWN BY RULE (which rule fired for successful matches)")
    print("=" * 100)
    for rule, count in rule_counts.most_common():
        pct = count / matched_speakers * 100 if matched_speakers else 0
        print(f"  {rule:20s}: {count:5d}  ({pct:.1f}% of matches)")
    new_rule_matches = rule_counts.get("initial_lastname", 0) + rule_counts.get("firstname_initial", 0)
    print(f"\n  Matches ONLY possible via the two NEW rules (initial+lastname "
          f"forms), i.e. would have been misses under plain substring alone: "
          f"{new_rule_matches}")

    print("\n" + "=" * 100)
    print(f"GENUINELY UNMATCHABLE — examples (up to 15, of {unmatched_speakers} total)")
    print("=" * 100)
    for call_id, disp_name, roster in unmatched_examples:
        print(f"  call_id={call_id}  speaker={disp_name!r}  "
              f"call's participant_emails={roster}")

    print("\nDONE")


if __name__ == "__main__":
    main()
