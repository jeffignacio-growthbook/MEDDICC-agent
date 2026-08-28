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

    # Load renewal pipeline ID from config (portable across deployments)
    cfg_path = Path(__file__).parent.parent / "config" / "client.yaml"
    cfg = yaml.safe_load(open(cfg_path))

    # Get renewal pipeline ID from pipeline.value_field.renewal_pipeline_ids
    renewal_pipeline_ids = cfg.get("pipeline", {}).get("value_field", {}).get("renewal_pipeline_ids", [])
    if not renewal_pipeline_ids:
        return {
            "rows": [],
            "count": 0,
            "error": "No renewal pipeline configured in config/client.yaml",
            "time_window": tw
        }

    renewal_pipeline_id = renewal_pipeline_ids[0]  # Use first renewal pipeline

    try:
        # Query for deals in renewal pipeline with close dates in range and open status
        filters = [
            ("eq", "pipeline", renewal_pipeline_id),  # Renewal pipeline from config
            ("gte", "close_date", tw["start"]),
            ("lte", "close_date", tw["end"]),
            ("neq", "deal_status", "won"),  # Exclude already closed-won
            ("neq", "deal_status", "lost"),  # Exclude closed-lost
        ]

        rows = select_all(
            sb,
            "deals",
            columns="deal_id,company_name,close_date,arr_usd,owner_email,segment,stage,pipeline",
            filters=filters
        )

        # Sort by close_date in Python (select_all doesn't support ordering)
        rows.sort(key=lambda r: r.get("close_date") or "")

        return {
            "rows": rows,
            "count": len(rows),
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
