#!/usr/bin/env python3
"""
Audit-only script: PIECE 1 of the rep-coaching-primitive build — Criterion C
calibration audit, run BEFORE any implementation.

Two phases, in order, because the second is worthless if the first fails:

PHASE 1: Spot-check the rep-speaker-identification heuristic (deal owner's
derived display name matched against call_transcripts.speakers) on 5-10
real calls. No existing code in this repo does this match today — it's a
brand-new heuristic, unverified. If it doesn't reliably pick the actual
rep out of the speaker list, Phase 2's talk-ratio numbers are built on
sand and must be reported as unreliable, not just its (deferred) threshold.

PHASE 2: If Phase 1 looks reliable, compute the pooled won-vs-lost
distribution of rep_talk_ratio and rep_question_share across GrowthBook's
own transcript-scored calls (call_scores.text_source='transcript') — same
75th-percentile empirical method SEGMENT_CYCLE_BENCHMARKS already uses.
Reports real sample sizes against min_evidence_count=30, never fabricates
a threshold if the data doesn't support one.

Rep-name derivation: identical transform to seed_targets.py
(email.split('@')[0].replace('.', ' ').title()), so the heuristic is
consistent with the rest of this codebase's own rep-naming convention,
not invented fresh.

READ-ONLY throughout. No writes. No primitive is designed or built here.
"""
import sys
import statistics
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from db import get_supabase
from supabase_client import select_all

MIN_EVIDENCE_COUNT = 30


def _derived_rep_name(owner_email: str) -> str:
    """Same transform seed_targets.py uses to derive a display name from
    an owner_email, so this heuristic matches the codebase's own
    established rep-naming convention rather than inventing a new one."""
    if not owner_email:
        return ""
    return owner_email.split("@")[0].replace(".", " ").title()


def _name_tokens(name: str):
    return set(t for t in (name or "").lower().replace(",", " ").split() if t)


def _match_rep_speaker(owner_email: str, speakers: dict):
    """Best-available heuristic: token-overlap match between the derived
    rep name and each speaker's display name. Returns (matched_key,
    matched_name, match_strength) or (None, None, 'no_match').
    match_strength: 'strong' (>=2 token overlap, e.g. first+last name),
    'weak' (1 token overlap, e.g. first name only), 'no_match'."""
    derived = _derived_rep_name(owner_email)
    derived_tokens = _name_tokens(derived)
    if not derived_tokens or not speakers:
        return None, None, "no_match"

    best_key, best_name, best_overlap = None, None, 0
    for key, disp_name in speakers.items():
        overlap = len(derived_tokens & _name_tokens(disp_name))
        if overlap > best_overlap:
            best_key, best_name, best_overlap = key, disp_name, overlap

    if best_overlap >= 2:
        return best_key, best_name, "strong"
    elif best_overlap == 1:
        return best_key, best_name, "weak"
    return None, None, "no_match"


