"""
Salesloft Sequencer Adapter

Fetches SDR email and sequence metrics from Salesloft.

Returns standardized metrics:
- emails_sent
- emails_opened
- emails_replied
- open_rate
- reply_rate
- calls_made
- connected_calls
- connect_rate
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


class SalesloftSequencerAdapter:
    """
    Salesloft email and sequence metrics adapter.

    Fetches:
    - Email activities (sent, opened, replied)
    - Call activities (made, connected)
    - Sequence performance metrics

    Authentication: Bearer token
    API docs: https://developers.salesloft.com/api.html
    """

    def __init__(self):
        """Initialize Salesloft adapter with API credentials."""
        api_key = os.getenv('SALESLOFT_API_KEY')

        if not api_key:
            raise ValueError(
                'SALESLOFT_API_KEY environment variable required for Salesloft adapter'
            )

        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        self.base_url = 'https://api.salesloft.com/v2'

    def get_metrics(
        self,
        since: date,
        until: date,
        user_ids: Optional[List[str]] = None,
        config: dict = None
    ) -> List[Dict]:
        """
        Fetch email and sequence metrics for date range and optional user filter.

        Args:
            since: Start date (reporting TZ)
            until: End date (reporting TZ)
            user_ids: Optional list of Salesloft user IDs to filter
            config: Client config for timezone conversion

        Returns:
            List of dicts with keys:
                - user_id: Salesloft user ID
                - user_name: User display name
                - emails_sent: Total emails sent
                - emails_opened: Unique opens
                - emails_replied: Unique replies
                - open_rate: {"value": float, "data_gap": bool}
                - reply_rate: {"value": float, "data_gap": bool}
                - calls_made: Total calls
                - connected_calls: Connected calls
                - connect_rate: {"value": float, "data_gap": bool}
        """
        # Convert reporting TZ dates to ISO string filters
        start_str, end_str = api_date_filters(since, until, config, tool="iso_str")

        # Fetch email activities
        email_metrics = self._get_email_metrics(start_str, end_str, user_ids)

        # Fetch call activities
        call_metrics = self._get_call_metrics(start_str, end_str, user_ids)

        # Merge metrics by user
        return self._merge_metrics(email_metrics, call_metrics)

    def _get_email_metrics(
        self,
        start_str: str,
        end_str: str,
        user_ids: Optional[List[str]]
    ) -> Dict[str, Dict]:
        """
        Fetch email activity metrics from Salesloft.

        Endpoint: GET /v2/activities.json
        Filters: type=email, created_at range
        """
        user_metrics = {}
        page = 1
        per_page = 100

        while True:
            params = {
                "type": "email",
                "created_at[gte]": start_str,
                "created_at[lte]": end_str,
                "per_page": per_page,
                "page": page
            }

            response = requests.get(
                f'{self.base_url}/activities.json',
                headers=self.headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            activities = safe_get(data, "data", default=[])

            if not activities:
                break

            # Aggregate by user
            for activity in activities:
                user_id = str(safe_get(activity, "user_id"))
                if not user_id:
                    continue

                # Filter by user_ids if specified
                if user_ids and user_id not in user_ids:
                    continue

                if user_id not in user_metrics:
                    user_metrics[user_id] = {
                        "user_id": user_id,
                        "user_name": safe_get(activity, "user", "name", default=f"User {user_id}"),
                        "emails_sent": 0,
                        "emails_opened": set(),  # Track unique email IDs
                        "emails_replied": set()  # Track unique email IDs
                    }

                # Email sent (all activities represent sent emails)
                user_metrics[user_id]["emails_sent"] += 1

                email_id = safe_get(activity, "email_id")

                # Check for opens
                if safe_get(activity, "opened"):
                    user_metrics[user_id]["emails_opened"].add(email_id)

                # Check for replies
                if safe_get(activity, "replied"):
                    user_metrics[user_id]["emails_replied"].add(email_id)

            # Check for next page
            metadata = safe_get(data, "metadata", default={})
            paging = safe_get(metadata, "paging", default={})

            if not safe_get(paging, "next_page"):
                break

            page += 1

        # Convert sets to counts
        for user_id in user_metrics:
            metrics = user_metrics[user_id]
            metrics["emails_opened"] = len(metrics["emails_opened"])
            metrics["emails_replied"] = len(metrics["emails_replied"])

        return user_metrics

    def _get_call_metrics(
        self,
        start_str: str,
        end_str: str,
        user_ids: Optional[List[str]]
    ) -> Dict[str, Dict]:
        """
        Fetch call activity metrics from Salesloft.

        Endpoint: GET /v2/calls.json
        Filters: created_at range
        """
        user_metrics = {}
        page = 1
        per_page = 100

        while True:
            params = {
                "created_at[gte]": start_str,
                "created_at[lte]": end_str,
                "per_page": per_page,
                "page": page
            }

            response = requests.get(
                f'{self.base_url}/calls.json',
                headers=self.headers,
                params=params,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            calls = safe_get(data, "data", default=[])

            if not calls:
                break

            # Aggregate by user
            for call in calls:
                user_id = str(safe_get(call, "user_id"))
                if not user_id:
                    continue

                # Filter by user_ids if specified
                if user_ids and user_id not in user_ids:
                    continue

                if user_id not in user_metrics:
                    user_metrics[user_id] = {
                        "user_id": user_id,
                        "user_name": safe_get(call, "user", "name", default=f"User {user_id}"),
                        "calls_made": 0,
                        "connected_calls": 0
                    }

                # Increment call count
                user_metrics[user_id]["calls_made"] += 1

                # Check disposition for connected calls
                raw_disposition = safe_get(call, "disposition")
                disposition = normalize_disposition(raw_disposition, "salesloft")

                if connected_from_disposition(disposition):
                    user_metrics[user_id]["connected_calls"] += 1

            # Check for next page
            metadata = safe_get(data, "metadata", default={})
            paging = safe_get(metadata, "paging", default={})

            if not safe_get(paging, "next_page"):
                break

            page += 1

        return user_metrics

    def _merge_metrics(
        self,
        email_metrics: Dict[str, Dict],
        call_metrics: Dict[str, Dict]
    ) -> List[Dict]:
        """
        Merge email and call metrics by user.

        Args:
            email_metrics: Dict of user_id -> email metrics
            call_metrics: Dict of user_id -> call metrics

        Returns:
            List of combined metrics dicts
        """
        # Get all user IDs from both sources
        all_user_ids = set(email_metrics.keys()) | set(call_metrics.keys())

        results = []

        for user_id in all_user_ids:
            email = email_metrics.get(user_id, {})
            calls = call_metrics.get(user_id, {})

            # Use first available user name
            user_name = (email.get("user_name") or
                        calls.get("user_name") or
                        f"User {user_id}")

            emails_sent = to_int(email.get("emails_sent"))
            emails_opened = to_int(email.get("emails_opened"))
            emails_replied = to_int(email.get("emails_replied"))
            calls_made = to_int(calls.get("calls_made"))
            connected_calls = to_int(calls.get("connected_calls"))

            results.append({
                "user_id": user_id,
                "user_name": user_name,
                "emails_sent": emails_sent,
                "emails_opened": emails_opened,
                "emails_replied": emails_replied,
                "open_rate": rate_or_gap(emails_opened, emails_sent),
                "reply_rate": rate_or_gap(emails_replied, emails_sent),
                "calls_made": calls_made,
                "connected_calls": connected_calls,
                "connect_rate": rate_or_gap(connected_calls, calls_made)
            })

        return results
