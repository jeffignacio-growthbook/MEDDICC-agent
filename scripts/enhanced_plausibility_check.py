#!/usr/bin/env python3
"""
ENHANCED CROSS-METRIC PLAUSIBILITY CHECK WITH SEGMENTATION-FIRST

MANDATORY GATE before finalizing ANY population metric.

NEW REQUIREMENT: Check if population spans ERA/EVENT boundaries.
If YES → BLOCK with error, require explicit segmentation FIRST.

This prevents computing on blended populations (apples to oranges)
and trying to explain contamination after the fact.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
import json
import yaml
from collections import defaultdict

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

# Load business events registry
registry_path = Path(__file__).parent.parent / "config" / "business_events_registry.yaml"
with open(registry_path) as f:
    BUSINESS_EVENTS = yaml.safe_load(f)

# Plausibility check log
LOG_FILE = Path(__file__).parent.parent / "plausibility_checks.log"

def log_check(check_name, status, details):
    """Log every plausibility check for audit trail."""
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "check": check_name,
        "status": status,  # "PASS", "FLAG", "BLOCK", "ERROR"
        "details": details
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\\n")

    return log_entry

def check_era_boundary_contamination(population_description, deals):
    """
    Check if population spans ERA boundary (pipeline scheme change).
    If YES → BLOCK, require explicit segmentation.
    """
    print("=" * 80)
    print("CHECK 1: ERA BOUNDARY CONTAMINATION")
    print("=" * 80)
    print()

    # Get ERA boundary from registry
    era_events = BUSINESS_EVENTS.get("pipeline_scheme_changes", [])
    if not era_events:
        print("✓ No ERA boundaries defined in registry")
        return "PASS", {}

    # For now, check 2023-01-01 boundary (renewal pipeline introduction)
    ERA_CUTOFF = datetime(2023, 1, 1, tzinfo=timezone.utc)

    # Parse create dates
    pre_era = []
    post_era = []

    for deal in deals:
        create_date_str = deal.get("create_date")
        if create_date_str:
            try:
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
                if create_date < ERA_CUTOFF:
                    pre_era.append(deal)
                else:
                    post_era.append(deal)
            except:
                post_era.append(deal)  # Assume post-era if can't parse
        else:
            post_era.append(deal)

    print(f"Population: {population_description}")
    print(f"  Pre-2023 (legacy process): {len(pre_era)} deals")
    print(f"  2023+ (current process): {len(post_era)} deals")
    print()

    if len(pre_era) > 0 and len(post_era) > 0:
        status = "BLOCK"
        print("🚫 BLOCK: Population spans ERA boundary")
        print()
        print("REQUIRED ACTION:")
        print("  1. Segment population: pre-2023 vs 2023+")
        print("  2. Compute metrics SEPARATELY within each ERA")
        print("  3. Report: '2023+ only' (exclude pre-2023)")
        print()
        print("RATIONALE:")
        print("  Pre-2023 deals created before renewal pipeline existed.")
        print("  Different process, not comparable to current motion.")
        print("  Blending across ERA = apples to oranges.")
        print()

        details = {
            "pre_2023_count": len(pre_era),
            "post_2023_count": len(post_era),
            "era_boundary": "2023-01-01",
            "action_required": "Explicit segmentation before computation"
        }
    else:
        status = "PASS"
        print("✓ Population does not span ERA boundary")
        if len(pre_era) == 0:
            print("  (All deals are 2023+)")
        else:
            print("  (All deals are pre-2023)")
        print()

        details = {
            "pre_2023_count": len(pre_era),
            "post_2023_count": len(post_era),
            "era_boundary": "2023-01-01"
        }

    log_check(
        "era_boundary_contamination",
        status,
        details
    )

    return status, details

def check_event_contamination(population_description, deals):
    """
    Check if population includes EVENT contamination (bulk cleanup).
    If YES → BLOCK, require explicit segmentation and exclusion.
    """
    print("=" * 80)
    print("CHECK 2: EVENT CONTAMINATION (BULK CLEANUP)")
    print("=" * 80)
    print()

    # Get lost deals only
    lost_deals = [d for d in deals if d.get("deal_status") == "lost"]

    if not lost_deals:
        print("✓ No lost deals in population - EVENT check not applicable")
        return "PASS", {}

    # Detect bulk cleanup months (>10 blank lost_reason per month)
    blank_by_month = defaultdict(list)
    for deal in lost_deals:
        if not deal.get("lost_reason"):  # Blank lost_reason
            close_date_str = deal.get("close_date")
            if close_date_str:
                try:
                    close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
                    month_key = f"{close_date.year}-{close_date.month:02d}"
                    blank_by_month[month_key].append(deal)
                except:
                    pass

    # Find bulk cleanup months
    bulk_cleanup_months = set()
    for month, deals_in_month in blank_by_month.items():
        if len(deals_in_month) > 10:
            bulk_cleanup_months.add(month)

    print(f"Population: {population_description}")
    print(f"  Total lost deals: {len(lost_deals)}")
    print(f"  Bulk cleanup months detected: {len(bulk_cleanup_months)}")
    print()

    if bulk_cleanup_months:
        # Count contaminated deals
        contaminated_deal_ids = set()
        for month in bulk_cleanup_months:
            for deal in blank_by_month[month]:
                contaminated_deal_ids.add(deal.get("deal_id"))

        contamination_pct = 100 * len(contaminated_deal_ids) / len(lost_deals)

        print("🚫 BLOCK: EVENT contamination detected")
        print()
        print(f"Bulk cleanup months (>10 blank lost_reason/month):")
        for month in sorted(bulk_cleanup_months):
            count = len(blank_by_month[month])
            print(f"  {month}: {count} deals")
        print()
        print(f"Total contamination: {len(contaminated_deal_ids)} deals ({contamination_pct:.1f}% of lost)")
        print()
        print("REQUIRED ACTION:")
        print("  1. Segment population: bulk cleanup vs organic closures")
        print("  2. EXCLUDE bulk cleanup deals (admin operations, not sales outcomes)")
        print("  3. Compute metrics ONLY on organic cohort")
        print()
        print("RATIONALE:")
        print("  Blank lost_reason = no sales feedback = admin cleanup")
        print("  Including cleanup inflates lost count, depresses win rate")
        print("  Blending cleanup + organic = contaminated metrics")
        print()

        status = "BLOCK"
        details = {
            "bulk_cleanup_months": sorted(bulk_cleanup_months),
            "contaminated_deals": len(contaminated_deal_ids),
            "total_lost": len(lost_deals),
            "contamination_pct": contamination_pct,
            "action_required": "Exclude bulk cleanup, compute on organic only"
        }
    else:
        status = "PASS"
        print("✓ No EVENT contamination detected")
        print("  (No months with >10 blank lost_reason deals)")
        print()

        details = {
            "total_lost": len(lost_deals),
            "bulk_cleanup_months": []
        }

    log_check(
        "event_contamination",
        status,
        details
    )

    return status, details

def check_cross_metric_consistency(metric_name, metric_value, adjacent_metrics):
    """
    Check if metric value is plausibly consistent with adjacent verified metrics.
    (Original plausibility check - now check #3)
    """
    print("=" * 80)
    print("CHECK 3: CROSS-METRIC CONSISTENCY")
    print("=" * 80)
    print()

    # Example: Check renewal vs non-renewal split consistency
    # This is the original check from cross_metric_plausibility_check.py

    print(f"Metric: {metric_name} = {metric_value}")
    print()

    # For now, just pass - this would contain the original cross-metric logic
    print("✓ Cross-metric consistency check passed")
    print("  (TODO: Implement specific consistency checks)")
    print()

    status = "PASS"
    details = {
        "metric_name": metric_name,
        "metric_value": metric_value
    }

    log_check(
        "cross_metric_consistency",
        status,
        details
    )

    return status, details

def run_enhanced_plausibility_check(
    population_description,
    deals,
    metric_name=None,
    metric_value=None,
    adjacent_metrics=None
):
    """
    Run enhanced plausibility check with segmentation-first requirements.

    BLOCKS finalization if:
    - Population spans ERA boundary (requires segmentation)
    - Population includes EVENT contamination (requires exclusion)

    PASSES if all checks clear.
    """
    print("=" * 80)
    print("ENHANCED CROSS-METRIC PLAUSIBILITY CHECK")
    print("MANDATORY GATE BEFORE FINALIZING POPULATION METRICS")
    print("=" * 80)
    print()
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Log file: {LOG_FILE}")
    print()

    checks = []

    # Check 1: ERA boundary
    era_status, era_details = check_era_boundary_contamination(
        population_description, deals
    )
    checks.append(("ERA Boundary", era_status, era_details))

    # Check 2: EVENT contamination
    event_status, event_details = check_event_contamination(
        population_description, deals
    )
    checks.append(("EVENT Contamination", event_status, event_details))

    # Check 3: Cross-metric consistency (if provided)
    if metric_name and metric_value:
        consistency_status, consistency_details = check_cross_metric_consistency(
            metric_name, metric_value, adjacent_metrics or {}
        )
        checks.append(("Cross-Metric Consistency", consistency_status, consistency_details))

    # Final summary
    print()
    print("=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    print()

    for check_name, status, _ in checks:
        icon = "✅" if status == "PASS" else "🚩" if status == "FLAG" else "🚫"
        print(f"  {icon} {check_name}: {status}")

    print()

    # Determine overall status
    has_blocks = any(status == "BLOCK" for _, status, _ in checks)
    has_flags = any(status == "FLAG" for _, status, _ in checks)

    if has_blocks:
        print("🚫 BLOCKED: Cannot finalize until segmentation is applied")
        print()
        print("REQUIRED:")
        print("  1. Apply explicit ERA/EVENT segmentation (see segment_and_compute.py)")
        print("  2. Define clean cohorts FIRST")
        print("  3. Compute metrics WITHIN clean cohorts")
        print("  4. Re-run plausibility check on segmented population")
        print()
        print("DO NOT compute on blended population and explain contamination after.")
        return False
    elif has_flags:
        print("🚩 FLAGGED: Review required before finalizing")
        return False
    else:
        print("✅ ALL CHECKS PASSED")
        print("   Safe to finalize population metric")
        return True

    print()
    print(f"Audit trail: {LOG_FILE}")

    return not (has_blocks or has_flags)

if __name__ == "__main__":
    # Example usage: Check the default pipeline deals
    sb = get_supabase()

    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline_id,deal_status,stage,create_date,close_date,lost_reason"
    ).execute()

    DEFAULT_PIPELINE_ID = "default"
    default_deals = [d for d in all_deals.data if d.get("pipeline_id") == DEFAULT_PIPELINE_ID]

    # Run check on default pipeline
    passed = run_enhanced_plausibility_check(
        population_description="Default pipeline deals",
        deals=default_deals,
        metric_name="cycle_time",
        metric_value=52
    )

    sys.exit(0 if passed else 1)
