"""
Renewal-specific handlers for CRO Slack Agent.

Separated from main handlers.py for clarity and testing.
"""

import sys
from pathlib import Path

# Add scripts to path for supabase_client
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from supabase_client import select_all


def query_upcoming_renewals(params: dict, sb) -> dict:
    """
    Return customers due to renew (future tense, upcoming renewals) in a time window.

    Filters for OPEN renewal pipeline deals (Upcoming Renewal, Renewal Engaged stages),
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
                    "stage": str
                },
                ...
            ],
            "count": int,
            "time_window": {"start": str, "end": str, "label": str}
        }
    """
    from api.handlers import _resolve_tw

    tw = _resolve_tw(params)

    try:
        # Query for deals in renewal pipeline with open stages
        # Using stage names from HubSpot export: "Upcoming Renewal (Renewal)" and "Renewal Engaged (Renewal)"
        # The "(Renewal)" suffix indicates the pipeline

        # First, try filtering by pipeline if the field exists
        filters = [
            ("gte", "close_date", tw["start"]),
            ("lte", "close_date", tw["end"]),
            ("neq", "deal_status", "won"),  # Exclude already closed-won
            ("neq", "deal_status", "lost"),  # Exclude closed-lost
        ]

        rows = select_all(
            sb,
            "deals",
            columns="deal_id,company_name,close_date,arr_usd,owner_email,segment,stage",
            filters=filters,
            order="close_date.asc"
        )

        # Post-filter for renewal stages (since we can't do LIKE in select_all filters)
        renewal_rows = [
            row for row in rows
            if row.get("stage") and (
                "Upcoming Renewal" in row["stage"] or
                "Renewal Engaged" in row["stage"] or
                "Renewal" in row.get("pipeline", "")
            )
        ]

        return {
            "rows": renewal_rows,
            "count": len(renewal_rows),
            "time_window": tw,
            "note": f"Found {len(renewal_rows)} upcoming renewals (open stages only, not closed-won)"
        }

    except Exception as e:
        return {
            "rows": [],
            "count": 0,
            "error": f"Failed to query renewals: {str(e)}",
            "time_window": tw
        }