def main():
    sb = get_supabase()

    print("=" * 100)
    print("PHASE 1: Rep-speaker-identification heuristic spot-check (5-10 real calls)")
    print("=" * 100)
    print("Heuristic: derive rep display name from deals.owner_email "
          "(seed_targets.py's own transform), token-match against "
          "call_transcripts.speakers. NOT existing code — brand new, unverified.\n")

    # Pull calls that are transcript-scored, linked to a deal, with a
    # multi-speaker transcript (so there's an actual rep/prospect distinction
    # to identify at all).
    call_scores_rows = select_all(sb, "call_scores",
        columns="call_id,deal_id,text_source")
    transcript_calls = {r["call_id"]: r for r in call_scores_rows
                        if r.get("text_source") == "transcript" and r.get("deal_id")}
    print(f"Total call_scores rows with text_source='transcript' AND deal_id set: "
          f"{len(transcript_calls)}")

    deals = select_all(sb, "deals", columns="deal_id,owner_email,stage,deal_status")
    deal_by_id = {d["deal_id"]: d for d in deals}

    transcripts = select_all(sb, "call_transcripts",
        columns="call_id,speakers,talk_time_seconds,question_count,total_speech_seconds")
    transcript_by_call = {t["call_id"]: t for t in transcripts}

    # Sample: calls with >=2 distinct speakers and a resolvable owner_email.
    sample = []
    for call_id, cs_row in transcript_calls.items():
        t = transcript_by_call.get(call_id)
        deal = deal_by_id.get(cs_row["deal_id"])
        if not t or not deal or not deal.get("owner_email"):
            continue
        speakers = t.get("speakers") or {}
        if len(speakers) < 2:
            continue
        sample.append((call_id, deal, t, speakers))

    print(f"Eligible calls for spot-check (transcript-scored, deal-linked, "
          f"owner known, 2+ speakers): {len(sample)}\n")

    spot_check_n = min(10, len(sample))
    strong, weak, no_match = 0, 0, 0
    for call_id, deal, t, speakers in sample[:spot_check_n]:
        owner_email = deal["owner_email"]
        derived = _derived_rep_name(owner_email)
        key, name, strength = _match_rep_speaker(owner_email, speakers)
        talk = t.get("talk_time_seconds") or {}
        print(f"call_id={call_id}  deal_id={deal['deal_id']}  "
              f"owner_email={owner_email}  derived_name={derived!r}")
        print(f"  speakers in transcript: {speakers}")
        print(f"  talk_time_seconds: {talk}")
        print(f"  MATCH: key={key!r} name={name!r} strength={strength}")
        print()
        if strength == "strong":
            strong += 1
        elif strength == "weak":
            weak += 1
        else:
            no_match += 1

    print(f"Spot-check summary (n={spot_check_n}): "
          f"strong_match={strong}, weak_match={weak}, no_match={no_match}")
    reliable = (strong / spot_check_n >= 0.7) if spot_check_n else False
    print(f"\n>>> HEURISTIC RELIABILITY CALL: "
          f"{'LOOKS RELIABLE ENOUGH TO PROCEED' if reliable else 'DOES NOT LOOK RELIABLE'} "
          f"(threshold: >=70% strong matches in the sample)")

    print("\n" + "=" * 100)
    print("PHASE 2: Won-vs-lost pooled distribution of rep_talk_ratio / rep_question_share")
    print("(Proceeding regardless of Phase 1's call, so the numbers exist to inspect — "
          "but treat them as UNRELIABLE if Phase 1 above did not clear the bar.)")
    print("=" * 100)

    from field_semantics import is_won, is_lost

    won_talk_ratios, lost_talk_ratios = [], []
    won_question_shares, lost_question_shares = [], []
    skipped_no_match = 0
    skipped_no_totals = 0

    for call_id, cs_row in transcript_calls.items():
        t = transcript_by_call.get(call_id)
        deal = deal_by_id.get(cs_row["deal_id"])
        if not t or not deal or not deal.get("owner_email"):
            continue
        stage = deal.get("stage")
        try:
            won = is_won(str(stage)) if stage else False
            lost = is_lost(str(stage)) if stage else False
        except Exception:
            won = lost = False
        if not (won or lost):
            continue  # only terminal (closed) deals count for this calibration

        speakers = t.get("speakers") or {}
        key, name, strength = _match_rep_speaker(deal["owner_email"], speakers)
        if not key or strength == "no_match":
            skipped_no_match += 1
            continue

        talk = t.get("talk_time_seconds") or {}
        total_speech = t.get("total_speech_seconds")
        rep_talk = talk.get(key)
        if not total_speech or rep_talk is None:
            skipped_no_totals += 1
            continue
        talk_ratio = rep_talk / total_speech

        qcount = t.get("question_count") or {}
        total_questions = sum(qcount.values()) if qcount else 0
        rep_questions = qcount.get(key, 0)
        question_share = (rep_questions / total_questions) if total_questions > 0 else None

        bucket_talk = won_talk_ratios if won else lost_talk_ratios
        bucket_talk.append(talk_ratio)
        if question_share is not None:
            bucket_q = won_question_shares if won else lost_question_shares
            bucket_q.append(question_share)

    print(f"Calls skipped (rep speaker could not be matched): {skipped_no_match}")
    print(f"Calls skipped (missing talk-time totals): {skipped_no_totals}\n")

    def _report(label, won_vals, lost_vals):
        print(f"--- {label} ---")
        for name, vals in (("WON", won_vals), ("LOST", lost_vals)):
            n = len(vals)
            gated = n >= MIN_EVIDENCE_COUNT
            print(f"  {name}: n={n} {'>= ' if gated else '< '}min_evidence_count={MIN_EVIDENCE_COUNT} "
                  f"({'CLEARS' if gated else 'DOES NOT CLEAR'} the floor)")
            if n:
                sorted_vals = sorted(vals)
                p25 = sorted_vals[int(0.25 * (n - 1))]
                p50 = statistics.median(sorted_vals)
                p75 = sorted_vals[int(0.75 * (n - 1))]
                print(f"    mean={statistics.mean(vals):.3f}  "
                      f"p25={p25:.3f}  median={p50:.3f}  p75={p75:.3f}")
        print()

    _report("rep_talk_ratio (rep talk seconds / total speech seconds)",
             won_talk_ratios, lost_talk_ratios)
    _report("rep_question_share (rep questions / total questions in call)",
             won_question_shares, lost_question_shares)

    print("=" * 100)
    print("VERDICT: does a real, data-grounded threshold emerge, or is this an honest")
    print("'insufficient data' deferral (same class as the MEDDICC staleness gate)?")
    print("=" * 100)
    both_cleared = (len(won_talk_ratios) >= MIN_EVIDENCE_COUNT and
                    len(lost_talk_ratios) >= MIN_EVIDENCE_COUNT)
    print(f"Both WON and LOST buckets clear min_evidence_count for talk_ratio: {both_cleared}")
    if both_cleared:
        sep = abs(statistics.mean(won_talk_ratios) - statistics.mean(lost_talk_ratios))
        print(f"Mean talk_ratio separation (won vs lost): {sep:.3f}")

    print("\nDONE")


if __name__ == "__main__":
    main()
