#!/usr/bin/env python3
"""Check stage distribution of no-ARR deals to determine if early-stage concentration."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase
from collections import Counter

sb = get_supabase()

# Get all active deals with stage information
result = sb.table('deals').select('deal_id, company_name, owner_email, stage, deal_value, arr_usd, pipeline').eq('deal_status', 'active').execute()

# Load stage configuration to understand stage order
import yaml
with open(Path(__file__).parent / 'config' / 'client.yaml') as f:
    config = yaml.safe_load(f)

# Build stage name lookup
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

# Separate into has-ARR and no-ARR
has_arr_deals = []
no_arr_deals = []

for d in result.data:
    value = d.get('deal_value') if d.get('deal_value') is not None else d.get('arr_usd')
    if value is None or value == 0:
        no_arr_deals.append(d)
    else:
        has_arr_deals.append(d)

print(f"Total active deals: {len(result.data)}")
print(f"Deals with ARR: {len(has_arr_deals)} ({(len(has_arr_deals)/len(result.data))*100:.1f}%)")
print(f"Deals without ARR: {len(no_arr_deals)} ({(len(no_arr_deals)/len(result.data))*100:.1f}%)")
print()

# Stage distribution for NO-ARR deals
no_arr_stages = Counter(d.get('stage') for d in no_arr_deals)

print("=" * 80)
print("STAGE DISTRIBUTION: No-ARR Deals (135)")
print("=" * 80)
print(f"{'Stage Name':<35} {'Count':>6} {'% of No-ARR':>12} {'Stage Order':>12}")
print("-" * 80)

# Sort by stage order
sorted_stages = sorted(
    no_arr_stages.items(),
    key=lambda x: stage_lookup.get(x[0], {}).get('order', 999)
)

early_stage_count = 0
mid_stage_count = 0
late_stage_count = 0

for stage_id, count in sorted_stages:
    stage_info = stage_lookup.get(stage_id, {'name': stage_id, 'order': '?'})
    stage_name = stage_info['name']
    stage_order = stage_info['order']
    pct = (count / len(no_arr_deals)) * 100

    print(f"{stage_name:<35} {count:>6} {pct:>11.1f}% {stage_order:>12}")

    # Categorize by stage order (handle string/int)
    try:
        order_num = int(stage_order) if stage_order != '?' else 999
    except (ValueError, TypeError):
        order_num = 999

    if order_num <= 2:
        early_stage_count += count
    elif order_num <= 5:
        mid_stage_count += count
    else:
        late_stage_count += count

print("-" * 80)
print()

# Summary by stage maturity
print("=" * 80)
print("SUMMARY BY STAGE MATURITY")
print("=" * 80)
print(f"Early stages (order 0-2): {early_stage_count:>6} ({(early_stage_count/len(no_arr_deals))*100:>5.1f}%)")
print(f"Mid stages   (order 3-5): {mid_stage_count:>6} ({(mid_stage_count/len(no_arr_deals))*100:>5.1f}%)")
print(f"Late stages  (order 6+):  {late_stage_count:>6} ({(late_stage_count/len(no_arr_deals))*100:>5.1f}%)")
print()

# Assessment
if early_stage_count / len(no_arr_deals) > 0.5:
    print("✓ ASSESSMENT: No-ARR deals are CONCENTRATED in early stages")
    print("  This is likely a TIMING issue, not data quality problem.")
    print("  Early-stage deals may legitimately not have ARR estimates yet.")
    print()
    print("  RECOMMENDATIONS:")
    print("  1. Exclude early stages from denominator (count only mid/late stage)")
    print("  2. OR raise threshold to account for normal early-stage uncertainty")
    print("  3. OR add stage-aware logic: alert only on mid/late stage no-ARR")
elif late_stage_count / len(no_arr_deals) > 0.3:
    print("⚠️  ASSESSMENT: Significant concentration in LATE stages")
    print("  This IS a data quality problem - late-stage deals should have ARR.")
    print("  20% threshold is appropriate and finding is valid.")
    print()
    print(f"  {late_stage_count} late-stage deals without ARR is actionable.")
else:
    print("📊 ASSESSMENT: Mixed distribution across stages")
    print("  Suggest refining trigger to be stage-aware.")
    print("  Consider separate thresholds or exclude early stages entirely.")

print()
print("=" * 80)
print("COMPARISON: Stage Distribution of Deals WITH ARR")
print("=" * 80)

has_arr_stages = Counter(d.get('stage') for d in has_arr_deals)
sorted_has_arr = sorted(
    has_arr_stages.items(),
    key=lambda x: stage_lookup.get(x[0], {}).get('order', 999)
)

print(f"{'Stage Name':<35} {'Count':>6} {'% of Has-ARR':>14}")
print("-" * 80)
for stage_id, count in sorted_has_arr[:10]:  # Top 10
    stage_info = stage_lookup.get(stage_id, {'name': stage_id})
    stage_name = stage_info['name']
    pct = (count / len(has_arr_deals)) * 100
    print(f"{stage_name:<35} {count:>6} {pct:>13.1f}%")
