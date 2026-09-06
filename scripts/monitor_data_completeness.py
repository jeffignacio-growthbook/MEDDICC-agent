#!/usr/bin/env python3
"""
Trigger 2: Data Completeness Monitor

SPEC: "127 active deals with no ARR. Alert when the share crosses a threshold,
not on every occurrence."

Alerts when the percentage of active deals without ARR exceeds acceptable threshold.

Usage:
    python scripts/monitor_data_completeness.py
    python scripts/monitor_data_completeness.py --dry-run
"""
import os
import sys
import yaml
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

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
    return config['monitoring']['data_integrity']['data_completeness']


def check_data_completeness(sb, config: Dict) -> Optional[Dict]:
    """
    Check active deals for missing ARR values.

    Stage-aware: Only counts mid/late stage deals (order >= 3) in denominator.
    Early-stage deals legitimately may not have ARR estimates yet.

    Returns alert evidence if threshold exceeded, None otherwise.
    """
    # Load stage configuration to identify early stages
    from pathlib import Path
    import yaml

    config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
    with open(config_path) as f:
        client_config = yaml.safe_load(f)

    # Build stage order lookup
    stage_order = {}
    for pipeline in client_config.get('pipeline', {}).get('pipelines', []):
        for stage in pipeline.get('stages', []):
            stage_id = stage.get('id')
            stage_order[stage_id] = stage.get('order', 999)

    # Query active deals
    result = sb.table('deals') \
        .select('deal_id, company_name, deal_value, owner_email, stage') \
        .eq('deal_status', 'active') \
        .execute()

    if not result.data:
        return None

    all_active_deals = result.data

    # Filter to mid/late stage deals only (order >= 3)
    # Early stages (0-2) legitimately lack ARR estimates
    active_deals = [
        deal for deal in all_active_deals
        if stage_order.get(deal.get('stage'), 999) >= 3
    ]

    # Skip if below minimum deal count
    if len(active_deals) < config['min_deals']:
        return None

    # Count deals with no ARR
    no_arr_deals = [
        deal for deal in active_deals
        if deal.get('deal_value') is None or deal.get('deal_value') == 0
    ]

    null_share = len(no_arr_deals) / len(active_deals) if len(active_deals) > 0 else 0

    # Check threshold
    if null_share <= config['max_null_share']:
        return None

    # Sample deals for evidence
    sample_size = min(20, len(no_arr_deals))
    sample_deals = no_arr_deals[:sample_size]

    # Count by owner
    from collections import Counter
    owner_counts = Counter()
    for deal in no_arr_deals:
        owner = deal.get('owner_email') or 'unassigned'
        owner_counts[owner] += 1

    # Count early-stage exclusions for transparency
    early_stage_deals = [d for d in all_active_deals if stage_order.get(d.get('stage'), 999) < 3]
    early_stage_no_arr = [d for d in early_stage_deals if (d.get('deal_value') is None or d.get('deal_value') == 0)]

    # Build evidence
    evidence = {
        'total_active_deals': len(active_deals),  # Mid/late stage only
        'no_arr_count': len(no_arr_deals),
        'null_share_pct': null_share * 100,
        'threshold_pct': config['max_null_share'] * 100,
        'owner_distribution': dict(owner_counts.most_common(10)),
        'sample_deals': [
            {
                'deal_id': deal['deal_id'],
                'deal_name': deal.get('company_name', 'Unknown'),
                'owner': deal.get('owner_email', 'unassigned'),
                'stage': deal.get('stage', 'unknown')
            }
            for deal in sample_deals
        ],
        # Transparency: show what was excluded
        'excluded_early_stage_deals': len(early_stage_deals),
        'excluded_early_stage_no_arr': len(early_stage_no_arr),
        'note': 'Only mid/late stage deals (order >= 3) counted. Early stages excluded as ARR may not be known yet.'
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
    parser = argparse.ArgumentParser(description='Monitor data completeness')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print results without sending alert')
    args = parser.parse_args()

    # Load config
    config = load_config()

    if not config['enabled']:
        print("Data completeness monitoring is disabled in config")
        return

    print("Checking data completeness (active deals with ARR)...")
    print()

    # Get Supabase client
    sb = get_supabase()

    # Check for completeness issues
    evidence = check_data_completeness(sb, config)

    if not evidence:
        print(f"✓ Data completeness acceptable")
        return

    # Build alert message
    top_owner = list(evidence['owner_distribution'].items())[0] if evidence['owner_distribution'] else ('unknown', 0)

    message = (
        f"⚠️ Data Completeness Alert\\n\\n"
        f"**{evidence['no_arr_count']} active deals** ({evidence['null_share_pct']:.1f}%) have no ARR value\\n"
        f"Threshold: {evidence['threshold_pct']:.0f}%\\n"
        f"Total active deals: {evidence['total_active_deals']}\\n\\n"
        f"**Top owner:** {top_owner[0]} ({top_owner[1]} deals)\\n\\n"
        f"**Impact:**\\n"
        f"• Pipeline value reporting incomplete\\n"
        f"• Forecast accuracy degraded\\n"
        f"• Resource allocation unclear\\n\\n"
        f"**Next steps:**\\n"
        f"1. Review sample deals in evidence\\n"
        f"2. Contact owners with missing ARR\\n"
        f"3. Update HubSpot deal values\\n"
        f"4. Establish data quality process"
    )

    # Send alert
    alert_url = os.getenv('ZAPIER_MONITORING_WEBHOOK_URL') if not args.dry_run else None

    if args.dry_run:
        print("\\n" + "="*70)
        print("DRY RUN - Alert would be sent with this payload:")
        print("="*70)

    send_monitoring_alert(
        monitor_name="data_completeness",
        threshold_config={
            'max_null_share': config['max_null_share'],
            'min_deals': config['min_deals']
        },
        evidence=evidence,
        message=message,
        alert_url=alert_url
    )

    print()
    print(f"⚠️  COMPLETENESS ALERT: {evidence['no_arr_count']} deals ({evidence['null_share_pct']:.1f}%) missing ARR")


if __name__ == '__main__':
    main()
