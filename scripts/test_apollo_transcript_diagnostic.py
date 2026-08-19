#!/usr/bin/env python3
"""Test Apollo transcript diagnostic logging."""

import os
import sys
import logging
from pathlib import Path

# Add paths
REPO_ROOT = Path(__file__).parent.parent
REVOPS_METRICS = REPO_ROOT.parent / 'revops-metrics'
if REVOPS_METRICS.exists():
    sys.path.insert(0, str(REVOPS_METRICS))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

# Set API key
os.environ['APOLLO_API_KEY'] = '05njgutZFqWl0tZ3YhPUig'

# Configure logging to show DEBUG level
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from apollo_client import get_apollo_client

# Test with a known failed call
FAILED_CALL_ID = "69bacf68e7c2d7000d1f7f6d"

def test_apollo_transcript_structure():
    """Test what the Apollo transcript structure actually looks like."""
    print(f"\n{'=' * 70}")
    print(f"Testing Apollo Call ID: {FAILED_CALL_ID}")
    print('=' * 70)

    client = get_apollo_client()

    try:
        detail = client.get_conversation(FAILED_CALL_ID)

        print(f"\n✅ Successfully fetched conversation")
        print(f"   Keys in response: {list(detail.keys())}")

        # Check transcript field
        transcript_list = detail.get('transcript', [])

        print(f"\n📊 Transcript Analysis:")
        print(f"   Type: {type(transcript_list)}")
        print(f"   Length: {len(transcript_list) if transcript_list else 0}")

        if transcript_list:
            print(f"\n   First entry: {str(transcript_list[0])[:200]}")

            # Check first entry structure
            sample = transcript_list[0]
            if isinstance(sample, dict):
                print(f"\n   Sample entry keys: {list(sample.keys())}")

                # Show what fields are available
                for key in ['speaker', 'words', 'text', 'content', 'utterance', 'user_name']:
                    if key in sample:
                        value = sample[key]
                        print(f"   ✓ Has '{key}': {str(value)[:100]}")

            # Show first 3 entries
            print(f"\n   First 3 entries:")
            for i, entry in enumerate(transcript_list[:3], 1):
                print(f"   {i}. {entry}")

        else:
            print(f"\n   ❌ Transcript list is empty or None")

            # Check if there are other fields that might contain transcript data
            print(f"\n   Other fields in response:")
            for key, value in detail.items():
                if key != 'transcript':
                    print(f"     - {key}: {type(value)} (len={len(value) if isinstance(value, (list, dict, str)) else 'N/A'})")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_apollo_transcript_structure()
