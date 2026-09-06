#!/usr/bin/env python3
"""
Trigger 7: Bulk Closed-Lost Event Monitor

Alerts when a high volume of deals transition to closed-lost within a short
time window. Catches departed-rep cleanups, mass disqualifications, workflow
errors, or other high-magnitude single-day events.

LESSON LEARNED: Ivan Gomez departure cleanup (281 deals in 59 minutes) went
undetected for 5 months. This monitor would have caught it in real-time.

Usage:
    python scripts/monitor_bulk_closed_lost.py
    python scripts/monitor_bulk_closed_lost.py --lookback-hours 24
"""
import os
import sys
import yaml
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# Add api to path for db access
sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))
from db import get_supabase


def load_config() -> Dict:
    """Load monitoring configuration."""
    config_path = Path(__file__).parent.parent / 'config' / 'monitoring.yaml'
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config['monitoring']['correctness']['bulk_closed_lost']


def get_recent_closed_lost_transitions(
    sb,
    lookback_hours: int = 24
) -> List[Dict]:
    """
    Query deals_snapshot for recent transitions to closed-lost.

    Returns list of deals that transitioned to closed-lost in the lookback window,
    with their snapshot timestamps, owner, and deal details.
    """
    # Calculate cutoff timestamp
    cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
    cutoff_str = cutoff.strftime('%Y-%m-%d')

    # Query deals_snapshot for recent snapshots
    # Look for deals where stage_id changed to a closed-lost variant
    result = sb.table('deals_snapshot') \
        .select('deal_id, snapshot_date, stage_id, pipeline_id, deal_value, owner_email') \
        .gte('snapshot_date', cutoff_str) \
        .execute()

    if not result.data:
        return []

    # Group by deal_id to find transitions
    from collections import defaultdict
    deal_snapshots = defaultdict(list)
    for snap in result.data:
        deal_snapshots[snap['deal_id']].append(snap)

    # Find deals that transitioned to closed-lost
    transitions = []
    closed_lost_stages = ['closedlost', '1297321624', '68509551']  # Include aliases

    for deal_id, snapshots in deal_snapshots.items():
        sorted_snaps = sorted(snapshots, key=lambda x: x['snapshot_date'])

        # Check if latest snapshot is closed-lost and previous wasn't
        if len(sorted_snaps) >= 2:
            latest = sorted_snaps[-1]
            previous = sorted_snaps[-2]

            if (latest['stage_id'] in closed_lost_stages and
                previous['stage_id'] not in closed_lost_stages):
                transitions.append({
                    'deal_id': deal_id,
                    'transition_date': latest['snapshot_date'],
                    'from_stage': previous['stage_id'],
                    'to_stage': latest['stage_id'],
                    'owner_id': latest.get('owner_email'),
                    'pipeline_id': latest.get('pipeline_id'),
                    'deal_value': latest.get('deal_value')
                })

    return transitions


def analyze_bulk_event(
    transitions: List[Dict],
    config: Dict
) -> Optional[Dict]:
    """
    Analyze transitions to determine if a bulk event occurred.

    Returns alert payload if thresholds exceeded, None otherwise.
    """
    if len(transitions) < config['min_deal_count']:
        return None

    # Sort by transition date
    sorted_trans = sorted(transitions, key=lambda x: x['transition_date'])

    # Check for clustering within time window
    window_minutes = config['time_window_minutes']
    max_count_in_window = 0
    window_start_idx = 0

    for i, trans in enumerate(sorted_trans):
        trans_time = datetime.fromisoformat(trans['transition_date'].replace('Z', ''))

        # Find all transitions within window from this one
        count = 1
        for j in range(i + 1, len(sorted_trans)):
            other_time = datetime.fromisoformat(sorted_trans[j]['transition_date'].replace('Z', ''))
            if (other_time - trans_time).total_seconds() / 60 <= window_minutes:
                count += 1
            else:
                break

        if count > max_count_in_window:
            max_count_in_window = count
            window_start_idx = i

    # Check if exceeds threshold
    if max_count_in_window < config['min_deal_count']:
        return None

    # Extract window
    window_trans = sorted_trans[window_start_idx:window_start_idx + max_count_in_window]

    # Analyze owner distribution
    owner_counts = Counter()
    for trans in window_trans:
        owner_id = trans.get('owner_id') or 'unassigned'
        owner_counts[owner_id] += 1

    # Check owner concentration
    if owner_counts:
        top_owner_pct = owner_counts.most_common(1)[0][1] / len(window_trans)
        if top_owner_pct < config.get('min_owner_concentration', 0.5):
            # Distributed across many owners, not a bulk action
            return None

    # Get sample deal details
    sample_size = min(config.get('sample_size', 20), len(window_trans))
    sample_deals = window_trans[:sample_size]

    # Fetch deal names from Supabase deals table
    deal_ids = [str(d['deal_id']) for d in sample_deals]
    deals_result = sb.table('deals').select('deal_id, company_name, num_notes').in_('deal_id', deal_ids).execute()

    deal_details = {str(d['deal_id']): d for d in deals_result.data}

    # Build evidence
    first_time = datetime.fromisoformat(window_trans[0]['transition_date'].replace('Z', ''))
    last_time = datetime.fromisoformat(window_trans[-1]['transition_date'].replace('Z', ''))

    evidence = {
        'deal_count': len(window_trans),
        'time_window': {
            'start': first_time.isoformat(),
            'end': last_time.isoformat(),
            'span_minutes': (last_time - first_time).total_seconds() / 60
        },
        'owner_distribution': dict(owner_counts.most_common(10)),
        'sample_deals': [
            {
                'deal_id': trans['deal_id'],
                'deal_name': deal_details.get(str(trans['deal_id']), {}).get('company_name', 'Unknown'),
                'owner_id': trans.get('owner_id', 'unassigned'),
                'transition_date': trans['transition_date']
            }
            for trans in sample_deals
        ],
        'activity_summary': {
            'with_notes': sum(1 for d in deal_details.values() if (d.get('num_notes') or 0) > 0),
            'sample_size': len(deal_details)
        }
    }

    return evidence


