#!/usr/bin/env python3
"""
Test q019: forecast_weekly staleness check
"""
import sys
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))
from db import get_supabase

def test_q019():
    sb = get_supabase()

    print("=" * 80)
    print("Q019: forecast_weekly Staleness Check")
    print("=" * 80)
    print()

    # Check if forecast_weekly table exists
    try:
        result = sb.table("forecast_weekly").select("*").limit(1).execute()
        table_exists = True
        print("✅ forecast_weekly table exists")
    except Exception as e:
        table_exists = False
        print(f"❌ forecast_weekly table does NOT exist: {e}")
        print()
        print("STATUS: MISSING HANDLER COVERAGE")
        print("This table is part of the precomputed metrics system.")
        return {"status": "MISSING_TABLE"}

    if table_exists:
        # Get most recent timestamp
        try:
            result = sb.table("forecast_weekly").select("computed_at").order(
                "computed_at", desc=True
            ).limit(1).execute()

            if result.data:
                last_computed = result.data[0].get("computed_at")
                if last_computed:
                    computed_dt = datetime.fromisoformat(last_computed.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    days_stale = (now - computed_dt).days

                    print(f"Last computed: {last_computed}")
                    print(f"Days stale: {days_stale}")
                    print()

                    print("VERIFIED VALUE for q019:")
                    print(f"  last_computed: {last_computed}")
                    print(f"  days_stale: {days_stale}")
                    print(f"  status: OPERATIONAL")
                    print()

                    return {
                        "last_computed": last_computed,
                        "days_stale": days_stale,
                        "status": "OPERATIONAL"
                    }
                else:
                    print("❌ computed_at field is NULL")
                    return {"status": "NULL_TIMESTAMP"}
            else:
                print("❌ forecast_weekly table is empty")
                return {"status": "EMPTY_TABLE"}
        except Exception as e:
            print(f"❌ Error querying forecast_weekly: {e}")
            return {"status": "QUERY_ERROR"}

if __name__ == "__main__":
    test_q019()
