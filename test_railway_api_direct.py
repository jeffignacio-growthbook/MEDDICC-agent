#!/usr/bin/env python3
"""Direct test of Railway API to see actual responses."""
import requests
import json
import os

# This should match what GitHub Actions uses
railway_url = os.environ.get('RAILWAY_URL', 'http://localhost:8080')

print(f"Testing Railway API: {railway_url}")
print("=" * 80)

# Test a simple question that should work
test_questions = [
    "What is our pipeline this quarter?",
    "What is team attainment for Q3?",
    "How is Christian tracking?"
]

for question in test_questions:
    print(f"\nQuestion: {question}")
    print("-" * 80)

    try:
        response = requests.post(
            f'{railway_url}/slack/question',
            json={
                'question': question,
                'user_id': 'calibration_test',
                'thread_ts': 'test_123'
            },
            timeout=10
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"Response Keys: {list(data.keys())}")
            print(f"Response (first 500 chars):")
            print(json.dumps(data, indent=2)[:500])

            # Check if it's an error response
            if 'error' in data:
                print(f"\n⚠️  API returned error: {data['error']}")
            elif 'text' in data:
                print(f"\n✓ Got text response (length: {len(data['text'])})")
        else:
            print(f"Error response: {response.text[:200]}")

    except Exception as e:
        print(f"Exception: {e}")

print("\n" + "=" * 80)
print("NOTE: Run this in GitHub Actions with RAILWAY_URL secret to test production API")
