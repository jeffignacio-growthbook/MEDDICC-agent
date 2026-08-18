#!/usr/bin/env python3
"""
Verify all four wiring fixes before Slack test.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

print("\n" + "="*80)
print("VERIFICATION: All Four Wiring Fixes")
print("="*80)

# ── Fix 1: Time resolver handles current_month ─────────────────────
print("\n[Fix 1] Testing time_resolver.resolve_time_window({'period': 'current_month'})...")
from api.time_resolver import resolve_time_window

result = resolve_time_window({'period': 'current_month'})
print(f"  Result: {result}")
assert 'August 2026' in result['label'] or 'August' in result['label'], \
    f"Expected August in label, got: {result['label']}"
assert result['start'] == '2026-08-01', f"Expected start 2026-08-01, got: {result['start']}"
print("  ✓ current_month returns August 2026 (Aug 1-31)")

result2 = resolve_time_window({'period': 'previous_month'})
print(f"  Result: {result2}")
assert 'July 2026' in result2['label'] or 'July' in result2['label'], \
    f"Expected July in label, got: {result2['label']}"
print("  ✓ previous_month returns July 2026")

# ── Fix 2: get_user_persona wired into process_and_reply ──────────
print("\n[Fix 2] Checking get_user_persona import in api/main.py...")
from api.main import process_and_reply
import inspect
source = inspect.getsource(process_and_reply)
assert 'get_user_persona' in source, "get_user_persona not imported in process_and_reply"
print("  ✓ get_user_persona imported in api/main.py")
assert 'persona = get_user_persona(sb, user_id)' in source, \
    "persona lookup not called in process_and_reply"
print("  ✓ persona = get_user_persona(sb, user_id) found")
assert 'persona=persona' in source, "persona not passed to route_question"
print("  ✓ persona passed to route_question")

# ── Fix 3: Team roster injected into DYNAMIC_SYSTEM_PROMPT ────────
print("\n[Fix 3] Checking DYNAMIC_SYSTEM_PROMPT for roster_text...")
from api.router import DYNAMIC_SYSTEM_PROMPT
assert '{roster_text}' in DYNAMIC_SYSTEM_PROMPT, \
    "roster_text placeholder not found in DYNAMIC_SYSTEM_PROMPT"
print("  ✓ {roster_text} placeholder found in DYNAMIC_SYSTEM_PROMPT")
assert "name-to-email matching" in DYNAMIC_SYSTEM_PROMPT or \
       "jake.stangl@growthbook.io" in DYNAMIC_SYSTEM_PROMPT, \
    "Name disambiguation example not found"
print("  ✓ Name disambiguation rules found in prompt")

print("\n[Fix 3] Checking route_question loads team roster...")
from api.router import route_question
source = inspect.getsource(route_question)
assert "team_roster = sb.table('user_personas')" in source.replace('"', "'"), \
    "team_roster not loaded in route_question"
print("  ✓ team_roster loaded from user_personas table")
assert 'roster_text=' in source, "roster_text not passed to dynamic_query_loop"
print("  ✓ roster_text passed to dynamic_query_loop calls")

# ── Fix 4: query_sdr_metrics handler description tuned ─────────────
print("\n[Fix 4] Checking query_sdr_metrics handler description...")
from api.router import HANDLER_DESCRIPTIONS
desc = HANDLER_DESCRIPTIONS.get('query_sdr_metrics', '')
assert 'how is Jake tracking this month' in desc, \
    "Example phrase 'how is Jake tracking this month' not found"
print("  ✓ Example phrase 'how is Jake tracking this month' found")
assert "show me Jake's calls" in desc, \
    "Example phrase 'show me Jake's calls' not found"
print("  ✓ Example phrase 'show me Jake's calls' found")

# ── All checks passed ──────────────────────────────────────────────
print("\n" + "="*80)
print("✓ ALL FOUR FIXES VERIFIED")
print("="*80)
print("\nReady for Slack test: 'how is Jake tracking this month?'")
print("\nExpected behavior:")
print("  1. [PERSONA] log line showing Jake Stangl lookup")
print("  2. Route to query_sdr_metrics handler (not dynamic_query)")
print("  3. Date filter: August 2026 (not Q3 Oct range)")
print("  4. WHERE owner_email = 'jake.stangl@growthbook.io' (not ilike '%jake%')")
print("\n" + "="*80 + "\n")
