"""
Aircall Dialer Adapter

Fetches SDR call metrics from Aircall.

Returns standardized metrics:
- calls_made
- answered_calls
- answer_rate
- missed_calls
- voicemails
- avg_duration_seconds
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
    api_date_filters,
    normalize_disposition,
    connected_from_disposition
)


class AircallDialerAdapter:
    """
    Aircall call metrics adapter.

    Fetches outbound call activities and aggregates by user.

    Authentication: Basic auth (API ID + Token)
    API docs: https://developer.aircall.io/api-references/
    """

    def __init__(self):
        """Initialize Aircall adapter with API credentials."""
        api_id = os.getenv('AIRCALL_API_ID')
        api_token = os.getenv('AIRCALL_API_TOKEN')

        if not api_id or not api_token:
            raise ValueError(
                'AIRCALL_API_ID and AIRCALL_API_TOKEN environment variables '
                'required for Aircall adapter'
            )

        self.headers = {
            'Content-Type': 'application/json'
        }
        self.auth = (api_id, api_token)
        self.base_url = 'https://api.aircall.io/v1'

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
            user_ids: Optional list of Aircall user IDs to filter
            config: Client config for timezone conversion

        Returns:
            List of dicts with keys:
                - user_id: Aircall user ID
                - user_name: User display name
                - calls_made: Total outbound calls
                - answered_calls: Calls answered
                - answer_rate: {"value": float, "data_gap": bool}
                - missed_calls: Missed calls
                - voicemails: Voicemails left
                - avg_duration_seconds: Average call duration
        """
        # Convert reporting TZ dates to Unix epoch timestamps
        start_epoch, end_epoch = api_date_filters(since, until, config, tool="epoch")

        # Fetch all outbound calls
        all_calls = self._fetch_calls(start_epoch, end_epoch, user_ids)

        # Aggregate by user
        return self._aggregate_metrics(all_calls)

    def _fetch_calls(
        self,
        start_epoch: int,
        end_epoch: int,
        user_ids: Optional[List[str]]
    ) -> List[Dict]:
        """
        Fetch call records from Aircall.

        Endpoint: GET /calls
        Filters: from (epoch), to (epoch), direction=outbound
        """
        all_calls = []
        page = 1
        per_page = 50  # Aircall max

        while True:
            params = {
                "from": start_epoch,
                "to": end_epoch,
                "direction": "outbound",
                "per_page": per_page,
                "page": page,
                "order": "asc"
            }

            response = requests.get(
                f'{self.base_url}/calls',
                headers=self.headers,
                auth=self.auth,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            calls = safe_get(data, "calls", default=[])

            if not calls:
                break

            # Filter by user_ids if specified
            if user_ids:
                calls = [
                    c for c in calls
                    if str(safe_get(c, "user_id")) in user_ids
                ]

            all_calls.extend(calls)

            # Check for next page
            meta = safe_get(data, "meta", default={})
            next_page = safe_get(meta, "next_page_link")

            if not next_page:
                break

            page += 1

        return all_calls

    def _aggregate_metrics(self, calls: List[Dict]) -> List[Dict]:
        """
        Aggregate call records by user.

        Args:
            calls: List of Aircall call dicts

        Returns:
            List of user metrics dicts
        """
        user_metrics = {}

        for call in calls:
            user_id = str(safe_get(call, "user_id"))
            if not user_id:
                continue

            if user_id not in user_metrics:
                user_metrics[user_id] = {
                    "user_id": user_id,
                    "user_name": safe_get(call, "user", "name", default=f"User {user_id}"),
                    "calls_made": 0,
                    "answered_calls": 0,
                    "missed_calls": 0,
                    "voicemails": 0,
                    "total_duration": 0  # Track for average calculation
                }

            metrics = user_metrics[user_id]

            # Increment call count
            metrics["calls_made"] += 1

            # Add duration (in seconds)
            duration = to_int(safe_get(call, "duration"))
            metrics["total_duration"] += duration

            # Normalize disposition and categorize
            raw_status = safe_get(call, "status")  # Aircall uses "status" field
            disposition = normalize_disposition(raw_status, "aircall")

            if connected_from_disposition(disposition):
                metrics["answered_calls"] += 1
            elif disposition == "no_answer":
                metrics["missed_calls"] += 1
            elif disposition == "voicemail":
                metrics["voicemails"] += 1

        # Calculate rates and averages
        results = []

        for user_id, metrics in user_metrics.items():
            calls_made = metrics["calls_made"]

            # Calculate average duration
            avg_duration = (
                metrics["total_duration"] / calls_made
                if calls_made > 0
                else 0
            )

            results.append({
                "user_id": user_id,
                "user_name": metrics["user_name"],
                "calls_made": calls_made,
                "answered_calls": metrics["answered_calls"],
                "answer_rate": rate_or_gap(metrics["answered_calls"], calls_made),
                "missed_calls": metrics["missed_calls"],
                "voicemails": metrics["voicemails"],
                "avg_duration_seconds": round(avg_duration, 1)
            })

        return results
