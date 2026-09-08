#!/usr/bin/env python3
"""
Verify if 96 Meeting Set / $0 deal_value deals are fresh prospects or stale records.

Check:
1. create_date distribution (recent vs old)
2. Activity presence (notes, calls, emails)
3. Age analysis
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_incremental_pipeline, stage_label

def analyze_age_and_activity():
    sb = get_supabase()

    # Get the 96 Meeting Set / $0 deal_value deals
    deals = sb.table("deals").select(
        "deal_id,company_name,deal_value,stage,owner_email,close_date,create_date,pipeline_id,expansion_arr,new_arr"
    ).eq("deal_status", "active").execute()

    # Filter to Meeting Set with $0 incremental ARR and $0 deal_value
    meeting_set_zero = []
    for deal in deals.data:
        if is_incremental_pipeline(deal):
            stage = stage_label(deal.get("stage"))
            expansion_arr = deal.get("expansion_arr") or 0
            new_arr = deal.get("new_arr") or 0
            incremental_value = expansion_arr + new_arr
            deal_value = deal.get("deal_value") or 0

            if stage == "Meeting Set" and incremental_value == 0 and deal_value == 0:
                meeting_set_zero.append(deal)

    print("=" * 80)
    print("ZERO-ARR MEETING SET DEALS - AGE & ACTIVITY ANALYSIS")
    print("=" * 80)
    print(f"Total Meeting Set deals with $0 ARR and $0 deal_value: {len(meeting_set_zero)}")
    print()

    # 1. CREATE_DATE DISTRIBUTION
    print("=" * 80)
    print("1. CREATE_DATE DISTRIBUTION")
    print("=" * 80)
    print()

    now = datetime.now(timezone.utc)
    age_buckets = {
        "0-7 days": [],
        "8-14 days": [],
        "15-30 days": [],
        "31-60 days": [],
        "61-90 days": [],
        "91+ days": [],
        "no_date": []
    }

    for deal in meeting_set_zero:
        create_date = deal.get("create_date")
        if not create_date:
            age_buckets["no_date"].append(deal)
            continue

        try:
            created = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
            age_days = (now - created).days

            if age_days <= 7:
                age_buckets["0-7 days"].append(deal)
            elif age_days <= 14:
                age_buckets["8-14 days"].append(deal)
            elif age_days <= 30:
                age_buckets["15-30 days"].append(deal)
            elif age_days <= 60:
                age_buckets["31-60 days"].append(deal)
            elif age_days <= 90:
                age_buckets["61-90 days"].append(deal)
            else:
                age_buckets["91+ days"].append(deal)
        except Exception as e:
            age_buckets["no_date"].append(deal)

    print(f"{'Age Bucket':<15} | {'Count':>6} | {'% of 96':>8}")
    print("-" * 35)

    for bucket, deals_list in age_buckets.items():
        pct = (len(deals_list) / len(meeting_set_zero)) * 100 if meeting_set_zero else 0
        print(f"{bucket:<15} | {len(deals_list):>6} | {pct:>7.1f}%")

    print()

    # Calculate median age
    ages = []
    for deal in meeting_set_zero:
        create_date = deal.get("create_date")
        if create_date:
            try:
                created = datetime.fromisoformat(create_date.replace("Z", "+00:00"))
                age_days = (now - created).days
                ages.append(age_days)
            except:
                pass

    if ages:
        ages.sort()
        median_age = ages[len(ages) // 2]
        print(f"Median age: {median_age} days")
        print()

        if median_age <= 30:
            print("✅ Interpretation: Median age ≤ 30 days - these are FRESH prospects")
        elif median_age <= 60:
            print("⚠️  Interpretation: Median age 31-60 days - moderately old, some cleanup needed")
        else:
            print("❌ Interpretation: Median age > 60 days - STALE records, cleanup required")
    print()

    # 2. ACTIVITY CHECK
    print("=" * 80)
    print("2. ACTIVITY PRESENCE CHECK")
    print("=" * 80)
    print()

    # Sample 20 random deals for activity check (API rate limiting consideration)
    import random
    sample_size = min(20, len(meeting_set_zero))
    sample_deals = random.sample(meeting_set_zero, sample_size)

    print(f"Checking activity for {sample_size} random deals...")
    print()

    has_activity = []
    no_activity = []

    for deal in sample_deals:
        deal_id = deal.get("deal_id")

        # Check for notes/engagements
        try:
            notes = sb.table("engagements").select("id").eq(
                "deal_id", deal_id
            ).execute()

            if notes.data and len(notes.data) > 0:
                has_activity.append(deal)
            else:
                no_activity.append(deal)
        except Exception as e:
            # Can't determine, assume no activity
            no_activity.append(deal)

    print(f"Sample results ({sample_size} deals checked):")
    print(f"  With activity (notes/engagements): {len(has_activity)} ({len(has_activity)/sample_size*100:.1f}%)")
    print(f"  No activity found: {len(no_activity)} ({len(no_activity)/sample_size*100:.1f}%)")
    print()

    if len(no_activity) > len(has_activity):
        print("❌ Interpretation: Majority have NO activity - likely abandoned placeholders")
    else:
        print("✅ Interpretation: Majority have activity - actively being worked")
    print()

    # 3. COMBINED ANALYSIS
    print("=" * 80)
    print("3. COMBINED AGE + ACTIVITY ANALYSIS")
    print("=" * 80)
    print()

    # Old deals (60+ days) that might be stale
    old_deals = age_buckets["61-90 days"] + age_buckets["91+ days"]
    old_count = len(old_deals)
    old_pct = (old_count / len(meeting_set_zero)) * 100 if meeting_set_zero else 0

    print(f"Deals 60+ days old: {old_count} ({old_pct:.1f}%)")
    print()

    if old_pct > 50:
        print("❌ CONCERNING: Majority of deals are 60+ days old")
        print("   → These should have progressed or been cleaned up")
        print("   → Indicates stale pipeline, not fresh early-stage prospects")
    elif old_pct > 25:
        print("⚠️  MODERATE: Significant portion (25-50%) are 60+ days old")
        print("   → Some cleanup needed, but not systemic crisis")
    else:
        print("✅ HEALTHY: < 25% are 60+ days old")
        print("   → Mostly fresh prospects, normal pipeline hygiene")
    print()

    # Show examples of oldest deals
    if old_deals:
        print("Sample of oldest deals (60+ days):")
        print()
        oldest = sorted(
            [d for d in old_deals if d.get("create_date")],
            key=lambda d: d.get("create_date")
        )[:5]

        for deal in oldest:
            create_date = deal.get("create_date", "")[:10]
            try:
                created = datetime.fromisoformat(deal.get("create_date").replace("Z", "+00:00"))
                age = (now - created).days
                print(f"  {deal.get('company_name')} (ID: {deal.get('deal_id')})")
                print(f"    Created: {create_date} ({age} days ago)")
                print(f"    Owner: {deal.get('owner_email')}")
                print()
            except:
                pass

if __name__ == "__main__":
    analyze_age_and_activity()
