#!/usr/bin/env python3
"""Check per-quarter distribution of null renewal_revenue."""
from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client
from datetime import datetime
from collections import defaultdict

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Get all renewal pipeline deals
response = supabase.table("deals") \
    .select("deal_id,close_date,renewal_revenue,stage") \
    .eq("pipeline_id", "866608541") \
    .execute()

deals = response.data

# Fiscal year starts in February (month 2)
# FY2027 = Feb 2026 - Jan 2027
# Q1 = Feb-Apr, Q2 = May-Jul, Q3 = Aug-Oct, Q4 = Nov-Jan

def get_fiscal_quarter(close_date_str):
    """Get fiscal quarter label from close date."""
    if not close_date_str:
        return 'no_close_date'

    try:
        close_date = datetime.fromisoformat(close_date_str[:10])
        year = close_date.year
        month = close_date.month

        # Fiscal year starts in February
        # If month >= 2, FY is year+1, else FY is year
        if month >= 2:
            fy = year + 1
        else:
            fy = year

        # Quarter within fiscal year
        # Feb-Apr = Q1, May-Jul = Q2, Aug-Oct = Q3, Nov-Jan = Q4
        if month in [2, 3, 4]:
            q = 1
        elif month in [5, 6, 7]:
            q = 2
        elif month in [8, 9, 10]:
            q = 3
        elif month in [11, 12, 1]:
            q = 4

        return f"FY{fy} Q{q}"
    except:
        return 'invalid_date'

# Group by quarter
by_quarter = defaultdict(lambda: {'total': 0, 'with_value': 0, 'nulls': 0, 'null_deals': []})

for deal in deals:
    fq = get_fiscal_quarter(deal.get('close_date'))
    by_quarter[fq]['total'] += 1

    renewal_rev = deal.get('renewal_revenue')
    if renewal_rev is not None and renewal_rev != 0:
        by_quarter[fq]['with_value'] += 1
    else:
        by_quarter[fq]['nulls'] += 1
        by_quarter[fq]['null_deals'].append(deal['deal_id'])

# Sort quarters chronologically
def quarter_sort_key(q):
    if q == 'no_close_date':
        return (9999, 0)
    if q == 'invalid_date':
        return (9998, 0)
    try:
        parts = q.split()
        fy = int(parts[0][2:])  # FY2027 -> 2027
        quarter = int(parts[1][1:])  # Q1 -> 1
        return (fy, quarter)
    except:
        return (9997, 0)

print("=" * 70)
print("NULL RENEWAL_REVENUE DISTRIBUTION BY FISCAL QUARTER")
print("=" * 70)
print()
print(f"{'Quarter':<15} {'Total':>6} {'With Value':>10} {'Nulls':>6} {'Null %':>7}")
print("-" * 70)

# Focus on FY2027 (the reporting year)
fy2027_quarters = []
other_quarters = []

for fq in sorted(by_quarter.keys(), key=quarter_sort_key):
    data = by_quarter[fq]
    null_pct = (data['nulls'] / data['total'] * 100) if data['total'] > 0 else 0

    print(f"{fq:<15} {data['total']:>6} {data['with_value']:>10} {data['nulls']:>6} {null_pct:>6.1f}%")

    if fq.startswith('FY2027'):
        fy2027_quarters.append((fq, data))
    else:
        other_quarters.append((fq, data))

print()
print("=" * 70)
print("FY2027 SUMMARY (the reporting year):")
print("=" * 70)

for fq, data in fy2027_quarters:
    null_pct = (data['nulls'] / data['total'] * 100) if data['total'] > 0 else 0
    coverage_pct = (data['with_value'] / data['total'] * 100) if data['total'] > 0 else 0

    print(f"\n{fq}:")
    print(f"  Total deals: {data['total']}")
    print(f"  With renewal_revenue: {data['with_value']} ({coverage_pct:.1f}%)")
    print(f"  Null renewal_revenue: {data['nulls']} ({null_pct:.1f}%)")

    if data['nulls'] > 0:
        print(f"  Null deal IDs: {data['null_deals'][:5]}{'...' if len(data['null_deals']) > 5 else ''}")

    # Gate threshold check (typical 5-10%)
    if null_pct > 10:
        print(f"  ⚠️  NULL RATE EXCEEDS 10% THRESHOLD")
        print(f"     Typical gate would trip and return null with reason")
    elif null_pct > 5:
        print(f"  ⚠️  NULL RATE EXCEEDS 5% (borderline)")
    else:
        print(f"  ✓  NULL RATE UNDER 5% (clean)")

print()
print("=" * 70)
print("RECOMMENDATION:")
print("=" * 70)

# Check if any FY2027 quarter has high null rate
high_null_quarters = [fq for fq, data in fy2027_quarters
                      if (data['nulls'] / data['total'] * 100) > 10]

if high_null_quarters:
    print(f"⚠️  {len(high_null_quarters)} quarter(s) exceed 10% null threshold:")
    for fq in high_null_quarters:
        data = by_quarter[fq]
        null_pct = (data['nulls'] / data['total'] * 100)
        print(f"   {fq}: {null_pct:.1f}% null ({data['nulls']}/{data['total']})")
    print()
    print("Handler should:")
    print("  1. Compute metrics from non-null subset")
    print("  2. Surface coverage: 'GRR X% across Y of Z renewals'")
    print("  3. NOT return null (data exists, just incomplete)")
else:
    print("✓ All FY2027 quarters have <10% null rate")
    print()
    print("Handler should:")
    print("  1. Exclude nulls per calculation (standard discipline)")
    print("  2. Report null count in metadata")
    print("  3. Compute clean ratios from non-null subset")
