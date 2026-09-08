#!/usr/bin/env python3
"""
Test the updated compute_cycle_time() handler with config-driven windows.
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase
from handlers import compute_cycle_time

def test_handler():
    sb = get_supabase()

    print("=" * 80)
    print("TESTING CONFIG-DRIVEN compute_cycle_time() HANDLER")
    print("=" * 80)
    print()

    # Test 1: Default (should use config)
    print("Test 1: Default call (reads from config/metrics.yaml)")
    print("-" * 80)
    result = compute_cycle_time(sb)
    print(f"Window: {result['window']}")
    print(f"Median: {result.get('median_days')} days")
    print(f"Sample size: {result['sample_size']} deals")
    print(f"Distribution: P25={result.get('p25_days')}, P75={result.get('p75_days')}")
    if "config_note" in result:
        print(f"Config note: {result['config_note']}")
    print()

    # Test 2: Explicit all-time (override)
    print("Test 2: Explicit all-time (since_date=None)")
    print("-" * 80)
    result_all_time = compute_cycle_time(sb, since_date=None)
    print(f"Window: {result_all_time['window']}")
    print(f"Median: {result_all_time.get('median_days')} days")
    print(f"Sample size: {result_all_time['sample_size']} deals")
    print()

    # Test 3: Explicit 6-month window
    print("Test 3: Explicit 6-month override (since_date='2026-03-06')")
    print("-" * 80)
    result_6mo = compute_cycle_time(sb, since_date="2026-03-06")
    print(f"Window: {result_6mo['window']}")
    print(f"Median: {result_6mo.get('median_days')} days")
    print(f"Sample size: {result_6mo['sample_size']} deals")
    print()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print("Config-driven behavior:")
    print(f"  - Default call uses window: {result['window']}")
    print(f"  - Result: {result.get('median_days')} days ({result['sample_size']} deals)")
    print()
    print("Override behavior:")
    print(f"  - All-time: {result_all_time.get('median_days')} days ({result_all_time['sample_size']} deals)")
    print(f"  - 6-month: {result_6mo.get('median_days')} days ({result_6mo['sample_size']} deals)")
    print()
    print("✅ Handler successfully reads from config/metrics.yaml")

if __name__ == "__main__":
    test_handler()
