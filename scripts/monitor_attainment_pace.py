#!/usr/bin/env python3
"""
Trigger 1: Attainment Pace Monitor

SPEC: "12.7% two-thirds through a quarter. Threshold on pace relative to plan,
not on an absolute number."

Alerts when attainment is below expected pace at a checkpoint in the quarter
(e.g., week 8 of 13). Useful for early warning that the team is behind plan.

Usage:
    python scripts/monitor_attainment_pace.py
    python scripts/monitor_attainment_pace.py --quarter "FY2027 Q1"
"""
import os
import sys
import yaml
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase


def load_config() -> Dict:
    """Load monitoring configuration."""
    config_path = Path(__file__).parent.parent / 'config' / 'monitoring.yaml'
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config['monitoring']['data_integrity']['attainment_pace']


def get_current_quarter_info(sb):
    """Get current fiscal quarter label and week number."""
    sys.path.insert(0, str(Path(__file__).parent))
    from utils import get_fiscal_quarter
    from datetime import date

    today = date.today()
    q_start, q_end, fiscal_quarter = get_fiscal_quarter(today)

    # Calculate week of quarter
    days_into_quarter = (today - q_start).days
    week_of_quarter = (days_into_quarter // 7) + 1
    week_of_quarter = min(week_of_quarter, 13)

    return fiscal_quarter, week_of_quarter, q_start, q_end


def get_quarter_attainment(sb, fiscal_quarter: str) -> Dict:
    """
    Calculate attainment for a fiscal quarter.

    Returns:
        {
            'closed_won_arr': float,
            'plan_arr': float,
            'attainment_pct': float,
            'deals_count': int
        }
    """
    # Query deals_snapshot for latest week of this quarter
    result = sb.table('deals_snapshot') \
        .select('deal_value, deal_status, fiscal_quarter, week_of_quarter') \
        .eq('fiscal_quarter', fiscal_quarter) \
        .order('week_of_quarter', desc=True) \
        .limit(1000) \
        .execute()

    if not result.data:
        return None

    # Get latest week
    latest_week = max(snap['week_of_quarter'] for snap in result.data)

    # Sum closed-won ARR
    closed_won_arr = sum(
        snap.get('deal_value', 0) or 0
        for snap in result.data
        if snap['week_of_quarter'] == latest_week and snap.get('deal_status') == 'won'
    )

    deals_count = sum(
        1 for snap in result.data
        if snap['week_of_quarter'] == latest_week and snap.get('deal_status') == 'won'
    )

    # Get plan from config or database
    # For now, return None for plan (would need to be configured per quarter)
    plan_arr = None

    return {
        'closed_won_arr': closed_won_arr,
        'plan_arr': plan_arr,
        'attainment_pct': None,  # Can't calculate without plan
        'deals_count': deals_count,
        'latest_week': latest_week
    }


def check_attainment_pace(
    attainment: Dict,
    current_week: int,
    config: Dict
) -> Optional[Dict]:
    """
    Check if attainment pace is below threshold.

    Returns alert evidence if threshold exceeded, None otherwise.
    """
    # Skip if we don't have plan data
    if not attainment or attainment['plan_arr'] is None:
        return None

    # Check if we're at the checkpoint week
    if current_week != config['check_at_week']:
        return None

    # Skip if plan is below minimum
    if attainment['plan_arr'] < config['min_arr_plan']:
        return None

    # Calculate expected pace
    # At week 8 of 13, should be at (8/13) = 61.5% of plan
    expected_pct = (current_week / 13.0) * 100

    # Calculate actual pace
    if attainment['attainment_pct'] is None and attainment['plan_arr']:
        attainment_pct = (attainment['closed_won_arr'] / attainment['plan_arr']) * 100
    else:
        attainment_pct = attainment['attainment_pct']

    # Check if below minimum pace threshold
    min_required_pct = expected_pct * (config['min_pace_pct'] / 100.0)

    if attainment_pct >= min_required_pct:
        return None

    # Build evidence
    evidence = {
        'current_week': current_week,
        'closed_won_arr': attainment['closed_won_arr'],
        'plan_arr': attainment['plan_arr'],
        'attainment_pct': attainment_pct,
        'expected_pct_at_week': expected_pct,
        'min_required_pct': min_required_pct,
        'pace_deficit': min_required_pct - attainment_pct,
        'deals_closed': attainment['deals_count']
    }

    return evidence


def send_monitoring_alert(
    monitor_name: str,
    threshold_config: Dict,
    evidence: Dict,
    message: str,
    alert_url: Optional[str] = None
) -> None:
    """Send monitoring alert via Zapier webhook."""
    payload = {
        "type": "monitoring_alert",
        "monitor": monitor_name,
        "fired_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
        "threshold_config": threshold_config,
        "evidence": evidence,
        "message": message
    }

    if alert_url:
        try:
            response = requests.post(alert_url, json=payload, timeout=10)
            response.raise_for_status()
            print(f"✓ Alert sent to {alert_url}")
        except Exception as e:
            print(f"⚠️  Failed to send alert: {e}")
    else:
        print("⚠️  No alert URL configured, printing payload:")
        print(json.dumps(payload, indent=2))


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Monitor attainment pace')
    parser.add_argument('--quarter', help='Fiscal quarter (e.g., "FY2027 Q1")')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print results without sending alert')
    args = parser.parse_args()

    # Load config
    config = load_config()

    if not config['enabled']:
        print("Attainment pace monitoring is disabled in config")
        return

    print("Checking attainment pace...")
    print()

    # Get Supabase client
    sb = get_supabase()

    # Determine quarter to check
    if args.quarter:
        fiscal_quarter = args.quarter
        current_week = config['check_at_week']  # Use configured checkpoint
    else:
        fiscal_quarter, current_week, q_start, q_end = get_current_quarter_info(sb)

    print(f"Quarter: {fiscal_quarter}")
    print(f"Current week: {current_week}")
    print()

    # Get attainment data
    attainment = get_quarter_attainment(sb, fiscal_quarter)

    if not attainment:
        print(f"⚠️  No data found for {fiscal_quarter}")
        return

    print(f"Closed-won ARR: ${attainment['closed_won_arr']:,.0f}")
    print(f"Deals closed: {attainment['deals_count']}")

    if attainment['plan_arr'] is None:
        print("⚠️  No plan configured - cannot check pace")
        print()
        print("To enable pace monitoring, add quarterly plans to config or database")
        return

    # Check for alert condition
    evidence = check_attainment_pace(attainment, current_week, config)

    if not evidence:
        print(f"✓ Pace is acceptable (at week {current_week})")
        return

    # Build alert message
    message = (
        f"⚠️ Attainment Pace Alert: {fiscal_quarter}\\n\\n"
        f"**Current Status (Week {evidence['current_week']}):**\\n"
        f"Attainment: {evidence['attainment_pct']:.1f}% of ${evidence['plan_arr']:,.0f} plan\\n"
        f"Expected at this point: {evidence['expected_pct_at_week']:.1f}%\\n"
        f"Minimum required: {evidence['min_required_pct']:.1f}%\\n"
        f"**Deficit: {evidence['pace_deficit']:.1f} percentage points**\\n\\n"
        f"Closed-won: ${evidence['closed_won_arr']:,.0f} ({evidence['deals_closed']} deals)\\n\\n"
        f"**Next steps:**\\n"
        f"1. Review pipeline coverage for remainder of quarter\\n"
        f"2. Identify deals that can close before quarter-end\\n"
        f"3. Accelerate qualification and closing activities"
    )

    # Send alert
    alert_url = os.getenv('ZAPIER_MONITORING_WEBHOOK_URL') if not args.dry_run else None

    if args.dry_run:
        print("\\n" + "="*70)
        print("DRY RUN - Alert would be sent with this payload:")
        print("="*70)

    send_monitoring_alert(
        monitor_name="attainment_pace",
        threshold_config={
            'min_pace_pct': config['min_pace_pct'],
            'check_at_week': config['check_at_week'],
            'min_arr_plan': config['min_arr_plan']
        },
        evidence=evidence,
        message=message,
        alert_url=alert_url
    )

    print()
    print(f"⚠️  PACE ALERT: {evidence['attainment_pct']:.1f}% vs {evidence['min_required_pct']:.1f}% required")


if __name__ == '__main__':
    main()
