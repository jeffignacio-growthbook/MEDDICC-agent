#!/usr/bin/env python3
"""
CONTINUOUS MONITORING: Negative Cycle Time Detection

UNIVERSAL RULE: Any deal where (close_date - create_date) < 0 is auto-excluded
from ALL cycle time, win rate, and date-diff metrics.

This script:
1. Detects deals with negative cycle times (data integrity violations)
2. Reports specific deal_ids, companies, and cycle days
3. Flags CRM migration artifacts, bulk import errors, data entry mistakes

Run as:
- Manual audit: python scripts/monitor_negative_cycle_times.py
- Wave 6 monitoring trigger: Alert if count > 0 (new violations)

Template-portable: Works with any client's data (universal rule).
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
import json

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase

def monitor_negative_cycle_times():
    """Detect and report deals with negative cycle times."""
    sb = get_supabase()

    print("=" * 80)
    print("NEGATIVE CYCLE TIME MONITORING")
    print("=" * 80)
    print()
    print("UNIVERSAL RULE: (close_date - create_date) < 0 → AUTO-EXCLUDED")
    print("Indicates: CRM migration, bulk import, or data entry error")
    print()

    # Fetch all deals with both dates
    all_deals = sb.table("deals").select(
        "deal_id,company_name,pipeline_id,deal_status,stage,create_date,close_date"
    ).execute()

    print(f"Total deals in database: {len(all_deals.data)}")
    print()

    # Find negative cycle time deals
    violations = []

    for deal in all_deals.data:
        create_date_str = deal.get("create_date")
        close_date_str = deal.get("close_date")

        if not create_date_str or not close_date_str:
            continue  # Skip deals without both dates

        try:
            create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
            close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))

            cycle_days = (close_date - create_date).days

            if cycle_days < 0:
                violations.append({
                    "deal_id": deal.get("deal_id"),
                    "company": deal.get("company_name") or "(blank)",
                    "pipeline_id": deal.get("pipeline_id"),
                    "deal_status": deal.get("deal_status"),
                    "stage": deal.get("stage"),
                    "create_date": create_date_str,
                    "close_date": close_date_str,
                    "cycle_days": cycle_days
                })
        except (ValueError, AttributeError, TypeError):
            # Date parsing failed - skip
            continue

    # Report
    print("=" * 80)
    print("VIOLATIONS DETECTED")
    print("=" * 80)
    print()

    if violations:
        print(f"🚩 {len(violations)} deal(s) with NEGATIVE cycle time")
        print()
        print("These deals are AUTO-EXCLUDED from cycle time, win rate, and all date-diff metrics.")
        print()

        # Sort by most negative first
        violations.sort(key=lambda v: v["cycle_days"])

        print(f"{'Deal ID':<15} {'Company':<30} {'Cycle Days':<12} {'Status':<10} {'Create Date':<12} {'Close Date':<12}")
        print("-" * 110)

        for v in violations:
            deal_id = str(v["deal_id"])
            company = v["company"][:29]
            cycle_days = v["cycle_days"]
            status = v["deal_status"] or ""
            create_date = v["create_date"][:10]
            close_date = v["close_date"][:10]

            print(f"{deal_id:<15} {company:<30} {cycle_days:<12} {status:<10} {create_date:<12} {close_date:<12}")

        print()
        print("=" * 80)
        print("RECOMMENDED ACTIONS")
        print("=" * 80)
        print()
        print("1. Investigate: Are these CRM migration artifacts or data entry errors?")
        print("2. Fix at source: Correct create_date in HubSpot if possible")
        print("3. Accept: If unfixable (historical migration), auto-exclusion is correct")
        print()
        print("NO CODE CHANGES NEEDED:")
        print("  is_valid_cycle_deal() in field_semantics.py already excludes these automatically.")
        print()

        # Export for manual review
        output_file = Path(__file__).parent.parent / "negative_cycle_times.json"
        with open(output_file, "w") as f:
            json.dump(violations, f, indent=2, default=str)

        print(f"Details exported to: {output_file}")
        print()

        return False  # Violations detected

    else:
        print("✅ NO VIOLATIONS DETECTED")
        print()
        print("All deals with both create_date and close_date have non-negative cycle times.")
        print()

        return True  # No violations

if __name__ == "__main__":
    clean = monitor_negative_cycle_times()
    sys.exit(0 if clean else 1)
