#!/usr/bin/env python3
"""Check renewal deal status breakdown."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client
from collections import Counter

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(supabase_url, supabase_key)

# Get all renewal deals with stage info
response = supabase.table("deals") \
    .select("deal_id,stage,pipeline_id") \
    .eq("pipeline_id", "866608541") \
    .execute()

deals = response.data

print(f"Renewal pipeline deals breakdown:")
print("=" * 70)
print(f"Total: {len(deals)}")

# Import field_semantics to classify stages
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'api'))
from field_semantics import is_won, is_lost

active = []
won = []
lost = []

for deal in deals:
    stage = deal.get('stage', '')
    if is_won(stage):
        won.append(deal)
    elif is_lost(stage):
        lost.append(deal)
    else:
        active.append(deal)

print(f"\nStatus breakdown:")
print(f"  Active (open): {len(active):3}")
print(f"  Closed Won:    {len(won):3}")
print(f"  Closed Lost:   {len(lost):3}")
print(f"  Total:         {len(deals):3}")

print(f"\nVerification:")
print(f"  deals_snapshot should have: {len(active)} (open deals only)")
print(f"  deals_snapshot actual:      145")
print(f"  Match: {'✓' if len(active) == 145 else '✗'}")
