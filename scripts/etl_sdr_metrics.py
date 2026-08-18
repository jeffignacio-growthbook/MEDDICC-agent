#!/usr/bin/env python3
"""
SDR Metrics ETL

Fetches daily SDR activity metrics from Apollo, Salesloft, and Aircall.
Writes to sdr_metrics and sdr_users tables in Supabase.

Usage:
  python etl_sdr_metrics.py --since 7d
  python etl_sdr_metrics.py --since 2026-07-01 --until 2026-07-31

Date handling:
- All dates are in reporting timezone (config/client.yaml: reporting.timezone)
- API calls are converted to UTC as required by each tool
- Metrics are stored with metric_date in reporting TZ for consistent aggregation
"""

import sys
import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from utils import load_client_config
from sdr_utils import today_in_reporting_tz, rate_or_gap
from adapters import ApolloDialerAdapter, SalesloftSequencerAdapter, AircallDialerAdapter
from supabase_client import SupabaseWriter


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Fetch SDR metrics from Apollo, Salesloft, and Aircall'
    )
    parser.add_argument(
        '--since',
        type=str,
        default='2d',
        help='Start date (YYYY-MM-DD or "Nd" for N days ago). Default: 2d'
    )
    parser.add_argument(
        '--until',
        type=str,
        default=None,
        help='End date (YYYY-MM-DD, defaults to today in reporting TZ)'
    )
    parser.add_argument(
        '--tool',
        type=str,
        choices=['apollo', 'salesloft', 'aircall', 'all'],
        default='all',
        help='Specific tool to run (default: all enabled tools)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print metrics without writing to database'
    )

    return parser.parse_args()


def parse_date_arg(date_str: str, config: dict) -> date:
    """
    Parse date argument.

    Args:
        date_str: "YYYY-MM-DD" or "Nd" (N days ago)
        config: Client config for reporting timezone

    Returns:
        date object in reporting timezone
    """
    if date_str.endswith('d'):
        # Parse "7d" as "7 days ago"
        days = int(date_str[:-1])
        return today_in_reporting_tz(config) - timedelta(days=days)
    else:
        # Parse as YYYY-MM-DD
        return date.fromisoformat(date_str)


def upsert_user(
    supabase,
    tool: str,
    tool_user_id: str,
    user_name: str
) -> None:
    """
    Upsert user to sdr_users table.

    Args:
        supabase: Supabase client
        tool: Tool name (apollo, salesloft, aircall)
        tool_user_id: User ID from tool
        user_name: User display name
    """
    user_data = {
        'tool': tool,
        'tool_user_id': tool_user_id,
        'user_name': user_name,
        'last_seen': 'now()'
    }

    # Use upsert to update last_seen on existing users
    supabase.table('sdr_users').upsert(
        user_data,
        on_conflict='tool,tool_user_id'
    ).execute()


def upsert_metrics(
    supabase,
    tool: str,
    metrics: List[Dict],
    metric_date: date
) -> None:
    """
    Upsert daily metrics to sdr_metrics table.

    Args:
        supabase: Supabase client
        tool: Tool name (apollo, salesloft, aircall)
        metrics: List of metric dicts from adapter
        metric_date: Date for these metrics (reporting TZ)
    """
    for metric in metrics:
        # Extract rate objects and determine data gap
        connect_rate_obj = metric.get('connect_rate', {})
        open_rate_obj = metric.get('open_rate', {})
        reply_rate_obj = metric.get('reply_rate', {})
        answer_rate_obj = metric.get('answer_rate', {})

        # A data gap exists if any key rate is null
        data_gap = (
            connect_rate_obj.get('data_gap', False) or
            open_rate_obj.get('data_gap', False) or
            reply_rate_obj.get('data_gap', False) or
            answer_rate_obj.get('data_gap', False)
        )

        metric_data = {
            'tool': tool,
            'tool_user_id': metric['user_id'],
            'user_name': metric['user_name'],
            'metric_date': metric_date.isoformat(),
            'calls_made': metric.get('calls_made', 0),
            'connected_calls': metric.get('connected_calls', 0),
            'connect_rate': connect_rate_obj.get('value'),
            'voicemails': metric.get('voicemails', 0),
            'no_answers': metric.get('no_answers', 0),
            'missed_calls': metric.get('missed_calls', 0),
            'bad_numbers': metric.get('bad_numbers', 0),
            'avg_duration_seconds': metric.get('avg_duration_seconds'),
            'emails_sent': metric.get('emails_sent', 0),
            'emails_opened': metric.get('emails_opened', 0),
            'emails_replied': metric.get('emails_replied', 0),
            'open_rate': open_rate_obj.get('value'),
            'reply_rate': reply_rate_obj.get('value'),
            'data_gap': data_gap,
            'etl_run_at': 'now()'
        }

        # Use answer_rate for Aircall (their terminology)
        if 'answered_calls' in metric:
            metric_data['connected_calls'] = metric['answered_calls']
            metric_data['connect_rate'] = answer_rate_obj.get('value')

        # Upsert (update if exists for this tool/user/date)
        supabase.table('sdr_metrics').upsert(
            metric_data,
            on_conflict='tool,tool_user_id,metric_date'
        ).execute()

        # Update user record
        upsert_user(supabase, tool, metric['user_id'], metric['user_name'])


