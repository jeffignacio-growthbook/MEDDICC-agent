#!/usr/bin/env python3
"""
Investigate the 5 longest-cycle deals (740, 561, 516, 500, 477 days) to find
common patterns: segment, deal size, owner, deal type, or other attributes.

Two outcomes:
1. They share something specific → actionable finding (e.g., "enterprise deals
   take 500+ days, track separately")
2. Genuinely unrelated → "increased variance, no clear driver" is correct
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from field_semantics import is_won

def investigate_outliers():
    sb = get_supabase()

    print("=" * 80)
    print("INVESTIGATING 5 LONGEST-CYCLE DEALS IN RECENT 12 MONTHS")
    print("=" * 80)
    print()

    # Get cutoff for 12-month window
    now = datetime.now(timezone.utc)
    cutoff_date = now - timedelta(days=12 * 30)

    # Fetch all won deals with extended attributes
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,stage,deal_value,"
        "pipeline,owner_email,segment,expansion_arr,new_arr,renewal_revenue,"
        "company_employee_count"
    ).execute()

    won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]

    # Filter to 12-month window and calculate cycle times
    recent_deals = []
    for deal in won_deals:
        close_date_str = deal.get("close_date")
        create_date_str = deal.get("create_date")

        if not close_date_str or not create_date_str:
            continue

        try:
            close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
            create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))

            if close_date.tzinfo is None:
                close_date = close_date.replace(tzinfo=timezone.utc)
            if create_date.tzinfo is None:
                create_date = create_date.replace(tzinfo=timezone.utc)

            if close_date >= cutoff_date:
                cycle_days = (close_date - create_date).days

                if cycle_days >= 0:
                    # Infer deal type from ARR fields
                    new_arr_val = deal.get("new_arr") or 0
                    expansion_arr_val = deal.get("expansion_arr") or 0
                    renewal_revenue_val = deal.get("renewal_revenue") or 0

                    if new_arr_val > 0 and expansion_arr_val == 0 and renewal_revenue_val == 0:
                        inferred_type = "New Business"
                    elif expansion_arr_val > 0:
                        inferred_type = "Expansion"
                    elif renewal_revenue_val > 0 and new_arr_val == 0 and expansion_arr_val == 0:
                        inferred_type = "Renewal"
                    else:
                        inferred_type = "Mixed/Unknown"

                    recent_deals.append({
                        "deal_id": deal.get("deal_id"),
                        "company_name": deal.get("company_name"),
                        "cycle_days": cycle_days,
                        "deal_value": deal.get("deal_value"),
                        "pipeline": deal.get("pipeline"),
                        "owner_email": deal.get("owner_email"),
                        "deal_type": inferred_type,
                        "segment": deal.get("segment"),
                        "expansion_arr": deal.get("expansion_arr"),
                        "new_arr": deal.get("new_arr"),
                        "renewal_revenue": deal.get("renewal_revenue"),
                        "company_employee_count": deal.get("company_employee_count"),
                        "close_date": close_date,
                        "create_date": create_date
                    })
        except (ValueError, AttributeError):
            continue

    # Sort by cycle time descending
    recent_deals.sort(key=lambda d: d["cycle_days"], reverse=True)

    # Top 5 outliers
    outliers = recent_deals[:5]

    print("TOP 5 LONGEST-CYCLE DEALS (12-month window)")
    print("-" * 80)
    print()

    for i, deal in enumerate(outliers, 1):
        print(f"#{i}. {deal['company_name']}")
        print(f"    Cycle time: {deal['cycle_days']} days")
        print(f"    Deal value: ${deal['deal_value']:,.0f}" if deal['deal_value'] else "    Deal value: N/A")
        print(f"    Pipeline: {deal['pipeline']}")
        print(f"    Owner: {deal['owner_email']}")
        print(f"    Deal type: {deal['deal_type']}")
        print(f"    Segment: {deal['segment']}")

        # Show company size if available
        emp_count = deal.get('company_employee_count')
        if emp_count:
            print(f"    Company size: {emp_count:,} employees")

        # ARR breakdown
        new_arr = deal.get('new_arr') or 0
        expansion_arr = deal.get('expansion_arr') or 0
        renewal_revenue = deal.get('renewal_revenue') or 0
        print(f"    ARR breakdown: New=${new_arr:,.0f}, Expansion=${expansion_arr:,.0f}, Renewal=${renewal_revenue:,.0f}")

        print(f"    Created: {deal['create_date'].date()}")
        print(f"    Closed: {deal['close_date'].date()}")
        print()

    # Pattern analysis
    print("=" * 80)
    print("PATTERN ANALYSIS")
    print("=" * 80)
    print()

    # Check for common attributes
    attributes = {
        "pipeline": [d.get("pipeline") for d in outliers],
        "owner_email": [d.get("owner_email") for d in outliers],
        "deal_type": [d.get("deal_type") for d in outliers],
        "segment": [d.get("segment") for d in outliers]
    }

    patterns_found = []

    for attr_name, values in attributes.items():
        # Remove None values
        values = [v for v in values if v is not None]

        if not values:
            continue

        # Check if all are the same
        unique_values = set(values)

        if len(unique_values) == 1:
            patterns_found.append(f"All 5 have same {attr_name}: '{values[0]}'")
        elif len(unique_values) <= 2:
            # Mostly concentrated
            from collections import Counter
            counts = Counter(values)
            most_common = counts.most_common(1)[0]
            if most_common[1] >= 4:
                patterns_found.append(f"{most_common[1]}/5 have {attr_name}: '{most_common[0]}'")

    # Check deal size patterns
    deal_values = [d.get("deal_value") for d in outliers if d.get("deal_value")]
    if deal_values:
        avg_outlier_value = sum(deal_values) / len(deal_values)

        # Compare to overall population
        all_values = [d.get("deal_value") for d in recent_deals if d.get("deal_value")]
        if all_values:
            avg_all_value = sum(all_values) / len(all_values)

            if avg_outlier_value > avg_all_value * 2:
                patterns_found.append(f"Outliers are 2x+ larger than average (${avg_outlier_value:,.0f} vs ${avg_all_value:,.0f})")

    # Check company size patterns
    emp_counts = [d.get("company_employee_count") for d in outliers if d.get("company_employee_count")]
    if emp_counts:
        avg_outlier_emp = sum(emp_counts) / len(emp_counts)

        # Compare to overall population
        all_emp_counts = [d.get("company_employee_count") for d in recent_deals if d.get("company_employee_count")]
        if all_emp_counts:
            avg_all_emp = sum(all_emp_counts) / len(all_emp_counts)

            if avg_outlier_emp > avg_all_emp * 2:
                patterns_found.append(f"Outliers are 2x+ larger companies ({avg_outlier_emp:,.0f} vs {avg_all_emp:,.0f} employees)")

    # Check if they're all new business, expansion, or renewal
    arr_types = []
    for deal in outliers:
        new_arr = deal.get('new_arr') or 0
        expansion_arr = deal.get('expansion_arr') or 0
        renewal_revenue = deal.get('renewal_revenue') or 0

        if new_arr > 0 and expansion_arr == 0 and renewal_revenue == 0:
            arr_types.append("New Business")
        elif expansion_arr > 0:
            arr_types.append("Expansion")
        elif renewal_revenue > 0 and new_arr == 0 and expansion_arr == 0:
            arr_types.append("Renewal")
        else:
            arr_types.append("Mixed/Unknown")

    unique_arr_types = set(arr_types)
    if len(unique_arr_types) == 1:
        patterns_found.append(f"All 5 are {arr_types[0]} deals")
    elif len(unique_arr_types) <= 2:
        from collections import Counter
        counts = Counter(arr_types)
        most_common = counts.most_common(1)[0]
        if most_common[1] >= 4:
            patterns_found.append(f"{most_common[1]}/5 are {most_common[0]} deals")

    print("COMMON PATTERNS DETECTED:")
    print("-" * 80)

    if patterns_found:
        for pattern in patterns_found:
            print(f"  ✓ {pattern}")
        print()
        print("⚠️  ACTIONABLE FINDING:")
        print("    These outliers share common attributes - not random variance.")
        print("    Worth investigating why this specific cohort takes 500+ days.")
    else:
        print("  None - outliers appear unrelated")
        print()
        print("✓ RANDOM VARIANCE CONFIRMED:")
        print("    No shared segment, rep, deal type, or size pattern.")
        print("    Truly increased variance without clear driver.")

    print()

    # Distribution comparison
    print("=" * 80)
    print("OUTLIERS vs POPULATION")
    print("=" * 80)
    print()

    non_outlier_deals = recent_deals[5:]

    if non_outlier_deals:
        from statistics import median

        outlier_cycles = [d["cycle_days"] for d in outliers]
        non_outlier_cycles = [d["cycle_days"] for d in non_outlier_deals]

        print(f"Outliers (top 5):")
        print(f"  Range: {min(outlier_cycles)}-{max(outlier_cycles)} days")
        print(f"  Median: {median(outlier_cycles):.0f} days")
        print()

        print(f"Rest of 12-month population (n={len(non_outlier_deals)}):")
        print(f"  Range: {min(non_outlier_cycles)}-{max(non_outlier_cycles)} days")
        print(f"  Median: {median(non_outlier_cycles):.0f} days")
        print()

        print(f"Gap: {median(outlier_cycles) - median(non_outlier_cycles):.0f} days between outliers and rest")

    print()
    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()

    if patterns_found:
        print("These 5 long-cycle deals are NOT random outliers - they cluster in:")
        for pattern in patterns_found:
            print(f"  • {pattern}")
        print()
        print("NARRATIVE FOR JEFF:")
        print('  "Recent 12-month median is elevated (157d vs 116d all-time) primarily')
        print('   due to [describe cluster pattern]. Worth investigating whether this')
        print('   cohort legitimately requires longer cycles or if there are process')
        print('   improvements that could accelerate them."')
    else:
        print("These 5 long-cycle deals have NO common pattern (different segments,")
        print("reps, deal types, sizes). This is genuinely increased variance.")
        print()
        print("NARRATIVE FOR JEFF:")
        print('  "Recent 12-month median is elevated (157d vs 116d all-time) due to')
        print('   increased variance - several deals taking 500+ days with no shared')
        print('   attributes. Monitor if this variance persists or returns to baseline."')

if __name__ == "__main__":
    investigate_outliers()
