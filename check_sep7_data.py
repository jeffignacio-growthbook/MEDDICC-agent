#!/usr/bin/env python3
"""
Check what waterfall data exists for Sep 7 EMEA.
Verify if "Other segments pending full row data" is a real data gap
or another synthesis invention.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

from supabase_client import select_all

print("=" * 70)
print("CHECK SEP 7 EMEA DATA")
print("=" * 70)
print()

# Get Sep 7 EMEA waterfall data (what the query retrieved)
sep7 = select_all(sb, 'waterfall_weekly',
    'week_ending,region,segment,beginning_value,ending_value,' +
    'won_value,lost_value,new_pipeline_value,net_change',
    filters=[
        ('eq', 'region', 'EMEA'),
        ('eq', 'week_ending', '2026-09-07')
    ])

print(f"Sep 7 EMEA rows: {len(sep7)}")
print()

if not sep7:
    print("❌ NO DATA - Sep 7 EMEA is genuinely missing from waterfall_weekly")
    print("   The 'pending' claim is CORRECT")
else:
    segments_present = {r['segment'] for r in sep7}
    expected_segments = {'Enterprise', 'Mid-Market', 'SMB', 'Unknown'}

    print(f"Segments present: {sorted(segments_present)}")
    print(f"Expected segments: {sorted(expected_segments)}")
    print()

    if segments_present == expected_segments:
        print("✅ ALL 4 SEGMENTS PRESENT")
        print("   The 'pending full row data' claim is INCORRECT")
        print()
        print("   Synthesis is still inventing data gaps that don't exist.")
    else:
        missing = expected_segments - segments_present
        print(f"⚠️  INCOMPLETE: Missing {missing}")
        print("   The 'pending' claim is CORRECT")

    print()
    print("Sep 7 data details:")
    for r in sorted(sep7, key=lambda x: x['segment']):
        seg = r['segment']
        beg = r.get('beginning_value', 0) or 0
        end = r.get('ending_value', 0) or 0
        won = r.get('won_value', 0) or 0
        lost = r.get('lost_value', 0) or 0
        new = r.get('new_pipeline_value', 0) or 0
        net = r.get('net_change', 0) or 0

        print(f"  {seg:15s}: beg=${beg:>10,.0f} end=${end:>10,.0f} " +
              f"won=${won:>7,.0f} lost=${lost:>7,.0f} new=${new:>7,.0f} net=${net:>8,.0f}")

print()
print("=" * 70)
print("CONCLUSION")
print("=" * 70)
print()

if sep7 and len(segments_present) == 4:
    print("VERDICT: Synthesis bug still present")
    print()
    print("Despite the fix:")
    print("  1. Data has all 4 segments for Sep 7")
    print("  2. Synthesis still says 'Other segments pending'")
    print("  3. Verification caught it (logged false_segment_partial_claim)")
    print()
    print("The verification layer works, but the prompt instruction isn't")
    print("strong enough to prevent the synthesis from inventing caveats.")
else:
    print("VERDICT: Claim is justified")
    print()
    print("Sep 7 data is genuinely incomplete or missing.")
