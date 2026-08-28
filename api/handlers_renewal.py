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

        # BUCKET BY FISCAL QUARTER - don't let synthesis re-infer quarters
        # Synthesis will use calendar quarters if we return flat rows.
        # Pre-bucket here using config's fiscal calendar, return quarters dict.
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from utils import get_fiscal_quarter
        from datetime import date as dt_date

        quarters = {}  # {label: {"rows": [...], "start": ..., "end": ..., "total_arr": ...}}

        for row in rows:
            close_str = row.get("close_date")
            if not close_str:
                continue

            # Determine fiscal quarter for this deal's close_date
            close_date = dt_date.fromisoformat(close_str[:10])
            q_start, q_end, q_label = get_fiscal_quarter(close_date, cfg)

            if q_label not in quarters:
                quarters[q_label] = {
                    "rows": [],
                    "start": q_start.isoformat(),
                    "end": q_end.isoformat(),
                    "total_arr": 0,
                    "count": 0
                }

            quarters[q_label]["rows"].append(row)
            quarters[q_label]["total_arr"] += (row.get("arr_usd") or 0)
            quarters[q_label]["count"] += 1

        # Sort quarters chronologically
        sorted_quarters = dict(sorted(quarters.items(), key=lambda x: x[1]["start"]))

        # Calculate overall totals
        total_deals = sum(q["count"] for q in sorted_quarters.values())
        total_arr = sum(q["total_arr"] for q in sorted_quarters.values())

        # Build note with missing value warning if applicable
        note = f"Found {total_deals} upcoming renewals in pipeline {renewal_pipeline_id} (open stages only)"
        if missing_count > 0:
            note += f". WARNING: {missing_count} deal(s) have renewal ARR in 'amount' field instead of 'renewal_revenue' - verify these values are correct (may be prior cycle value, expansion only, or placeholder)"

        return {
            "quarters": sorted_quarters,  # Pre-bucketed by fiscal quarter
            "count": total_deals,
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
