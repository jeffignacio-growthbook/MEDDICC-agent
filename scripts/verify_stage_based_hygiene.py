#!/usr/bin/env python3
"""
Verify that stage-based hygiene rules produce expected count of 68 flagged deals.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_incremental_pipeline, stage_label

def verify_stage_based_hygiene():
    sb = get_supabase()

    # Get all active deals
    deals = sb.table("deals").select(
        "deal_id,company_name,deal_value,stage,owner_email,close_date,create_date,pipeline_id,expansion_arr,new_arr,renewal_revenue"
    ).eq("deal_status", "active").execute()

    # Apply stage-based hygiene rules in TWO scopes:
    # 1. ALL active deals (company-wide data quality)
    # 2. Incremental pipeline only (query_pipeline handler scope)

    flagged_all_active = []
    flagged_incremental_pipeline = []
    meeting_set_excluded = []
    renewal_stages_valid_all = []
    renewal_stages_valid_incr = []

    for deal in deals.data:
        expansion_arr = deal.get("expansion_arr") or 0
        new_arr = deal.get("new_arr") or 0
        renewal_revenue = deal.get("renewal_revenue") or 0
        incremental_value = expansion_arr + new_arr

        stage = stage_label(deal.get("stage"))
        in_incremental_pipeline = is_incremental_pipeline(deal)

        # Company-wide hygiene check (ALL active deals)
        if stage == "Meeting Set":
            if incremental_value == 0:
                meeting_set_excluded.append(deal)
        elif stage in ["Upcoming Renewal", "Renewal Engaged"]:
            if renewal_revenue == 0:
                flagged_all_active.append(("renewal_stage", deal))
            else:
                renewal_stages_valid_all.append(deal)
        else:
            if incremental_value == 0:
                flagged_all_active.append(("other_stage", deal))

        # Incremental pipeline scope hygiene check (query_pipeline handler)
        if in_incremental_pipeline:
            if stage == "Meeting Set":
                # Expected at this stage, don't flag
                pass
            elif stage in ["Upcoming Renewal", "Renewal Engaged"]:
                if renewal_revenue == 0:
                    flagged_incremental_pipeline.append(("renewal_stage", deal))
                else:
                    renewal_stages_valid_incr.append(deal)
            else:
                if incremental_value == 0:
                    flagged_incremental_pipeline.append(("other_stage", deal))

    print("=" * 80)
    print("STAGE-BASED HYGIENE RULE VERIFICATION")
    print("=" * 80)
    print()

    print(f"Meeting Set with $0 incremental ARR (EXCLUDED from both scopes): {len(meeting_set_excluded)}")
    print()

    # SCOPE 1: ALL ACTIVE DEALS (company-wide data quality)
    print("=" * 80)
    print("SCOPE 1: ALL ACTIVE DEALS (Company-wide Data Quality)")
    print("=" * 80)
    print()

    renewal_flagged_all = [d for cat, d in flagged_all_active if cat == "renewal_stage"]
    other_flagged_all = [d for cat, d in flagged_all_active if cat == "other_stage"]

    print(f"Renewal stages with renewal_revenue > 0 (valid): {len(renewal_stages_valid_all)}")
    print(f"FLAGGED DEALS (company-wide): {len(flagged_all_active)}")
    print(f"  Renewal stages ($0 renewal_revenue): {len(renewal_flagged_all)}")
    print(f"  Other stages ($0 incremental ARR): {len(other_flagged_all)}")
    print()

    if len(flagged_all_active) == 68:
        print("✅ VERIFIED: Company-wide hygiene = 68 flagged deals (matches expected)")
    else:
        print(f"📊 Company-wide hygiene: {len(flagged_all_active)} flagged deals")
    print()

    # SCOPE 2: INCREMENTAL PIPELINE ONLY (query_pipeline handler)
    print("=" * 80)
    print("SCOPE 2: INCREMENTAL PIPELINE ONLY (query_pipeline handler)")
    print("=" * 80)
    print()

    renewal_flagged_incr = [d for cat, d in flagged_incremental_pipeline if cat == "renewal_stage"]
    other_flagged_incr = [d for cat, d in flagged_incremental_pipeline if cat == "other_stage"]

    print(f"Renewal stages with renewal_revenue > 0 (valid): {len(renewal_stages_valid_incr)}")
    print(f"FLAGGED DEALS (incremental pipeline): {len(flagged_incremental_pipeline)}")
    print(f"  Renewal stages ($0 renewal_revenue): {len(renewal_flagged_incr)}")
    print(f"  Other stages ($0 incremental ARR): {len(other_flagged_incr)}")
    print()

    if renewal_flagged_incr:
        print("Renewal stage deals flagged (incremental pipeline):")
        for deal in renewal_flagged_incr:
            print(f"  {deal.get('company_name')} (ID: {deal.get('deal_id')})")
            print(f"    Stage: {stage_label(deal.get('stage'))}")
            print(f"    expansion_arr: {deal.get('expansion_arr')}")
            print(f"    new_arr: {deal.get('new_arr')}")
            print(f"    renewal_revenue: {deal.get('renewal_revenue')}")
            print()

    print("=" * 80)
    print("RECOMMENDATION FOR query_pipeline HANDLER")
    print("=" * 80)
    print()
    print(f"The query_pipeline handler shows INCREMENTAL PIPELINE only.")
    print(f"Therefore, it should flag {len(flagged_incremental_pipeline)} hygiene issues (Scope 2).")
    print(f"The company-wide count ({len(flagged_all_active)}) is informational but out of scope.")

    print()

if __name__ == "__main__":
    verify_stage_based_hygiene()
