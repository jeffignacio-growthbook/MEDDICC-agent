#!/usr/bin/env python3
"""
Diagnose why prior_arr is only populated for 1/14 deals in 2026 Q1.

Checks:
1. Historical population pattern (recent vs. always sparse)
2. Whether prior_arr can be derived from previous deal records
3. Whether gap is Q1-specific or widespread
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("PRIOR_ARR GAP DIAGNOSIS")
print("=" * 80)
print()

hs = HubSpotDealsClient()

# Fetch ALL closed won renewal deals with relevant fields
properties = [
    'dealname',
    'closedate',
    'createdate',
    'hs_object_id',
    'prior_arr',
    'gb_arr',
    'renewal_revenue',
    'expansion_revenue',
    'contraction_revenue',
    'incremental_arr',
    'amount',
    'associations.company'
]

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"

print("Fetching all closed won renewal deals...")

body = {
    "filterGroups": [
        {
            "filters": [
                {
                    "propertyName": "pipeline",
                    "operator": "EQ",
                    "value": RENEWAL_PIPELINE_ID
                },
                {
                    "propertyName": "dealstage",
                    "operator": "EQ",
                    "value": CLOSED_WON_STAGE_ID
                }
            ]
        }
    ],
    "properties": properties,
    "limit": 100
}

all_deals = []
after = None

while True:
    if after:
        body["after"] = after

    response = hs.session.post(
        f"{hs.BASE_URL}/crm/v3/objects/deals/search",
        json=body
    )

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        sys.exit(1)

    data = response.json()
    results = data.get('results', [])
    all_deals.extend(results)

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

print(f"✓ Fetched {len(all_deals)} closed won renewal deals")
print()

# Parse deals
parsed_deals = []

for deal in all_deals:
    props = deal.get('properties', {})

    closedate_str = props.get('closedate')
    createdate_str = props.get('createdate')

    closedate = None
    createdate = None

    if closedate_str:
        try:
            closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
        except:
            pass

    if createdate_str:
        try:
            createdate = datetime.fromisoformat(createdate_str.replace('Z', '+00:00'))
        except:
            pass

    prior_arr = props.get('prior_arr')
    has_prior_arr = prior_arr is not None and prior_arr != '' and float(prior_arr) != 0

    parsed_deals.append({
        'id': deal.get('id'),
        'name': props.get('dealname', 'Unknown'),
        'closedate': closedate,
        'createdate': createdate,
        'prior_arr': float(prior_arr) if prior_arr else None,
        'gb_arr': float(props.get('gb_arr') or 0),
        'renewal_revenue': float(props.get('renewal_revenue') or 0),
        'expansion_revenue': float(props.get('expansion_revenue') or 0),
        'contraction_revenue': float(props.get('contraction_revenue') or 0),
        'incremental_arr': float(props.get('incremental_arr') or 0),
        'amount': float(props.get('amount') or 0),
        'has_prior_arr': has_prior_arr
    })

# ============================================================================
# CHECK 1: Historical population pattern
# ============================================================================
print("=" * 80)
print("CHECK 1: HISTORICAL POPULATION PATTERN")
print("=" * 80)
print()

# Group by quarter
by_quarter = defaultdict(lambda: {'total': 0, 'with_prior': 0, 'deals': []})

for deal in parsed_deals:
    if not deal['closedate']:
        continue

    year = deal['closedate'].year
    quarter = (deal['closedate'].month - 1) // 3 + 1
    qtr_key = f"{year} Q{quarter}"

    by_quarter[qtr_key]['total'] += 1
    if deal['has_prior_arr']:
        by_quarter[qtr_key]['with_prior'] += 1
    by_quarter[qtr_key]['deals'].append(deal)

print("Prior_arr population by quarter:")
print()

for qtr in sorted(by_quarter.keys()):
    data = by_quarter[qtr]
    total = data['total']
    with_prior = data['with_prior']
    pct = (with_prior / total * 100) if total > 0 else 0

    print(f"{qtr}: {with_prior}/{total} deals ({pct:.1f}%)")

print()

# Check if there's a trend (was it better historically?)
quarters_sorted = sorted(by_quarter.keys())
if len(quarters_sorted) >= 2:
    first_qtr_pct = (by_quarter[quarters_sorted[0]]['with_prior'] /
                     by_quarter[quarters_sorted[0]]['total'] * 100)
    last_qtr_pct = (by_quarter[quarters_sorted[-1]]['with_prior'] /
                    by_quarter[quarters_sorted[-1]]['total'] * 100)

    print("Historical trend:")
    print(f"  Earliest quarter ({quarters_sorted[0]}): {first_qtr_pct:.1f}%")
    print(f"  Latest quarter ({quarters_sorted[-1]}): {last_qtr_pct:.1f}%")
    print()

    if first_qtr_pct > 50 and last_qtr_pct < 20:
        print("⚠️  PROCESS REGRESSION DETECTED")
        print("   Field was populated historically but stopped being filled in.")
        print("   This is a fixable data entry issue.")
    elif first_qtr_pct < 20 and last_qtr_pct < 20:
        print("ℹ️  CONSISTENTLY SPARSE")
        print("   Field has always been rarely populated.")
        print("   This suggests it's not part of standard workflow.")
    else:
        print("ℹ️  INCONSISTENT PATTERN")
        print("   Population varies quarter to quarter.")
    print()

# ============================================================================
# CHECK 2: Can prior_arr be derived from previous deals?
# ============================================================================
print("=" * 80)
print("CHECK 2: CAN PRIOR_ARR BE DERIVED FROM PREVIOUS DEALS?")
print("=" * 80)
print()

print("Checking if renewal_revenue approximates prior_arr...")
print()

# For deals with both prior_arr and renewal_revenue populated
comparison_deals = [d for d in parsed_deals
                   if d['has_prior_arr'] and d['renewal_revenue'] > 0]

if comparison_deals:
    print(f"Deals with both prior_arr and renewal_revenue: {len(comparison_deals)}")
    print()

    for deal in comparison_deals[:10]:  # Show first 10
        diff = abs(deal['prior_arr'] - deal['renewal_revenue'])
        diff_pct = (diff / deal['prior_arr'] * 100) if deal['prior_arr'] > 0 else 0

        print(f"  {deal['name']}")
        print(f"    Prior ARR: ${deal['prior_arr']:,.2f}")
        print(f"    Renewal revenue: ${deal['renewal_revenue']:,.2f}")
        print(f"    Difference: ${diff:,.2f} ({diff_pct:.1f}%)")
        print()

    # Check if renewal_revenue is a good proxy
    avg_diff_pct = sum(abs(d['prior_arr'] - d['renewal_revenue']) / d['prior_arr'] * 100
                       for d in comparison_deals if d['prior_arr'] > 0) / len(comparison_deals)

    print(f"Average difference: {avg_diff_pct:.1f}%")
    print()

    if avg_diff_pct < 5:
        print("✓ RENEWAL_REVENUE IS GOOD PROXY")
        print("  renewal_revenue ≈ prior_arr (within 5%)")
        print("  Can use renewal_revenue as starting ARR for GRR calculation")
        print()
        print("  RECOMMENDATION: Create hygiene rule")
        print('  Rule: "derive_prior_arr_from_renewal_revenue"')
        print("  When prior_arr missing, use renewal_revenue as starting ARR")
    elif avg_diff_pct < 15:
        print("⚠️  RENEWAL_REVENUE IS APPROXIMATE")
        print(f"  renewal_revenue ≈ prior_arr (within {avg_diff_pct:.1f}%)")
        print("  Could use with caveat, but not exact")
    else:
        print("✗ RENEWAL_REVENUE IS NOT A PROXY")
        print(f"  renewal_revenue differs from prior_arr by {avg_diff_pct:.1f}% avg")
        print("  Cannot use as substitute")

else:
    print("⚠️  Cannot compare - no deals with both fields populated")
    print()

print()

# Alternative: Check if we can derive from incremental_arr
print("Checking if prior_arr can be derived from other fields...")
print()

# For deals with prior_arr, check relationship to other fields
derivable_deals = [d for d in parsed_deals if d['has_prior_arr']]

if derivable_deals:
    print("Sample deals with prior_arr:")
    for deal in derivable_deals[:5]:
        # Try: prior_arr = gb_arr - incremental_arr?
        derived_prior = deal['gb_arr'] - deal['incremental_arr']

        print(f"  {deal['name']}")
        print(f"    Prior ARR (actual): ${deal['prior_arr']:,.2f}")
        print(f"    GB ARR: ${deal['gb_arr']:,.2f}")
        print(f"    Incremental ARR: ${deal['incremental_arr']:,.2f}")
        print(f"    GB ARR - Incremental: ${derived_prior:,.2f}")
        print(f"    Renewal revenue: ${deal['renewal_revenue']:,.2f}")
        print()

# ============================================================================
# CHECK 3: Is gap widespread or Q1-specific?
# ============================================================================
print("=" * 80)
print("CHECK 3: IS GAP WIDESPREAD OR Q1-SPECIFIC?")
print("=" * 80)
print()

overall_with_prior = sum(1 for d in parsed_deals if d['has_prior_arr'])
overall_pct = (overall_with_prior / len(parsed_deals) * 100) if parsed_deals else 0

print(f"Overall across all quarters:")
print(f"  {overall_with_prior}/{len(parsed_deals)} deals have prior_arr ({overall_pct:.1f}%)")
print()

q1_2026_data = by_quarter.get('2026 Q1', {'total': 0, 'with_prior': 0})
q1_with_prior = q1_2026_data['with_prior']
q1_total = q1_2026_data['total']
q1_pct = (q1_with_prior / q1_total * 100) if q1_total > 0 else 0

print(f"2026 Q1 specifically:")
print(f"  {q1_with_prior}/{q1_total} deals have prior_arr ({q1_pct:.1f}%)")
print()

if abs(q1_pct - overall_pct) < 5:
    print("ℹ️  GAP IS WIDESPREAD")
    print("   2026 Q1 is consistent with overall pattern.")
    print("   This is not a Q1-specific issue.")
else:
    print("⚠️  Q1 IS ANOMALOUS")
    print(f"   Q1 ({q1_pct:.1f}%) differs from overall ({overall_pct:.1f}%)")

# ============================================================================
# FINAL DETERMINATION
# ============================================================================
print()
print("=" * 80)
print("DETERMINATION: PATH FORWARD FOR GRR")
print("=" * 80)
print()

# Summarize findings
can_derive = False
derivation_method = None

if comparison_deals and avg_diff_pct < 5:
    can_derive = True
    derivation_method = "renewal_revenue"
    print("✓ PRIOR_ARR CAN BE DERIVED")
    print()
    print(f"  Method: Use renewal_revenue as proxy for prior_arr")
    print(f"  Accuracy: Within {avg_diff_pct:.1f}% on average")
    print(f"  Coverage: {len(comparison_deals)} deals validated")
    print()
    print("RECOMMENDED PATH:")
    print("  1. Create hygiene rule: derive_prior_arr_from_renewal_revenue")
    print("  2. Apply to all renewal deals missing prior_arr")
    print("  3. Re-run GRR calculation with derived starting ARR")
    print("  4. Document as derivation (not raw field)")
    print()
    print("This becomes a registry-tracked hygiene rule, not a one-off fix.")

elif overall_pct < 10:
    print("⚠️  PRIOR_ARR IS GENUINELY ABSENT")
    print()
    print(f"  Only {overall_pct:.1f}% of renewal deals have prior_arr")
    print("  No clear derivation method found")
    print("  This is a PERMANENT DATA GAP")
    print()
    print("HONEST OUTCOME:")
    print("  GRR is NOT YET COMPUTABLE as a cohort metric")
    print("  (Missing required input field: starting ARR)")
    print()
    print("Evidence preserved:")
    print("  - Contraction arithmetic PROVEN correct ($36,250 exact match)")
    print("  - Formula ready the moment prior_arr becomes available")
    print("  - Same pattern as Signal 1/3 deferral")
    print()
    print("DO NOT report n=1 cohort as successful dogfood test.")

else:
    print("ℹ️  MIXED SITUATION")
    print()
    print(f"  {overall_pct:.1f}% of deals have prior_arr")
    print("  May be derivable but needs investigation")
    print()
    print("NEXT STEPS:")
    print("  - Investigate alternative derivation methods")
    print("  - Check if sequential deal records exist per customer")
    print("  - Consider manual data remediation for key accounts")

print()
print("=" * 80)
print(f"Population rate: {overall_pct:.1f}%")
print(f"Can derive: {can_derive}")
if can_derive:
    print(f"Derivation method: {derivation_method}")
print("=" * 80)
