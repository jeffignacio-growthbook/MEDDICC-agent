#!/usr/bin/env python3
"""
Verify if activity/engagement data is populated for ANY deals.

Checks:
1. Do deals WITH incremental ARR show activity?
2. What tables exist for activity data?
3. Is "zero activity" real or a query artifact?
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_incremental_pipeline

def verify_activity_baseline():
    sb = get_supabase()

    print("=" * 80)
    print("ACTIVITY BASELINE VERIFICATION")
    print("=" * 80)
    print()

    # 1. Check what activity/engagement tables exist
    print("1. CHECKING AVAILABLE TABLES FOR ACTIVITY DATA")
    print("=" * 80)
    print()

    # Check engagements table
    try:
        engagements_count = sb.table("engagements").select("id", count="exact").execute()
        print(f"✅ engagements table exists: {engagements_count.count} total rows")
    except Exception as e:
        print(f"❌ engagements table error: {e}")
        engagements_count = None

    # Check notes table
    try:
        notes_count = sb.table("notes").select("id", count="exact").execute()
        print(f"✅ notes table exists: {notes_count.count} total rows")
    except Exception as e:
        print(f"❌ notes table error: {e}")
        notes_count = None

    # Check calls table
    try:
        calls_count = sb.table("calls").select("id", count="exact").execute()
        print(f"✅ calls table exists: {calls_count.count} total rows")
    except Exception as e:
        print(f"❌ calls table error: {e}")
        calls_count = None

    # Check emails table
    try:
        emails_count = sb.table("emails").select("id", count="exact").execute()
        print(f"✅ emails table exists: {emails_count.count} total rows")
    except Exception as e:
        print(f"❌ emails table error: {e}")
        emails_count = None

    print()

    # 2. Sample deals WITH incremental ARR
    print("=" * 80)
    print("2. ACTIVITY CHECK FOR DEALS WITH INCREMENTAL ARR")
    print("=" * 80)
    print()

    deals = sb.table("deals").select(
        "deal_id,company_name,expansion_arr,new_arr,deal_value"
    ).eq("deal_status", "active").execute()

    # Filter to deals with incremental ARR > 0
    with_arr = []
    for deal in deals.data:
        if is_incremental_pipeline(deal):
            expansion_arr = deal.get("expansion_arr") or 0
            new_arr = deal.get("new_arr") or 0
            incremental_value = expansion_arr + new_arr

            if incremental_value > 0:
                with_arr.append(deal)

    # Sample 15 random deals
    import random
    sample_size = min(15, len(with_arr))
    sample_deals = random.sample(with_arr, sample_size)

    print(f"Checking activity for {sample_size} deals WITH incremental ARR > 0...")
    print()

    has_activity_count = 0
    no_activity_count = 0

    for deal in sample_deals:
        deal_id = deal.get("deal_id")
        company = deal.get("company_name")
        incremental = (deal.get("expansion_arr") or 0) + (deal.get("new_arr") or 0)

        # Check engagements
        activity_found = False
        try:
            if engagements_count:
                eng = sb.table("engagements").select("id").eq("deal_id", deal_id).limit(1).execute()
                if eng.data:
                    activity_found = True
        except:
            pass

        # Check notes if available
        try:
            if notes_count and not activity_found:
                notes = sb.table("notes").select("id").eq("deal_id", deal_id).limit(1).execute()
                if notes.data:
                    activity_found = True
        except:
            pass

        if activity_found:
            has_activity_count += 1
            print(f"  ✅ {company}: ${incremental:,.0f} - HAS activity")
        else:
            no_activity_count += 1
            print(f"  ❌ {company}: ${incremental:,.0f} - NO activity")

    print()
    print(f"Results for deals WITH incremental ARR:")
    print(f"  Has activity: {has_activity_count} / {sample_size} ({has_activity_count/sample_size*100:.1f}%)")
    print(f"  No activity: {no_activity_count} / {sample_size} ({no_activity_count/sample_size*100:.1f}%)")
    print()

    # 3. Interpretation
    print("=" * 80)
    print("3. INTERPRETATION")
    print("=" * 80)
    print()

    if no_activity_count == sample_size:
        print("❌ QUERY ARTIFACT: Even deals WITH incremental ARR show zero activity")
        print("   → This is a query/schema issue, NOT specific to zero-ARR deals")
        print("   → Activity data isn't being captured or joined correctly")
        print("   → DO NOT claim '100% no activity' as a meaningful finding")
        print()
        print("   Possible causes:")
        print("   - Activity tracked in different table/system")
        print("   - deal_id field name mismatch")
        print("   - Sparse population of engagement tables")
        print("   - Activity logging not implemented")
    elif has_activity_count > sample_size * 0.5:
        print("✅ BASELINE WORKS: Majority of ARR-classified deals show activity")
        print("   → Activity tracking is working")
        print("   → Zero-ARR deals genuinely having no activity IS a meaningful finding")
        print("   → Safe to report 'no activity' for zero-ARR population")
    else:
        print("⚠️  MIXED: Some ARR-classified deals have activity, but not majority")
        print("   → Activity tracking is partially working")
        print("   → 'No activity' finding is somewhat meaningful but not definitive")

    print()

    # 4. Check a specific high-value deal we know exists
    print("=" * 80)
    print("4. SPOT CHECK: Known High-Value Deal")
    print("=" * 80)
    print()

    # Check Anthropic (we know it's $500K expansion)
    anthropic = sb.table("deals").select("deal_id,company_name").eq(
        "company_name", "Anthropic"
    ).eq("deal_status", "active").execute()

    if anthropic.data:
        anthro_deal_id = anthropic.data[0].get("deal_id")
        print(f"Anthropic deal_id: {anthro_deal_id}")

        # Check for activity
        try:
            eng = sb.table("engagements").select("id").eq("deal_id", anthro_deal_id).execute()
            print(f"  engagements count: {len(eng.data) if eng.data else 0}")
        except Exception as e:
            print(f"  engagements error: {e}")

        try:
            if notes_count:
                notes = sb.table("notes").select("id").eq("deal_id", anthro_deal_id).execute()
                print(f"  notes count: {len(notes.data) if notes.data else 0}")
        except Exception as e:
            print(f"  notes error: {e}")
    else:
        print("Anthropic deal not found")

    print()

if __name__ == "__main__":
    verify_activity_baseline()
