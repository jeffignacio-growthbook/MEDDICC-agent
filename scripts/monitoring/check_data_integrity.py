#!/usr/bin/env python3
"""
Wave 6 — Check 2: Data Integrity

- Value completeness: 127 active deals with no ARR
- Forecast category coverage: 3 deals in COMMIT out of 432
- Unscored late-stage deals: 5 Q3 deals with no MEDDICC data

All three fired this week on real data.
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'api'))

from supabase_client import select_all
from db import get_supabase
import yaml
import requests


def load_monitoring_config() -> dict:
    config_path = Path(__file__).parent.parent.parent / 'config' / 'monitoring.yaml'
    with open(config_path) as f:
        return yaml.safe_load(f)


def check_value_completeness(sb, config: dict) -> Optional[Dict]:
    """
    Check for active deals missing ARR values.

    Alert on the share crossing threshold, not on each occurrence.
    """
    max_null_share = config['max_null_share']
    min_deals = config['min_deals']

    # Get active deals
    deals = select_all(sb, 'deals',
        columns='deal_id,company_name,new_arr,expansion_arr',
        filters=[('eq', 'deal_status', 'active')]
    )

    if len(deals) < min_deals:
        return None  # Not enough deals for meaningful check

    # Count deals with no ARR (both new_arr and expansion_arr are null or 0)
    missing_arr = [
        d for d in deals
        if (not d.get('new_arr') or d['new_arr'] == 0) and
           (not d.get('expansion_arr') or d['expansion_arr'] == 0)
    ]

    null_share = len(missing_arr) / len(deals)

    if null_share > max_null_share:
        return {
            'check': 'value_completeness',
            'total_deals': len(deals),
            'missing_arr_count': len(missing_arr),
            'missing_arr_share': null_share,
            'threshold': max_null_share,
            'severity': 'warning',
            'examples': [d['company_name'] for d in missing_arr[:5]]
        }

    return None


def check_forecast_category_coverage(sb, config: dict) -> Optional[Dict]:
    """
    Check for low COMMIT coverage in forecast categories.

    Three deals in COMMIT out of 432 is a process finding.
    """
    min_commit_share = config['min_commit_share']
    min_deals = config['min_deals']

    # Get active deals with forecast_category
    deals = select_all(sb, 'deals',
        columns='deal_id,forecast_category',
        filters=[('eq', 'deal_status', 'active')]
    )

    if len(deals) < min_deals:
        return None

    commit_deals = [d for d in deals if d.get('forecast_category') == 'COMMIT']
    commit_share = len(commit_deals) / len(deals)

    if commit_share < min_commit_share:
        return {
            'check': 'forecast_category_coverage',
            'total_deals': len(deals),
            'commit_count': len(commit_deals),
            'commit_share': commit_share,
            'threshold': min_commit_share,
            'severity': 'warning'
        }

    return None


def check_unscored_late_stage(sb, config: dict) -> Optional[Dict]:
    """
    Check for late-stage deals with no MEDDICC scores.

    Five Q3 deals with no MEDDICC data at all. Late stage with no call
    evidence is a different problem from a low score.
    """
    late_stages = config['late_stages']
    max_unscored = config['max_unscored_count']

    # Get active deals in late stage
    deals = select_all(sb, 'deals',
        columns='deal_id,company_name,stage,close_date',
        filters=[('eq', 'deal_status', 'active')]
    )

    late_stage_deals = [d for d in deals if d.get('stage') in late_stages]

    if not late_stage_deals:
        return None

    # Check which deals have MEDDICC scores
    deal_ids = [d['deal_id'] for d in late_stage_deals]

    # Get analyses for these deals
    analyses = select_all(sb, 'analyses',
        columns='deal_id,overall_score',
        filters=[('in', 'deal_id', deal_ids)]
    )

    scored_deal_ids = set(a['deal_id'] for a in analyses)
    unscored = [d for d in late_stage_deals if d['deal_id'] not in scored_deal_ids]

    if len(unscored) > max_unscored:
        return {
            'check': 'unscored_late_stage',
            'late_stage_count': len(late_stage_deals),
            'unscored_count': len(unscored),
            'threshold': max_unscored,
            'severity': 'warning',
            'examples': [(d['company_name'], d['stage']) for d in unscored[:5]]
        }

    return None


def format_alert_message(finding: Dict) -> str:
    """Format data integrity finding as Slack alert."""
    check = finding['check']

    if check == 'value_completeness':
        count = finding['missing_arr_count']
        total = finding['total_deals']
        share = finding['missing_arr_share']
        examples = finding['examples']

        return (
            f"⚠️ **Data Completeness Alert**\n\n"
            f"**Issue:** {count} of {total} active deals ({share:.1%}) have no ARR recorded\n"
            f"**Threshold:** {finding['threshold']:.0%}\n"
            f"**Impact:** Pipeline coverage calculations are unreliable\n"
            f"**Examples:** {', '.join(examples[:3])}...\n"
            f"**Action:** Worth a hygiene pass before the forecast call"
        )

    elif check == 'forecast_category_coverage':
        count = finding['commit_count']
        total = finding['total_deals']
        share = finding['commit_share']

        return (
            f"⚠️ **Forecast Category Alert**\n\n"
            f"**Issue:** Only {count} of {total} deals ({share:.1%}) are in COMMIT\n"
            f"**Threshold:** {finding['threshold']:.0%}\n"
            f"**Impact:** Low COMMIT coverage indicates forecast process is degrading\n"
            f"**Action:** Check with AEs on why deals aren't being committed"
        )

    elif check == 'unscored_late_stage':
        count = finding['unscored_count']
        late_count = finding['late_stage_count']
        examples = finding['examples']

        examples_text = '\n'.join([f"  - {name} ({stage})" for name, stage in examples[:3]])

        return (
            f"⚠️ **MEDDICC Coverage Alert**\n\n"
            f"**Issue:** {count} of {late_count} late-stage deals have no MEDDICC scores\n"
            f"**Impact:** Can't assess risk or coach reps on these deals\n"
            f"**Examples:**\n{examples_text}\n"
            f"**Action:** Check if calls exist but weren't scored, or if no calls recorded"
        )

    return f"Unknown check: {check}"


def send_alert(finding: Dict, config: dict, dry_run: bool = False):
    """Send alert via Zapier webhook."""
    zapier_url = os.getenv('ZAPIER_ALERT_URL')

    if not zapier_url:
        print("  [ALERT] ZAPIER_ALERT_URL not set, skipping send")
        return

    payload = {
        "type": "monitoring_data_integrity",
        "check": finding['check'],
        "severity": finding['severity'],
        "message": format_alert_message(finding),
        "channel": config.get('channels', {}).get('operational', 'revops_alerts'),
        "timestamp": datetime.utcnow().isoformat(),
        **{k: v for k, v in finding.items() if k not in ['check', 'severity', 'examples']}
    }

    if dry_run:
        print(f"  [ALERT] DRY RUN - would send to {zapier_url}")
        return

    try:
        response = requests.post(zapier_url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"  [ALERT] Sent successfully")
        else:
            print(f"  [ALERT] Failed: {response.status_code}")
    except Exception as e:
        print(f"  [ALERT] Error sending: {e}")


def main(dry_run: bool = False):
    """Run data integrity checks."""
    print()
    print("=" * 80)
    print("WAVE 6 — DATA INTEGRITY MONITORING")
    print("=" * 80)
    print()

    config = load_monitoring_config()

    if not config['monitoring']['enabled']:
        print("Monitoring disabled in config")
        return []

    integrity_config = config['monitoring']['data_integrity']
    sb = get_supabase()

    checks = [
        ('Value Completeness', check_value_completeness, integrity_config['value_completeness']),
        ('Forecast Category Coverage', check_forecast_category_coverage, integrity_config['forecast_category_coverage']),
        ('Unscored Late-Stage Deals', check_unscored_late_stage, integrity_config['unscored_late_stage'])
    ]

    findings = []

    for check_name, check_func, check_config in checks:
        if not check_config['enabled']:
            print(f"[{check_name}] Disabled")
            continue

        print(f"[{check_name}]")
        finding = check_func(sb, check_config)

        if finding:
            print(f"  Status: ⚠ Alert")
            print(f"  Severity: {finding['severity']}")
            print()
            print("  Alert message:")
            for line in format_alert_message(finding).split('\n'):
                print(f"    {line}")
            print()

            findings.append(finding)
            send_alert(finding, config['monitoring'], dry_run=dry_run)
        else:
            print(f"  Status: ✓ Pass")
            print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    if findings:
        print(f"Found {len(findings)} data integrity issue(s):")
        for f in findings:
            print(f"  - {f['check']}")
    else:
        print("✓ All data integrity checks passed")

    print()

    return findings


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Check data integrity')
    parser.add_argument('--dry-run', action='store_true',
                       help='Print alerts without sending')
    args = parser.parse_args()

    findings = main(dry_run=args.dry_run)

    sys.exit(1 if findings else 0)
