#!/usr/bin/env python3
"""Calculate data completeness metrics excluding early stages."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase

sb = get_supabase()

# Get all active deals
result = sb.table('deals').select('deal_id, company_name, owner_email, stage, deal_value, arr_usd').eq('deal_status', 'active').execute()

# Load stage configuration
import yaml
with open(Path(__file__).parent / 'config' / 'client.yaml') as f:
    config = yaml.safe_load(f)

# Build stage order lookup
stage_order = {}
for pipeline in config.get('pipeline', {}).get('pipelines', []):
    for stage in pipeline.get('stages', []):
        stage_id = stage.get('id')
        stage_order[stage_id] = stage.get('order', 999)

# Calculate metrics
all_deals = result.data
no_arr_all = [d for d in all_deals if (d.get('deal_value') or d.get('arr_usd') or 0) == 0]

# Exclude early stages (order 0-2)
mid_late_deals = [d for d in all_deals if stage_order.get(d.get('stage'), 999) >= 3]
no_arr_mid_late = [d for d in mid_late_deals if (d.get('deal_value') or d.get('arr_usd') or 0) == 0]

# Late stages only (order 6+)
late_deals = [d for d in all_deals if stage_order.get(d.get('stage'), 999) >= 6]
no_arr_late = [d for d in late_deals if (d.get('deal_value') or d.get('arr_usd') or 0) == 0]

print("=" * 80)
print("DATA COMPLETENESS: Current vs Stage-Aware Metrics")
print("=" * 80)
print()

print("CURRENT TRIGGER (all active deals):")
print(f"  Total deals:           {len(all_deals)}")
print(f"  Deals without ARR:     {len(no_arr_all)} ({(len(no_arr_all)/len(all_deals))*100:.1f}%)")
print(f"  Threshold:             20%")
print(f"  Status:                🔥 FIRING (30.6% > 20%)")
print()

print("OPTION 1: Exclude Early Stages (order 0-2) from denominator")
print(f"  Mid/late stage deals:  {len(mid_late_deals)}")
print(f"  Without ARR:           {len(no_arr_mid_late)} ({(len(no_arr_mid_late)/len(mid_late_deals))*100:.1f}%)")
print(f"  Threshold:             20%")
if len(no_arr_mid_late)/len(mid_late_deals) > 0.20:
    print(f"  Status:                🔥 STILL FIRING")
else:
    print(f"  Status:                ✓ Would be clean")
print()

print("OPTION 2: Late Stages Only (order 6+)")
print(f"  Late stage deals:      {len(late_deals)}")
print(f"  Without ARR:           {len(no_arr_late)} ({(len(no_arr_late)/len(late_deals))*100:.1f}%)")
print(f"  Threshold:             20%")
if len(late_deals) > 0 and len(no_arr_late)/len(late_deals) > 0.20:
    print(f"  Status:                🔥 STILL FIRING")
else:
    print(f"  Status:                ✓ Would be clean")
print()

print("=" * 80)
print("RECOMMENDATION")
print("=" * 80)

if len(no_arr_mid_late)/len(mid_late_deals) <= 0.20:
    print("✓ EXCLUDE EARLY STAGES from denominator")
    print()
    print("  Rationale:")
    print("  - Early-stage deals (order 0-2) legitimately lack ARR estimates")
    print("  - 97% of no-ARR deals are in these stages")
    print("  - Mid/late stage no-ARR rate is acceptable")
    print()
    print("  Proposed trigger logic:")
    print("  - Count only deals in stages with order >= 3")
    print("  - Keep 20% threshold")
    print(f"  - Result: {len(no_arr_mid_late)}/{len(mid_late_deals)} = {(len(no_arr_mid_late)/len(mid_late_deals))*100:.1f}% (under threshold)")
else:
    print("⚠️  PROBLEM PERSISTS even excluding early stages")
    print()
    print("  Even in mid/late stages:")
    print(f"  - {len(no_arr_mid_late)} of {len(mid_late_deals)} deals ({(len(no_arr_mid_late)/len(mid_late_deals))*100:.1f}%) lack ARR")
    print("  - This IS a data quality problem")
    print()
    print("  Recommendation: Keep current trigger as-is, address data quality")

print()
print("Current early-stage deals by owner (for context):")
early_deals = [d for d in all_deals if stage_order.get(d.get('stage'), 999) <= 2]
no_arr_early = [d for d in early_deals if (d.get('deal_value') or d.get('arr_usd') or 0) == 0]

from collections import Counter
early_owners = Counter(d.get('owner_email', 'unassigned') for d in no_arr_early)
print(f"  Total early-stage no-ARR: {len(no_arr_early)}")
print("  Top 5 owners:")
for owner, count in early_owners.most_common(5):
    print(f"    {owner}: {count} deals")
