#!/usr/bin/env python3
"""
Verify Sept 6 answer accuracy: Was "$110K Q3 expansion" correct?
Compare delivered answer against actual Q3 expansion ARR in database.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all

print("=" * 70)
print("SEPT 6 ANSWER VERIFICATION")
print("=" * 70)
print()

print("Question asked (Sept 6, 2026):")
print('  "How much expansion ARR is in the renewal pipeline for Q3 and Q4?"')
print()

print("Answer delivered:")
print('  "$110K Q3 expansion"')
print('  Based on 7 deals (after aggregate_results failed, recovery query ran)')
print()

print("=" * 70)
print("VERIFICATION QUERY: Q3 Expansion ARR (Aug-Oct 2026)")
print("=" * 70)
print()

# Run the exact query to check Q3 expansion
q3_deals = select_all(sb, 'deals',
    'deal_id,company_name,close_date,incremental_arr,deal_status,owner_email',
    filters=[
        ('eq', 'pipeline_id', '866608541'),
        ('gte', 'close_date', '2026-08-01'),
        ('lte', 'close_date', '2026-10-31'),
        ('eq', 'deal_status', 'active'),
        ('gt', 'incremental_arr', 0)
    ])

print(f"Found {len(q3_deals)} deals with expansion ARR (incremental_arr > 0)")
print()

if not q3_deals:
    print("❌ NO EXPANSION DEALS FOUND IN Q3")
    print()
    print("This means the $110K answer was WRONG.")
    print("Need to check if deals exist without incremental_arr filter.")
    sys.exit(1)

# Calculate total
total_expansion = sum(d['incremental_arr'] for d in q3_deals if d.get('incremental_arr'))

print("Q3 Expansion Deals:")
print("-" * 70)
for d in sorted(q3_deals, key=lambda x: x.get('incremental_arr', 0), reverse=True):
    company = d.get('company_name', 'Unknown')
    arr = d.get('incremental_arr', 0)
    close = d.get('close_date', 'N/A')
    owner = d.get('owner_email', 'N/A').split('@')[0] if d.get('owner_email') else 'N/A'
    print(f"  • {company:30s} ${arr:>10,.0f} | {close} | {owner}")

print()
print("=" * 70)
print("TOTALS")
print("=" * 70)
print(f"Deal count: {len(q3_deals)}")
print(f"Total expansion ARR: ${total_expansion:,.0f}")
print()

# Compare to delivered answer
delivered_amount = 110000  # $110K from answer excerpt
delivered_count = 7  # 7 deals from recovery query

print("=" * 70)
print("COMPARISON")
print("=" * 70)
print()
print(f"Delivered answer: ${delivered_amount:,} from {delivered_count} deals")
print(f"Actual data:      ${total_expansion:,.0f} from {len(q3_deals)} deals")
print()

# Calculate discrepancy
amount_diff = total_expansion - delivered_amount
amount_diff_pct = (amount_diff / delivered_amount * 100) if delivered_amount > 0 else 0
count_diff = len(q3_deals) - delivered_count

print(f"Difference:       ${amount_diff:+,.0f} ({amount_diff_pct:+.1f}%)")
print(f"                  {count_diff:+d} deals")
print()

print("=" * 70)
print("VERDICT")
print("=" * 70)
print()

# Thresholds for significance
AMOUNT_THRESHOLD = 10000  # $10K or more is material
PERCENT_THRESHOLD = 10     # 10% or more is material

if abs(amount_diff) < AMOUNT_THRESHOLD and abs(amount_diff_pct) < PERCENT_THRESHOLD:
    print("✅ ANSWER WAS CORRECT")
    print()
    print(f"Difference of ${abs(amount_diff):,.0f} ({abs(amount_diff_pct):.1f}%) is within tolerance.")
    print("The recovery query's 7 deals correctly captured Q3 expansion ARR.")
    print()
    print("**Impact: LOW**")
    print("  - Bug did not affect answer accuracy")
    print("  - User received correct information despite internal failure")
    print("  - No correction needed")
elif len(q3_deals) == delivered_count:
    print("⚠️  EXACT DEAL COUNT MATCH BUT DIFFERENT TOTAL")
    print()
    print(f"Both queries found {len(q3_deals)} deals, but ARR totals differ by ${abs(amount_diff):,.0f}")
    print()
    print("Possible causes:")
    print("  - Rounding in answer presentation")
    print("  - Data changed between Sept 6 and now")
    print("  - Answer excerpt was truncated (may have shown more precise number)")
    print()
    print("**Impact: MEDIUM**")
    print("  - Need to check full answer (not just excerpt)")
    print("  - If real discrepancy, answer was materially wrong")
else:
    print("❌ ANSWER WAS WRONG")
    print()
    print(f"Actual Q3 expansion: ${total_expansion:,.0f} from {len(q3_deals)} deals")
    print(f"Delivered answer:    ${delivered_amount:,} from {delivered_count} deals")
    print()
    print(f"User received UNDERSTATED figure by ${abs(amount_diff):,.0f} ({abs(amount_diff_pct):+.1f}%)")
    print()
    print("**Impact: HIGH**")
    print("  - Real answer to real question was materially incorrect")
    print("  - User may have made decisions based on wrong number")
    print("  - Consider notifying stakeholder who received this answer")
    print()
    print("Missing deals:")
    if len(q3_deals) > delivered_count:
        missing_deals = q3_deals[delivered_count:]
        for d in missing_deals[:10]:  # Show first 10 missing
            company = d.get('company_name', 'Unknown')
            arr = d.get('incremental_arr', 0)
            print(f"  • {company}: ${arr:,.0f}")
        if len(missing_deals) > 10:
            print(f"  ... and {len(missing_deals) - 10} more")

print()
print("=" * 70)
print("NEXT STEPS")
print("=" * 70)
print()

if abs(amount_diff) < AMOUNT_THRESHOLD:
    print("✅ No correction needed - answer was accurate")
    print()
    print("1. Document this verification in SEPT6_SILENT_FAILURE_IMPACT.md")
    print("2. Proceed with implementing the three fixes")
    print("3. Mark impact as 'verified LOW' in documentation")
else:
    print("⚠️  Correction may be needed")
    print()
    print("1. Pull full answer (not just excerpt) to verify exact number stated")
    print("2. Check if data has changed since Sept 6 (deals closed, ARR updated)")
    print("3. If answer was genuinely wrong:")
    print("   - Document corrected figure in incident log")
    print("   - Consider whether to notify recipient")
    print("   - Use as case study for importance of fixing this bug")
    print("4. Proceed with implementing the three fixes")
    print("5. Mark impact as 'verified HIGH' in documentation")

print()
print("=" * 70)

# Also check Q4 for completeness (answer mentioned both Q3 and Q4)
print()
print("BONUS: Q4 Verification (Oct-Jan 2027)")
print("=" * 70)

q4_deals = select_all(sb, 'deals',
    'deal_id,company_name,close_date,incremental_arr,deal_status',
    filters=[
        ('eq', 'pipeline_id', '866608541'),
        ('gte', 'close_date', '2026-11-01'),
        ('lte', 'close_date', '2027-01-31'),
        ('eq', 'deal_status', 'active'),
        ('gt', 'incremental_arr', 0)
    ])

if q4_deals:
    q4_total = sum(d['incremental_arr'] for d in q4_deals if d.get('incremental_arr'))
    print(f"Q4 expansion: ${q4_total:,.0f} from {len(q4_deals)} deals")
    print()
    print("Top 3 Q4 deals:")
    for d in sorted(q4_deals, key=lambda x: x.get('incremental_arr', 0), reverse=True)[:3]:
        print(f"  • {d.get('company_name', 'Unknown'):30s} ${d.get('incremental_arr', 0):>10,.0f}")
else:
    print("No Q4 expansion deals found")
