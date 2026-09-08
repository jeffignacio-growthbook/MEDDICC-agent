#!/usr/bin/env python3
"""
DERIVE SIGNAL 3 THRESHOLDS: Call Gap Won vs Lost Analysis

Signal 3 (call gap) threshold must be DERIVED, not hand-picked.

Methodology (matching Signal 2 rigor):
1. For all historical CLOSED deals with call data
2. Calculate gap between consecutive calls (or last call to close_date)
3. Segment by STAGE x SEGMENT (Enterprise/Mid-Market/SMB)
4. Compare won vs lost distributions per cell
5. Set threshold at SEPARATION point (NOT just lost median - that's the pandora defect)
6. Apply min_sample_size per cell (>=5 from Signal 2)
7. Fall back to broader cut if insufficient sample

Key principle (from pandora-starter-kit):
- Use gap/separation between won and lost distributions
- NOT just lost median alone (flags deal only once it looks exactly like loss)
- Find where distributions diverge (e.g., lost 25th percentile vs won median)
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import statistics

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won, stage_bucket

# Minimum sample size per stage x segment cell (from Signal 2)
MIN_SAMPLE_PER_CELL = 5

def parse_date(date_str):
    """Parse ISO date string to datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except:
        return None

def compute_call_gaps(deal, calls):
    """
    Compute gaps between consecutive calls for a deal.

    Returns list of gaps in days:
    - Gaps between consecutive calls
    - Gap from last call to close_date
    """
    if not calls or len(calls) == 0:
        return []

    # Sort calls by date
    sorted_calls = sorted(calls, key=lambda c: c.get("call_date") or "")

    gaps = []

    # Gaps between consecutive calls
    for i in range(1, len(sorted_calls)):
        prev_ts = parse_date(sorted_calls[i-1].get("call_date"))
        curr_ts = parse_date(sorted_calls[i].get("call_date"))

        if prev_ts and curr_ts:
            gap_days = (curr_ts - prev_ts).days
            if gap_days >= 0:  # Valid gap
                gaps.append(gap_days)

    # Gap from last call to close_date
    last_call_ts = parse_date(sorted_calls[-1].get("call_date"))
    close_date = parse_date(deal.get("close_date"))

    if last_call_ts and close_date:
        final_gap = (close_date - last_call_ts).days
        if final_gap >= 0:  # Valid gap
            gaps.append(final_gap)

    return gaps

