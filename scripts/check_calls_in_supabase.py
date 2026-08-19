#!/usr/bin/env python3
"""Check if calls exist in Supabase for Perplexity and IKEA."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Set env vars
os.environ.setdefault('SUPABASE_URL', 'https://htgvkqycrwesdysustxd.supabase.co')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Z3ZrcXljcndlc2R5c3VzdHhkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTg4NTI5MiwiZXhwIjoyMTAxNDYxMjkyfQ.aeJFp6OwucNplQClgNGcC6pFZu_zfVK7ATim_MC_Wn4')

from supabase_client import SupabaseWriter

def check_calls(company_pattern: str, label: str):
    """Check calls for a company pattern."""
    print(f"\n{'=' * 60}")
    print(f"{label}")
    print('=' * 60)

    writer = SupabaseWriter()
    sb = writer.client

    # First find the deal_id(s)
    deals_result = sb.table('deals').select('deal_id, company_name').ilike('company_name', company_pattern).execute()

    if not deals_result.data:
        print(f"No deals found matching pattern: {company_pattern}")
        return

    print(f"\nFound {len(deals_result.data)} deal(s):")
    for deal in deals_result.data:
        print(f"  - {deal.get('company_name')} (ID: {deal.get('deal_id')})")

    # Get all deal IDs
    deal_ids = [d['deal_id'] for d in deals_result.data]

    # Query calls for these deals
    calls_result = sb.table('calls').select('source, call_date, summary').in_('deal_id', deal_ids).order('call_date', desc=True).limit(5).execute()

    if not calls_result.data:
        print(f"\n❌ No calls found in Supabase for these deals")
        return

    print(f"\n✅ Found {len(calls_result.data)} recent call(s) in Supabase:")
    for i, call in enumerate(calls_result.data, 1):
        source = call.get('source', 'unknown')
        call_date = call.get('call_date', 'unknown')
        summary = call.get('summary', '')
        preview = summary[:100] if summary else '[No summary]'

        print(f"\n{i}. {call_date} ({source})")
        print(f"   Preview: {preview}...")
        print(f"   Length: {len(summary) if summary else 0} chars")

if __name__ == '__main__':
    check_calls('%perplexity%', "PERPLEXITY")
    check_calls('%ikea%', "IKEA/INGKA")

    print("\n" + "=" * 60)
    print("Check complete")
    print("=" * 60)
