#!/usr/bin/env python3
"""Simple query to check segment distribution in Supabase."""
import os
import sys
from collections import defaultdict

try:
    from supabase import create_client
except ImportError:
    print("Installing supabase...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "supabase"])
    from supabase import create_client

# Get credentials from environment
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_KEY')

if not supabase_url or not supabase_key:
    print("❌ Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    print("\nTry running:")
    print('  export SUPABASE_URL="$(gh secret list | grep SUPABASE_URL)"')
    print('  export SUPABASE_SERVICE_KEY="$(gh secret list | grep SUPABASE_SERVICE_KEY)"')
    sys.exit(1)

# Connect and query
sb = create_client(supabase_url, supabase_key)

print("Querying segment distribution from Supabase...")
result = sb.table('deals').select(
    'segment, deal_value, deal_status'
).eq('deal_status', 'active').execute()

if not result.data:
    print("No active deals found in Supabase")
    sys.exit(0)

# Aggregate by segment
segments = defaultdict(lambda: {'count': 0, 'total': 0.0})

for deal in result.data:
    seg = deal.get('segment') or 'Unknown'
    val = deal.get('deal_value') or 0
    try:
        val = float(val) if val is not None else 0
    except (ValueError, TypeError):
        val = 0

    segments[seg]['count'] += 1
    segments[seg]['total'] += val

# Print results
print('\n' + '='*80)
print('Segment Distribution (Active Deals)')
print('='*80)
print(f"{'Segment':<15} {'Count':>8} {'Total Value':>15} {'Avg Value':>12}")
print('-'*80)

for seg in sorted(segments.keys(), key=lambda s: segments[s]['count'], reverse=True):
    data = segments[seg]
    count = data['count']
    total = data['total']
    avg = total / count if count > 0 else 0

    print(f"{seg:<15} {count:>8,} ${total:>14,.0f} ${avg:>11,.0f}")

print('-'*80)

total_deals = sum(d['count'] for d in segments.values())
unknown_count = segments.get('Unknown', {}).get('count', 0)
unknown_pct = (100 * unknown_count / total_deals) if total_deals > 0 else 0

print(f'\nTotal Active Deals: {total_deals:,}')
print(f'Unknown Bucket: {unknown_count:,} deals ({unknown_pct:.1f}%)')
print('='*80)
