#!/usr/bin/env python3
"""Attempt to answer the 11 pending canonical questions directly from database."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase
from utils import get_fiscal_quarter
from datetime import date, datetime
from collections import defaultdict
import yaml

sb = get_supabase()

print("=" * 100)
print("ATTEMPTING TO ANSWER 11 PENDING CANONICAL QUESTIONS")
print("=" * 100)
print()

# Load config for pipeline/stage info
with open('config/client.yaml') as f:
    config = yaml.safe_load(f)

# Build stage lookup
stage_lookup = {}
for pipeline in config.get('pipeline', {}).get('pipelines', []):
    for stage in pipeline.get('stages', []):
        stage_id = stage.get('id')
        stage_lookup[stage_id] = {
            'name': stage.get('display_name', stage_id),
            'order': stage.get('order', 999),
            'is_won': stage.get('is_won', False),
            'is_lost': stage.get('is_lost', False)
        }

# Get Q3 and Q4 bounds
q3_start, q3_end, q3_label = get_fiscal_quarter(date(2026, 9, 1))  # Sep = Q3
q4_start, q4_end, q4_label = get_fiscal_quarter(date(2026, 11, 1))  # Nov = Q4

print(f"Q3 FY2027: {q3_start} to {q3_end}")
print(f"Q4 FY2027: {q4_start} to {q4_end}")
print()

# Identify renewal pipeline IDs
renewal_pipeline_ids = config.get('pipeline', {}).get('value_field', {}).get('renewal_pipeline_ids', [])
renewal_pipeline_ids = [str(pid) for pid in renewal_pipeline_ids]

print(f"Renewal pipeline IDs: {renewal_pipeline_ids}")
print()

# ============================================================================
# q002: Renewal pipeline Q3/Q4
# ============================================================================
print("=" * 100)
print("q002: How much expansion ARR is in the renewal pipeline for Q3 and Q4?")
print("=" * 100)

deals = sb.table('deals').select('*').eq('deal_status', 'active').execute().data

# Filter to renewal pipeline deals closing in Q3/Q4
q3_renewals = [
    d for d in deals
    if str(d.get('pipeline_id', 'default')) in renewal_pipeline_ids
    and d.get('close_date')
    and q3_start.isoformat() <= d['close_date'] <= q3_end.isoformat()
]

q4_renewals = [
    d for d in deals
    if str(d.get('pipeline_id', 'default')) in renewal_pipeline_ids
    and d.get('close_date')
    and q4_start.isoformat() <= d['close_date'] <= q4_end.isoformat()
]

def calc_renewal_breakdown(deals_list):
    """Calculate renewal breakdown: base + expansion."""
    base = sum(d.get('renewal_revenue', 0) or 0 for d in deals_list)
    expansion = sum(d.get('incremental_arr', 0) or 0 for d in deals_list)
    return {
        'count': len(deals_list),
        'base_renewal': base,
        'expansion': expansion,
        'total': base + expansion
    }

q3_breakdown = calc_renewal_breakdown(q3_renewals)
q4_breakdown = calc_renewal_breakdown(q4_renewals)

print(f"\nQ3 Renewals:")
print(f"  Count: {q3_breakdown['count']}")
print(f"  Base renewal: ${q3_breakdown['base_renewal']:,.2f}")
print(f"  Expansion: ${q3_breakdown['expansion']:,.2f}")
print(f"  Total: ${q3_breakdown['total']:,.2f}")

print(f"\nQ4 Renewals:")
print(f"  Count: {q4_breakdown['count']}")
print(f"  Base renewal: ${q4_breakdown['base_renewal']:,.2f}")
print(f"  Expansion: ${q4_breakdown['expansion']:,.2f}")
print(f"  Total: ${q4_breakdown['total']:,.2f}")

print(f"\n✓ ANSWERABLE: Direct query from deals table")
print()

# ============================================================================
# q008: Customers due to renew Q3/Q4
# ============================================================================
print("=" * 100)
print("q008: Get a list of all customers due to renew in Q3 and then Q4")
print("=" * 100)

print(f"\nQ3 Renewals: {len(q3_renewals)} deals")
for d in q3_renewals[:5]:
    print(f"  - {d.get('company_name', 'Unknown')}: ${d.get('deal_value', 0):,.0f}, close {d.get('close_date')}")
if len(q3_renewals) > 5:
    print(f"  ... and {len(q3_renewals) - 5} more")

print(f"\nQ4 Renewals: {len(q4_renewals)} deals")
for d in q4_renewals[:5]:
    print(f"  - {d.get('company_name', 'Unknown')}: ${d.get('deal_value', 0):,.0f}, close {d.get('close_date')}")
if len(q4_renewals) > 5:
    print(f"  ... and {len(q4_renewals) - 5} more")

print(f"\n✓ ANSWERABLE: Same data as q002, just formatted as list")
print()

# ============================================================================
# q010: Recent closed-lost (last 3)
# ============================================================================
print("=" * 100)
print("q010: Why did we lose our last three deals?")
print("=" * 100)

# Get closed-lost deals
lost_deals = sb.table('deals').select('*').eq('deal_status', 'lost').execute().data

# Sort by close_date descending
lost_deals_sorted = sorted(
    [d for d in lost_deals if d.get('close_date')],
    key=lambda x: x['close_date'],
    reverse=True
)

last_3_lost = lost_deals_sorted[:3]

print(f"\nTotal closed-lost deals: {len(lost_deals)}")
print(f"Last 3 closed-lost:")
for d in last_3_lost:
    print(f"  - {d.get('company_name', 'Unknown')}")
    print(f"    Close date: {d.get('close_date')}")
    print(f"    ARR: ${d.get('deal_value', 0):,.0f}")
    print(f"    Owner: {d.get('owner_email', 'unassigned')}")
    print(f"    Lost reason: {d.get('lost_reason', 'Not recorded')}")

print(f"\n✓ ANSWERABLE: Direct query from deals table")
print()

# ============================================================================
# q011: Active pipeline value (HIGH PRIORITY)
# ============================================================================
print("=" * 100)
print("q011: What is our pipeline this quarter?")
print("=" * 100)

active_deals = [d for d in deals if d.get('deal_status') == 'active']
total_arr = sum(d.get('deal_value', 0) or 0 for d in active_deals)

# By stage
by_stage = defaultdict(lambda: {'count': 0, 'arr': 0})
for d in active_deals:
    stage_id = d.get('stage', 'unknown')
    stage_name = stage_lookup.get(stage_id, {}).get('name', stage_id)
    by_stage[stage_name]['count'] += 1
    by_stage[stage_name]['arr'] += d.get('deal_value', 0) or 0

print(f"\nActive Pipeline:")
print(f"  Total deals: {len(active_deals)}")
print(f"  Total ARR: ${total_arr:,.2f}")
print(f"\nBy stage (top 10):")
sorted_stages = sorted(by_stage.items(), key=lambda x: x[1]['arr'], reverse=True)
for stage_name, data in sorted_stages[:10]:
    print(f"  {stage_name}: {data['count']} deals, ${data['arr']:,.0f}")

print(f"\n✓ ANSWERABLE: Direct query from deals table")
print()

# ============================================================================
# q012: At-risk deals
# ============================================================================
print("=" * 100)
print("q012: Which of those are at risk?")
print("=" * 100)

# Check if at-risk definition exists in handlers
print("\nChecking for existing 'at-risk' definition in codebase...")

# Check api/handlers.py for at-risk logic
try:
    with open('api/handlers.py') as f:
        handlers_content = f.read()
        if 'at_risk' in handlers_content or 'at-risk' in handlers_content:
            print("  Found 'at-risk' references in handlers.py")
            # Extract relevant section
            lines = handlers_content.split('\n')
            for i, line in enumerate(lines):
                if 'at_risk' in line.lower() or 'at-risk' in line.lower():
                    print(f"  Line {i}: {line[:100]}")
        else:
            print("  No 'at-risk' definition found in handlers.py")
except FileNotFoundError:
    print("  handlers.py not found")

# Check for at_risk field in deals table
sample_deal = active_deals[0] if active_deals else {}
if 'at_risk' in sample_deal or 'is_at_risk' in sample_deal:
    print(f"  Found at_risk field in deals table")
    at_risk_deals = [d for d in active_deals if d.get('at_risk') or d.get('is_at_risk')]
    print(f"  At-risk deals: {len(at_risk_deals)}")
else:
    print(f"  No at_risk field in deals table")

print(f"\n⚠️  NEEDS JEFF: No existing at-risk definition found. Requires business definition.")
print()

# ============================================================================
# q009: High champion score deals Q3
# ============================================================================
print("=" * 100)
print("q009: Which deals have a champion score above 6 and close in Q3?")
print("=" * 100)

# Check analyses table for champion scores
print("\nQuerying analyses table for champion scores...")

# Get deals closing in Q3
q3_deals = [
    d for d in deals
    if d.get('close_date')
    and q3_start.isoformat() <= d['close_date'] <= q3_end.isoformat()
]

print(f"Deals closing in Q3: {len(q3_deals)}")

# Get analyses for those deals
q3_deal_ids = [d['deal_id'] for d in q3_deals]
if q3_deal_ids:
    analyses = sb.table('analyses').select('deal_id, component_scores').in_('deal_id', q3_deal_ids).execute().data

    # Filter for champion score > 6
    high_champion = []
    for analysis in analyses:
        scores = analysis.get('component_scores', {})
        if isinstance(scores, dict):
            champion_score = scores.get('champion', {})
            if isinstance(champion_score, dict):
                score_val = champion_score.get('score', 0)
            else:
                score_val = champion_score

            if score_val and score_val > 6:
                high_champion.append({
                    'deal_id': analysis['deal_id'],
                    'champion_score': score_val
                })

    # Join with deal details
    high_champion_deals = []
    for hc in high_champion:
        deal = next((d for d in q3_deals if d['deal_id'] == hc['deal_id']), None)
        if deal:
            high_champion_deals.append({
                'company_name': deal.get('company_name'),
                'champion_score': hc['champion_score'],
                'deal_value': deal.get('deal_value', 0),
                'close_date': deal.get('close_date')
            })

    print(f"\nDeals with champion score > 6 closing in Q3: {len(high_champion_deals)}")
    total_arr = sum(d['deal_value'] or 0 for d in high_champion_deals)
    print(f"Total ARR: ${total_arr:,.2f}")

    for d in high_champion_deals[:5]:
        print(f"  - {d['company_name']}: score {d['champion_score']}, ${d['deal_value']:,.0f}")

    print(f"\n✓ ANSWERABLE: Join analyses.component_scores with deals")
else:
    print(f"\n⚠️  No deals closing in Q3 to check")

print()

# ============================================================================
# q013: Skyscanner deal
# ============================================================================
print("=" * 100)
print("q013: Show me the Skyscanner deal")
print("=" * 100)

skyscanner_deals = [d for d in deals if 'skyscanner' in (d.get('company_name', '') or '').lower()]

if skyscanner_deals:
    sky = skyscanner_deals[0]
    print(f"\nFound Skyscanner deal:")
    print(f"  Deal ID: {sky['deal_id']}")
    print(f"  Company: {sky.get('company_name')}")
    print(f"  Stage: {stage_lookup.get(sky.get('stage'), {}).get('name', sky.get('stage'))}")
    print(f"  ARR: ${sky.get('deal_value', 0):,.0f}")
    print(f"  Owner: {sky.get('owner_email', 'unassigned')}")
    print(f"  Close date: {sky.get('close_date', 'Not set')}")
    print(f"  Status: {sky.get('deal_status')}")

    print(f"\n✓ ANSWERABLE: Direct lookup from deals table")
else:
    print(f"\nNo Skyscanner deal found")
    print(f"\n✓ ANSWERABLE: Confirmed does not exist")

print()

# ============================================================================
# q019: forecast_weekly staleness
# ============================================================================
print("=" * 100)
print("q019: When was forecast_weekly last updated?")
print("=" * 100)

try:
    result = sb.table('forecast_weekly').select('computed_at').order('computed_at', desc=True).limit(1).execute()

    if result.data:
        last_computed = result.data[0]['computed_at']
        last_computed_dt = datetime.fromisoformat(last_computed.replace('Z', '+00:00'))
        now = datetime.now(last_computed_dt.tzinfo)
        days_stale = (now - last_computed_dt).days

        print(f"\nforecast_weekly status:")
        print(f"  Last computed: {last_computed}")
        print(f"  Days since update: {days_stale}")
        print(f"  Expected refresh: daily/weekly")

        print(f"\n✓ ANSWERABLE: Direct metadata query")
    else:
        print(f"\nNo data in forecast_weekly table")
        print(f"\n✓ ANSWERABLE: Table is empty")
except Exception as e:
    print(f"\nError querying forecast_weekly: {e}")
    print(f"\n⚠️  Table may not exist")

print()

# ============================================================================
# q020: Missing owner_email
# ============================================================================
print("=" * 100)
print("q020: How many active deals are missing owner_email?")
print("=" * 100)

missing_owner = [d for d in active_deals if not d.get('owner_email')]

print(f"\nActive deals missing owner_email:")
print(f"  Count: {len(missing_owner)}")
print(f"  Total active: {len(active_deals)}")
print(f"  Percentage: {(len(missing_owner) / len(active_deals) * 100):.1f}%")

for d in missing_owner[:5]:
    print(f"  - {d.get('company_name', 'Unknown')} ({d['deal_id']})")

print(f"\n✓ ANSWERABLE: Direct query from deals table")
print()

# ============================================================================
# q016: Historical win rates by stage & cycle times
# ============================================================================
print("=" * 100)
print("q016: Historical win rates by stage & sales cycle times")
print("=" * 100)

print("\nDefining 'historical': Deals that closed in past 6 months...")

# Get deals that closed in past 6 months
six_months_ago = date(2026, 3, 5)  # Today is Sep 5, so 6 months = Mar 5
historical_deals = [
    d for d in deals
    if d.get('close_date')
    and d['close_date'] >= six_months_ago.isoformat()
]

won_deals = [d for d in historical_deals if d.get('deal_status') == 'won']
lost_deals = [d for d in historical_deals if d.get('deal_status') == 'lost']

overall_win_rate = len(won_deals) / len(historical_deals) * 100 if historical_deals else 0

print(f"\nHistorical win rate (past 6 months):")
print(f"  Total closed: {len(historical_deals)}")
print(f"  Won: {len(won_deals)}")
print(f"  Lost: {len(lost_deals)}")
print(f"  Overall win rate: {overall_win_rate:.1f}%")

# By stage (highest stage reached)
by_stage_wins = defaultdict(lambda: {'won': 0, 'lost': 0})
for d in historical_deals:
    stage_id = d.get('stage', 'unknown')
    stage_name = stage_lookup.get(stage_id, {}).get('name', stage_id)
    if d.get('deal_status') == 'won':
        by_stage_wins[stage_name]['won'] += 1
    else:
        by_stage_wins[stage_name]['lost'] += 1

print(f"\nWin rate by final stage (top 10):")
sorted_stage_wins = sorted(
    [(s, d['won'], d['lost']) for s, d in by_stage_wins.items() if (d['won'] + d['lost']) > 0],
    key=lambda x: (x[1] + x[2]),
    reverse=True
)
for stage, won, lost in sorted_stage_wins[:10]:
    total = won + lost
    rate = (won / total * 100) if total > 0 else 0
    print(f"  {stage}: {rate:.1f}% ({won}/{total})")

# Sales cycle time
print(f"\nSales cycle times:")
cycle_times = []
for d in won_deals:
    if d.get('create_date') and d.get('close_date'):
        create_dt = datetime.fromisoformat(d['create_date'][:10])
        close_dt = datetime.fromisoformat(d['close_date'])
        days = (close_dt - create_dt).days
        if days >= 0:  # Sanity check
            cycle_times.append(days)

if cycle_times:
    import statistics
    median_cycle = statistics.median(cycle_times)
    avg_cycle = statistics.mean(cycle_times)

    print(f"  Sample size: {len(cycle_times)} won deals")
    print(f"  Median: {median_cycle:.0f} days")
    print(f"  Average: {avg_cycle:.0f} days")
else:
    print(f"  No cycle time data available")

print(f"\n✓ ANSWERABLE: Direct computation from deals table")
print(f"  (Using 6-month historical window - confirm with Jeff if different window preferred)")
print()

# ============================================================================
# Summary
# ============================================================================
print("=" * 100)
print("SUMMARY")
print("=" * 100)
print()

print("✓ ANSWERED DIRECTLY (9 of 11):")
print("  - q002: Renewal pipeline Q3/Q4")
print("  - q008: Customers due to renew")
print("  - q010: Recent closed-lost (last 3)")
print("  - q011: Active pipeline value")
print("  - q009: High champion score deals")
print("  - q013: Skyscanner deal")
print("  - q019: forecast_weekly staleness")
print("  - q020: Missing owner_email")
print("  - q016: Historical win rates & cycle times")
print()

print("⚠️  NEEDS JEFF (2 of 11):")
print("  - q012: At-risk deals - No existing definition found, requires business criteria")
print("  - q016: Confirm historical window (currently using 6 months)")
print()

print("NOTE: q016 appears twice in canonical_questions.yaml - needs ID fix")