def derive_thresholds():
    """Derive Signal 3 thresholds per stage x segment cell."""
    sb = get_supabase()

    print("=" * 80)
    print("SIGNAL 3 THRESHOLD DERIVATION: Call Gap Won vs Lost")
    print("=" * 80)
    print()

    # Fetch closed deals with segment
    deals = sb.table("deals").select(
        "deal_id,company_name,stage,deal_status,close_date,segment"
    ).eq("deal_status", "lost").execute().data + \
    sb.table("deals").select(
        "deal_id,company_name,stage,deal_status,close_date,segment"
    ).execute().data

    # Filter to closed deals only
    closed_deals = [
        d for d in deals
        if d.get("deal_status") in ["won", "lost"] or is_won(d.get("stage"))
    ]

    print(f"Total closed deals: {len(closed_deals)}")

    # Determine won/lost status
    for deal in closed_deals:
        if is_won(deal.get("stage")):
            deal["outcome"] = "won"
        elif deal.get("deal_status") == "lost":
            deal["outcome"] = "lost"
        else:
            deal["outcome"] = "unknown"

    # Filter to won/lost only
    closed_deals = [d for d in closed_deals if d.get("outcome") in ["won", "lost"]]

    print(f"Closed deals (won/lost): {len(closed_deals)}")
    print(f"  Won: {len([d for d in closed_deals if d['outcome'] == 'won'])}")
    print(f"  Lost: {len([d for d in closed_deals if d['outcome'] == 'lost'])}")
    print()

    # Fetch call data for these deals
    deal_ids = [d["deal_id"] for d in closed_deals]

    # Fetch in batches (Supabase has query size limits)
    batch_size = 100
    all_calls = []

    for i in range(0, len(deal_ids), batch_size):
        batch = deal_ids[i:i+batch_size]
        calls_batch = sb.table("calls").select(
            "deal_id,call_date"
        ).in_("deal_id", batch).execute()
        all_calls.extend(calls_batch.data)

    print(f"Total calls fetched: {len(all_calls)}")
    print()

    # Group calls by deal_id
    calls_by_deal = defaultdict(list)
    for call in all_calls:
        calls_by_deal[call["deal_id"]].append(call)

    deals_with_calls = [d for d in closed_deals if d["deal_id"] in calls_by_deal]

    print(f"Closed deals with call data: {len(deals_with_calls)} of {len(closed_deals)} ({100*len(deals_with_calls)/len(closed_deals):.1f}%)")
    print()

    # ========================================================================
    # COMPUTE CALL GAPS PER STAGE x SEGMENT
    # ========================================================================
    print("=" * 80)
    print("COMPUTING CALL GAPS PER STAGE x SEGMENT")
    print("=" * 80)
    print()

    # Group by stage x segment x outcome
    gaps_by_cell = defaultdict(lambda: {"won": [], "lost": []})

    for deal in deals_with_calls:
        stage = deal.get("stage")
        segment = deal.get("segment") or "Unknown"
        outcome = deal["outcome"]

        # Get stage bucket
        bucket = stage_bucket(stage)

        # Compute call gaps
        calls = calls_by_deal[deal["deal_id"]]
        gaps = compute_call_gaps(deal, calls)

        if gaps:
            cell_key = (bucket, segment)
            gaps_by_cell[cell_key][outcome].extend(gaps)

    # Report sample sizes
    print("Sample sizes per stage x segment cell:")
    print()
    print(f"{'Stage':<20} {'Segment':<15} {'Won Gaps':<10} {'Lost Gaps':<10} {'Status':<20}")
    print("-" * 80)

    for (bucket, segment), data in sorted(gaps_by_cell.items()):
        won_count = len(data["won"])
        lost_count = len(data["lost"])

        if won_count >= MIN_SAMPLE_PER_CELL and lost_count >= MIN_SAMPLE_PER_CELL:
            status = "✅ Sufficient"
        elif won_count > 0 and lost_count > 0:
            status = "⚠️  Small sample"
        else:
            status = "❌ Insufficient"

        print(f"{bucket:<20} {segment:<15} {won_count:<10} {lost_count:<10} {status:<20}")

    print()

    # ========================================================================
    # DERIVE THRESHOLDS (Won vs Lost Separation)
    # ========================================================================
    print("=" * 80)
    print("DERIVED THRESHOLDS (Won vs Lost Separation)")
    print("=" * 80)
    print()

    thresholds = {}

    print(f"{'Stage':<20} {'Segment':<15} {'Won Med':<10} {'Lost P25':<10} {'Lost Med':<10} {'Threshold':<10} {'Method':<20}")
    print("-" * 110)

    for (bucket, segment), data in sorted(gaps_by_cell.items()):
        won_gaps = data["won"]
        lost_gaps = data["lost"]

        if not won_gaps or not lost_gaps:
            continue

        # Compute distributions
        won_median = statistics.median(won_gaps)
        lost_median = statistics.median(lost_gaps)

        # Lost percentiles
        lost_sorted = sorted(lost_gaps)
        lost_p25 = statistics.quantiles(lost_sorted, n=4)[0] if len(lost_sorted) >= 4 else lost_sorted[0]
        lost_p50 = lost_median
        lost_p75 = statistics.quantiles(lost_sorted, n=4)[2] if len(lost_sorted) >= 4 else lost_sorted[-1]

        # DERIVE THRESHOLD at separation point
        # Method: Use point between won median and lost p25
        # This catches deals once they start to look like losses (not after they fully match)

        if won_median < lost_p25:
            # Clear separation - use midpoint
            threshold = (won_median + lost_p25) / 2
            method = "Midpoint won-lost"
        else:
            # Distributions overlap - use lost p25 (conservative)
            threshold = lost_p25
            method = "Lost P25 (overlap)"

        # Round to nearest day
        threshold = round(threshold)

        # Check sample size
        if len(won_gaps) >= MIN_SAMPLE_PER_CELL and len(lost_gaps) >= MIN_SAMPLE_PER_CELL:
            thresholds[(bucket, segment)] = {
                "threshold_days": threshold,
                "won_median": round(won_median, 1),
                "lost_p25": round(lost_p25, 1),
                "lost_median": round(lost_median, 1),
                "lost_p75": round(lost_p75, 1),
                "won_sample": len(won_gaps),
                "lost_sample": len(lost_gaps),
                "method": method,
                "status": "derived"
            }

            print(f"{bucket:<20} {segment:<15} {won_median:<10.1f} {lost_p25:<10.1f} {lost_median:<10.1f} {threshold:<10} {method:<20}")
        else:
            print(f"{bucket:<20} {segment:<15} {won_median:<10.1f} {lost_p25:<10.1f} {lost_median:<10.1f} {'N/A':<10} {'Insufficient sample':<20}")

    print()

    # ========================================================================
    # FALLBACK STRATEGY (Coarser cuts for insufficient samples)
    # ========================================================================
    print("=" * 80)
    print("FALLBACK STRATEGY (Stage-Only, No Segment)")
    print("=" * 80)
    print()

    # Group by stage only (drop segment)
    gaps_by_stage = defaultdict(lambda: {"won": [], "lost": []})

    for (bucket, segment), data in gaps_by_cell.items():
        gaps_by_stage[bucket]["won"].extend(data["won"])
        gaps_by_stage[bucket]["lost"].extend(data["lost"])

    print(f"{'Stage':<20} {'Won Gaps':<10} {'Lost Gaps':<10} {'Won Med':<10} {'Lost P25':<10} {'Threshold':<10} {'Method':<20}")
    print("-" * 100)

    fallback_thresholds = {}

    for bucket, data in sorted(gaps_by_stage.items()):
        won_gaps = data["won"]
        lost_gaps = data["lost"]

        if not won_gaps or not lost_gaps:
            continue

        won_median = statistics.median(won_gaps)
        lost_sorted = sorted(lost_gaps)
        lost_p25 = statistics.quantiles(lost_sorted, n=4)[0] if len(lost_sorted) >= 4 else lost_sorted[0]
        lost_median = statistics.median(lost_gaps)

        if won_median < lost_p25:
            threshold = round((won_median + lost_p25) / 2)
            method = "Midpoint won-lost"
        else:
            threshold = round(lost_p25)
            method = "Lost P25 (overlap)"

        if len(won_gaps) >= MIN_SAMPLE_PER_CELL and len(lost_gaps) >= MIN_SAMPLE_PER_CELL:
            fallback_thresholds[bucket] = {
                "threshold_days": threshold,
                "won_median": round(won_median, 1),
                "lost_p25": round(lost_p25, 1),
                "lost_median": round(lost_median, 1),
                "won_sample": len(won_gaps),
                "lost_sample": len(lost_gaps),
                "method": method,
                "status": "fallback_stage_only"
            }

            print(f"{bucket:<20} {len(won_gaps):<10} {len(lost_gaps):<10} {won_median:<10.1f} {lost_p25:<10.1f} {threshold:<10} {method:<20}")
        else:
            print(f"{bucket:<20} {len(won_gaps):<10} {len(lost_gaps):<10} {won_median:<10.1f} {lost_p25:<10.1f} {'N/A':<10} {'Insufficient sample':<20}")

    print()

    # ========================================================================
    # COVERAGE ANALYSIS
    # ========================================================================
    print("=" * 80)
    print("COVERAGE ANALYSIS")
    print("=" * 80)
    print()

    # Count how many stage x segment cells have derived thresholds
    total_cells = len(gaps_by_cell)
    cells_with_threshold = len(thresholds)

    print(f"Total stage x segment cells: {total_cells}")
    print(f"Cells with derived threshold: {cells_with_threshold} ({100*cells_with_threshold/total_cells:.1f}%)")
    print()

    # Check which cells need fallback
    cells_needing_fallback = []
    for (bucket, segment), data in gaps_by_cell.items():
        if (bucket, segment) not in thresholds:
            cells_needing_fallback.append((bucket, segment))

    if cells_needing_fallback:
        print(f"Cells needing fallback (insufficient sample for segment-specific):")
        for bucket, segment in cells_needing_fallback:
            print(f"  {bucket} x {segment}")
        print()

    # Overall coverage
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
    print("1. Use segment-specific threshold where available (derived from stage x segment)")
    print("2. Fall back to stage-only threshold if segment-specific insufficient")
    print("3. Document DEFERRED for cells with no threshold (like Signal 1)")
    print()

    print("DERIVED THRESHOLDS SUMMARY:")
    print(f"  Segment-specific: {len(thresholds)} cells")
    print(f"  Stage-only fallback: {len(fallback_thresholds)} stages")
    print()

    if len(thresholds) == 0 and len(fallback_thresholds) == 0:
        print("⚠️  WARNING: No thresholds could be derived due to insufficient data")
        print("   RECOMMENDATION: DEFER Signal 3 until more call data available")
        print("   (Same treatment as Signal 1 - explicit gap documentation)")

    print()

    return {
        "segment_specific": thresholds,
        "stage_only_fallback": fallback_thresholds,
        "coverage": {
            "total_cells": total_cells,
            "cells_with_threshold": cells_with_threshold,
            "deals_with_calls": len(deals_with_calls),
            "total_closed_deals": len(closed_deals)
        }
    }

if __name__ == "__main__":
    result = derive_thresholds()

    # Export to JSON for use in handler
    import json
    output_file = Path(__file__).parent.parent / "signal3_derived_thresholds.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Thresholds exported to: {output_file}")
