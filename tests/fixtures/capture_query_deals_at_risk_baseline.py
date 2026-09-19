#!/usr/bin/env python3
"""
Capture query_deals_at_risk regression baseline for the Handler 6/6
unified-routing migration (Step C) — the final handler in the Phase 2
migration set.

Runs query_deals_at_risk against REAL current database state for the
realistic default question and an entity-scoped variant. Saves output
as a JSON fixture, matching the established convention
(capture_query_pipeline_baseline.py, capture_query_stale_deals_
baseline.py, capture_query_win_loss_baseline.py).
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from handlers import query_deals_at_risk
from db import get_supabase


async def capture_baseline():
    """Capture query_deals_at_risk output for the realistic default
    question (all active deals, no scope) and a raw-unresolved
    time_window variant — the exact shape that crashed query_win_loss's
    Step C run before the _resolve_tw() fix, deliberately re-tested here
    to confirm that fix actually protects this handler too."""
    sb = get_supabase()

    print("Capturing query_deals_at_risk baseline against live database...")
    print("=" * 80)

    print("\n1. No filters (baseline, all active deals)")
    result1 = await query_deals_at_risk({}, sb)
    print(f"   total_at_risk: {result1.get('total_at_risk')}")
    print(f"   deals_at_risk returned: {len(result1.get('deals_at_risk', []))}")
    print(f"   message: {result1.get('message')}")
    print(f"   payload size: {len(json.dumps(result1, default=str))} chars")

    print("\n2. Raw, unresolved time_window spec (regression check for the "
          "_resolve_tw() fix found during Handler 5's audit)")
    result2 = await query_deals_at_risk(
        {"time_window": {"period": "last_N_days", "n": 30}}, sb)
    print(f"   total_at_risk: {result2.get('total_at_risk')}")
    print(f"   deals_at_risk returned: {len(result2.get('deals_at_risk', []))}")

    fixtures = {
        "captured_at": "2026-09-19 (Handler 6/6 migration, Step C baseline)",
        "test_cases": [
            {"name": "no_filters_all_active", "params": {}, "result": result1},
            {"name": "raw_time_window_last_30_days",
             "params": {"time_window": {"period": "last_N_days", "n": 30}},
             "result": result2},
        ],
        "critical_fields_to_verify": [
            "total_at_risk", "deals_at_risk (length and sample deal_ids)",
            "message (when total_at_risk is 0)",
        ],
    }

    output_path = Path(__file__).parent / "query_deals_at_risk_baseline.json"
    with open(output_path, "w") as f:
        json.dump(fixtures, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print(f"✅ Baseline captured to: {output_path}")


if __name__ == "__main__":
    asyncio.run(capture_baseline())
