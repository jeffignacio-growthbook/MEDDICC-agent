#!/usr/bin/env python3
"""Check if CSV deals have renewal_revenue populated in database."""
from dotenv import load_dotenv
load_dotenv()

import os
import csv
from supabase import create_client

csv_path = "/Users/jeffignacio/Downloads/HubSpot Custom Report Renewal Aug 28 2026/renewal-arr.csv"

# Read CSV deal IDs
csv_deal_ids = []
csv_renewal_arr = {}
with open(csv_path, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        deal_id = row['Deal ID']
        csv_deal_ids.append(deal_id)
        csv_renewal_arr[deal_id] = row.get('Renewal ARR', '0')

print(f"CSV contains {len(csv_deal_ids)} deals")
print("=" * 70)

# Check database
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Get renewal pipeline deals from database with renewal_revenue
response = supabase.table("deals") \
    .select("deal_id,renewal_revenue,pipeline_id") \
    .eq("pipeline_id", "866608541") \
    .execute()

db_renewal_deals = {d['deal_id']: d for d in response.data}

print(f"Database has {len(db_renewal_deals)} renewal pipeline deals")
print()

# Check overlap
csv_renewal_ids = set(csv_deal_ids)
db_renewal_ids = set(db_renewal_deals.keys())

in_both = csv_renewal_ids & db_renewal_ids
in_csv_only = csv_renewal_ids - db_renewal_ids
in_db_only = db_renewal_ids - csv_renewal_ids

print(f"Overlap analysis:")
print(f"  In both CSV and DB:      {len(in_both)}")
print(f"  In CSV only (not in DB): {len(in_csv_only)}")
print(f"  In DB only (not in CSV): {len(in_db_only)}")
print()

# For deals in both, check renewal_revenue population
deals_in_both = [db_renewal_deals[did] for did in in_both]
with_renewal_rev = [d for d in deals_in_both if d.get('renewal_revenue') is not None and d['renewal_revenue'] != 0]
without_renewal_rev = [d for d in deals_in_both if d.get('renewal_revenue') is None or d['renewal_revenue'] == 0]

print(f"For deals in both CSV and database ({len(in_both)} deals):")
print(f"  With renewal_revenue (non-zero): {len(with_renewal_rev)}")
print(f"  Without renewal_revenue (null/0): {len(without_renewal_rev)}")
print()

# Check CSV Renewal ARR values for deals without renewal_revenue in DB
if without_renewal_rev:
    print(f"Sample deals in CSV but renewal_revenue=NULL in DB (first 5):")
    for i, deal in enumerate(without_renewal_rev[:5]):
        deal_id = deal['deal_id']
        csv_arr = csv_renewal_arr.get(deal_id, 'N/A')
        print(f"  [{i+1}] {deal_id} | CSV Renewal ARR: {csv_arr} | DB renewal_revenue: NULL")
    print()

# Hypothesis: CSV filters on "Renewal ARR is known"
# If true, all CSV deals should have non-zero Renewal ARR in the CSV itself
csv_with_arr = sum(1 for did in csv_deal_ids if csv_renewal_arr[did] not in ('0', '', 'N/A'))
csv_without_arr = len(csv_deal_ids) - csv_with_arr

print(f"CSV 'Renewal ARR' field population:")
print(f"  Non-zero: {csv_with_arr} ({csv_with_arr/len(csv_deal_ids)*100:.1f}%)")
print(f"  Zero/blank: {csv_without_arr} ({csv_without_arr/len(csv_deal_ids)*100:.1f}%)")
print()

print("=" * 70)
print("FILTER INFERENCE:")
if csv_without_arr == 0:
    print("  ✓ All CSV deals have non-zero 'Renewal ARR' in the CSV")
    print("  → HubSpot report likely filters on 'Renewal ARR is known'")
    print(f"  → Report population: deals with renewal_revenue present")
elif csv_without_arr < len(csv_deal_ids) * 0.1:
    print(f"  ⚠ {csv_without_arr} CSV deals have zero/blank Renewal ARR (<10%)")
    print("  → Report may filter on 'Renewal ARR is known' with exceptions")
else:
    print(f"  ✗ {csv_without_arr} CSV deals have zero/blank Renewal ARR ({csv_without_arr/len(csv_deal_ids)*100:.0f}%)")
    print("  → Report does NOT filter on 'Renewal ARR is known'")
    print("  → Different filter criteria")