def get_checkpoint(supabase, tool: str) -> Optional[date]:
    """
    Get last successful ETL date for a tool.

    Args:
        supabase: Supabase client
        tool: Tool name (apollo, salesloft, aircall)

    Returns:
        Last success date or None if never run
    """
    try:
        result = supabase.table('etl_checkpoints').select('last_success_date').eq('tool', tool).execute()
        if result.data and len(result.data) > 0:
            last_date_str = result.data[0]['last_success_date']
            if last_date_str:
                return date.fromisoformat(last_date_str)
    except Exception:
        pass
    return None


def save_checkpoint(supabase, tool: str, success_date: date) -> None:
    """
    Save successful ETL checkpoint for a tool.

    Args:
        supabase: Supabase client
        tool: Tool name (apollo, salesloft, aircall)
        success_date: Date successfully processed
    """
    checkpoint_data = {
        'tool': tool,
        'last_run_at': 'now()',
        'last_success_date': success_date.isoformat()
    }

    supabase.table('etl_checkpoints').upsert(
        checkpoint_data,
        on_conflict='tool'
    ).execute()


def fetch_apollo(since: date, until: date, config: dict, dry_run: bool) -> int:
    """Fetch Apollo metrics with rate limit handling."""
    print(f"\n{'='*80}")
    print("APOLLO DIALER METRICS")
    print(f"{'='*80}\n")

    adapter = ApolloDialerAdapter()

    try:
        metrics = adapter.get_metrics(since, until, user_ids=None, config=config)
    except Exception as e:
        # Check if rate limit error
        if '429' in str(e) or 'Too Many Requests' in str(e):
            print(f"\n⚠️  Apollo rate limit hit: {e}")
            print(f"  Apollo's rate limit resets hourly.")
            print(f"  The daily GitHub Actions job will retry tomorrow.")
            print(f"  For manual runs, wait 1 hour and try again with --since 1d")

            if not dry_run:
                # Save checkpoint for what we attempted
                # Next run will pick up from last successful date
                supabase = SupabaseWriter().client
                last_checkpoint = get_checkpoint(supabase, 'apollo')
                if last_checkpoint:
                    print(f"  Last successful run: {last_checkpoint}")
                    print(f"  Next run will continue from there")

            return 0  # Graceful exit - no users processed
        else:
            # Not a rate limit error, re-raise
            raise

    print(f"  Fetched metrics for {len(metrics)} users")

    if dry_run:
        for m in metrics[:3]:  # Show first 3
            print(f"\n  User: {m['user_name']}")
            print(f"    Calls: {m['calls_made']}, Voicemails: {m['voicemails']}")
            connect_rate = m['connect_rate']
            if connect_rate.get('data_gap'):
                print(f"    Connect rate: {connect_rate['reason']}")
            else:
                print(f"    Connect rate: {connect_rate['value']}")
            print(f"    Dispositions: {m['dispositions']}")
            if m.get('logging_gap'):
                print(f"    ⚠️  Logging gap: {m['logging_gap']} (reps not logging outcomes)")
        return len(metrics)

    supabase = SupabaseWriter().client

    # Apollo returns cumulative metrics for the date range
    # Store as metrics for the end date
    upsert_metrics(supabase, 'apollo', metrics, until)

    # Save successful checkpoint
    save_checkpoint(supabase, 'apollo', until)

    print(f"  ✓ Wrote metrics to sdr_metrics table")
    print(f"  ✓ Checkpoint saved: {until}")
    return len(metrics)


