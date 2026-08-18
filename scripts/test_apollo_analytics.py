#!/usr/bin/env python3
"""
Test Apollo Analytics API availability.

Tests:
1. Analytics API (premium tier) - POST /v1/analytics/table_view
2. Calls API (fallback) - GET /v1/calls

Reports which endpoints are available and architectural implications.
"""

import requests
import json
from datetime import datetime, timedelta

API_KEY = "05njgutZFqWl0tZ3YhPUig"
BASE_URL = "https://api.apollo.io/v1"

headers = {
    "X-Api-Key": API_KEY,
    "Content-Type": "application/json"
}

print("=" * 80)
print("APOLLO API AVAILABILITY TEST")
print("=" * 80)
print()

# Test 1: Analytics API
print("[TEST 1] Analytics API - Premium Tier Feature")
print()

analytics_payload = {
    "group_by_field": "user_id",
    "analytics_name": "users_analytics",
    "start_date": "2026-07-01T00:00:00.000Z",
    "end_date": "2026-07-31T23:59:59.999Z",
    "metric_fields": ["num_phone_calls", "percent_connected_calls"]
}

try:
    response = requests.post(
        f"{BASE_URL}/analytics/table_view",
        headers=headers,
        json=analytics_payload,
        timeout=10
    )

    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        buckets = data.get("table_response", {}).get("buckets", [])
        print(f"✓ Analytics API AVAILABLE")
        print(f"  Returned {len(buckets)} user buckets")
        print(f"  Architecture: Efficient aggregated queries")
    elif response.status_code == 404:
        print(f"✗ Analytics API NOT AVAILABLE (404)")
        print(f"  Likely requires premium/enterprise plan tier")
        print(f"  Architecture: Must use calls API with client-side aggregation")
    elif response.status_code == 403:
        print(f"✗ Analytics API FORBIDDEN (403)")
        print(f"  API key lacks required permissions")
    else:
        print(f"✗ Unexpected status: {response.status_code}")
        print(f"  Response: {response.text[:200]}")

except Exception as e:
    print(f"✗ Request failed: {e}")

print()

# Test 2: Calls API (fallback)
print("[TEST 2] Calls API - Standard Tier Fallback")
print()

try:
    response = requests.get(
        f"{BASE_URL}/calls",
        headers=headers,
        params={"page": 1, "per_page": 10},
        timeout=10
    )

    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        calls = data.get("calls", [])
        pagination = data.get("pagination", {})
        total_entries = pagination.get("total_entries", 0)
        total_pages = pagination.get("total_pages", 0)

        print(f"✓ Calls API AVAILABLE")
        print(f"  Returned {len(calls)} calls (page 1)")
        print(f"  Total entries: {total_entries}")
        print(f"  Total pages: {total_pages}")
        print(f"  Architecture: Must page through {total_pages} pages @ 200 per page")
    else:
        print(f"✗ Calls API failed: {response.status_code}")
        print(f"  Response: {response.text[:200]}")

except Exception as e:
    print(f"✗ Request failed: {e}")

print()
print("=" * 80)
print("ARCHITECTURAL IMPLICATIONS")
print("=" * 80)
print()

print("If Analytics API is NOT available:")
print()
print("Performance Impact:")
print("  - Every metric query requires paging through ALL calls")
print("  - Example: 1,000 calls = 5 API requests @ 200/page")
print("  - Example: 10,000 calls = 50 API requests")
print("  - ETL runtime: ~10-30 seconds per run vs <1 second with Analytics")
print()
print("Recommended Approach:")
print("  1. Keep dual-mode adapter (Analytics + calls fallback)")
print("  2. Default to calls API for standard tier accounts")
print("  3. Document Analytics API as premium upgrade path")
print("  4. Add --max-pages limit to prevent runaway pagination")
print()
print("Client Impact:")
print("  - Standard tier: SDR metrics work but slower")
print("  - Premium tier: Fast aggregated queries")
print("  - Template repo: Must document both modes")
