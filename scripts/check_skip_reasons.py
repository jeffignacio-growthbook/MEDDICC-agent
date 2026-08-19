#!/usr/bin/env python3
"""
Check detailed skip reasons for specific deals.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from github_memory import GitHubMemory
from run_nightly import get_calls_for_company

def check_deal(deal_id: str, deal_name: str, company_name: str):
    """Check why a deal is being skipped."""
    print(f"\n{'=' * 60}")
    print(f"{deal_name} ({deal_id})")
    print(f"Company: {company_name}")
    print('=' * 60)

    try:
        memory = GitHubMemory()

        # Get calls from cache
        fireflies_calls, apollo_calls, new_count = get_calls_for_company(
            company_name, since_date=None, memory=memory
        )

        total_calls = len(fireflies_calls) + len(apollo_calls)
        print(f"\nTotal calls in cache: {total_calls}")
        print(f"  Fireflies: {len(fireflies_calls)}")
        print(f"  Apollo: {len(apollo_calls)}")

        # Combine and sort by date
        all_calls_sorted = sorted(
            fireflies_calls + apollo_calls,
            key=lambda c: c.get('date', ''),
        )

        # Extract summaries
        all_summaries = []
        for call in all_calls_sorted:
            summary = None
            if 'formatted_summary' in call and call['formatted_summary']:
                summary = call['formatted_summary']
            elif 'summary' in call and call['summary']:
                summary = call['summary']

            if summary and summary.strip():
                call_date = call.get('date', 'Unknown')
                source = call.get('source', 'unknown')
                quality = call.get('summary_quality', 'unknown')
                all_summaries.append({
                    'date': call_date,
                    'summary': summary,
                    'source': source,
                    'quality': quality,
                    'length': len(summary)
                })

        # Sort by date ascending
        all_summaries.sort(key=lambda x: x['date'])

        print(f"\nValid summaries found: {len(all_summaries)}")

        # GUARD 1: No calls
        if len(all_summaries) == 0:
            print("\n❌ GUARD 1 FIRED: No calls with valid summaries")
            return

        # Show all summaries
        print("\nAll calls with summaries:")
        for i, s in enumerate(all_summaries, 1):
            print(f"  {i}. {s['date']} ({s['source']}) - {s['length']} chars - quality: {s['quality']}")
            if s['quality'] == 'corrupted':
                print(f"     Preview: {s['summary'][:100]}...")

        # Check most recent call
        most_recent = all_summaries[-1]
        print(f"\nMost recent call:")
        print(f"  Date: {most_recent['date']}")
        print(f"  Source: {most_recent['source']}")
        print(f"  Length: {most_recent['length']} chars")
        print(f"  Quality: {most_recent['quality']}")

        # GUARD 3: Most recent call too short
        if most_recent['length'] < 100:
            print(f"\n❌ GUARD 3 FIRED: Most recent call summary too short ({most_recent['length']} < 100)")
            print(f"\nSummary preview:")
            print(f"{most_recent['summary'][:200]}")
            return

        print(f"\n✅ PASSED ALL GUARDS")
        print("Deal should be analyzed")

    except Exception as e:
        print(f"\n⚠️  ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Top deals that are still skipped
    deals = [
        ("57207848177", "Ingka Ikea", "ingka-ikea"),
        ("55853063629", "Perplexity AI", "perplexity-ai"),
    ]

    for deal_id, name, company_slug in deals:
        check_deal(deal_id, name, company_slug)

    print("\n" + "=" * 60)
    print("Check complete")
    print("=" * 60)
