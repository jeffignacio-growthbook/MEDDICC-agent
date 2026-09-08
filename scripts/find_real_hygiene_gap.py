#!/usr/bin/env python3
"""
Find real, uncodified hygiene issues in GrowthBook data.

Look for patterns that contaminate metrics but aren't yet in the registry:
- Test/demo deals from specific owners
- Deals below reasonable thresholds
- Specific stages that shouldn't count
- Zero-value deals in won population
- Other real data quirks
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from collections import Counter

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.field_semantics import is_won, is_open, is_renewal_base

sb = create_client(
    os.environ['SUPABASE_URL'],
    os.environ['SUPABASE_SERVICE_KEY']
)

print("="*80)
print("SEARCHING FOR REAL, UNCODIFIED HYGIENE ISSUES")
print("="*80)
print()

# Fetch all deals with relevant fields
all_deals = sb.table("deals").select(
    "deal_id,company_name,stage,deal_value,pipeline_id,create_date,close_date,renewal_revenue"
).execute()

print(f"Total deals in database: {len(all_deals.data)}")
print()

# Filter to won deals (excluding renewals)
RENEWAL_PIPELINE_ID = "866608541"
won_deals = [d for d in all_deals.data if is_won(d.get("stage"))]
non_renewal_won = [d for d in won_deals if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

print(f"Won deals (all): {len(won_deals)}")
print(f"Won deals (non-renewal): {len(non_renewal_won)}")
print()

# ============================================================================
# HYGIENE ISSUE 1: Zero or NULL deal values in won population
# ============================================================================

print("─"*80)
print("HYGIENE ISSUE CHECK 1: Zero or NULL deal values")
print("─"*80)
print()

zero_value_won = [d for d in non_renewal_won if not d.get("deal_value") or d.get("deal_value") == 0]

print(f"Won deals with NULL or $0 value: {len(zero_value_won)}")

if zero_value_won:
    print()
    print("Examples:")
    for deal in zero_value_won[:5]:
        print(f"  - {deal.get('company_name')} (ID: {deal.get('deal_id')})")
        print(f"    Stage: {deal.get('stage')}, Value: {deal.get('deal_value')}")
    print()
    print("✓ POTENTIAL HYGIENE RULE: exclude_zero_value_deals")
    print("  Rationale: Won deals with $0 value are likely data quality issues")
else:
    print("✗ No zero-value won deals found")

print()

# ============================================================================
# HYGIENE ISSUE 2: Deals below minimum threshold
# ============================================================================

print("─"*80)
print("HYGIENE ISSUE CHECK 2: Deals below minimum threshold")
print("─"*80)
print()

# Calculate distribution of deal values
deal_values = sorted([d.get("deal_value", 0) or 0 for d in non_renewal_won])
n = len(deal_values)

if n > 0:
    min_value = deal_values[0]
    p10 = deal_values[int(n * 0.1)]
    p25 = deal_values[int(n * 0.25)]
    median = deal_values[n // 2]

    print(f"Deal value distribution (non-renewal won):")
    print(f"  Min: ${min_value:,.2f}")
    print(f"  10th percentile: ${p10:,.2f}")
    print(f"  25th percentile: ${p25:,.2f}")
    print(f"  Median: ${median:,.2f}")
    print()

    # Check for deals below $5K (likely test/pilot deals)
    small_deals = [d for d in non_renewal_won if d.get("deal_value", 0) and d.get("deal_value") < 5000]

    if small_deals:
        print(f"Won deals < $5K: {len(small_deals)}")
        print()
        print("Examples:")
        for deal in small_deals[:5]:
            print(f"  - {deal.get('company_name')}: ${deal.get('deal_value', 0):,.2f}")
        print()
        print("✓ POTENTIAL HYGIENE RULE: exclude_pilot_deals")
        print("  Rationale: Deals < $5K may be pilots/tests, not representative of pipeline")
    else:
        print("✗ No deals < $5K found")

print()

# ============================================================================
# HYGIENE ISSUE 3: Test/demo companies (by name pattern)
# ============================================================================

print("─"*80)
print("HYGIENE ISSUE CHECK 3: Test/demo companies")
print("─"*80)
print()

# Check for suspicious patterns in company names
test_companies = [d for d in non_renewal_won
                  if d.get("company_name") and
                  any(keyword in d.get("company_name", "").lower()
                      for keyword in ['test', 'demo', 'internal', 'example'])]

if test_companies:
    print(f"Potential test/demo companies: {len(test_companies)}")
    print()
    print("Examples:")
    for deal in test_companies[:5]:
        print(f"  - {deal.get('company_name')}: ${deal.get('deal_value', 0):,.2f}")
    print()
    print("✓ POTENTIAL HYGIENE RULE: exclude_test_companies")
    print("  Rationale: Companies with 'test'/'demo' in name are likely test data")
else:
    print("✗ No obvious test/demo companies found")

print()

# ============================================================================
# HYGIENE ISSUE 4: Active deals with very high ages (stale pipeline)
# ============================================================================

print("─"*80)
print("HYGIENE ISSUE CHECK 4: Stale pipeline (old active deals)")
print("─"*80)
print()

from datetime import datetime

active_deals = [d for d in all_deals.data if is_open(d.get("stage"))]
non_renewal_active = [d for d in active_deals if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

# Calculate age of active deals
stale_deals = []
for deal in non_renewal_active:
    create_date_str = deal.get("create_date")
    if create_date_str:
        try:
            if isinstance(create_date_str, str):
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
            else:
                create_date = create_date_str

            age_days = (datetime.now(create_date.tzinfo) - create_date).days

            # Flag deals older than 180 days
            if age_days > 180:
                stale_deals.append({
                    "deal": deal,
                    "age_days": age_days
                })
        except:
            pass

if stale_deals:
    print(f"Active deals older than 180 days: {len(stale_deals)}")

    # Calculate total value
    stale_value = sum(d["deal"].get("deal_value", 0) or 0 for d in stale_deals)
    total_active_value = sum(d.get("deal_value", 0) or 0 for d in non_renewal_active)

    print(f"Stale pipeline value: ${stale_value:,.2f}")
    print(f"Total active pipeline: ${total_active_value:,.2f}")
    print(f"Stale percentage: {(stale_value / total_active_value * 100):.1f}%")
    print()

    print("Examples (oldest):")
    for item in sorted(stale_deals, key=lambda x: x["age_days"], reverse=True)[:5]:
        deal = item["deal"]
        age = item["age_days"]
        print(f"  - {deal.get('company_name')}: {age} days old, ${deal.get('deal_value', 0):,.2f}")
    print()

    print("✓ POTENTIAL HYGIENE RULE: exclude_stale_pipeline")
    print("  Rationale: Deals open >180 days may be stale/abandoned, contaminate pipeline velocity")
else:
    print("✗ No stale deals found")

print()

# ============================================================================
# SUMMARY AND RECOMMENDATION
# ============================================================================

print("="*80)
print("SUMMARY: Real Hygiene Gaps for Test 2")
print("="*80)
print()

has_zero_value = len(zero_value_won) > 0 if 'zero_value_won' in locals() else False
has_small_deals = len(small_deals) > 0 if 'small_deals' in locals() else False
has_test_companies = len(test_companies) > 0 if 'test_companies' in locals() else False
has_stale = len(stale_deals) > 0 if 'stale_deals' in locals() else False

if has_zero_value:
    print("✓ BEST CANDIDATE: Zero-value won deals")
    print(f"  Found: {len(zero_value_won)} deals")
    print("  Test case: Calculate total won value")
    print("  Naive: Includes zero-value deals")
    print("  Correct: Excludes zero-value deals (data quality issue)")
    print("  Missing rule: exclude_zero_value_deals")
    print()

if has_small_deals:
    print("✓ CANDIDATE: Small pilot deals")
    print(f"  Found: {len(small_deals)} deals < $5K")
    print("  Test case: Calculate average deal size")
    print("  Naive: Includes pilot deals (drags down average)")
    print("  Correct: Excludes <$5K deals")
    print("  Missing rule: exclude_pilot_deals")
    print()

if has_stale:
    print("✓ CANDIDATE: Stale pipeline")
    print(f"  Found: {len(stale_deals)} deals > 180 days old")
    print(f"  Value: ${stale_value:,.2f} ({(stale_value / total_active_value * 100):.1f}% of pipeline)")
    print("  Test case: Calculate active pipeline value")
    print("  Naive: Includes stale deals")
    print("  Correct: Excludes deals >180 days old")
    print("  Missing rule: exclude_stale_pipeline")
    print()

if not any([has_zero_value, has_small_deals, has_test_companies, has_stale]):
    print("✗ No obvious uncodified hygiene issues found")
    print("  Current data is relatively clean")
    print("  May need to construct synthetic test case")
