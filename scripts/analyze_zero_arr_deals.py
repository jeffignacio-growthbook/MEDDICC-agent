#!/usr/bin/env python3
"""
Analyze the 126 deals with $0 incremental ARR.

These are deals in pipeline but with expansion_arr=0/NULL AND new_arr=0/NULL.
Check if they're real deals with missing classification or placeholder records.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import csv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_incremental_pipeline, stage_label

def analyze_zero_arr_deals():
    sb = get_supabase()

    # Get all active deals
    deals = sb.table("deals").select(
        "deal_id,company_name,deal_value,stage,owner_email,close_date,create_date,pipeline_id,expansion_arr,new_arr,renewal_revenue"
    ).eq("deal_status", "active").execute()

    # Filter to incremental pipeline deals with $0 incremental ARR
    zero_arr_deals = []
    for deal in deals.data:
        if is_incremental_pipeline(deal):
            expansion_arr = deal.get("expansion_arr") or 0
            new_arr = deal.get("new_arr") or 0
            incremental_value = expansion_arr + new_arr

            if incremental_value == 0:
                zero_arr_deals.append(deal)

    print("=" * 80)
    print(f"ZERO-ARR DEALS ANALYSIS")
    print("=" * 80)
    print(f"Total deals with $0 incremental ARR: {len(zero_arr_deals)}")
    print()

    # 1. PIVOT SUMMARY by stage
    print("=" * 80)
    print("1. PIVOT SUMMARY - BY STAGE")
    print("=" * 80)
    print()

    from collections import defaultdict
    stage_stats = defaultdict(lambda: {"count": 0, "total_value": 0, "deals": []})

    for deal in zero_arr_deals:
        stage = stage_label(deal.get("stage"))
        deal_value = deal.get("deal_value") or 0

        stage_stats[stage]["count"] += 1
        stage_stats[stage]["total_value"] += deal_value
        stage_stats[stage]["deals"].append(deal)

    # Sort by count descending
    sorted_stages = sorted(stage_stats.items(), key=lambda x: x[1]["count"], reverse=True)

    print(f"{'Stage':<30} | {'Count':>6} | {'Total deal_value':>18} | {'Avg deal_value':>15}")
    print("-" * 80)

    for stage, stats in sorted_stages:
        avg_value = stats["total_value"] / stats["count"] if stats["count"] > 0 else 0
        print(f"{stage:<30} | {stats['count']:>6} | ${stats['total_value']:>17,.0f} | ${avg_value:>14,.0f}")

    print()

    # 2. Check deal_value > 0 vs deal_value = 0
    print("=" * 80)
    print("2. DEAL_VALUE DISTRIBUTION")
    print("=" * 80)
    print()

    has_value = [d for d in zero_arr_deals if (d.get("deal_value") or 0) > 0]
    no_value = [d for d in zero_arr_deals if (d.get("deal_value") or 0) == 0]

    total_value_with_value = sum(d.get("deal_value") or 0 for d in has_value)

    print(f"Deals with deal_value > 0: {len(has_value)} deals (${total_value_with_value:,.0f} total)")
    print(f"Deals with deal_value = 0: {len(no_value)} deals")
    print()
    print("Interpretation:")
    if len(has_value) > len(no_value):
        print("  → Majority have deal_value > 0 - these are REAL deals with missing ARR classification")
    else:
        print("  → Majority have deal_value = 0 - likely placeholder/test records")
    print()

    # 3. Owner distribution
    print("=" * 80)
    print("4. OWNER DISTRIBUTION")
    print("=" * 80)
    print()

    owner_counts = defaultdict(int)
    for deal in zero_arr_deals:
        owner = deal.get("owner_email") or "unassigned"
        owner_counts[owner] += 1

    sorted_owners = sorted(owner_counts.items(), key=lambda x: x[1], reverse=True)

    print(f"{'Owner':<40} | {'Count':>6} | {'% of 126':>8}")
    print("-" * 60)

    for owner, count in sorted_owners[:10]:
        pct = (count / len(zero_arr_deals)) * 100
        print(f"{owner:<40} | {count:>6} | {pct:>7.1f}%")

    if len(sorted_owners) > 10:
        others_count = sum(c for _, c in sorted_owners[10:])
        others_pct = (others_count / len(zero_arr_deals)) * 100
        print(f"{'... others':<40} | {others_count:>6} | {others_pct:>7.1f}%")

    print()
    print("Interpretation:")
    top_owner_count = sorted_owners[0][1] if sorted_owners else 0
    top_owner_pct = (top_owner_count / len(zero_arr_deals)) * 100 if zero_arr_deals else 0

    if top_owner_pct > 50:
        print(f"  → Concentrated: {sorted_owners[0][0]} owns {top_owner_pct:.1f}% - specific person's habit")
    elif top_owner_pct > 30:
        print(f"  → Moderately concentrated: Top owner has {top_owner_pct:.1f}% - worth direct conversation")
    else:
        print(f"  → Broadly spread: Top owner has {top_owner_pct:.1f}% - systemic data-entry gap")
    print()

    # 3. Export full deal list to CSV
    print("=" * 80)
    print("3. FULL DEAL LIST - CSV EXPORT")
    print("=" * 80)
    print()

    output_file = Path(__file__).parent.parent / "zero_arr_deals_analysis.csv"

    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "Stage", "deal_id", "company_name", "deal_value",
            "owner_email", "close_date", "create_date",
            "expansion_arr", "new_arr", "renewal_revenue"
        ])

        # Sort by stage, then deal_value descending within stage
        for stage, stats in sorted_stages:
            stage_deals = sorted(
                stats["deals"],
                key=lambda d: d.get("deal_value") or 0,
                reverse=True
            )

            for deal in stage_deals:
                writer.writerow([
                    stage,
                    deal.get("deal_id"),
                    deal.get("company_name"),
                    deal.get("deal_value") or 0,
                    deal.get("owner_email") or "",
                    deal.get("close_date") or "",
                    deal.get("create_date") or "",
                    deal.get("expansion_arr"),
                    deal.get("new_arr"),
                    deal.get("renewal_revenue")
                ])

    print(f"✅ Full deal list exported to: {output_file}")
    print(f"   {len(zero_arr_deals)} deals grouped by stage, sorted by deal_value descending")
    print()

if __name__ == "__main__":
    analyze_zero_arr_deals()
