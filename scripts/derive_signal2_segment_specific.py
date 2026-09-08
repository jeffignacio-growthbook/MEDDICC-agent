#!/usr/bin/env python3
"""
DERIVE SIGNAL 2 THRESHOLDS: Segment-Specific Time-in-Stage

Signal 2 (time-in-stage) must be computed WITHIN each segment's own distribution,
not one global percentile across all segments.

Rationale:
- Enterprise deals naturally sit in stages longer than SMB deals
- A single global percentile would systematically:
  - Over-flag SMB (their normal duration < global 75th percentile)
  - Under-flag Enterprise (their normal duration > global 75th percentile)

Methodology:
1. For each STAGE x SEGMENT cell, compute 75th percentile of stage duration
2. Use historical WON deals only (success pattern, not failures)
3. Apply min_sample_size per cell (>=5 from Signal 2 config)
4. Fall back to stage-only (drop segment) if insufficient sample

This matches the rigor already applied to Signal 2 in original implementation.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import defaultdict
import statistics

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won, stage_bucket

# Minimum sample size per stage x segment cell
MIN_SAMPLE_PER_CELL = 5

def parse_date(date_str):
    """Parse ISO date string to datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except:
        return None

def derive_segment_specific_thresholds():
    """Derive Signal 2 (time-in-stage) thresholds per stage x segment cell."""
    sb = get_supabase()

    print("=" * 80)
    print("SIGNAL 2 SEGMENT-SPECIFIC THRESHOLD DERIVATION")
    print("=" * 80)
    print()

    # Fetch WON deals with segment and stage history
    won_deals = sb.table("deals").select(
        "deal_id,company_name,stage,segment,close_date"
    ).execute().data

    # Filter to won deals only
    won_deals = [d for d in won_deals if is_won(d.get("stage"))]

    print(f"Total won deals: {len(won_deals)}")
    print()

    # Fetch stage history for won deals
    deal_ids = [d["deal_id"] for d in won_deals]

    batch_size = 100
    all_stage_updates = []

    for i in range(0, len(deal_ids), batch_size):
        batch = deal_ids[i:i+batch_size]
        updates_batch = sb.table("stage_updates").select(
            "deal_id,old_stage,new_stage,updated_at"
        ).in_("deal_id", batch).order("updated_at", desc=False).execute()
        all_stage_updates.extend(updates_batch.data)

    print(f"Total stage updates fetched: {len(all_stage_updates)}")
    print()

    # Group stage updates by deal
    updates_by_deal = defaultdict(list)
    for update in all_stage_updates:
        updates_by_deal[update["deal_id"]].append(update)

    # ========================================================================
    # COMPUTE STAGE DURATIONS PER SEGMENT
    # ========================================================================
    print("=" * 80)
    print("COMPUTING STAGE DURATIONS PER SEGMENT")
    print("=" * 80)
    print()

    # Collect stage durations per stage x segment cell
    durations_by_cell = defaultdict(list)

    for deal in won_deals:
        deal_id = deal["deal_id"]
        segment = deal.get("segment") or "Unknown"
        close_date = parse_date(deal.get("close_date"))

        if deal_id not in updates_by_deal:
            continue  # No stage history

        stage_updates = updates_by_deal[deal_id]

        # Compute duration in each stage
        for i in range(len(stage_updates)):
            old_stage = stage_updates[i].get("old_stage")
            new_stage = stage_updates[i].get("new_stage")
            enter_time = parse_date(stage_updates[i].get("updated_at"))

            if not enter_time:
                continue

            # Determine exit time (next stage update or close_date)
            if i + 1 < len(stage_updates):
                exit_time = parse_date(stage_updates[i+1].get("updated_at"))
            else:
                exit_time = close_date  # Last stage until close

            if not exit_time:
                continue

            # Compute duration in days
            duration_days = (exit_time - enter_time).days

            if duration_days < 0:
                continue  # Invalid data

            # Get stage bucket for new_stage
            bucket = stage_bucket(new_stage)

            if bucket in ["closed_won", "closed_lost", "unknown"]:
                continue  # Skip terminal stages

            # Add to cell
            cell_key = (bucket, segment)
            durations_by_cell[cell_key].append(duration_days)

    # ========================================================================
    # DERIVE THRESHOLDS (75th Percentile per Segment)
    # ========================================================================
    print("Sample sizes per stage x segment cell:")
    print()
    print(f"{'Stage':<20} {'Segment':<15} {'Sample Size':<12} {'Status':<20}")
    print("-" * 70)

    for (bucket, segment), durations in sorted(durations_by_cell.items()):
        sample_size = len(durations)

        if sample_size >= MIN_SAMPLE_PER_CELL:
            status = "✅ Sufficient"
        elif sample_size > 0:
            status = "⚠️  Small sample"
        else:
            status = "❌ Insufficient"

        print(f"{bucket:<20} {segment:<15} {sample_size:<12} {status:<20}")

    print()

    # Compute 75th percentiles
    print("=" * 80)
    print("DERIVED THRESHOLDS (75th Percentile per Segment)")
    print("=" * 80)
    print()

    thresholds = {}

    print(f"{'Stage':<20} {'Segment':<15} {'Median':<10} {'P75':<10} {'Sample':<10} {'Status':<15}")
    print("-" * 85)

    for (bucket, segment), durations in sorted(durations_by_cell.items()):
        if len(durations) < MIN_SAMPLE_PER_CELL:
            continue  # Insufficient sample

        sorted_durations = sorted(durations)
        median_days = statistics.median(sorted_durations)
        p75_days = statistics.quantiles(sorted_durations, n=4)[2] if len(sorted_durations) >= 4 else sorted_durations[-1]

        thresholds[(bucket, segment)] = {
            "threshold_days": round(p75_days),
            "median_days": round(median_days, 1),
            "sample_size": len(durations),
            "status": "derived"
        }

        print(f"{bucket:<20} {segment:<15} {median_days:<10.1f} {p75_days:<10.1f} {len(durations):<10} {'Derived':<15}")

    print()

    # ========================================================================
    # FALLBACK STRATEGY (Stage-Only, No Segment)
    # ========================================================================
    print("=" * 80)
    print("FALLBACK STRATEGY (Stage-Only, No Segment)")
    print("=" * 80)
    print()

    # Group by stage only (drop segment)
    durations_by_stage = defaultdict(list)

    for (bucket, segment), durations in durations_by_cell.items():
        durations_by_stage[bucket].extend(durations)

    print(f"{'Stage':<20} {'Sample Size':<12} {'Median':<10} {'P75':<10} {'Status':<15}")
    print("-" * 70)

    fallback_thresholds = {}

    for bucket, durations in sorted(durations_by_stage.items()):
        if len(durations) < MIN_SAMPLE_PER_CELL:
            print(f"{bucket:<20} {len(durations):<12} {'N/A':<10} {'N/A':<10} {'Insufficient':<15}")
            continue

        sorted_durations = sorted(durations)
        median_days = statistics.median(sorted_durations)
        p75_days = statistics.quantiles(sorted_durations, n=4)[2] if len(sorted_durations) >= 4 else sorted_durations[-1]

        fallback_thresholds[bucket] = {
            "threshold_days": round(p75_days),
            "median_days": round(median_days, 1),
            "sample_size": len(durations),
            "status": "fallback_stage_only"
        }

        print(f"{bucket:<20} {len(durations):<12} {median_days:<10.1f} {p75_days:<10.1f} {'Fallback':<15}")

    print()

    # ========================================================================
    # COVERAGE ANALYSIS
    # ========================================================================
    print("=" * 80)
    print("COVERAGE ANALYSIS")
    print("=" * 80)
    print()

    total_cells = len(durations_by_cell)
    cells_with_threshold = len(thresholds)

    print(f"Total stage x segment cells: {total_cells}")
    print(f"Cells with derived threshold: {cells_with_threshold} ({100*cells_with_threshold/total_cells:.1f}%)")
    print()

    # Check which cells need fallback
    cells_needing_fallback = []
    for (bucket, segment), durations in durations_by_cell.items():
        if (bucket, segment) not in thresholds:
            cells_needing_fallback.append((bucket, segment))

    if cells_needing_fallback:
        print(f"Cells needing fallback (insufficient sample for segment-specific):")
        for bucket, segment in cells_needing_fallback:
            print(f"  {bucket} x {segment}")
        print()

    print(f"Stage-only fallbacks available: {len(fallback_thresholds)} stages")
    print()

    # ========================================================================
    # FINAL RECOMMENDATION
    # ========================================================================
    print("=" * 80)
    print("FINAL RECOMMENDATION")
    print("=" * 80)
    print()

    print("IMPLEMENTATION STRATEGY:")
    print()
    print("1. Use segment-specific threshold where available")
    print("2. Fall back to stage-only threshold if segment-specific insufficient")
    print("3. No global threshold - each segment has its own natural pace")
    print()

    print("DERIVED THRESHOLDS SUMMARY:")
    print(f"  Segment-specific: {len(thresholds)} cells")
    print(f"  Stage-only fallback: {len(fallback_thresholds)} stages")
    print()

    print("WHY SEGMENT-SPECIFIC MATTERS:")
    print("  Enterprise deals sit longer in stages (larger ACV, more stakeholders)")
    print("  SMB deals move faster (smaller ACV, fewer stakeholders)")
    print("  Global threshold would systematically over-flag SMB, under-flag Enterprise")
    print()

    return {
        "segment_specific": thresholds,
        "stage_only_fallback": fallback_thresholds,
        "coverage": {
            "total_cells": total_cells,
            "cells_with_threshold": cells_with_threshold,
            "won_deals": len(won_deals)
        }
    }

if __name__ == "__main__":
    result = derive_segment_specific_thresholds()

    # Export to JSON for use in handler
    import json
    output_file = Path(__file__).parent.parent / "signal2_segment_specific_thresholds.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Thresholds exported to: {output_file}")
