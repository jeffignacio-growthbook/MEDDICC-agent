#!/usr/bin/env python3
"""
Stale deal diagnostic for Q3 2026 open deals.

Same criteria as Dribbleup/Joyteractive check:
- >180 days past close_date OR
- (No activity >60 days AND >90 days past close)

Exclude confirmed stale from best-case GRR numerator.
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
print("Q3 2026 OPEN DEALS STALE DIAGNOSTIC")
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

# Q3 2026 period
q3_start = datetime(2026, 7, 1, tzinfo=tz.utc)
q3_end = datetime(2026, 9, 30, 23, 59, 59, tzinfo=tz.utc)

print(f"Q3 2026: {q3_start.strftime('%Y-%m-%d')} to {q3_end.strftime('%Y-%m-%d')}")
print(f"Today: {datetime.now(tz.utc).strftime('%Y-%m-%d')} (23 days until Q3 ends)")
print()

# Fetch Q3 renewal deals
properties = [
    'dealname',
    'closedate',
    'dealstage',
    'renewal_revenue',
    'contraction_revenue',
    'expansion_revenue',
    'createdate',
    'hs_lastmodifieddate',
    'notes_last_updated',
    'notes_last_contacted',
    'num_notes',
    'num_associated_contacts',
    'hs_date_entered_1297321618'  # Upcoming Renewal
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

# Filter to Q3 open deals
now = datetime.now(tz.utc)
q3_open_deals = []

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
    if stage in [CLOSED_WON_STAGE_ID, CLOSED_LOST_STAGE_ID]:
        continue

    renewal_revenue = float(props.get('renewal_revenue') or 0)

    q3_open_deals.append({
        'id': deal.get('id'),
        'name': props.get('dealname', 'Unknown'),
        'closedate': closedate,
        'stage': stage,
        'stage_name': STAGE_NAMES.get(stage, f'Unknown ({stage})'),
        'renewal_revenue': renewal_revenue,
        'contraction_revenue': float(props.get('contraction_revenue') or 0),
        'expansion_revenue': float(props.get('expansion_revenue') or 0),
        'props': props
    })

print(f"Found {len(q3_open_deals)} open deals in Q3 2026")
print()

# Diagnose each deal
stale_deals = []
active_deals = []

print("=" * 80)
print("INDIVIDUAL DEAL DIAGNOSTICS")
print("=" * 80)
print()

for deal in sorted(q3_open_deals, key=lambda x: x['closedate']):
    props = deal['props']

    print(f"Deal: {deal['name']}")
    print(f"  Close date: {deal['closedate'].strftime('%Y-%m-%d')}")
    print(f"  Stage: {deal['stage_name']}")
    print(f"  Renewal revenue: ${deal['renewal_revenue']:,.2f}")

    # Calculate days past close
    days_past_close = (now - deal['closedate']).days

    if days_past_close > 0:
        print(f"  Days past close: {days_past_close}")
    else:
        print(f"  Days until close: {abs(days_past_close)}")

    # Last activity
    last_modified_str = props.get('hs_lastmodifieddate')
    days_since_modified = None
    if last_modified_str:
        try:
            last_modified = datetime.fromisoformat(last_modified_str.replace('Z', '+00:00'))
            days_since_modified = (now - last_modified).days
            print(f"  Last modified: {last_modified.strftime('%Y-%m-%d')} ({days_since_modified} days ago)")
        except:
            pass

    # Notes
    num_notes = props.get('num_notes')
    if num_notes:
        print(f"  Notes: {num_notes}")

    # Stage entry
    entry_str = props.get('hs_date_entered_1297321618')
    days_in_stage = None
    if entry_str:
        try:
            entry_date = datetime.fromisoformat(entry_str.replace('Z', '+00:00'))
            days_in_stage = (now - entry_date).days
            print(f"  Days in stage: {days_in_stage}")
        except:
            pass

    print()

    # STALE CRITERIA (same as Q1 diagnostic)
    stale_indicators = []

    # Criterion 1: >180 days past close date
    if days_past_close > 180:
        stale_indicators.append(f">180 days past close ({days_past_close} days)")

    # Criterion 2: No activity in >60 days
    if days_since_modified and days_since_modified > 60:
        stale_indicators.append(f"No activity in {days_since_modified} days")

    # Criterion 3: >90 days in same stage
    if days_in_stage and days_in_stage > 90:
        stale_indicators.append(f"{days_in_stage} days in same stage")

    # Determine stale status
    is_stale = False

    if days_past_close > 180:
        # Definitely stale if >180 days past close
        is_stale = True
    elif len(stale_indicators) >= 2:
        # Stale if 2+ indicators (e.g., no activity + long in stage)
        is_stale = True

    if stale_indicators:
        print(f"  Stale indicators: {len(stale_indicators)}")
        for indicator in stale_indicators:
            print(f"    - {indicator}")
        print()

    if is_stale:
        print(f"  DETERMINATION: ⚠️ STALE/ABANDONED")
        print(f"    → Exclude from best-case GRR numerator")
        stale_deals.append(deal)
    else:
        print(f"  DETERMINATION: ✓ ACTIVE/IN PLAY")
        print(f"    → Include in best-case GRR numerator")
        active_deals.append(deal)

    print()
    print("-" * 80)
    print()

# Summary
print("=" * 80)
print("SUMMARY")
print("=" * 80)
print()

print(f"Total Q3 open deals: {len(q3_open_deals)}")
print(f"  Active/in play: {len(active_deals)}")
print(f"  Stale/abandoned: {len(stale_deals)}")
print()

if stale_deals:
    print("Stale deals to exclude from best-case:")
    for deal in stale_deals:
        print(f"  - {deal['name']} (${deal['renewal_revenue']:,.0f})")
    print()

# Calculate GRR metrics
print("=" * 80)
print("Q3 GRR CALCULATIONS")
print("=" * 80)
print()

# Get Q3 resolved deals (won/lost)
q3_all_deals = []
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

    if renewal_revenue == 0:
        continue

    q3_all_deals.append({
        'name': props.get('dealname', 'Unknown'),
        'stage': stage,
        'is_won': stage == CLOSED_WON_STAGE_ID,
        'is_lost': stage == CLOSED_LOST_STAGE_ID,
        'is_open': stage not in [CLOSED_WON_STAGE_ID, CLOSED_LOST_STAGE_ID],
        'renewal_revenue': renewal_revenue,
        'contraction_revenue': float(props.get('contraction_revenue') or 0),
        'expansion_revenue': float(props.get('expansion_revenue') or 0)
    })

resolved_deals = [d for d in q3_all_deals if not d['is_open']]
won_deals = [d for d in resolved_deals if d['is_won']]

# 1. Resolved GRR (current reality)
denominator_resolved = sum(d['renewal_revenue'] for d in resolved_deals)
won_renewal = sum(d['renewal_revenue'] for d in won_deals)
total_contraction = sum(d['contraction_revenue'] for d in won_deals)
total_expansion = sum(d['expansion_revenue'] for d in won_deals)

numerator_grr_resolved = won_renewal - total_contraction
grr_resolved = (numerator_grr_resolved / denominator_resolved * 100) if denominator_resolved > 0 else 0

numerator_nrr_resolved = numerator_grr_resolved + total_expansion
nrr_resolved = (numerator_nrr_resolved / denominator_resolved * 100) if denominator_resolved > 0 else 0

print("1. RESOLVED GRR (current reality - 10 deals resolved):")
print(f"   Cohort: {len(resolved_deals)} deals ({len(won_deals)} won, {len(resolved_deals) - len(won_deals)} lost)")
print(f"   Denominator: ${denominator_resolved:,.2f}")
print(f"   GRR: {grr_resolved:.2f}%")
print(f"   NRR: {nrr_resolved:.2f}%")
print()

# 2. Best-case GRR (assume active opens win)
active_open_revenue = sum(d['renewal_revenue'] for d in active_deals)
active_open_expansion = sum(d['expansion_revenue'] for d in active_deals)

denominator_bestcase = denominator_resolved + active_open_revenue
numerator_grr_bestcase = numerator_grr_resolved + active_open_revenue
grr_bestcase = (numerator_grr_bestcase / denominator_bestcase * 100) if denominator_bestcase > 0 else 0

numerator_nrr_bestcase = numerator_nrr_resolved + active_open_revenue + active_open_expansion
nrr_bestcase = (numerator_nrr_bestcase / denominator_bestcase * 100) if denominator_bestcase > 0 else 0

print("2. BEST-CASE GRR (assume active opens win, stale excluded):")
print(f"   Resolved: {len(resolved_deals)} deals (${denominator_resolved:,.2f})")
print(f"   + Active opens: {len(active_deals)} deals (${active_open_revenue:,.2f})")
print(f"   Total denominator: ${denominator_bestcase:,.2f}")
print(f"   GRR: {grr_bestcase:.2f}%")
print(f"   NRR: {nrr_bestcase:.2f}%")
print()

# 3. Comparison: best-case if stale were included
stale_revenue = sum(d['renewal_revenue'] for d in stale_deals)
stale_expansion = sum(d['expansion_revenue'] for d in stale_deals)

denominator_naive = denominator_resolved + active_open_revenue + stale_revenue
numerator_grr_naive = numerator_grr_resolved + active_open_revenue + stale_revenue
grr_naive = (numerator_grr_naive / denominator_naive * 100) if denominator_naive > 0 else 0

numerator_nrr_naive = numerator_nrr_resolved + active_open_revenue + active_open_expansion + stale_revenue + stale_expansion
nrr_naive = (numerator_nrr_naive / denominator_naive * 100) if denominator_naive > 0 else 0

print("3. NAIVE BEST-CASE (if stale were wrongly included):")
print(f"   Total with stale: {len(resolved_deals) + len(active_deals) + len(stale_deals)} deals")
print(f"   Stale revenue: ${stale_revenue:,.2f}")
print(f"   GRR: {grr_naive:.2f}%")
print(f"   NRR: {nrr_naive:.2f}%")
print()

print("Impact of excluding stale:")
print(f"  GRR difference: {grr_naive - grr_bestcase:.2f} ppts (naive - honest)")
print(f"  This is the inflation from counting dead records as wins")
print()

print("=" * 80)
print("FINAL REPORT")
print("=" * 80)
print()

print(f"Q3 2026 GRR (resolved only): {grr_resolved:.2f}% ({len(won_deals)}/{len(resolved_deals)} deals)")
print(f"Q3 2026 GRR (best-case, stale excluded): {grr_bestcase:.2f}% (ceiling among deals genuinely in play)")
print(f"Q3 deals reclassified as stale: {len(stale_deals)}")
print()

print("Honest best-case keeps Q3 ceiling realistic:")
print(f"  Active opens: {len(active_deals)} deals (${active_open_revenue:,.0f})")
print(f"  Stale excluded: {len(stale_deals)} deals (${stale_revenue:,.0f})")
print(f"  Not counting dead records as potential wins")
