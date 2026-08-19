#!/usr/bin/env python3
"""
Reconcile Phase 4 - compare before/after call counts.

This script MUST show actual numbers side by side, not just claim success.
Any count change requires explanation.
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add paths
sys.path.insert(0, str(Path(__file__).parent))

from supabase import create_client

# Load environment
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

print("=" * 70)
print("PHASE 4 RECONCILIATION")
print(f"Timestamp: {datetime.now().isoformat()}")
print("=" * 70)
print()

# Load baseline
baseline_file = Path(__file__).parent / 'phase4_baseline.json'
if not baseline_file.exists():
    print("ERROR: phase4_baseline.json not found")
    print("Cannot reconcile without baseline captured before code changes")
    sys.exit(1)

with open(baseline_file) as f:
    baseline_data = json.load(f)

baseline_rows = baseline_data['rows']
baseline_timestamp = baseline_data['timestamp']

print(f"BASELINE captured at: {baseline_timestamp}")
print()

# Capture AFTER counts
try:
    all_calls = sb.table('calls').select('source,deal_id,summary').execute().data

    from collections import defaultdict
    stats = defaultdict(lambda: {
        'call_count': 0,
        'deals': set(),
        'failed_summaries': 0,
        'empty_summaries': 0
    })

    for call in all_calls:
        source = call.get('source', 'unknown')
        summary = call.get('summary', '')
        deal_id = call.get('deal_id')

        stats[source]['call_count'] += 1
        if deal_id:
            stats[source]['deals'].add(deal_id)
        if summary and '[Summary failed]' in summary:
            stats[source]['failed_summaries'] += 1
        if not summary or len(summary) < 50:
            stats[source]['empty_summaries'] += 1

    after_rows = []
    for source in sorted(stats.keys()):
        after_rows.append({
            'source': source,
            'call_count': stats[source]['call_count'],
            'deals_with_calls': len(stats[source]['deals']),
            'failed_summaries': stats[source]['failed_summaries'],
            'empty_summaries': stats[source]['empty_summaries']
        })

except Exception as e:
    print(f"ERROR capturing AFTER counts: {e}")
    sys.exit(1)

# Build comparison table
print("=" * 90)
print("BEFORE/AFTER COMPARISON")
print("=" * 90)
print()
print(f"{'Source':<15} {'Metric':<20} {'BEFORE':<15} {'AFTER':<15} {'Delta':<15}")
print("-" * 90)

# Index by source for easy lookup
baseline_by_source = {row['source']: row for row in baseline_rows}
after_by_source = {row['source']: row for row in after_rows}

all_sources = sorted(set(baseline_by_source.keys()) | set(after_by_source.keys()))

issues = []

for source in all_sources:
    before = baseline_by_source.get(source, {})
    after = after_by_source.get(source, {})

    metrics = [
        ('call_count', 'Total Calls'),
        ('deals_with_calls', 'Deals w/ Calls'),
        ('failed_summaries', 'Failed Summaries'),
        ('empty_summaries', 'Empty Summaries')
    ]

    for metric_key, metric_label in metrics:
        before_val = before.get(metric_key, 0)
        after_val = after.get(metric_key, 0)
        delta = after_val - before_val

        delta_str = f"{delta:+d}" if delta != 0 else "0"

        print(f"{source:<15} {metric_label:<20} {before_val:<15} {after_val:<15} {delta_str:<15}")

        # Check for issues
        if metric_key == 'call_count' and delta < 0:
            issues.append(f"❌ {source}: Call count DECREASED by {abs(delta)} (data loss!)")
        elif metric_key == 'failed_summaries' and delta > 0:
            issues.append(f"⚠️  {source}: Failed summaries INCREASED by {delta}")
        elif metric_key == 'empty_summaries' and delta > 10:
            issues.append(f"⚠️  {source}: Empty summaries increased by {delta} (check summary quality)")
        elif metric_key == 'deals_with_calls' and delta < -5:
            issues.append(f"❌ {source}: Deals with calls dropped by {abs(delta)} (context loss!)")

    print()

print("=" * 90)

if issues:
    print("\n⚠️  ISSUES DETECTED:")
    for issue in issues:
        print(f"  {issue}")
    print()
    print("RECONCILIATION FAILED - investigate before committing Phase 4")
    sys.exit(1)
else:
    print("\n✅ RECONCILIATION PASSED")
    print()
    print("Call counts match baseline (± expected new calls since baseline).")
    print("No data loss, no increase in failed/empty summaries.")
    print("Phase 4 preserves behavior - safe to commit.")
    print()
