"""
Apollo Dialer Adapter

Fetches SDR call metrics from Apollo.io.
Note: Apollo Analytics API requires premium plan tier.
This adapter falls back to calls API when Analytics is unavailable.

Returns standardized metrics:
- calls_made
- connected_calls
- connect_rate
- voicemails
- no_answers
- bad_numbers
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


class ApolloDialerAdapter:
    """
    Apollo.io call metrics adapter.

    Supports two modes:
    1. Analytics API (premium tier) - aggregated metrics by user
    2. Calls API (fallback) - individual call records, aggregated client-side

    Authentication: X-Api-Key header
    API docs: https://apolloio.github.io/apollo-api-docs/
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
        self.base_url = 'https://api.apollo.io/v1'

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
                - connected_calls: Calls with connected disposition
                - connect_rate: {"value": float, "data_gap": bool}
                - voicemails: Count
                - no_answers: Count
                - bad_numbers: Count
        """
        # Try Analytics API first (premium feature)
        try:
            return self._get_analytics_metrics(since, until, user_ids, config)
        except Exception as e:
            print(f"Apollo Analytics API unavailable (premium tier): {e}")
            print("Falling back to calls API aggregation...")
            return self._get_calls_metrics(since, until, user_ids, config)

    def _get_analytics_metrics(
        self,
        since: date,
        until: date,
        user_ids: Optional[List[str]],
        config: dict
    ) -> List[Dict]:
        """
        Fetch metrics from Apollo Analytics API (premium tier).

        Endpoint: POST /v1/analytics/table_view
        Returns pre-aggregated metrics by user.
        """
        # Convert reporting TZ dates to UTC filters
        filters = api_date_filters(since, until, config, tool="iso")

        # Build request body
        request_body = {
            "group_by_field": "user_id",
            "analytics_name": "users_analytics",
            "start_date": filters["min"],
            "end_date": filters["max"],
            "metric_fields": [
                "num_phone_calls",
                "percent_connected_calls",
                "num_connected_calls",
                "num_voicemails",
                "num_no_answers"
            ]
        }

        # Filter by specific users if provided
        if user_ids:
            request_body["filter"] = {"user_ids": user_ids}

        response = requests.post(
            f'{self.base_url}/analytics/table_view',
            headers=self.headers,
            json=request_body,
            timeout=30
        )

        # Check for permissions/plan tier issues
        if response.status_code == 403:
            raise ValueError("Analytics API requires premium plan tier")

        response.raise_for_status()
        data = response.json()

        # Extract buckets using sdr_utils helper
        buckets = flatten_buckets(data, "num_phone_calls")

        if not buckets:
            raise ValueError("Empty analytics response (may need premium tier)")

        # Transform to standard metrics format
        results = []
        for bucket in buckets:
            user_id = safe_get(bucket, "key")

            # Apollo Analytics returns percent_ fields as decimals (0.23 = 23%)
            calls_made = to_int(safe_get(bucket, "num_phone_calls"))
            connected_calls = to_int(safe_get(bucket, "num_connected_calls"))

            results.append({
                "user_id": user_id,
                "user_name": safe_get(bucket, "name", default=f"User {user_id}"),
                "calls_made": calls_made,
                "connected_calls": connected_calls,
                "connect_rate": rate_or_gap(connected_calls, calls_made),
                "voicemails": to_int(safe_get(bucket, "num_voicemails")),
                "no_answers": to_int(safe_get(bucket, "num_no_answers")),
                "bad_numbers": to_int(safe_get(bucket, "num_bad_numbers"))
            })

        return results

    def _get_calls_metrics(
        self,
        since: date,
        until: date,
        user_ids: Optional[List[str]],
        config: dict
    ) -> List[Dict]:
        """
        Fetch individual call records and aggregate client-side.

        Endpoint: GET /v1/calls
        Fallback when Analytics API is unavailable.
        """
        # Convert reporting TZ dates to UTC filters
        filters = api_date_filters(since, until, config, tool="iso")

        # Fetch all calls for date range
        params = {
            "created_at_min": filters["min"],
            "created_at_max": filters["max"],
            "per_page": 200  # Max allowed
        }

        all_calls = []
        page = 1

        while True:
            params["page"] = page

            response = requests.get(
                f'{self.base_url}/calls',
                headers=self.headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            calls = safe_get(data, "calls", default=[])

            if not calls:
                break

            all_calls.extend(calls)

            # Check if more pages exist
            pagination = safe_get(data, "pagination", default={})
            total_pages = to_int(safe_get(pagination, "total_pages"))

            if page >= total_pages:
                break

            page += 1

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
                user_metrics[user_id] = {
                    "user_id": user_id,
                    "user_name": safe_get(call, "user", "name", default=f"User {user_id}"),
                    "calls_made": 0,
                    "connected_calls": 0,
                    "voicemails": 0,
                    "no_answers": 0,
                    "bad_numbers": 0
                }

            # Increment call count
            user_metrics[user_id]["calls_made"] += 1

            # Normalize disposition and categorize
            raw_disposition = safe_get(call, "disposition")
            disposition = normalize_disposition(raw_disposition, "apollo")

            if connected_from_disposition(disposition):
                user_metrics[user_id]["connected_calls"] += 1
            elif disposition == "voicemail":
                user_metrics[user_id]["voicemails"] += 1
            elif disposition == "no_answer":
                user_metrics[user_id]["no_answers"] += 1
            elif disposition == "bad_number":
                user_metrics[user_id]["bad_numbers"] += 1

        # Calculate connect rates
        results = []
        for metrics in user_metrics.values():
            metrics["connect_rate"] = rate_or_gap(
                metrics["connected_calls"],
                metrics["calls_made"]
            )
            results.append(metrics)

        return results
