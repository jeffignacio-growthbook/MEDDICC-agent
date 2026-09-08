#!/usr/bin/env python3
"""
Direct verification of the 2 renewal stage deals flagged as hygiene issues.
Confirms renewal_revenue is genuinely $0/NULL, not a data-pull error.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import stage_label

def verify_renewal_flags():
    sb = get_supabase()

    # Pull the two specific deals
    deal_ids = ["62929860909", "63434182718"]  # Neon, Funding Pips

    for deal_id in deal_ids:
        deal = sb.table("deals").select(
            "deal_id,company_name,stage,expansion_arr,new_arr,renewal_revenue,deal_value,owner_email,close_date"
        ).eq("deal_id", deal_id).execute()

        if deal.data:
            d = deal.data[0]
            print("=" * 80)
            print(f"DEAL: {d.get('company_name')} (ID: {deal_id})")
            print("=" * 80)
            print(f"Stage: {stage_label(d.get('stage'))}")
            print(f"Owner: {d.get('owner_email')}")
            print(f"Close Date: {d.get('close_date')}")
            print()
            print("ARR Fields (raw from database):")
            print(f"  expansion_arr: {repr(d.get('expansion_arr'))}")
            print(f"  new_arr: {repr(d.get('new_arr'))}")
            print(f"  renewal_revenue: {repr(d.get('renewal_revenue'))}")
            print(f"  deal_value: {repr(d.get('deal_value'))}")
            print()

            expansion_arr = d.get("expansion_arr") or 0
            new_arr = d.get("new_arr") or 0
            renewal_revenue = d.get("renewal_revenue") or 0

            print("Calculated values:")
            print(f"  incremental_value = expansion_arr + new_arr = {expansion_arr + new_arr}")
            print(f"  renewal_revenue (coalesced) = {renewal_revenue}")
            print()

            print("Hygiene check:")
            stage = stage_label(d.get("stage"))
            if stage in ["Upcoming Renewal", "Renewal Engaged"]:
                if renewal_revenue == 0:
                    print(f"  ❌ FLAGGED: Renewal stage with $0 renewal_revenue")
                    print(f"     This is a genuine data quality gap (renewal base not recorded)")
                else:
                    print(f"  ✅ VALID: Renewal stage with renewal_revenue = ${renewal_revenue:,.0f}")
            print()

if __name__ == "__main__":
    verify_renewal_flags()
