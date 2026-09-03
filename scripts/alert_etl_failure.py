#!/usr/bin/env python3
"""
Alert on ETL failure - sends Zapier webhook if ETL job fails twice in a row.

Usage in GitHub Actions workflow:
  - name: Alert on failure
    if: failure()
    env:
      ZAPIER_ALERT_URL: ${{ secrets.ZAPIER_ALERT_URL }}
    run: python scripts/alert_etl_failure.py --job ${{ github.job }} --run-id ${{ github.run_id }}

Requires ZAPIER_ALERT_URL in GitHub Secrets and Railway environment.

Payload format matches agent responses with type discriminator:
  {
    "type": "etl_failure",
    "job": "etl-calls",
    "consecutive_failures": 2,
    "run_url": "...",
    "message": "..."
  }
"""
import os
import sys
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))

from db import get_supabase
from supabase_client import select_all


def send_zapier_alert(job_name: str, run_id: str, failure_count: int):
    """Send alert via Zapier webhook."""
    import requests

    zapier_url = os.getenv('ZAPIER_ALERT_URL')
    if not zapier_url:
        print("⚠️  ZAPIER_ALERT_URL not set - cannot send alert")
        return False

    repo_url = f"https://github.com/{os.getenv('GITHUB_REPOSITORY', 'unknown')}"
    run_url = f"{repo_url}/actions/runs/{run_id}"

    # Payload structure:
    # Option 1: Reuse existing hook with type discriminator
    # Option 2: Dedicated alert hook (simpler payload)
    # Using Option 1 format - Zap can branch on type field
    payload = {
        "type": "etl_failure",
        "job": job_name,
        "consecutive_failures": failure_count,
        "run_id": run_id,
        "run_url": run_url,
        "failed_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
        "message": f"ETL job '{job_name}' failed {failure_count} times in a row"
    }

    try:
        response = requests.post(zapier_url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"✓ Alert sent to Zapier for {job_name}")
        return True
    except Exception as e:
        print(f"✗ Failed to send Zapier alert: {e}")
        return False


def record_failure(job_name: str, run_id: str) -> int:
    """
    Record ETL failure in database and return consecutive failure count.
    Returns 0 if this is first failure, 1 if second consecutive, etc.
    """
    try:
        sb = get_supabase()

        # Check for recent failures (last 3 days)
        three_days_ago = (datetime.utcnow() - timedelta(days=3)).isoformat()

        recent_failures = select_all(sb, 'etl_failures',
            columns='job_name,failed_at,run_id',
            filters=[
                ('eq', 'job_name', job_name),
                ('gte', 'failed_at', three_days_ago)
            ]
        )

        # Count consecutive failures (no success between)
        consecutive = len(recent_failures)

        # Record this failure
        sb.table('etl_failures').insert({
            'job_name': job_name,
            'run_id': run_id,
            'failed_at': datetime.utcnow().isoformat(),
            'consecutive_count': consecutive + 1
        }).execute()

        return consecutive + 1

    except Exception as e:
        # If we can't record failures, assume first failure and alert anyway
        print(f"⚠️  Could not record failure in database: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description='Alert on ETL failure')
    parser.add_argument('--job', required=True, help='Job name (e.g., etl-calls)')
    parser.add_argument('--run-id', required=True, help='GitHub Actions run ID')
    parser.add_argument('--threshold', type=int, default=2,
                       help='Alert after N consecutive failures (default: 2)')

    args = parser.parse_args()

    print(f"Checking ETL failure for job: {args.job}")

    # Record failure and get consecutive count
    consecutive = record_failure(args.job, args.run_id)

    print(f"Consecutive failures: {consecutive}")

    # Alert if threshold reached
    if consecutive >= args.threshold:
        print(f"Threshold reached ({consecutive} >= {args.threshold}) - sending alert")
        send_zapier_alert(args.job, args.run_id, consecutive)
    else:
        print(f"Below threshold ({consecutive} < {args.threshold}) - no alert sent")

    # Always exit 0 so workflow continues (failure already recorded)
    return 0


if __name__ == '__main__':
    sys.exit(main())
