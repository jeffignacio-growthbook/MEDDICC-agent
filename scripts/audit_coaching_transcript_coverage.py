#!/usr/bin/env python3
"""
Audit-only script: PART 1 of the rep-coaching-primitive pre-scoping audit —
transcript availability, the hard prerequisite.

Answers, with real live numbers (never rounded up):
1. What fraction of DEALS have at least one linked call with a usable
   transcript (call_transcripts.transcript_quality IN ('full','partial') —
   'fragments_only' and 'unavailable' are NOT usable for coaching-level
   analysis of what was actually said).
2. What fraction of CALLS (not just deals) have a usable transcript, broken
   out by transcript_quality, so the calls.deal_id resolution rate and the
   transcript-fetch rate are reported as two SEPARATE numbers, not
   conflated into one "coverage" figure.
3. Whether call_transcripts carries structured per-speaker metrics
   (talk_time_seconds, question_count, longest_monologue) alongside the raw
   text, and how often those are populated (vs. null when unavailable).

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


def main():
    sb = get_supabase()

    print("=" * 100)
    print("STEP 1: deals table — total count")
    print("=" * 100)
    deals = select_all(sb, "deals", columns="deal_id,deal_status")
    total_deals = len(deals)
    active_deals = sum(1 for d in deals if d.get("deal_status") == "active")
    print(f"Total deals (all statuses): {total_deals}")
    print(f"Active deals: {active_deals}")

    print("\n" + "=" * 100)
    print("STEP 2: calls table — deal_id resolution rate")
    print("=" * 100)
    calls = select_all(sb, "calls", columns="call_id,deal_id,call_intent,call_date")
    total_calls = len(calls)
    calls_with_deal_id = [c for c in calls if c.get("deal_id")]
    print(f"Total rows in calls table: {total_calls}")
    print(f"Calls with a resolved deal_id: {len(calls_with_deal_id)} "
          f"({len(calls_with_deal_id) / total_calls * 100:.1f}% of calls)" if total_calls else "N/A")

    intent_counts = Counter(c.get("call_intent") for c in calls)
    print(f"call_intent breakdown: {dict(intent_counts)}")

    deals_with_any_call = {c["deal_id"] for c in calls_with_deal_id}
    print(f"\nDistinct deals with at least one resolved call: {len(deals_with_any_call)} "
          f"({len(deals_with_any_call) / total_deals * 100:.1f}% of ALL {total_deals} deals, "
          f"not rounded up)" if total_deals else "N/A")

    print("\n" + "=" * 100)
    print("STEP 3: call_transcripts table — transcript_quality breakdown")
    print("=" * 100)
    transcripts = select_all(sb, "call_transcripts",
        columns="call_id,source,transcript_quality,char_count,"
                "talk_time_seconds,question_count,longest_monologue_seconds,"
                "sentence_count,unavailable_reason")
    total_transcripts = len(transcripts)
    print(f"Total rows in call_transcripts: {total_transcripts}")

    quality_counts = Counter(t.get("transcript_quality") for t in transcripts)
    print(f"transcript_quality breakdown (ALL transcript rows, not deal-scoped): {dict(quality_counts)}")

    usable_qualities = {"full", "partial"}
    usable_transcripts = [t for t in transcripts if t.get("transcript_quality") in usable_qualities]
    print(f"\nUsable transcripts (quality IN {usable_qualities}): {len(usable_transcripts)} "
          f"({len(usable_transcripts) / total_transcripts * 100:.1f}% of all {total_transcripts} "
          f"transcript rows)" if total_transcripts else "N/A")

    # Structured metrics population, among usable transcripts only
    with_talk_time = sum(1 for t in usable_transcripts if t.get("talk_time_seconds"))
    with_question_count = sum(1 for t in usable_transcripts if t.get("question_count"))
    with_monologue = sum(1 for t in usable_transcripts if t.get("longest_monologue_seconds") is not None)
    n_usable = len(usable_transcripts) or 1
    print(f"\nAmong usable transcripts, structured per-speaker metrics populated:")
    print(f"  talk_time_seconds populated: {with_talk_time}/{len(usable_transcripts)} "
          f"({with_talk_time / n_usable * 100:.1f}%)")
    print(f"  question_count populated: {with_question_count}/{len(usable_transcripts)} "
          f"({with_question_count / n_usable * 100:.1f}%)")
    print(f"  longest_monologue_seconds populated: {with_monologue}/{len(usable_transcripts)} "
          f"({with_monologue / n_usable * 100:.1f}%)")

    avg_char_count = None
    char_counts = [t.get("char_count") for t in usable_transcripts if t.get("char_count")]
    if char_counts:
        avg_char_count = sum(char_counts) / len(char_counts)
        print(f"\nAvg char_count among usable transcripts: {avg_char_count:,.0f} "
              f"(n={len(char_counts)})")

    unavailable_reasons = Counter(
        t.get("unavailable_reason") for t in transcripts
        if t.get("transcript_quality") == "unavailable")
    print(f"\nunavailable_reason breakdown (top 10): {unavailable_reasons.most_common(10)}")

    print("\n" + "=" * 100)
    print("STEP 4: THE COMPOUND NUMBER — fraction of ALL DEALS with >=1 usable transcript")
    print("=" * 100)
    call_to_deal = {c["call_id"]: c.get("deal_id") for c in calls_with_deal_id}
    deals_with_usable_transcript = set()
    for t in usable_transcripts:
        did = call_to_deal.get(t["call_id"])
        if did:
            deals_with_usable_transcript.add(did)

    print(f"Deals with >=1 call that has a USABLE transcript (full/partial): "
          f"{len(deals_with_usable_transcript)}")
    if total_deals:
        print(f"  = {len(deals_with_usable_transcript) / total_deals * 100:.1f}% of ALL "
              f"{total_deals} deals (not rounded up)")
    if active_deals:
        active_deal_ids = {d["deal_id"] for d in deals if d.get("deal_status") == "active"}
        active_with_transcript = deals_with_usable_transcript & active_deal_ids
        print(f"  = {len(active_with_transcript)} of {active_deals} ACTIVE deals "
              f"({len(active_with_transcript) / active_deals * 100:.1f}%)")

    print("\nDONE")


if __name__ == "__main__":
    main()
