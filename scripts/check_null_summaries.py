#!/usr/bin/env python3
"""Check how many calls have NULL summaries."""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get all calls
result = sb.table('calls').select('call_id,summary,is_internal,call_intent').execute()
calls = result.data

total = len(calls)
null_summary = sum(1 for c in calls if c.get('summary') is None)
empty_summary = sum(1 for c in calls if c.get('summary') == '')
short_summary = sum(1 for c in calls if c.get('summary') and len(c.get('summary', '')) < 100)

# Check non-internal calls specifically
non_internal = [c for c in calls if not c.get('is_internal')]
null_non_internal = sum(1 for c in non_internal if c.get('summary') is None)

# Check calls with intent that would trigger objection extraction
try:
    from enrichment.call_intent_classifier import ENRICHMENT_PROFILE
    qualifying_calls = [
        c for c in non_internal
        if c.get('call_intent') in ENRICHMENT_PROFILE
        and ENRICHMENT_PROFILE[c['call_intent']].get('extract_objections')
    ]
except ImportError:
    # If can't import, just check all non-internal calls
    print("Note: Could not import ENRICHMENT_PROFILE, checking all non-internal calls")
    qualifying_calls = non_internal
null_qualifying = sum(1 for c in qualifying_calls if c.get('summary') is None)

print("=== Call Summary Analysis ===")
print(f"Total calls: {total:,}")
print(f"NULL summaries: {null_summary:,} ({null_summary/total*100:.1f}%)")
print(f"Empty string summaries: {empty_summary:,}")
print(f"Short summaries (<100 chars): {short_summary:,}")
print()
print(f"Non-internal calls: {len(non_internal):,}")
print(f"  NULL summaries: {null_non_internal:,} ({null_non_internal/len(non_internal)*100:.1f}%)")
print()
print(f"Calls qualifying for objection extraction: {len(qualifying_calls):,}")
if qualifying_calls:
    print(f"  NULL summaries: {null_qualifying:,} ({null_qualifying/len(qualifying_calls)*100:.1f}%)")
else:
    print(f"  NULL summaries: {null_qualifying:,}")
print()
print("=" * 60)
if null_qualifying > 0:
    print("IMPACT: NULL summaries are PRESENT in qualifying calls.")
    print("        This bug has been crashing objection extraction")
    print("        on EVERY weekly run since Aug 9, 2026.")
    print(f"        Affected: {null_qualifying} calls out of {len(qualifying_calls)} qualifying")
else:
    print("IMPACT: No NULL summaries found in qualifying calls.")
    print("        This is likely a NEW edge case triggered tonight.")