def send_monitoring_alert(
    monitor_name: str,
    threshold_config: Dict,
    evidence: Dict,
    message: str,
    alert_url: Optional[str] = None
) -> None:
    """
    Send monitoring alert via Zapier webhook.

    Uses the generic payload structure demonstrated in demo_monitoring_alert_payloads.py.
    """
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
    parser = argparse.ArgumentParser(description='Monitor for bulk closed-lost events')
    parser.add_argument('--lookback-hours', type=int, default=24,
                        help='Hours to look back for transitions (default: 24)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print results without sending alert')
    args = parser.parse_args()

    # Load config
    config = load_config()

    if not config['enabled']:
        print("Bulk closed-lost monitoring is disabled in config")
        return

    print(f"Checking for bulk closed-lost events (lookback: {args.lookback_hours}h)")
    print()

    # Get Supabase client
    sb = get_supabase()

    # Get recent transitions
    transitions = get_recent_closed_lost_transitions(sb, args.lookback_hours)
    print(f"Found {len(transitions)} closed-lost transitions in last {args.lookback_hours}h")

    if not transitions:
        print("✓ No bulk events detected")
        return

    # Analyze for bulk event
    evidence = analyze_bulk_event(transitions, config)

    if not evidence:
        print(f"✓ No bulk events detected (threshold: {config['min_deal_count']} deals)")
        return

    # Build alert message
    owner_dist = evidence['owner_distribution']
    top_owner = list(owner_dist.items())[0] if owner_dist else ('unknown', 0)

    message = (
        f"⚠️ Bulk Closed-Lost Event Detected\\n\\n"
        f"**{evidence['deal_count']} deals** closed-lost within "
        f"**{evidence['time_window']['span_minutes']:.0f} minutes**\\n\\n"
        f"Time window: {evidence['time_window']['start']} to {evidence['time_window']['end']}\\n"
        f"Top owner: {top_owner[0]} ({top_owner[1]} deals)\\n\\n"
        f"**Possible causes:**\\n"
        f"• Departed rep pipeline cleanup\\n"
        f"• Bulk disqualification workflow\\n"
        f"• Mass data quality correction\\n"
        f"• Accidental bulk edit\\n\\n"
        f"**Next steps:**\\n"
        f"1. Check HubSpot workflow logs for this time window\\n"
        f"2. Identify top owner and confirm intentional action\\n"
        f"3. Review sample deals for common patterns\\n"
        f"4. Document in tickets/ if intentional cleanup"
    )

    # Send alert
    alert_url = os.getenv('ZAPIER_MONITORING_WEBHOOK_URL') if not args.dry_run else None

    if args.dry_run:
        print("\\n" + "="*70)
        print("DRY RUN - Alert would be sent with this payload:")
        print("="*70)

    send_monitoring_alert(
        monitor_name="bulk_closed_lost",
        threshold_config={
            'min_deal_count': config['min_deal_count'],
            'time_window_minutes': config['time_window_minutes'],
            'min_owner_concentration': config.get('min_owner_concentration', 0.5)
        },
        evidence=evidence,
        message=message,
        alert_url=alert_url
    )

    print()
    print(f"⚠️  BULK EVENT DETECTED: {evidence['deal_count']} deals in {evidence['time_window']['span_minutes']:.0f} min")
    print(f"   Owner concentration: {top_owner[1]}/{evidence['deal_count']} from {top_owner[0]}")


if __name__ == '__main__':
    main()
