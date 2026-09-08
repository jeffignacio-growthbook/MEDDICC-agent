#!/usr/bin/env python3
"""Calculate ground truth for pipeline_value metric."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.field_semantics import is_open, is_renewal_base

sb = create_client(
    os.environ['SUPABASE_URL'],
    os.environ['SUPABASE_SERVICE_KEY']
)

# Fetch all active deals
all_deals = sb.table("deals").select(
    "deal_id,company_name,stage,deal_value,new_arr,expansion_arr,renewal_revenue,pipeline_id"
).execute()

active = [d for d in all_deals.data if is_open(d.get("stage"))]

print(f"Total active deals: {len(active)}")
print()

# Naive: Sum ALL deal_value
naive_total = sum(d.get("deal_value", 0) or 0 for d in active)
print(f"Naive pipeline (all deal_value): ${naive_total:,.2f}")
print()

# Clean: Exclude renewals, sum incremental ARR only
RENEWAL_PIPELINE_ID = "866608541"
non_renewal_deals = [d for d in active if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]

clean_total = sum(d.get("deal_value", 0) or 0 for d in non_renewal_deals)
print(f"Clean pipeline (exclude renewal pipeline): ${clean_total:,.2f}")
print(f"  Non-renewal deals: {len(non_renewal_deals)}")
print()

# Alternative clean: Sum new_arr + expansion_arr (incremental components)
incremental_total = sum(
    (d.get("new_arr", 0) or 0) + (d.get("expansion_arr", 0) or 0)
    for d in active
)
print(f"Clean pipeline (new_arr + expansion_arr): ${incremental_total:,.2f}")
print()

# Show renewal contamination
renewal_deals = [d for d in active if d.get("pipeline_id") == RENEWAL_PIPELINE_ID]
renewal_total = sum(d.get("deal_value", 0) or 0 for d in renewal_deals)
print(f"Renewal pipeline deals: {len(renewal_deals)}")
print(f"Renewal pipeline value: ${renewal_total:,.2f}")
print()

contamination = naive_total - clean_total
contamination_pct = (contamination / naive_total * 100) if naive_total > 0 else 0

print(f"Contamination: ${contamination:,.2f} ({contamination_pct:.1f}%)")
print()

print("GROUND TRUTH FOR PHASE 2B TEST:")
print(f"  Naive (expected): ~${naive_total:,.0f}")
print(f"  Clean (correct): ~${clean_total:,.0f}")
print(f"  Difference: ${contamination:,.0f}")
