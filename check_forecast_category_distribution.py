#!/usr/bin/env python3
"""Check forecast_category distribution across all active deals."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'api'))

from dotenv import load_dotenv
load_dotenv()

from db import get_supabase

sb = get_supabase()

# Get forecast_category distribution
result = sb.table('deals').select('deal_id, forecast_category').eq('deal_status', 'active').execute()

from collections import Counter
forecast_dist = Counter(d.get('forecast_category') for d in result.data)

print(f"Total active deals: {len(result.data)}")
print(f"\nForecast Category Distribution:")
print(f"{'Category':<20} {'Count':>6} {'%':>6}")
print("=" * 35)

for category, count in forecast_dist.most_common():
    pct = (count / len(result.data)) * 100
    display_cat = category if category else "(null/empty)"
    print(f"{display_cat:<20} {count:>6} {pct:>6.1f}%")

# Check if field is actually used
non_null = sum(count for cat, count in forecast_dist.items() if cat)
print(f"\nSummary:")
print(f"Deals with non-null forecast_category: {non_null} ({(non_null/len(result.data))*100:.1f}%)")
print(f"Deals with null/empty: {len(result.data) - non_null} ({((len(result.data) - non_null)/len(result.data))*100:.1f}%)")

if non_null > 0:
    print("\n✓ Field IS USED - Trigger 3 finding is REAL (zero deals in COMMIT is a process failure)")
else:
    print("\n⚠️ Field is NOT USED - Trigger 3 should be disabled or threshold set to 0%")
