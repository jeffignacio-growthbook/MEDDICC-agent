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

        # Select renewal_revenue and arr_usd (fallback when renewal_revenue is NULL)
        rows = select_all(
            sb,
            "deals",
            columns=f"deal_id,company_name,close_date,{renewal_value_field},arr_usd,owner_email,segment,stage,pipeline",
            filters=filters
        )

        # Use renewal_revenue if populated, fall back to arr_usd (from amount) if NULL
        # Matches compute_deal_value fallback pattern (config: pipeline.value_field.fallback)
        for row in rows:
            rr = row.get(renewal_value_field)
            fallback = row.get("arr_usd", 0)
            # Use renewal_revenue if present, otherwise fall back to arr_usd
            row["arr_usd"] = rr if rr is not None else fallback
            # Remove renewal_revenue from output (callers expect arr_usd)
            if renewal_value_field in row:
                row.pop(renewal_value_field)

        # Sort by close_date in Python (select_all doesn't support ordering)
        rows.sort(key=lambda r: r.get("close_date") or "")

        # Calculate total renewal ARR
        total_arr = sum(row.get("arr_usd") or 0 for row in rows)

        return {
            "rows": rows,
            "count": len(rows),
            "total_arr": total_arr,
            "time_window": tw,
            "note": f"Found {len(rows)} upcoming renewals in pipeline {renewal_pipeline_id} (open stages only)"
        }

    except Exception as e:
        return {
            "rows": [],
            "count": 0,
            "error": f"Failed to query renewals: {str(e)}",
            "time_window": tw
        }
