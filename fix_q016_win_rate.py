#!/usr/bin/env python3
"""Fix q016 - Historical win rates by fetching ALL deals, not just active."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase
from datetime import date, datetime
from collections import defaultdict
import yaml
import statistics

sb = get_supabase()

print("=" * 100)
print("q016: Historical Win Rates & Sales Cycle Times (FIXED)")
print("=" * 100)
print()

# Load config for stage lookup
with open('config/client.yaml') as f:
    config = yaml.safe_load(f)

# Build stage lookup
stage_lookup = {}
for pipeline in config.get('pipeline', {}).get('pipelines', []):
    for stage in pipeline.get('stages', []):
        stage_id = stage.get('id')
        stage_lookup[stage_id] = {
            'name': stage.get('display_name', stage_id),
            'order': stage.get('order', 999)
        }

# Fetch ALL deals (not just active)
print("Fetching ALL deals (active, won, lost)...")
all_deals = sb.table('deals').select('*').execute().data
print(f"Total deals in database: {len(all_deals)}")
print()

# Define historical window: past 6 months
six_months_ago = date(2026, 3, 5)  # Sep 5 - 6 months = Mar 5
print(f"Historical window: {six_months_ago} to 2026-09-05 (6 months)")
print()

# Filter to deals that closed in past 6 months
historical_deals = [
    d for d in all_deals
    if d.get('close_date')
    and d['close_date'] >= six_months_ago.isoformat()
    and d.get('deal_status') in ['won', 'lost']
]

won_deals = [d for d in historical_deals if d.get('deal_status') == 'won']
lost_deals = [d for d in historical_deals if d.get('deal_status') == 'lost']

overall_win_rate = (len(won_deals) / len(historical_deals) * 100) if historical_deals else 0

print("=" * 100)
print("OVERALL WIN RATE")
print("=" * 100)
print(f"Total closed (won + lost): {len(historical_deals)}")
print(f"Won: {len(won_deals)}")
print(f"Lost: {len(lost_deals)}")
print(f"Overall win rate: {overall_win_rate:.1f}%")
print()

# Win rate by stage (final stage before close)
print("=" * 100)
print("WIN RATE BY STAGE")
print("=" * 100)

by_stage_wins = defaultdict(lambda: {'won': 0, 'lost': 0})
for d in historical_deals:
    stage_id = d.get('stage', 'unknown')
    stage_name = stage_lookup.get(stage_id, {}).get('name', stage_id)
    if d.get('deal_status') == 'won':
        by_stage_wins[stage_name]['won'] += 1
    else:
        by_stage_wins[stage_name]['lost'] += 1

# Sort by total volume
sorted_stages = sorted(
    [(s, d['won'], d['lost']) for s, d in by_stage_wins.items()],
    key=lambda x: (x[1] + x[2]),
    reverse=True
)

by_stage_list = []
for stage, won, lost in sorted_stages:
    total = won + lost
    rate = (won / total * 100) if total > 0 else 0
    print(f"  {stage}: {rate:.1f}% ({won} won / {total} total)")
    by_stage_list.append({
        'stage_name': stage,
        'win_rate': round(rate, 1),
        'won_count': won,
        'total_count': total
    })

print()

# Sales cycle times
print("=" * 100)
print("SALES CYCLE TIMES")
print("=" * 100)

cycle_times = []
for d in won_deals:
    if d.get('create_date') and d.get('close_date'):
        try:
            # Handle both date and datetime strings
            create_str = d['create_date'][:10] if len(d['create_date']) > 10 else d['create_date']
            close_str = d['close_date'][:10] if len(d['close_date']) > 10 else d['close_date']

            create_dt = datetime.fromisoformat(create_str)
            close_dt = datetime.fromisoformat(close_str)

            days = (close_dt - create_dt).days
            if days >= 0:  # Sanity check
                cycle_times.append(days)
        except Exception as e:
            print(f"  Warning: Could not parse dates for deal {d.get('deal_id')}: {e}")
            continue

if cycle_times:
    median_days = statistics.median(cycle_times)
    mean_days = statistics.mean(cycle_times)
    print(f"Won deals with cycle data: {len(cycle_times)}")
    print(f"Median cycle time: {median_days:.0f} days")
    print(f"Mean cycle time: {mean_days:.1f} days")
    print(f"Min: {min(cycle_times)} days")
    print(f"Max: {max(cycle_times)} days")
else:
    median_days = None
    print("No cycle time data available (missing create_date or close_date)")

print()

# Cycle time by stage
print("=" * 100)
print("CYCLE TIME BY STAGE")
print("=" * 100)

cycle_by_stage = defaultdict(list)
for d in won_deals:
    if d.get('create_date') and d.get('close_date'):
        stage_id = d.get('stage', 'unknown')
        stage_name = stage_lookup.get(stage_id, {}).get('name', stage_id)

        try:
            create_str = d['create_date'][:10] if len(d['create_date']) > 10 else d['create_date']
            close_str = d['close_date'][:10] if len(d['close_date']) > 10 else d['close_date']

            create_dt = datetime.fromisoformat(create_str)
            close_dt = datetime.fromisoformat(close_str)

            days = (close_dt - create_dt).days
            if days >= 0:
                cycle_by_stage[stage_name].append(days)
        except:
            continue

by_stage_cycle_list = []
for stage, times in sorted(cycle_by_stage.items(), key=lambda x: len(x[1]), reverse=True):
    if times:
        median_stage_days = statistics.median(times)
        print(f"  {stage}: {median_stage_days:.0f} days median ({len(times)} won deals)")
        by_stage_cycle_list.append({
            'stage_name': stage,
            'median_days_in_stage': round(median_stage_days, 0),
            'sample_size': len(times)
        })

print()
print("=" * 100)
print("VERIFIED VALUE FOR canonical_questions.yaml")
print("=" * 100)
print()
print("verified_value:")
print(f"  overall_win_rate: {overall_win_rate:.1f}")
print(f"  overall_median_cycle_days: {int(median_days) if median_days else 'null'}")
print(f"  by_stage:")
for stage_data in by_stage_list[:5]:  # Top 5 stages
    print(f"    - stage_name: \"{stage_data['stage_name']}\"")
    print(f"      win_rate: {stage_data['win_rate']}")
    print(f"      sample_size: {stage_data['total_count']}")
print(f"  date_range: \"{six_months_ago} to 2026-09-05\"")
print(f"  sample_size: {len(historical_deals)}")
print(f"  note: \"Historical win rate from past 6 months of closed deals. Sep 5, 2026.\"")
