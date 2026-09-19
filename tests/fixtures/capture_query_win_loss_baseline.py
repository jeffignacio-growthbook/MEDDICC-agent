#!/usr/bin/env python3
"""
Capture query_win_loss regression baseline for the Handler 5/6 unified-
routing migration (Step C).

Runs query_win_loss against REAL current database state for the realistic
default question and a couple of filtered variants. Saves output as a
JSON fixture, matching capture_query_pipeline_baseline.py and
capture_query_stale_deals_baseline.py's own convention exactly, so this
handler's synthesis-layer exposure can be checked the same way theirs
was (see tests/test_synthesis_truncation_fix.py and PENDING_WORK.md's
"SYSTEMIC FINDING: Synthesis-truncation bug is pipeline-wide").
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from handlers import query_win_loss
from db import get_supabase


async def capture_baseline():
    """Capture query_win_loss output for the realistic default question
    plus a couple of filter variants."""
    sb = get_supabase()

    print("Capturing query_win_loss baseline against live database...")
    print("=" * 80)

    # Test case 1: No filters (realistic default — "why are we losing" /
    # "win loss summary" both resolve to this, current quarter)
    print("\n1. No filters (baseline, current quarter)")
    result1 = await query_win_loss({}, sb)
    print(f"   win_count: {result1.get('win_count')}")
    print(f"   loss_count: {result1.get('loss_count')}")
    print(f"   has_narratives: {result1.get('has_narratives')}")
    print(f"   payload size: {len(json.dumps(result1, default=str))} chars")

    # Test case 2: Explicit last-90-days window (a realistic "why did we
    # lose last quarter" style broader window)
    print("\n2. time_window=last 90 days")
    result2 = await query_win_loss(
        {"time_window": {"period": "last_N_days", "n": 90}}, sb)
    print(f"   win_count: {result2.get('win_count')}")
    print(f"   loss_count: {result2.get('loss_count')}")
    print(f"   payload size: {len(json.dumps(result2, default=str))} chars")

    fixtures = {
        "captured_at": "2026-09-19 (Handler 5/6 migration, Step C baseline)",
        "test_cases": [
            {"name": "no_filters_current_quarter", "params": {}, "result": result1},
            {"name": "last_90_days", "params": {"time_window": {"period": "last_N_days", "n": 90}}, "result": result2},
        ],
        "critical_fields_to_verify": [
            "win_count", "loss_count", "has_narratives",
            "wins (length and sample deal_ids)",
            "losses (length and sample deal_ids)",
        ],
    }

    output_path = Path(__file__).parent / "query_win_loss_baseline.json"
    with open(output_path, "w") as f:
        json.dump(fixtures, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print(f"✅ Baseline captured to: {output_path}")


if __name__ == "__main__":
    asyncio.run(capture_baseline())
