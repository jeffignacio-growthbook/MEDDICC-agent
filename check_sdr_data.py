#!/usr/bin/env python3
"""Check SDR table data to diagnose handler error."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))
from api.db import get_supabase

sb = get_supabase()

print("\n" + "="*80)
print("SDR DATA DIAGNOSTICS")
print("="*80)

# Check sdr_users table
print("\n1. sdr_users table:")
result = sb.table('sdr_users').select('*').execute()
print(f"   Total rows: {len(result.data)}")
for user in result.data[:10]:  # Show first 10
    print(f"   - {user.get('user_name'):20} {user.get('user_email'):35} ({user.get('tool')})")

# Check for Jake Stangl specifically
print("\n2. Looking for Jake Stangl (jake.stangl@growthbook.io):")
jake_rows = sb.table('sdr_users').select('*').eq('user_email', 'jake.stangl@growthbook.io').execute()
print(f"   Found {len(jake_rows.data)} rows")
if jake_rows.data:
    for row in jake_rows.data:
        print(f"   - tool: {row.get('tool')}, tool_user_id: {row.get('tool_user_id')}")
else:
    print("   ✗ No rows found for jake.stangl@growthbook.io")
    print("\n   Trying case-insensitive search:")
    # Try ilike search
    all_users = result.data
    jake_matches = [u for u in all_users if 'jake' in u.get('user_email', '').lower()]
    if jake_matches:
        print(f"   Found {len(jake_matches)} matches with 'jake' in email:")
        for u in jake_matches:
            print(f"     - {u.get('user_email')} ({u.get('user_name')})")
    else:
        print("   No users with 'jake' in email found")

# Check sdr_metrics table
print("\n3. sdr_metrics table:")
metrics_result = sb.table('sdr_metrics').select('*').limit(5).execute()
print(f"   Total sample rows: {len(metrics_result.data)}")
if metrics_result.data:
    print("   Sample row:")
    sample = metrics_result.data[0]
    for key, value in sample.items():
        print(f"     {key}: {value}")

    # Check date range
    all_dates = sb.table('sdr_metrics').select('metric_date').execute()
    dates = [row.get('metric_date') for row in all_dates.data if row.get('metric_date')]
    if dates:
        print(f"\n   Date range in sdr_metrics: {min(dates)} to {max(dates)}")
else:
    print("   (empty table)")

print("\n" + "="*80 + "\n")
