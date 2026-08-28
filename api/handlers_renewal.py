"""
Renewal-specific handlers for CRO Slack Agent.

Separated from main handlers.py for clarity and testing.
"""

import sys
from pathlib import Path

# Add scripts to path for supabase_client
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from supabase_client import select_all


async def query_upcoming_renewals(params: dict, sb) -> dict:
    """
    Return customers due to renew (future tense, upcoming renewals) in a time window.

    Filters for OPEN renewal pipeline deals (pipeline_id from config),
    NOT closed-won renewals. This handler exists because "due to renew" (forward-looking)
    was misinterpreted as "already renewed" (past tense) by the dynamic loop.

    Returns:
        {
            "rows": [
                {
                    "deal_id": str,
                    "company_name": str,
                    "close_date": str (YYYY-MM-DD),
                    "arr_usd": float,
                    "owner_email": str,
                    "segment": str,
                    "stage": str,
                    "pipeline": str
                },
                ...
            ],
            "count": int,
            "time_window": {"start": str, "end": str, "label": str}
        }
    """
    from api.handlers import _resolve_tw
    import yaml

    tw = _resolve_tw(params)

    # Load renewal pipeline ID and value field from config (portable across deployments)
    cfg_path = Path(__file__).parent.parent / "config" / "client.yaml"
    cfg = yaml.safe_load(open(cfg_path))

    vf_config = cfg.get("pipeline", {}).get("value_field", {})

    # Get renewal pipeline ID from config
    renewal_pipeline_ids = vf_config.get("renewal_pipeline_ids", [])
    if not renewal_pipeline_ids:
        return {
            "rows": [],
            "count": 0,
            "error": "No renewal pipeline configured in config/client.yaml (pipeline.value_field.renewal_pipeline_ids)",
            "time_window": tw
        }

    renewal_pipeline_id = renewal_pipeline_ids[0]  # Use first renewal pipeline

    # Get renewal value field from config
    renewal_components = vf_config.get("renewal_components", [])
    if not renewal_components:
        return {
            "rows": [],
            "count": 0,
            "error": "No renewal value field configured in config/client.yaml (pipeline.value_field.renewal_components)",
            "time_window": tw
        }

    renewal_value_field = renewal_components[0]  # Use first renewal component (renewal_revenue)

    try:
        # Query for deals in renewal pipeline with close dates in range and open status
        filters = [
            ("eq", "pipeline", renewal_pipeline_id),  # Renewal pipeline from config
            ("gte", "close_date", tw["start"]),
            ("lte", "close_date", tw["end"]),
            ("neq", "deal_status", "won"),  # Exclude already closed-won
            ("neq", "deal_status", "lost"),  # Exclude closed-lost
        ]

        # Select renewal_revenue and arr_usd to detect missing values
        rows = select_all(
            sb,
            "deals",
            columns=f"deal_id,company_name,close_date,{renewal_value_field},arr_usd,owner_email,segment,stage,pipeline",
            filters=filters
        )

        # Use renewal_revenue if populated, mark missing values with flag
        # Do NOT auto-fallback to arr_usd - amount may hold wrong value (prior cycle,
        # expansion only, placeholder). Fallbacks substitute plausible-but-wrong numbers.
        missing_count = 0
        for row in rows:
            rr = row.get(renewal_value_field)
            fallback = row.get("arr_usd", 0)

            if rr is not None:
                # renewal_revenue populated - use it
                row["arr_usd"] = rr
                row["value_source"] = "renewal_revenue"
            elif fallback > 0:
                # renewal_revenue NULL but amount has value - flag for review
                row["arr_usd"] = fallback
                row["value_source"] = "amount (renewal ARR not set)"
                missing_count += 1
            else:
                # Both NULL - genuinely blank
                row["arr_usd"] = 0
                row["value_source"] = "not set"
                missing_count += 1

            # Remove renewal_revenue from output (callers expect arr_usd)
            if renewal_value_field in row:
                row.pop(renewal_value_field)

        # Sort by close_date in Python (select_all doesn't support ordering)
        rows.sort(key=lambda r: r.get("close_date") or "")

        # Calculate total renewal ARR
        total_arr = sum(row.get("arr_usd") or 0 for row in rows)

        # Build note with missing value warning if applicable
        note = f"Found {len(rows)} upcoming renewals in pipeline {renewal_pipeline_id} (open stages only)"
        if missing_count > 0:
            note += f". WARNING: {missing_count} deal(s) have renewal ARR in 'amount' field instead of 'renewal_revenue' - verify these values are correct (may be prior cycle value, expansion only, or placeholder)"

        return {
            "rows": rows,
            "count": len(rows),
            "total_arr": total_arr,
            "missing_renewal_revenue_count": missing_count,
            "time_window": tw,
            "note": note
        }

    except Exception as e:
        return {
            "rows": [],
            "count": 0,
            "error": f"Failed to query renewals: {str(e)}",
            "time_window": tw
        }
