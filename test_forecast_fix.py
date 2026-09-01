#!/usr/bin/env python3
"""
Test forecast question flow after waterfall fix.

Checks:
1. Does it scope to Q3 rather than all open pipeline?
2. Does it use forecast_weekly's precomputed values or sum raw deals?
3. Does it say "Incremental ARR" rather than "ARR"?
4. Does the new by_stage plausibility check fire?
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'api'))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client

def test_waterfall_output():
    """Test query_waterfall returns correct population statement."""
    print("=== Test 1: query_waterfall Population Statement ===\n")

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Credentials not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Import and run query_waterfall
    from handlers import query_waterfall

    params = {
        "question": "show me the pipeline",
        "time_window": None
    }

    result = None
    try:
        import asyncio
        result = asyncio.run(query_waterfall(params, sb))
    except Exception as e:
        print(f"Error running query_waterfall: {e}")
        import traceback
        traceback.print_exc()
        return

    if result and "pipeline_summary" in result:
        summary = result["pipeline_summary"]
        print(f"total_open_count: {summary.get('total_open_count')}")
        print(f"total_open_arr: ${summary.get('total_open_arr', 0):,.0f}")
        print(f"\npopulation_statement: {summary.get('population_statement')}\n")

        # Check by_stage sum
        by_stage = summary.get('by_stage', [])
        stage_sum = sum(s.get('count', 0) for s in by_stage)
        print(f"by_stage sum: {stage_sum}")
        print(f"Matches total_open_count? {stage_sum == summary.get('total_open_count')}")
    else:
        print("No pipeline_summary in result")


def test_plausibility_check():
    """Test that plausibility check would fire on old buggy data."""
    print("\n=== Test 2: Plausibility Check ===\n")

    from plausibility import check_sum_consistency

    # Simulate old buggy data (317 total, 168 in by_stage)
    old_buggy_data = {
        "pipeline_summary": {
            "total_open_count": 317,
            "by_stage": [
                {"stage_name": "Discovery", "count": 87, "arr": 1000},
                {"stage_name": "Technical Evaluation", "count": 32, "arr": 500},
                {"stage_name": "Scoping", "count": 24, "arr": 300},
                {"stage_name": "Review", "count": 14, "arr": 200},
                {"stage_name": "Negotiating", "count": 9, "arr": 100},
                {"stage_name": "Awaiting Signature", "count": 2, "arr": 50},
            ]
        }
    }

    violations = check_sum_consistency(old_buggy_data)

    if violations:
        print(f"✓ Plausibility check FIRED ({len(violations)} violations):\n")
        for v in violations:
            print(f"  {v.severity.upper()}: {v.message}")
            if v.context:
                print(f"  Context: {v.context}")
    else:
        print("✗ Plausibility check did NOT fire (this is a problem)")


def test_forecast_weekly_availability():
    """Check if forecast_weekly has Q3 data ready."""
    print("\n=== Test 3: forecast_weekly Q3 Data ===\n")

    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  Credentials not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Check for Q3 data
    result = sb.table('forecast_weekly').select('*').eq('fiscal_quarter', 'FY2027 Q3').execute()

    if result.data:
        row = result.data[0]
        print(f"✓ forecast_weekly has Q3 data:")
        print(f"  pipeline_id: {row['pipeline_id']}")
        print(f"  open_pipeline_value: ${row['open_pipeline_value']:,.0f}")
        print(f"  stage_weighted_forecast: ${row['stage_weighted_forecast']:,.0f}")
        print(f"  category_weighted_forecast: ${row['category_weighted_forecast']:,.0f}")
        print(f"  week_ending: {row['week_ending']}")
        print(f"\nNOTE: If dynamic loop uses this, it should say:")
        print(f"  'Q3 open pipeline: ${row['open_pipeline_value']:,.0f}'")
        print(f"  NOT 'all open pipeline across all quarters'")
    else:
        print("✗ No Q3 data in forecast_weekly")
        print("  Need to run: python scripts/analytics/compute_forecast.py")


def check_field_display_names():
    """Check if field_semantics.yaml has display names."""
    print("\n=== Test 4: Field Display Names ===\n")

    import yaml
    semantics_path = REPO_ROOT / 'config' / 'field_semantics.yaml'

    if not semantics_path.exists():
        print("✗ field_semantics.yaml not found")
        return

    with open(semantics_path) as f:
        semantics = yaml.safe_load(f)

    # Check if deal_value has a display name
    deal_value_display = None
    for field, config in semantics.items():
        if field == 'deal_value' or field == 'arr_usd':
            display = config.get('display_name') or config.get('label')
            print(f"{field}: {display or 'NO DISPLAY NAME'}")
            if field == 'deal_value':
                deal_value_display = display

    if deal_value_display:
        print(f"\n✓ deal_value has display name: '{deal_value_display}'")
    else:
        print(f"\n✗ deal_value has NO display name")
        print("  Should add: 'display_name: Incremental ARR'")


if __name__ == '__main__':
    test_waterfall_output()
    test_plausibility_check()
    test_forecast_weekly_availability()
    check_field_display_names()

    print("\n" + "="*60)
    print("NEXT STEP: Re-ask forecast question in Slack")
    print("="*60)
    print("\nQuestion to ask: 'What do you forecast for Q3?'")
    print("\nWatch for:")
    print("  1. Does answer scope to Q3 close dates only?")
    print("  2. Does it read from forecast_weekly table?")
    print("  3. Does it say 'Incremental ARR' not 'ARR'?")
    print("  4. Check Railway logs for [PLAUSIBILITY] warnings")
    print("  5. Check Railway logs for [WATERFALL] scope filter counts")
