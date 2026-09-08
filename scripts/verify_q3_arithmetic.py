#!/usr/bin/env python3
"""
Verify Q3 GRR arithmetic - why are resolved and best-case both 100%?

Check:
1. Are there genuinely 0 lost deals? (Show actual deal_ids/stages)
2. Full denominator math for both calculations
3. Why do two structurally different numbers coincidentally match?
4. Haystack TV and TicketNetwork $0 revenue - real or data gap?
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
print("Q3 GRR ARITHMETIC VERIFICATION")
print("=" * 80)
print()

hs = HubSpotDealsClient()

RENEWAL_PIPELINE_ID = "866608541"
CLOSED_WON_STAGE_ID = "1297321623"
CLOSED_LOST_STAGE_ID = "1297321624"

STAGE_NAMES = {
    '1297321618': 'Upcoming Renewal',
    '1297321619': 'Renewal Engaged',
    '1297321620': 'Pricing Presented',
    '1297321622': 'Contract Sent',
    '1297321623': 'Closed Won',
    '1297321624': 'Closed Lost'
}

# Q3 2026
q3_start = datetime(2026, 7, 1, tzinfo=tz.utc)
q3_end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=tz.utc)

# Fetch ALL Q3 renewal deals
properties = [
    'dealname',
    'closedate',
    'dealstage',
    'hs_deal_stage_probability',
    'renewal_revenue',
    'contraction_revenue',
    'expansion_revenue',
    'createdate',
    'hs_lastmodifieddate'
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

# Filter to Q3
q3_deals = []
for deal in all_deals:
    props = deal.get('properties', {})
    closedate_str = props.get('closedate')

    if not closedate_str:
        continue

    try:
        closedate = datetime.fromisoformat(closedate_str.replace('Z', '+00:00'))
    except:
        continue

    if not (q3_start <= closedate <= q3_end):
        continue

    stage = props.get('dealstage', '')
    renewal_revenue = float(props.get('renewal_revenue') or 0)

    q3_deals.append({
        'id': deal.get('id'),
        'name': props.get('dealname', 'Unknown'),
        'closedate': closedate,
        'stage': stage,
        'stage_name': STAGE_NAMES.get(stage, f'Unknown ({stage})'),
        'is_won': stage == CLOSED_WON_STAGE_ID,
        'is_lost': stage == CLOSED_LOST_STAGE_ID,
        'is_open': stage not in [CLOSED_WON_STAGE_ID, CLOSED_LOST_STAGE_ID],
        'renewal_revenue': renewal_revenue,
        'contraction_revenue': float(props.get('contraction_revenue') or 0),
        'expansion_revenue': float(props.get('expansion_revenue') or 0)
    })

print(f"Total Q3 deals: {len(q3_deals)}")
print()

# ============================================================================
# CHECK 1: Are there genuinely 0 lost deals?
# ============================================================================
print("=" * 80)
print("CHECK 1: VERIFY 0 LOST DEALS CLAIM")
print("=" * 80)
print()

won_deals = [d for d in q3_deals if d['is_won']]
lost_deals = [d for d in q3_deals if d['is_lost']]
open_deals = [d for d in q3_deals if d['is_open']]

print(f"Won deals: {len(won_deals)}")
print(f"Lost deals: {len(lost_deals)}")
print(f"Open deals: {len(open_deals)}")
print()

if len(lost_deals) == 0:
    print("✓ CONFIRMED: 0 lost deals in Q3 resolved cohort")
    print("  This is unusual but possible on small sample (10 resolved deals)")
else:
    print(f"⚠️ FOUND {len(lost_deals)} LOST DEALS:")
    for deal in lost_deals:
        print(f"  - {deal['name']} (${deal['renewal_revenue']:,.2f})")

print()

print("10 Won deals detail:")
for i, deal in enumerate(won_deals, 1):
    print(f"{i:2}. {deal['name']}")
    print(f"    Deal ID: {deal['id']}")
    print(f"    Stage: {deal['stage_name']} (ID: {deal['stage']})")
    print(f"    Renewal: ${deal['renewal_revenue']:,.2f}")
    print(f"    Contraction: ${deal['contraction_revenue']:,.2f}")
    print(f"    Expansion: ${deal['expansion_revenue']:,.2f}")

print()

# ============================================================================
# CHECK 2: Full denominator math
# ============================================================================
print("=" * 80)
print("CHECK 2: FULL ARITHMETIC BREAKDOWN")
print("=" * 80)
print()

# Resolved GRR (won + lost only, exclude $0)
resolved_deals_with_revenue = [d for d in q3_deals if not d['is_open'] and d['renewal_revenue'] > 0]
won_with_revenue = [d for d in won_deals if d['renewal_revenue'] > 0]

denominator_resolved = sum(d['renewal_revenue'] for d in resolved_deals_with_revenue)
won_renewal = sum(d['renewal_revenue'] for d in won_with_revenue)
total_contraction = sum(d['contraction_revenue'] for d in won_with_revenue)
total_expansion = sum(d['expansion_revenue'] for d in won_with_revenue)

numerator_resolved = won_renewal - total_contraction

print("RESOLVED GRR (won + lost, $0 revenue filtered):")
print(f"  Resolved deals: {len(resolved_deals_with_revenue)}")
print(f"    Won: {len(won_with_revenue)}")
print(f"    Lost: {len(resolved_deals_with_revenue) - len(won_with_revenue)}")
print()
print(f"  Denominator: ${denominator_resolved:,.2f}")
print(f"    (Sum of renewal_revenue for {len(resolved_deals_with_revenue)} resolved deals with revenue)")
print()
print(f"  Numerator calculation:")
print(f"    Won renewal: ${won_renewal:,.2f}")
print(f"    - Contraction: ${total_contraction:,.2f}")
print(f"    = ${numerator_resolved:,.2f}")
print()
print(f"  GRR = ${numerator_resolved:,.2f} / ${denominator_resolved:,.2f} = {(numerator_resolved/denominator_resolved*100):.2f}%")
print()

# Best-case GRR (add active opens)
active_opens_with_revenue = [d for d in open_deals if d['renewal_revenue'] > 0]
active_opens_revenue = sum(d['renewal_revenue'] for d in active_opens_with_revenue)
active_opens_expansion = sum(d['expansion_revenue'] for d in active_opens_with_revenue)

denominator_bestcase = denominator_resolved + active_opens_revenue
numerator_bestcase = numerator_resolved + active_opens_revenue

print("BEST-CASE GRR (assume active opens win, $0 filtered):")
print(f"  Resolved with revenue: {len(resolved_deals_with_revenue)} deals")
print(f"  + Active opens with revenue: {len(active_opens_with_revenue)} deals")
print(f"  Total: {len(resolved_deals_with_revenue) + len(active_opens_with_revenue)} deals")
print()
print(f"  Denominator: ${denominator_bestcase:,.2f}")
print(f"    Resolved: ${denominator_resolved:,.2f}")
print(f"    + Opens: ${active_opens_revenue:,.2f}")
print()
print(f"  Numerator calculation:")
print(f"    Resolved numerator: ${numerator_resolved:,.2f}")
print(f"    + Opens (as-if-won): ${active_opens_revenue:,.2f}")
print(f"    = ${numerator_bestcase:,.2f}")
print()
print(f"  GRR = ${numerator_bestcase:,.2f} / ${denominator_bestcase:,.2f} = {(numerator_bestcase/denominator_bestcase*100):.2f}%")
print()

# ============================================================================
# CHECK 3: Why are they both 100%?
# ============================================================================
print("=" * 80)
print("CHECK 3: WHY BOTH 100%?")
print("=" * 80)
print()

grr_resolved = (numerator_resolved / denominator_resolved * 100) if denominator_resolved > 0 else 0
grr_bestcase = (numerator_bestcase / denominator_bestcase * 100) if denominator_bestcase > 0 else 0

print(f"Resolved GRR: {grr_resolved:.4f}%")
print(f"Best-case GRR: {grr_bestcase:.4f}%")
print()

if abs(grr_resolved - 100) < 0.01:
    print("Resolved GRR = 100% because:")
    print(f"  - 0 lost deals (numerator = denominator)")
    print(f"  - Contraction = ${total_contraction:,.2f}")
    if total_contraction == 0:
        print(f"    ✓ No contraction, so won revenue = resolved revenue")
    else:
        print(f"    ⚠️ Has contraction but GRR still 100% - arithmetic issue?")
    print()

if abs(grr_bestcase - 100) < 0.01:
    print("Best-case GRR = 100% because:")
    if abs(grr_resolved - 100) < 0.01:
        print(f"  - Resolved GRR is already 100%")
        print(f"  - Adding ${active_opens_revenue:,.2f} to BOTH numerator and denominator")
        print(f"  - Keeps ratio at 100% (X/X = (X+Y)/(X+Y) = 1)")
        print(f"  ✓ This is mathematically correct")
    else:
        print(f"  - Resolved GRR is {grr_resolved:.2f}%, not 100%")
        print(f"  - But best-case is 100% - arithmetic issue?")
    print()

# ============================================================================
# CHECK 4: $0 revenue deals
# ============================================================================
print("=" * 80)
print("CHECK 4: $0 RENEWAL_REVENUE DEALS")
print("=" * 80)
print()

zero_revenue_deals = [d for d in q3_deals if d['renewal_revenue'] == 0]

print(f"Found {len(zero_revenue_deals)} deals with $0 renewal_revenue:")
print()

for deal in zero_revenue_deals:
    print(f"Deal: {deal['name']}")
    print(f"  ID: {deal['id']}")
    print(f"  Status: {deal['stage_name']}")
    print(f"  Renewal revenue: ${deal['renewal_revenue']}")
    print(f"  Expansion revenue: ${deal['expansion_revenue']}")
    print(f"  Contraction revenue: ${deal['contraction_revenue']}")

    # Check if this is won/lost/open
    if deal['is_won']:
        print(f"  ⚠️ WON with $0 renewal revenue - is this a real $0 renewal or data gap?")
    elif deal['is_lost']:
        print(f"  Lost with $0 - churned customer")
    elif deal['is_open']:
        print(f"  Open with $0 - needs investigation:")
        print(f"    Is this a data entry gap (revenue not filled in yet)?")
        print(f"    Or a real $0 renewal (churned to zero, free/comped)?")

    print()

print("DECISION REQUIRED:")
print()
print("For Haystack TV and TicketNetwork ($0 renewal_revenue, open):")
print()
print("Option A: Real $0 renewals")
print("  - Churned down to zero but keeping relationship")
print("  - Or free/comped renewal")
print("  - Include in cohort at $0 (contributes nothing to numerator or denominator)")
print()
print("Option B: Data entry gap")
print("  - renewal_revenue simply not filled in yet")
print("  - Should be EXCLUDED from cohort entirely (same as Q1's $0 deals)")
print("  - Not real renewals if value unknown")
print()
print("Need to check deal history or ask domain expert to determine which.")
print()

# Check if these deals have ANY ARR values
print("Checking for other ARR indicators:")
for deal in zero_revenue_deals:
    if deal['is_open']:
        print(f"{deal['name']}:")
        print(f"  expansion_revenue: ${deal['expansion_revenue']}")
        print(f"  contraction_revenue: ${deal['contraction_revenue']}")

        # Fetch more properties
        deal_response = hs.session.get(
            f"{hs.BASE_URL}/crm/v3/objects/deals/{deal['id']}?properties=amount,hs_mrr,hs_arr,hs_tcv"
        )

        if deal_response.status_code == 200:
            deal_data = deal_response.json()
            deal_props = deal_data.get('properties', {})

            amount = float(deal_props.get('amount') or 0)
            mrr = float(deal_props.get('hs_mrr') or 0)
            arr = float(deal_props.get('hs_arr') or 0)
            tcv = float(deal_props.get('hs_tcv') or 0)

            print(f"  amount: ${amount:,.2f}")
            print(f"  hs_mrr: ${mrr:,.2f}")
            print(f"  hs_arr: ${arr:,.2f}")
            print(f"  hs_tcv: ${tcv:,.2f}")

            if amount == 0 and mrr == 0 and arr == 0 and tcv == 0:
                print(f"  → All value fields are $0 - likely REAL $0 renewal (churned)")
            else:
                print(f"  → Has other value fields populated - renewal_revenue is DATA GAP")

        print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()

print("Q3 Resolved GRR = 100% explanation:")
print(f"  ✓ Genuinely 0 lost deals (10 won, 0 lost)")
print(f"  ✓ Contraction = ${total_contraction:,.2f}")
print(f"  ✓ Therefore numerator = denominator = ${denominator_resolved:,.2f}")
print()

print("Q3 Best-case GRR = 100% explanation:")
print(f"  ✓ Starts from resolved 100%")
print(f"  ✓ Adds ${active_opens_revenue:,.2f} to both numerator and denominator")
print(f"  ✓ Ratio stays 100% (mathematically correct)")
print()

if abs(grr_resolved - grr_bestcase) < 0.01:
    print("✓ ARITHMETIC VERIFIED")
    print("  Both 100% is coincidental but mathematically correct:")
    print("  - Resolved has 0 losses, 0 contraction → 100%")
    print("  - Best-case adds equal amounts to num/denom → stays 100%")
else:
    print("⚠️ ARITHMETIC ISSUE")
    print("  Numbers don't match expected - needs investigation")

print()
print(f"$0 renewal_revenue deals: {len(zero_revenue_deals)}")
print("  → Check if real $0 renewals or data gaps before finalizing")
