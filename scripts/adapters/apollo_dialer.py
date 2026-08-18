"""
Apollo Dialer Adapter

Fetches SDR call metrics from Apollo.io phone_calls API.

What Apollo Provides:
- calls_made: Reliable (count of call records)
- voicemails: Reliable (voicemail_dropped boolean field)
- dispositions: Partial (phone_call_outcome_id often null, ~30%+ unknown)

What Apollo Does NOT Provide:
- connect_rate: No reliable answered/connected signal in API response
  (duration is often 0, terminal_call_status doesn't indicate answered)
- For connect rate, use Salesloft or Aircall adapters

Returns standardized metrics with data_gap flags where data is unavailable.
"""

import os
import requests
import sys
from datetime import date, datetime
from typing import Dict, List, Optional
from pathlib import Path

# Import SDR utilities
sys.path.insert(0, str(Path(__file__).parent.parent))
from sdr_utils import (
    safe_get,
    to_float,
    to_int,
    rate_or_gap,
    flatten_buckets,
    api_date_filters,
    normalize_disposition,
    connected_from_disposition
)


# Apollo Analytics API does not exist or requires unavailable tier
# Use phone_calls API with client-side aggregation
ANALYTICS_FIRST = False


class ApolloDialerAdapter:
    """
    Apollo.io call metrics adapter.

    Authentication: X-Api-Key header
    API docs: https://apolloio.github.io/apollo-api-docs/

    Note: Apollo's phone_calls API has significant data gaps.
    Connect rate is not calculable. Dispositions are often missing.
    """

    def __init__(self):
        """Initialize Apollo adapter with API credentials."""
        api_key = os.getenv('APOLLO_API_KEY')

        if not api_key:
            raise ValueError(
                'APOLLO_API_KEY environment variable required for Apollo adapter'
            )

        self.headers = {
            'X-Api-Key': api_key,
            'Content-Type': 'application/json',
            'Cache-Control': 'no-cache'
        }
        # Correct base URL includes /api/ prefix
        self.base_url = 'https://api.apollo.io/api/v1'

    def get_metrics(
        self,
        since: date,
        until: date,
        user_ids: Optional[List[str]] = None,
        config: dict = None
    ) -> List[Dict]:
        """
        Fetch call metrics for date range and optional user filter.

        Args:
            since: Start date (reporting TZ)
            until: End date (reporting TZ)
            user_ids: Optional list of Apollo user IDs to filter
            config: Client config for timezone conversion

        Returns:
            List of dicts with keys:
                - user_id: Apollo user ID
                - user_name: User display name
                - calls_made: Total calls
                - voicemails: Count (from voicemail_dropped field)
                - connect_rate: {"value": None, "data_gap": True, "reason": "..."}
                - dispositions: {"connected": N, "no_answer": N, "unknown": N}
                - logging_gap: True if >30% of calls have unknown disposition
        """
        return self._get_calls_metrics(since, until, user_ids, config)

    def _get_calls_metrics(
        self,
        since: date,
        until: date,
        user_ids: Optional[List[str]],
        config: dict
    ) -> List[Dict]:
        """
        Fetch individual call records and aggregate client-side.

        Endpoint: GET /api/v1/phone_calls/search
        Apollo returns call records with:
        - user_id (who made the call)
        - start_time (ISO timestamp)
        - voicemail_dropped (boolean)
        - phone_call_outcome_id (often null)
        - terminal_call_status (cancelled, completed, etc.)
        - duration (often 0, unreliable)
        """
        # Convert reporting TZ dates to UTC filters
        filters = api_date_filters(since, until, config, tool="iso")

        # Fetch all calls for date range
        # Note: Apollo phone_calls/search max per_page is 50 (422 error if higher)
        params = {
            "per_page": 50  # Apollo max allowed
        }

        all_calls = []
        page = 1

        while True:
            params["page"] = page

            response = requests.get(
                f'{self.base_url}/phone_calls/search',
                headers=self.headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            calls = safe_get(data, "phone_calls", default=[])

            if not calls:
                break

            all_calls.extend(calls)

            # Check if more pages exist
            pagination = safe_get(data, "pagination", default={})
            total_pages = to_int(safe_get(pagination, "total_pages"))

            if page >= total_pages or len(calls) < 50:
                break

            page += 1

        # Filter by date range (Apollo doesn't support date params on phone_calls/search)
        date_filtered_calls = []
        for call in all_calls:
            start_time_str = safe_get(call, "start_time")
            if not start_time_str:
                continue

            try:
                # Parse ISO timestamp
                call_date = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')).date()
                if since <= call_date <= until:
                    date_filtered_calls.append(call)
            except (ValueError, AttributeError):
                continue

        all_calls = date_filtered_calls

        # Filter by user_ids if specified
        if user_ids:
            all_calls = [
                c for c in all_calls
                if safe_get(c, "user_id") in user_ids
            ]

        # Aggregate by user
        user_metrics = {}

        for call in all_calls:
            user_id = safe_get(call, "user_id")
            if not user_id:
                continue

            if user_id not in user_metrics:
                # Get caller name from call record
                caller_name = safe_get(call, "caller_name", default=f"User {user_id}")

                user_metrics[user_id] = {
                    "user_id": user_id,
                    "user_name": caller_name,
                    "calls_made": 0,
                    "voicemails": 0,
                    "dispositions": {
                        "connected": 0,
                        "voicemail": 0,
                        "no_answer": 0,
                        "busy": 0,
                        "bad_number": 0,
                        "unknown": 0
                    }
                }

            # Increment call count
            user_metrics[user_id]["calls_made"] += 1

            # Voicemail detection: Use voicemail_dropped field (reliable)
            voicemail_dropped = safe_get(call, "voicemail_dropped")
            if voicemail_dropped is True:
                user_metrics[user_id]["voicemails"] += 1
                user_metrics[user_id]["dispositions"]["voicemail"] += 1
                continue  # Don't double-count as unknown

            # Disposition categorization: Use phone_call_outcome_id
            # Note: This field is often null. We normalize what we can.
            outcome_id = safe_get(call, "phone_call_outcome_id")
            terminal_status = safe_get(call, "terminal_call_status")

            # Normalize disposition using sdr_utils helper
            # Apollo doesn't provide disposition text, only IDs
            # We can't reliably determine "connected" vs other outcomes
            disposition = normalize_disposition(outcome_id, "apollo")

            if disposition == "unknown":
                # Try terminal_call_status as fallback
                if terminal_status == "busy":
                    user_metrics[user_id]["dispositions"]["busy"] += 1
                elif terminal_status in ["no-answer", "failed"]:
                    user_metrics[user_id]["dispositions"]["no_answer"] += 1
                else:
                    user_metrics[user_id]["dispositions"]["unknown"] += 1
            else:
                # Use normalized disposition
                user_metrics[user_id]["dispositions"][disposition] += 1

        # Build results with summary metrics
        results = []
        for metrics in user_metrics.values():
            # Calculate logging gap: >30% unknown = poor logging
            total_calls = metrics["calls_made"]
            unknown_calls = metrics["dispositions"]["unknown"]
            logging_gap = (unknown_calls / total_calls) > 0.30 if total_calls > 0 else False

            # Connect rate: Apollo does NOT provide a reliable connected signal
            # Do not fabricate using duration or recording presence
            connect_rate = {
                "value": None,
                "data_gap": True,
                "reason": "Apollo calls API does not expose a reliable answered/connected signal. Use Salesloft or Aircall for connect rate."
            }

            results.append({
                "user_id": metrics["user_id"],
                "user_name": metrics["user_name"],
                "calls_made": metrics["calls_made"],
                "voicemails": metrics["voicemails"],
                "connect_rate": connect_rate,
                "dispositions": metrics["dispositions"],
                "logging_gap": logging_gap
            })

        return results

    def get_call_summary(
        self,
        since: date,
        until: date,
        config: dict = None
    ) -> Dict:
        """
        Get team-level call summary for date range.

        Returns only what Apollo actually provides reliably:
        - Total calls made
        - Total voicemails dropped
        - Disposition breakdown (with unknown bucket)
        - Connect rate: ALWAYS data_gap=True (Apollo doesn't provide this)
        """
        metrics = self.get_metrics(since, until, user_ids=None, config=config)

        total_calls = sum(m["calls_made"] for m in metrics)
        total_voicemails = sum(m["voicemails"] for m in metrics)

        # Aggregate dispositions
        disposition_summary = {
            "connected": 0,
            "voicemail": 0,
            "no_answer": 0,
            "busy": 0,
            "bad_number": 0,
            "unknown": 0
        }

        for m in metrics:
            for key, count in m["dispositions"].items():
                disposition_summary[key] += count

        # Check logging gap across all users
        unknown_pct = disposition_summary["unknown"] / total_calls if total_calls > 0 else 0
        logging_gap = unknown_pct > 0.30

        return {
            "calls_made": total_calls,
            "voicemails": total_voicemails,
            "connect_rate": {
                "value": None,
                "data_gap": True,
                "reason": "Apollo calls API does not expose a reliable answered/connected signal. Use Salesloft or Aircall for connect rate."
            },
            "dispositions": disposition_summary,
            "logging_gap": logging_gap,
            "logging_gap_pct": round(unknown_pct * 100, 1) if total_calls > 0 else 0
        }
