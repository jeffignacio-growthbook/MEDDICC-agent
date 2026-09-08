#!/usr/bin/env python3
"""
INVESTIGATION 2: Check pipeline_id classification across ALL deals.

Confirm:
1. Only 2 pipelines exist (default + renewal) or find third/legacy
2. pipeline_id "866608541" for renewals is consistent historically
3. Old deals don't use different scheme
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import Counter, defaultdict

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

def investigate_pipelines():
    sb = get_supabase()

    print("=" * 80)
    print("INVESTIGATION 2: PIPELINE_ID CLASSIFICATION")
    print("=" * 80)
    print()

    # Fetch ALL deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline,pipeline_id,deal_status,stage,create_date,close_date"
    ).execute()

    print(f"Total deals in database: {len(all_deals.data)}")
    print()

    # ========================================================================
    # CHECK 1: DISTINCT pipeline_id values
    # ========================================================================
    print("=" * 80)
    print("CHECK 1: DISTINCT PIPELINE_ID VALUES")
    print("=" * 80)
    print()

    pipeline_id_counts = Counter(d.get("pipeline_id") for d in all_deals.data)

    print("All distinct pipeline_id values:")
    for pid, count in sorted(pipeline_id_counts.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(all_deals.data)
        print(f"  '{pid}': {count} deals ({pct:.1f}%)")

    print()

    if len(pipeline_id_counts) > 2:
        print(f"⚠️  MORE THAN 2 PIPELINE_IDs: Found {len(pipeline_id_counts)}")
        print("   Need to understand what each represents")
    else:
        print(f"✓ Only 2 pipeline_ids found (expected)")

    print()

    # ========================================================================
    # CHECK 2: Pipeline names (if available)
    # ========================================================================
    print("=" * 80)
    print("CHECK 2: PIPELINE NAMES (HUMAN-READABLE)")
    print("=" * 80)
    print()

    # Check pipeline (name) field
    pipeline_name_counts = Counter(d.get("pipeline") for d in all_deals.data)

    print("Pipeline names:")
    for name, count in sorted(pipeline_name_counts.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(all_deals.data)
        print(f"  '{name}': {count} deals ({pct:.1f}%)")

    print()

    # Map pipeline_id to pipeline name
    print("Mapping pipeline_id → pipeline name:")
    pid_to_name = {}
    for deal in all_deals.data:
        pid = deal.get("pipeline_id")
        name = deal.get("pipeline")
        if pid and name:
            if pid not in pid_to_name:
                pid_to_name[pid] = name
            elif pid_to_name[pid] != name:
                print(f"  ⚠️  Inconsistent: pipeline_id '{pid}' maps to both '{pid_to_name[pid]}' and '{name}'")

    for pid, name in pid_to_name.items():
        print(f"  '{pid}' → '{name}'")

    print()

    # ========================================================================
    # CHECK 3: Historical consistency (pipeline_id over time)
    # ========================================================================
    print("=" * 80)
    print("CHECK 3: HISTORICAL CONSISTENCY")
    print("=" * 80)
    print()

    # Parse create dates and group by year
    by_year = defaultdict(lambda: Counter())

    for deal in all_deals.data:
        create_date_str = deal.get("create_date")
        pid = deal.get("pipeline_id")

        if create_date_str:
            try:
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
                year = create_date.year
                by_year[year][pid] += 1
            except:
                pass

    print("Pipeline_id distribution by year (based on create_date):")
    for year in sorted(by_year.keys()):
        print(f"  {year}:")
        year_total = sum(by_year[year].values())
        for pid, count in sorted(by_year[year].items(), key=lambda x: -x[1]):
            pct = 100 * count / year_total if year_total > 0 else 0
            print(f"    '{pid}': {count} ({pct:.1f}%)")

    print()

    # Check if there was a scheme change
    print("Checking for scheme changes:")
    pids_by_year = {year: set(by_year[year].keys()) for year in by_year.keys()}

    scheme_changes = []
    years = sorted(pids_by_year.keys())
    for i in range(1, len(years)):
        prev_year = years[i-1]
        curr_year = years[i]

        new_pids = pids_by_year[curr_year] - pids_by_year[prev_year]
        removed_pids = pids_by_year[prev_year] - pids_by_year[curr_year]

        if new_pids or removed_pids:
            scheme_changes.append({
                "year": curr_year,
                "new": new_pids,
                "removed": removed_pids
            })

    if scheme_changes:
        print("⚠️  SCHEME CHANGES DETECTED:")
        for change in scheme_changes:
            print(f"  {change['year']}:")
            if change['new']:
                print(f"    New pipeline_ids: {change['new']}")
            if change['removed']:
                print(f"    Removed pipeline_ids: {change['removed']}")
    else:
        print("✓ No scheme changes detected - consistent over time")

    print()

    # ========================================================================
    # CHECK 4: Won deals by pipeline_id over time
    # ========================================================================
    print("=" * 80)
    print("CHECK 4: WON DEALS BY PIPELINE_ID")
    print("=" * 80)
    print()

    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]

    won_by_pid = Counter(d.get("pipeline_id") for d in won_deals)

    print(f"Won deals by pipeline_id (n={len(won_deals)}):")
    for pid, count in sorted(won_by_pid.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(won_deals)
        name = pid_to_name.get(pid, "unknown")
        print(f"  '{pid}' ({name}): {count} ({pct:.1f}%)")

    print()

    # ========================================================================
    # CHECK 5: Lost deals by pipeline_id
    # ========================================================================
    print("=" * 80)
    print("CHECK 5: LOST DEALS BY PIPELINE_ID")
    print("=" * 80)
    print()

    lost_deals = [d for d in all_deals.data if d.get("deal_status") == "lost"]

    lost_by_pid = Counter(d.get("pipeline_id") for d in lost_deals)

    print(f"Lost deals by pipeline_id (n={len(lost_deals)}):")
    for pid, count in sorted(lost_by_pid.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(lost_deals)
        name = pid_to_name.get(pid, "unknown")
        print(f"  '{pid}' ({name}): {count} ({pct:.1f}%)")

    print()

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("=" * 80)
    print("INVESTIGATION 2 SUMMARY")
    print("=" * 80)
    print()

    print(f"Distinct pipeline_ids: {len(pipeline_id_counts)}")
    for pid, count in sorted(pipeline_id_counts.items(), key=lambda x: -x[1]):
        name = pid_to_name.get(pid, "unknown")
        print(f"  '{pid}' ({name}): {count} deals")

    print()

    if len(pipeline_id_counts) == 2:
        print("✓ Clean 2-pipeline structure (default + renewal)")
    else:
        print(f"⚠️  {len(pipeline_id_counts)} pipelines - need to classify each")

    if scheme_changes:
        print("⚠️  Historical scheme changes detected - old deals may be miscategorized")
    else:
        print("✓ No scheme changes - consistent classification")

    print()

    # Calculate win rates by pipeline
    print("Win rates by pipeline_id:")
    for pid in pipeline_id_counts.keys():
        won_count = won_by_pid.get(pid, 0)
        lost_count = lost_by_pid.get(pid, 0)
        closed = won_count + lost_count

        if closed > 0:
            win_rate = 100 * won_count / closed
            name = pid_to_name.get(pid, "unknown")
            print(f"  '{pid}' ({name}): {win_rate:.1f}% ({won_count}/{closed})")

if __name__ == "__main__":
    investigate_pipelines()