def fetch_salesloft(since: date, until: date, config: dict, dry_run: bool) -> int:
    """Fetch Salesloft metrics."""
    print(f"\n{'='*80}")
    print("SALESLOFT SEQUENCER METRICS")
    print(f"{'='*80}\n")

    adapter = SalesloftSequencerAdapter()
    metrics = adapter.get_metrics(since, until, user_ids=None, config=config)

    print(f"  Fetched metrics for {len(metrics)} users")

    if dry_run:
        for m in metrics[:3]:  # Show first 3
            print(f"\n  User: {m['user_name']}")
            print(f"    Emails: {m['emails_sent']}, Opens: {m['emails_opened']}, Replies: {m['emails_replied']}")
            print(f"    Calls: {m['calls_made']}, Connects: {m['connected_calls']}")
        return len(metrics)

    supabase = SupabaseWriter().client

    # Salesloft returns cumulative metrics for the date range
    # Store as metrics for the end date
    upsert_metrics(supabase, 'salesloft', metrics, until)

    print(f"  ✓ Wrote metrics to sdr_metrics table")
    return len(metrics)


def fetch_aircall(since: date, until: date, config: dict, dry_run: bool) -> int:
    """Fetch Aircall metrics."""
    print(f"\n{'='*80}")
    print("AIRCALL DIALER METRICS")
    print(f"{'='*80}\n")

    adapter = AircallDialerAdapter()
    metrics = adapter.get_metrics(since, until, user_ids=None, config=config)

    print(f"  Fetched metrics for {len(metrics)} users")

    if dry_run:
        for m in metrics[:3]:  # Show first 3
            print(f"\n  User: {m['user_name']}")
            print(f"    Calls: {m['calls_made']}, Answered: {m['answered_calls']}")
            print(f"    Answer rate: {m['answer_rate']}")
        return len(metrics)

    supabase = SupabaseWriter().client

    # Aircall returns cumulative metrics for the date range
    # Store as metrics for the end date
    upsert_metrics(supabase, 'aircall', metrics, until)

    print(f"  ✓ Wrote metrics to sdr_metrics table")
    return len(metrics)


def main():
    """Main ETL orchestration with incremental checkpoint support."""
    args = parse_args()
    config = load_client_config()

    # Parse date range in reporting timezone
    until = (
        parse_date_arg(args.until, config)
        if args.until
        else today_in_reporting_tz(config)
    )

    # Determine since date: use checkpoint if available, otherwise use --since arg
    since = parse_date_arg(args.since, config)

    # Check for checkpoint to enable incremental ETL
    if not args.dry_run:
        try:
            supabase = SupabaseWriter().client
            # Check each enabled tool's checkpoint
            tools_config = config.get('sdr_tools', {})
            if tools_config.get('apollo', {}).get('enabled', False):
                apollo_checkpoint = get_checkpoint(supabase, 'apollo')
                if apollo_checkpoint:
                    # Use checkpoint + 1 day to avoid re-processing same day
                    checkpoint_since = apollo_checkpoint + timedelta(days=1)
                    if checkpoint_since > since:
                        print(f"  Using Apollo checkpoint: {apollo_checkpoint}")
                        print(f"  Fetching from {checkpoint_since} instead of {since}")
                        since = checkpoint_since
        except Exception as e:
            # If checkpoint check fails, use the provided --since arg
            print(f"  ⚠️  Checkpoint check failed: {e}")
            print(f"  Using --since arg: {since}")

    print(f"\nSDR Metrics ETL")
    print(f"Date range: {since} to {until} (reporting TZ)")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")

    total_users = 0

    # Determine which tools to run
    tools_config = config.get('sdr_tools', {})
    enabled_tools = []

    if args.tool == 'all':
        # Run all tools that are configured
        if tools_config.get('apollo', {}).get('enabled', False):
            enabled_tools.append('apollo')
        if tools_config.get('salesloft', {}).get('enabled', False):
            enabled_tools.append('salesloft')
        if tools_config.get('aircall', {}).get('enabled', False):
            enabled_tools.append('aircall')
    else:
        # Run specific tool only
        enabled_tools = [args.tool]

    if not enabled_tools:
        print("\n⚠️  No SDR tools enabled in config/client.yaml")
        print("Add sdr_tools section with tool.enabled = true")
        return

    # Fetch from each enabled tool
    try:
        if 'apollo' in enabled_tools:
            total_users += fetch_apollo(since, until, config, args.dry_run)

        if 'salesloft' in enabled_tools:
            total_users += fetch_salesloft(since, until, config, args.dry_run)

        if 'aircall' in enabled_tools:
            total_users += fetch_aircall(since, until, config, args.dry_run)

    except Exception as e:
        print(f"\n❌ ETL failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print(f"\n{'='*80}")
    print(f"ETL {'DRY RUN ' if args.dry_run else ''}COMPLETE")
    print(f"{'='*80}")
    print(f"\nTotal users processed: {total_users}")
    print(f"Date range: {since} to {until}")

    if not args.dry_run:
        print(f"\n✓ Metrics written to Supabase")
        print(f"✓ Users updated in sdr_users table")


if __name__ == '__main__':
    main()
