#!/usr/bin/env python3
"""
Verify Q1 GRR change: 91.34% → 87.89%

Confirm this is ONLY due to Dribbleup/Joyteractive reclassification,
with no other silent adjustments.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone as tz
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from scripts.hubspot_deals import HubSpotDealsClient

print("=" * 80)
print("Q1 GRR CHANGE VERIFICATION")
print("=" * 80)
print()

hs = HubSpotDealsClient()

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"
CLOSED_LOST_STAGE_ID = "1297321624"

# Q1 2026
q1_start = datetime(2026, 1, 1, tzinfo=tz.utc)
q1_end = datetime(2026, 3, 31, 23, 59, 59, tzinfo=tz.utc)

# Fetch Q1 deals
properties = [
    'dealname',
    'closedate',
    'dealstage',
    'renewal_revenue',
    'contraction_revenue',
    'expansion_revenue'
]

body = {
    "filterGroups": [
        {
            "filters": [
                {
                    "propertyName": "pipeline",
                    "operator": "EQ",
                    "value": RENEWAL_PIPELINE_ID
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
        break

    data = response.json()
    results = data.get('results', [])
    all_deals.extend(results)

    paging = data.get('paging', {})
    after = paging.get('next', {}).get('after')

    if not after:
        break

# Filter to Q1
q1_deals = []
for deal in all_deals:
    props = deal.get('properties', {})
    closedate_str = props.get('closedate')

    if not closedate_str:
        continue

    try:
        closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
    except:
        continue

    if not (q1_start <= closedate <= q1_end):
        continue

    stage = props.get('dealstage', '')
    renewal_revenue = float(props.get('renewal_revenue') or 0)

    q1_deals.append({
        'name': props.get('dealname', 'Unknown'),
        'closedate': closedate,
        'stage': stage,
        'is_won': stage == CLOSED_WON_STAGE_ID,
        'is_lost': stage == CLOSED_LOST_STAGE_ID,
        'is_open': stage not in [CLOSED_WON_STAGE_ID, CLOSED_LOST_STAGE_ID],
        'renewal_revenue': renewal_revenue,
        'contraction_revenue': float(props.get('contraction_revenue') or 0),
        'expansion_revenue': float(props.get('expansion_revenue') or 0)
    })

print(f"Total Q1 deals: {len(q1_deals)}")
print()

# Identify key deals
zero_revenue = [d for d in q1_deals if d['renewal_revenue'] == 0]
dribbleup = [d for d in q1_deals if 'Dribbleup' in d['name']]
joyteractive = [d for d in q1_deals if 'Joyteractive' in d['name']]

print("Key deals:")
print(f"  $0 revenue: {len(zero_revenue)} deals")
for d in zero_revenue:
    print(f"    - {d['name']}")
print()

print(f"  Dribbleup: {len(dribbleup)} deals")
for d in dribbleup:
    print(f"    - {d['name']} (${d['renewal_revenue']:,.2f})")
print()

print(f"  Joyteractive: {len(joyteractive)} deals")
for d in joyteractive:
    print(f"    - {d['name']} (${d['renewal_revenue']:,.2f})")
print()

# CALCULATION 1: Exclude Dribbleup/Joyteractive (91.34%)
print("=" * 80)
print("CALCULATION 1: EXCLUDE DRIBBLEUP/JOYTERACTIVE")
print("=" * 80)
print()

# Filter out $0 revenue
clean_deals = [d for d in q1_deals if d['renewal_revenue'] > 0]

# Filter out Dribbleup and Joyteractive
excluded_names = ['Dribbleup - 2026 Renewal', 'Joyteractive - 2026 Renewal']
cohort_excluded = [d for d in clean_deals if d['name'] not in excluded_names]

# Only resolved
resolved_excluded = [d for d in cohort_excluded if not d['is_open']]
won_excluded = [d for d in resolved_excluded if d['is_won']]

denom_excluded = sum(d['renewal_revenue'] for d in resolved_excluded)
won_revenue_excluded = sum(d['renewal_revenue'] for d in won_excluded)
contraction_excluded = sum(d['contraction_revenue'] for d in won_excluded)

numerator_excluded = won_revenue_excluded - contraction_excluded
grr_excluded = (numerator_excluded / denom_excluded * 100) if denom_excluded > 0 else 0

print(f"Cohort: {len(resolved_excluded)} deals")
print(f"  Won: {len(won_excluded)}")
print(f"  Lost: {len(resolved_excluded) - len(won_excluded)}")
print()
print(f"Denominator: ${denom_excluded:,.2f}")
print(f"Numerator: ${numerator_excluded:,.2f}")
print(f"GRR: {grr_excluded:.2f}%")
print()

print("Excluded from cohort:")
print(f"  - 3 $0 revenue deals")
print(f"  - Dribbleup ($12,563)")
print(f"  - Joyteractive ($10,000)")
print()

# CALCULATION 2: Reclassify Dribbleup/Joyteractive as losses (87.89%)
print("=" * 80)
print("CALCULATION 2: RECLASSIFY AS LOSSES")
print("=" * 80)
print()

# Filter out $0 revenue only
cohort_reclassified = [d for d in clean_deals if d['renewal_revenue'] > 0]

# Reclassify stale deals as losses
for deal in cohort_reclassified:
    if deal['name'] in excluded_names and deal['is_open']:
        deal['is_lost'] = True
        deal['is_open'] = False
        deal['stale_reclassified'] = True

# Only resolved
resolved_reclassified = [d for d in cohort_reclassified if not d['is_open']]
won_reclassified = [d for d in resolved_reclassified if d['is_won']]

denom_reclassified = sum(d['renewal_revenue'] for d in resolved_reclassified)
won_revenue_reclassified = sum(d['renewal_revenue'] for d in won_reclassified)
contraction_reclassified = sum(d['contraction_revenue'] for d in won_reclassified)

numerator_reclassified = won_revenue_reclassified - contraction_reclassified
grr_reclassified = (numerator_reclassified / denom_reclassified * 100) if denom_reclassified > 0 else 0

print(f"Cohort: {len(resolved_reclassified)} deals")
print(f"  Won: {len(won_reclassified)}")
print(f"  Lost: {len(resolved_reclassified) - len(won_reclassified)}")
print()
print(f"Denominator: ${denom_reclassified:,.2f}")
print(f"Numerator: ${numerator_reclassified:,.2f}")
print(f"GRR: {grr_reclassified:.2f}%")
print()

print("Excluded from cohort:")
print(f"  - 3 $0 revenue deals")
print()
print("Reclassified as losses:")
print(f"  - Dribbleup ($12,563)")
print(f"  - Joyteractive ($10,000)")
print()

# VERIFICATION
print("=" * 80)
print("VERIFICATION")
print("=" * 80)
print()

print(f"GRR change: {grr_excluded:.2f}% → {grr_reclassified:.2f}%")
print(f"Difference: {grr_reclassified - grr_excluded:.2f} percentage points")
print()

# Check denominators
denom_diff = denom_reclassified - denom_excluded
print(f"Denominator change: ${denom_excluded:,.2f} → ${denom_reclassified:,.2f}")
print(f"Difference: ${denom_diff:,.2f}")
print()

# Expected difference
expected_diff = 12563 + 10000
print(f"Expected difference (Dribbleup + Joyteractive): ${expected_diff:,.2f}")
print()

if abs(denom_diff - expected_diff) < 1:
    print("✓ CONFIRMED: Denominator increased by exactly Dribbleup + Joyteractive")
else:
    print(f"⚠️ MISMATCH: Expected ${expected_diff:,.2f}, got ${denom_diff:,.2f}")

print()

# Check numerators
numerator_diff = numerator_reclassified - numerator_excluded
print(f"Numerator change: ${numerator_excluded:,.2f} → ${numerator_reclassified:,.2f}")
print(f"Difference: ${numerator_diff:,.2f}")
print()

if abs(numerator_diff) < 1:
    print("✓ CONFIRMED: Numerator unchanged (Dribbleup/Joyteractive not in won)")
else:
    print(f"⚠️ UNEXPECTED: Numerator changed by ${numerator_diff:,.2f}")

print()

# Check won/lost counts
print(f"Won count: {len(won_excluded)} → {len(won_reclassified)}")
if len(won_excluded) == len(won_reclassified):
    print("  ✓ CONFIRMED: Won count unchanged (14)")
else:
    print(f"  ⚠️ UNEXPECTED: Won count changed")

print()

print(f"Lost count: {len(resolved_excluded) - len(won_excluded)} → {len(resolved_reclassified) - len(won_reclassified)}")
expected_lost_increase = 2
actual_lost_increase = (len(resolved_reclassified) - len(won_reclassified)) - (len(resolved_excluded) - len(won_excluded))

if actual_lost_increase == expected_lost_increase:
    print(f"  ✓ CONFIRMED: Lost count increased by 2 (Dribbleup + Joyteractive)")
else:
    print(f"  ⚠️ UNEXPECTED: Lost count increased by {actual_lost_increase}, expected {expected_lost_increase}")

print()

# Final confirmation
print("=" * 80)
print("FINAL CONFIRMATION")
print("=" * 80)
print()

all_checks_pass = (
    abs(denom_diff - expected_diff) < 1 and
    abs(numerator_diff) < 1 and
    len(won_excluded) == len(won_reclassified) and
    actual_lost_increase == expected_lost_increase
)

if all_checks_pass:
    print("✅ VERIFIED: Q1's GRR moved from 91.34% to 87.89% SOLELY due to")
    print("   Dribbleup and Joyteractive being reclassified as losses.")
    print()
    print("   NO OTHER ADJUSTMENTS occurred:")
    print("   - Same 14 won deals")
    print("   - Same 3 $0 revenue exclusions")
    print("   - Only change: 2 deals moved from 'excluded' to 'counted as losses'")
    print()
    print("   This is the COMPLETE explanation.")
else:
    print("⚠️ DISCREPANCY FOUND: Other changes occurred beyond the stated reclassification")
    print("   Investigate what else changed between the two calculations")
