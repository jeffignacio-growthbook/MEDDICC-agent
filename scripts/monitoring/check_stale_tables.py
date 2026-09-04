#!/usr/bin/env python3
"""
Wave 6 — Check 1: Stale Precomputed Tables

Simplest check, unambiguous, would have caught forecast_weekly being 21 days old.
Proves the monitoring path works end-to-end.
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'api'))

from supabase_client import select_all
from db import get_supabase
import yaml
import requests


def load_monitoring_config() -> dict:
    """Load monitoring configuration."""
    config_path = Path(__file__).parent.parent.parent / 'config' / 'monitoring.yaml'
    with open(config_path) as f:
        return yaml.safe_load(f)


def check_table_staleness(sb, table_name: str, config: dict) -> Optional[Dict]:
    """
    Check if a precomputed table is stale.

    Returns alert dict if stale, None otherwise.
    """
    max_age_days = config['max_age_days']
    computed_at_col = config['computed_at_column']

    try:
        # Get most recent computed_at timestamp
        result = sb.table(table_name) \
            .select(computed_at_col) \
            .order(computed_at_col, desc=True) \
            .limit(1) \
            .execute()

        if not result.data:
            return {
                'table': table_name,
                'status': 'empty',
                'message': f"Table {table_name} has no rows",
                'severity': 'critical'
            }

        last_computed = result.data[0][computed_at_col]
        last_computed_dt = datetime.fromisoformat(last_computed.replace('Z', '+00:00'))
        age_days = (datetime.now(last_computed_dt.tzinfo) - last_computed_dt).days

        if age_days > max_age_days:
            return {
                'table': table_name,
                'status': 'stale',
                'age_days': age_days,
                'max_age_days': max_age_days,
                'last_computed': last_computed[:10],
                'severity': 'warning' if age_days < max_age_days * 2 else 'critical'
            }

        return None  # Table is fresh

    except Exception as e:
        return {
            'table': table_name,
            'status': 'error',
            'message': str(e),
            'severity': 'error'
        }


def format_alert_message(finding: Dict) -> str:
    """
    Format stale table finding as Slack alert.

    Framed as cause: "the forecast_weekly table is stale; forecasts may be outdated."
    """
    table = finding['table']
    status = finding['status']

    if status == 'empty':
        return (
            f"⚠️ **Stale Data Alert**\n\n"
            f"**Table:** `{table}`\n"
            f"**Issue:** Table is empty\n"
            f"**Impact:** Queries against this table will fail\n"
            f"**Action:** Check ETL logs and re-run table refresh"
        )

    elif status == 'stale':
        age = finding['age_days']
        max_age = finding['max_age_days']
        last_computed = finding['last_computed']

        return (
            f"⚠️ **Stale Data Alert**\n\n"
            f"**Table:** `{table}`\n"
            f"**Last updated:** {last_computed} ({age} days ago)\n"
            f"**Threshold:** {max_age} days\n"
            f"**Impact:** Forecasts and reports may be outdated\n"
            f"**Action:** Run `python scripts/refresh_{table}.py` to update"
        )

    elif status == 'error':
        return (
            f"⚠️ **Monitoring Error**\n\n"
            f"**Table:** `{table}`\n"
            f"**Issue:** {finding['message']}\n"
            f"**Action:** Check table exists and monitoring config is correct"
        )

    return f"Unknown status: {status}"


def send_alert(finding: Dict, config: dict, dry_run: bool = False):
    """
    Send alert via Zapier webhook.

    Reuses ETL alerting path — same hook, type discriminator.
    """
    zapier_url = os.getenv('ZAPIER_ALERT_URL')

    if not zapier_url:
        print("  [ALERT] ZAPIER_ALERT_URL not set, skipping send")
        return

    payload = {
        "type": "monitoring_stale_table",
        "table": finding['table'],
        "severity": finding['severity'],
        "age_days": finding.get('age_days'),
        "max_age_days": finding.get('max_age_days'),
        "message": format_alert_message(finding),
        "channel": config.get('channels', {}).get('operational', 'revops_alerts'),
        "timestamp": datetime.utcnow().isoformat()
    }

    if dry_run:
        print(f"  [ALERT] DRY RUN - would send to {zapier_url}")
        print(f"  Payload: {payload}")
        return

    try:
        response = requests.post(zapier_url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"  [ALERT] Sent successfully")
        else:
            print(f"  [ALERT] Failed: {response.status_code} {response.text[:100]}")
    except Exception as e:
        print(f"  [ALERT] Error sending: {e}")


def should_suppress(sb, finding: Dict, suppression_days: int) -> bool:
    """
    Check if this finding was recently alerted.

    Returns True if should suppress (already alerted recently).
    """
    # TODO: Implement alert suppression tracking
    # For now, always alert (will be noisy initially)
    return False


def main(dry_run: bool = False):
    """Run stale table checks."""
    print()
    print("=" * 80)
    print("WAVE 6 — STALE TABLE MONITORING")
    print("=" * 80)
    print()

    config = load_monitoring_config()

    if not config['monitoring']['enabled']:
        print("Monitoring disabled in config")
        return

    stale_config = config['monitoring']['data_integrity']['stale_tables']

    if not stale_config['enabled']:
        print("Stale table checks disabled in config")
        return

    sb = get_supabase()

    print(f"Checking {len(stale_config['tables'])} precomputed tables...")
    print()

    findings = []

    for table_name, table_config in stale_config['tables'].items():
        print(f"[{table_name}]")
        finding = check_table_staleness(sb, table_name, table_config)

        if finding:
            print(f"  Status: {finding['status']}")
            if finding['status'] == 'stale':
                print(f"  Age: {finding['age_days']} days (threshold: {finding['max_age_days']})")
                print(f"  Severity: {finding['severity']}")
            findings.append(finding)

            # Check suppression
            suppression_days = config['monitoring']['suppression_window_days']
            if should_suppress(sb, finding, suppression_days):
                print(f"  SUPPRESSED (alerted within last {suppression_days} days)")
            else:
                print(f"  Alert message:")
                print()
                for line in format_alert_message(finding).split('\n'):
                    print(f"    {line}")
                print()

                send_alert(finding, config['monitoring'], dry_run=dry_run)
        else:
            print(f"  Status: ✓ Fresh")

        print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    if findings:
        print(f"Found {len(findings)} stale table(s):")
        for f in findings:
            print(f"  - {f['table']}: {f['status']}")
    else:
        print("✓ All precomputed tables are fresh")

    print()

    return findings


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Check for stale precomputed tables')
    parser.add_argument('--dry-run', action='store_true',
                       help='Print alerts without sending')
    args = parser.parse_args()

    findings = main(dry_run=args.dry_run)

    # Exit with error code if critical findings
    critical = [f for f in findings if f.get('severity') == 'critical']
    if critical:
        sys.exit(1)
