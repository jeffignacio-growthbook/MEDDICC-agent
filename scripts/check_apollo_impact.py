#!/usr/bin/env python3
"""Check impact of Apollo failed summaries on active pipeline."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Set credentials
os.environ['SUPABASE_URL'] = 'https://htgvkqycrwesdysustxd.supabase.co'
os.environ['SUPABASE_SERVICE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Z3ZrcXljcndlc2R5c3VzdHhkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTg4NTI5MiwiZXhwIjoyMTAxNDYxMjkyfQ.aeJFp6OwucNplQClgNGcC6pFZu_zfVK7ATim_MC_Wn4'

from supabase_client import SupabaseWriter

def main():
    print(f"\n{'=' * 70}")
    print("Apollo [Summary failed] Impact Analysis")
    print('=' * 70)

    writer = SupabaseWriter()
    sb = writer.client

    # Query 1: Overall count
    print("\n📊 Overall Impact:")

    # Get all failed calls
    all_failed = sb.table('calls').select('deal_id, call_id').eq('source', 'apollo').like('summary', '%Summary failed%').execute()

    if all_failed.data:
        unique_deals = set(call.get('deal_id') for call in all_failed.data if call.get('deal_id'))
        print(f"   Affected deals: {len(unique_deals)}")
        print(f"   Affected calls: {len(all_failed.data)}")
    else:
        print("   No failed calls found")

    # Query 2: Active pipeline impact
    print("\n💰 Active Pipeline Impact (Top 20 by ARR):")
    print(f"{'Company':<30} {'ARR':>12} {'Stage':<20} {'Failed Calls':>13}")
    print("=" * 80)

    # Direct query for active deals with failed calls
    failed_calls = sb.table('calls').select('deal_id, call_id, title').eq('source', 'apollo').like('summary', '%Summary failed%').execute()

    if failed_calls.data:
        # Get unique deal IDs
        deal_ids = list(set(call['deal_id'] for call in failed_calls.data if call.get('deal_id')))

        # Get deal info for these IDs
        if deal_ids:
            deals_result = sb.table('deals').select('deal_id, company_name, arr_usd, stage, deal_status').in_('deal_id', deal_ids).eq('deal_status', 'active').execute()

            if deals_result.data:
                # Count calls per deal
                calls_per_deal = {}
                for call in failed_calls.data:
                    deal_id = call.get('deal_id')
                    if deal_id:
                        calls_per_deal[deal_id] = calls_per_deal.get(deal_id, 0) + 1

                # Sort by ARR
                deals_sorted = sorted(deals_result.data, key=lambda x: float(x.get('arr_usd') or 0), reverse=True)

                total_arr = 0
                for deal in deals_sorted[:20]:
                    company = deal.get('company_name', 'Unknown')[:30]
                    arr = float(deal.get('arr_usd') or 0)
                    total_arr += arr
                    stage = deal.get('stage', 'Unknown')[:20]
                    failed_count = calls_per_deal.get(deal.get('deal_id'), 0)

                    print(f"{company:<30} ${arr:>11,.0f} {stage:<20} {failed_count:>13}")

                print("=" * 80)
                print(f"{'Total ARR at risk:':<30} ${total_arr:>11,.0f}")
                print(f"\nActive deals affected: {len(deals_sorted)}")
            else:
                print("   No active deals found with failed Apollo calls")
    else:
        print("   No failed Apollo calls found in Supabase")

    print("\n" + "=" * 70)
    print("Analysis complete")
    print("=" * 70)

if __name__ == '__main__':
    main()
