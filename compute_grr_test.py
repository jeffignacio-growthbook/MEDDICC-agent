#!/usr/bin/env python3
"""Test GRR/NRR computation against HubSpot reference figures."""
from dotenv import load_dotenv
load_dotenv()

import os
import sys
from pathlib import Path
from supabase import create_client
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))
from utils import load_client_config
from api.field_semantics import is_won, is_lost

# Load config for fiscal quarters
config = load_client_config()

# Connect to database
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Get all renewal pipeline deals
response = supabase.table("deals") \
    .select("deal_id,company_name,stage,close_date,renewal_revenue,arr_usd,deal_value") \
    .eq("pipeline_id", "866608541") \
    .execute()

all_renewal_deals = response.data

print(f"Total renewal pipeline deals: {len(all_renewal_deals)}")
print("=" * 70)

# Filter to deals with renewal_revenue (simulating "Renewal ARR is known")
deals_with_rr = [d for d in all_renewal_deals if d.get('renewal_revenue') is not None and d.get('renewal_revenue') != 0]
deals_without_rr = [d for d in all_renewal_deals if d.get('renewal_revenue') is None or d.get('renewal_revenue') == 0]

print(f"Deals with renewal_revenue (non-zero): {len(deals_with_rr)}")
print(f"Deals without renewal_revenue (null/0): {len(deals_without_rr)}")
print()

# Compute GRR for Q1 and Q2 FY2027 using both populations
# Q1 FY2027 = Nov 2026 - Jan 2027
# Q2 FY2027 = Feb 2027 - Apr 2027

def get_fiscal_quarter_label(close_date_str, config):
    """Get fiscal quarter label from close date."""
    if not close_date_str:
        return None
    try:
        from datetime import date
        close_date = date.fromisoformat(close_date_str[:10])

        # Get fiscal year start month from config
        fy_start = config.get('fiscal', {}).get('fy_start_month', 2)  # Default Feb

        # Determine fiscal year
        if close_date.month >= fy_start:
            fy = close_date.year + 1
        else:
            fy = close_date.year

        # Determine quarter
        month_offset = (close_date.month - fy_start) % 12
        quarter = (month_offset // 3) + 1

        return f"FY{fy} Q{quarter}"
    except:
        return None

# Group by quarter
def compute_metrics(deals, label):
    """Compute GRR/NRR by quarter."""
    by_quarter = defaultdict(lambda: {'won': [], 'lost': [], 'open': [], 'all': []})

    for deal in deals:
        quarter = get_fiscal_quarter_label(deal.get('close_date'), config)
        if not quarter:
            continue

        stage = deal.get('stage', '')
        renewal_rev = deal.get('renewal_revenue', 0) or 0

        by_quarter[quarter]['all'].append(renewal_rev)

        if is_won(stage):
            by_quarter[quarter]['won'].append(renewal_rev)
        elif is_lost(stage):
            by_quarter[quarter]['lost'].append(renewal_rev)
        else:
            by_quarter[quarter]['open'].append(renewal_rev)

    print(f"\n{label}:")
    print("=" * 70)

    for q in sorted(by_quarter.keys()):
        data = by_quarter[q]
        total_rr = sum(data['all'])
        won_rr = sum(data['won'])
        lost_rr = sum(data['lost'])
        open_rr = sum(data['open'])

        # Closed only
        closed_total = won_rr + lost_rr
        grr_closed = (won_rr / closed_total * 100) if closed_total > 0 else None
        churn_closed = (100 - grr_closed) if grr_closed is not None else None

        # Assume open wins
        assume_total = total_rr
        grr_open = (won_rr / assume_total * 100) if assume_total > 0 else None
        churn_open = (100 - grr_open) if grr_open is not None else None

        print(f"\n{q}:")
        print(f"  Total renewal_revenue: ${total_rr:>12,.0f}  ({len(data['all'])} deals)")
        print(f"    Won:  ${won_rr:>12,.0f}  ({len(data['won'])} deals)")
        print(f"    Lost: ${lost_rr:>12,.0f}  ({len(data['lost'])} deals)")
        print(f"    Open: ${open_rr:>12,.0f}  ({len(data['open'])} deals)")
        print()
        print(f"  Closed Only:")
        if grr_closed is not None:
            print(f"    GRR:   {grr_closed:>5.1f}%  (won / closed)")
            print(f"    Churn: {churn_closed:>5.1f}%")
        else:
            print(f"    GRR:   N/A (no closed deals)")
        print()
        print(f"  Assume Open Wins:")
        if grr_open is not None:
            print(f"    GRR:   {grr_open:>5.1f}%  (won / total)")
            print(f"    Churn: {churn_open:>5.1f}%")

# Test both populations
compute_metrics(all_renewal_deals, "ALL RENEWAL PIPELINE DEALS (253)")
compute_metrics(deals_with_rr, "ONLY DEALS WITH RENEWAL_REVENUE (210)")

print("\n" + "=" * 70)
print("REFERENCE FIGURES FROM HUBSPOT:")
print("  Q1 2027 | Closed: GRR 77%, churn 23% | Open: GRR 78%, churn 22%")
print("  Q2 2027 | Closed: GRR 97%, churn  3% | Open: GRR 97%, churn  3%")
