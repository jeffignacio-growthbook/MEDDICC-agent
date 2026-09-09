#!/usr/bin/env python3
"""
Test ARR reconciliation check on the week with $206K discrepancy (2026-06-29).

Expected outcome:
- Should detect that UNKNOWN/Unknown group has ARR changes masked by precedence
- Should report ~$206K of ARR delta masked by precedence system
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

# Add scripts to path
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / '.env')

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    sys.exit(1)

from supabase import create_client
from utils import load_client_config
from supabase_client import select_all

sys.path.insert(0, str(REPO_ROOT / 'scripts' / 'analytics'))
from compute_waterfall_segmented import compute_waterfall_for_dates

sys.path.insert(0, str(REPO_ROOT / 'api'))
from field_semantics import is_test_deal

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
config = load_client_config()

# Load qualification data
qual_rows = select_all(sb, 'deals', columns='deal_id, qualified_date')
qual_map = {
    row['deal_id']: {'qualified_date': row.get('qualified_date')}
    for row in qual_rows
}

# Load enrichment data
enrichment_rows = select_all(sb, 'deals', columns='deal_id, company_name')
enrichment_map = {
    row['deal_id']: {
        'company_name': row.get('company_name') or ''
    }
    for row in enrichment_rows
}

# Load deal status data
deal_status_rows = select_all(sb, 'deals', columns='deal_id, close_date, stage')
deal_status_map = {
    row['deal_id']: {
        'close_date': row.get('close_date'),
        'stage': row.get('stage')
    }
    for row in deal_status_rows
}

threshold = config.get('pipelines', {}).get('default', {}).get('qualified_stage_order', 2)

print("Testing ARR reconciliation check on week 2026-06-29")
print("=" * 70)

prev_week = '2026-06-22'
test_week = '2026-06-29'

print(f"\nComputing waterfall: {prev_week} → {test_week}\n")

results = compute_waterfall_for_dates(
    sb, config, qual_map, enrichment_map, deal_status_map, is_test_deal, threshold,
    prev_week, test_week,
    computed_source='prospective'
)

print("\n" + "=" * 70)
print("ARR RECONCILIATION TEST RESULTS")
print("=" * 70)

# Filter to UNKNOWN/Unknown group
unknown_results = [r for r in results if r['region'] == 'UNKNOWN' and r['segment'] == 'Unknown']

if unknown_results:
    r = unknown_results[0]
    print(f"\nUNKNOWN/Unknown group:")
    print(f"  Expected ARR delta (all stayed deals): ${r['expected_arr_delta']:,.2f}")
    print(f"  ARR masked by precedence:              ${r['arr_masked_by_precedence']:,.2f}")
    print(f"  arr_change_value captured:             ${r['arr_change_value']:,.2f}")
    print(f"  ARR reconciliation issue:              {r['arr_reconciliation_issue']}")

    if r['arr_reconciliation_issue']:
        print(f"\n✓ ARR RECONCILIATION CHECK WORKING")
        print(f"  Detected ${abs(r['arr_masked_by_precedence']):,.0f} of ARR change masked by precedence")

        # Check if this matches our expected ~$206K
        if abs(abs(r['arr_masked_by_precedence']) - 206000) < 10000:
            print(f"\n✓ MATCHES EXPECTED $206K DISCREPANCY")
            print(f"  The ARR reconciliation check successfully detected the root cause")
        else:
            print(f"\n⚠️  ARR masked (${abs(r['arr_masked_by_precedence']):,.0f}) doesn't match expected $206K")
    else:
        print(f"\n✗ ARR RECONCILIATION CHECK DID NOT DETECT ISSUE")
else:
    print("\n✗ UNKNOWN/Unknown group not found in results")

# Show all groups with ARR issues
arr_issues = [r for r in results if r.get('arr_reconciliation_issue', False)]
if arr_issues:
    print(f"\n\nAll groups with ARR reconciliation issues:")
    for r in arr_issues:
        print(f"  {r['group']}: ${r['arr_masked_by_precedence']:,.0f} masked")
