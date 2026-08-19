#!/usr/bin/env python3
"""Find an Apollo call with [Summary failed] to test diagnostic logging."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Set credentials
os.environ['SUPABASE_URL'] = 'https://htgvkqycrwesdysustxd.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Z3ZrcXljcndlc2R5c3VzdHhkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTg4NTI5MiwiZXhwIjoyMTAxNDYxMjkyfQ.aeJFp6OwucNplQClgNGcC6pFZu_zfVK7ATim_MC_Wn4'

from supabase_client import SupabaseWriter

writer = SupabaseWriter()
sb = writer.client

# Find Apollo calls with [Summary failed]
result = sb.table('calls').select('call_id, deal_id, title, call_date, summary').eq('source', 'apollo').like('summary', '%Summary failed%').order('call_date', desc=True).limit(5).execute()

if result.data:
    print(f"Found {len(result.data)} Apollo calls with [Summary failed]:\n")
    for i, call in enumerate(result.data, 1):
        print(f"{i}. Call ID: {call.get('call_id')}")
        print(f"   Deal ID: {call.get('deal_id')}")
        print(f"   Title: {call.get('title')}")
        print(f"   Date: {call.get('call_date')}")
        print(f"   Summary preview: {call.get('summary', '')[:100]}...")
        print()

    # Return the first one for testing
    first_call = result.data[0]
    print(f"\nTest with this call ID: {first_call.get('call_id')}")
    print(f"Deal ID: {first_call.get('deal_id')}")
else:
    print("No Apollo calls found with [Summary failed] in Supabase")
