#!/usr/bin/env python3
"""Test Supabase call loading for Perplexity and IKEA deals."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Set credentials
os.environ['SUPABASE_URL'] = 'https://htgvkqycrwesdysustxd.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Z3ZrcXljcndlc2R5c3VzdHhkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTg4NTI5MiwiZXhwIjoyMTAxNDYxMjkyfQ.aeJFp6OwucNplQClgNGcC6pFZu_zfVK7ATim_MC_Wn4'

from github_memory import GitHubMemory
from run_nightly import get_calls_for_company

def test_deal(deal_id: str, company_name: str, label: str):
    """Test call loading for a specific deal."""
    print(f"\n{'=' * 60}")
    print(f"{label}")
    print(f"Deal ID: {deal_id}")
    print(f"Company: {company_name}")
    print('=' * 60)

    memory = GitHubMemory()

    # Test with Supabase (new path)
    ff_calls, ap_calls, total = get_calls_for_company(
        company_name=company_name,
        since_date=None,
        memory=memory,
        deal_id=deal_id
    )

    print(f"\n✅ Loaded from Supabase:")
    print(f"  Fireflies: {len(ff_calls)} calls")
    print(f"  Apollo: {len(ap_calls)} calls")
    print(f"  Total: {total} calls")

    # Show most recent call
    all_calls = sorted(ff_calls + ap_calls, key=lambda c: c.get('date', ''), reverse=True)
    if all_calls:
        most_recent = all_calls[0]
        print(f"\nMost recent call:")
        print(f"  Date: {most_recent.get('date')}")
        print(f"  Source: {most_recent.get('source')}")
        print(f"  Title: {most_recent.get('title', 'N/A')}")
        summary = most_recent.get('summary', '')
        print(f"  Summary length: {len(summary)} chars")
        if len(summary) >= 100:
            print(f"  ✅ PASSES Guard 3 (summary >= 100 chars)")
        else:
            print(f"  ❌ FAILS Guard 3 (summary < 100 chars)")
        if summary:
            print(f"  Preview: {summary[:100]}...")

if __name__ == '__main__':
    test_deal(
        deal_id='54442852124',
        company_name='Perplexity AI',
        label='PERPLEXITY'
    )

    test_deal(
        deal_id='50347229229',
        company_name='Ingka Ikea',
        label='IKEA'
    )

    print("\n" + "=" * 60)
    print("Test complete")
    print("=" * 60)
