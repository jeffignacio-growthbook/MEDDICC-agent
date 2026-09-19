#!/usr/bin/env python3
"""
Audit-only script: does rep_targets have ANY row for FY2026 Q3, FY2026 Q4,
FY2027 Q1, or FY2027 Q2 (the 4 complete quarters used in the coverage-curve
audit), independent of config/targets.yaml (which only has fy2027_q3 -
this checks the live table directly, in case a target was ever set via
the Slack 'set [team] target' path instead of the YAML seed).

Answers Jeff's direct question: was there ever a real target for those
quarters, or does none exist at all. READ-ONLY. No writes.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from db import get_supabase
from supabase_client import select_all


def main():
    sb = get_supabase()

    all_rows = select_all(sb, "rep_targets",
        columns="id,period,level,entity_name,metric,target_value,set_at,set_by_slack")

    print(f"Total rows in rep_targets (ALL periods, no filter): {len(all_rows)}\n")

    by_period = {}
    for r in all_rows:
        by_period.setdefault(r.get("period"), []).append(r)

    print("Distinct periods with ANY row:")
    for period in sorted(by_period):
        print(f"  {period}: {len(by_period[period])} rows")

    print()
    target_periods = ["FY2026_Q3", "FY2026 Q3", "FY2027_Q1", "FY2027 Q1",
                       "FY2027_Q2", "FY2027 Q2", "FY2026_Q4", "FY2026 Q4"]
    print("Checking the 4 complete quarters specifically (both label formats):")
    for p in target_periods:
        rows = by_period.get(p, [])
        print(f"  {p!r}: {len(rows)} rows" + (f" -> {rows}" if rows else ""))

    print("\nDONE")


if __name__ == "__main__":
    main()
