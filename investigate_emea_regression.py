#!/usr/bin/env python3
"""
Investigate EMEA regression from production Slack query.

Key questions:
1. Why did model query without region=eq.EMEA filter?
2. Why did it answer after 1 iteration without drilling down?
3. Did synthesis prompt changes (b830d2d, 0bdd0a5, f1d42d7) cause this?

Production behavior (2026-09-09 17:12):
  Iteration 0: filter_table waterfall_weekly (NO region filter) → 50 rows
  Iteration 1: Answered immediately with fabricated "EMEA doesn't exist" claim

Expected behavior (from yesterday's tests):
  Iteration 0: filter_table waterfall_weekly region=eq.EMEA → 16-20 rows
  Iteration 1: Answer with EMEA-specific data
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'api'))

from dotenv import load_dotenv
load_dotenv()

print("=" * 70)
print("EMEA REGRESSION INVESTIGATION")
print("=" * 70)
print()

# Step 1: Confirm EMEA data exists
from supabase import create_client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

print("Step 1: Verify EMEA data exists")
print("-" * 70)

result = sb.table('waterfall_weekly').select('region, week_ending').eq('region', 'EMEA').gte('week_ending', '2026-08-24').execute()

print(f"EMEA rows in waterfall_weekly (last 2 weeks): {len(result.data)}")
if result.data:
    weeks = set(r['week_ending'] for r in result.data)
    print(f"Weeks present: {sorted(weeks)}")
    print()
    print("✅ EMEA DATA EXISTS - Slack answer claim was FABRICATED")
else:
    print("❌ NO EMEA DATA - Slack answer was correct")
print()

# Step 2: Compare query patterns
print("Step 2: Compare query patterns")
print("-" * 70)
print()

print("PRODUCTION QUERY (2026-09-09 17:12):")
print("  Iteration 0: filter_table waterfall_weekly")
print("    Filters: week_ending >= 2026-08-24, week_ending <= 2026-09-09")
print("    NO REGION FILTER ❌")
print("    Result: 50 rows (all regions mixed)")
print()
print("  Iteration 1: Answered immediately")
print("    Claimed: 'EMEA region isn't tracked'")
print()

print("EXPECTED QUERY (from yesterday's tests):")
print("  Iteration 0: filter_table waterfall_weekly")
print("    Filters: week_ending >= 2026-08-24, region = EMEA")
print("    Result: 16-20 rows (EMEA only)")
print()
print("  Iteration 1: Answer with EMEA breakdown")
print()

# Step 3: Check synthesis prompt for "answer early" bias
print("Step 3: Check if synthesis prompt changes caused regression")
print("-" * 70)
print()

print("Recent synthesis prompt changes:")
print("  b830d2d (2026-09-09): Added aggregation instruction")
print("  0bdd0a5 (2026-09-09): Added zero vs missing distinction")
print("  f1d42d7 (2026-09-09): Added dimension naming instruction")
print()

print("Current synthesis prompt excerpt:")
with open('api/router.py', 'r') as f:
    content = f.read()
    # Find the aggregation instruction
    start = content.find('CRITICAL AGGREGATION RULE')
    if start != -1:
        excerpt = content[start:start+800]
        print(excerpt[:600])
        print()

print("HYPOTHESIS: Prompt says 'Report data from EVERY row' which might")
print("make model think it HAS all data after one query, even when it")
print("retrieved ALL regions instead of filtering to the requested one.")
print()

# Step 4: Root cause analysis
print("Step 4: Root cause analysis")
print("-" * 70)
print()

print("The model:")
print("  1. Queried waterfall_weekly for last 2 weeks (correct)")
print("  2. Did NOT add region=eq.EMEA filter (WRONG)")
print("  3. Got 50 rows with ALL regions mixed together")
print("  4. Saw 20-row sample in synthesis (aggregated view)")
print("  5. Did NOT see EMEA in the sample (or saw mixed data)")
print("  6. Concluded 'EMEA not tracked' instead of 'I need to filter by EMEA'")
print()

print("This is NOT a synthesis issue - synthesis worked on wrong data.")
print("This IS a query generation issue - model didn't extract 'EMEA' from")
print("question and add it as a filter.")
print()

print("Why didn't it filter by region?")
print("  Option A: Question classifier/schema context didn't emphasize region")
print("  Option B: Model overlooked 'EMEA' in question text")
print("  Option C: Recent prompt changes made model less thorough in query building")
print()

# Step 5: Check if this is systematic
print("Step 5: Is this a systemic regression?")
print("-" * 70)
print()

print("To test: Re-run same question and see if it happens again")
print("If yes: Recent changes broke query generation")
print("If no: One-off LLM variability")
print()

print("=" * 70)
print("RECOMMENDATION")
print("=" * 70)
print()

print("DO NOT patch synthesis prompt again.")
print()
print("The issue is in QUERY GENERATION (iteration 0), not synthesis (iteration 1).")
print()
print("Root cause: Model queried without region filter, so synthesis never")
print("had a chance to see EMEA-specific data.")
print()
print("Investigation needed:")
print("  1. Re-run same question to check if reproducible")
print("  2. If reproducible: Check if synthesis prompt changes affected")
print("     query generation behavior (made model less thorough)")
print("  3. If reproducible: Consider whether routing to query_pipeline_movement")
print("     (with proper region handling) would prevent this")
