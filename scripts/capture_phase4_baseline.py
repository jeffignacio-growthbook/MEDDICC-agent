#!/usr/bin/env python3
"""
Capture Phase 4 baseline - call counts before ETL rewrite.

This MUST run before any code changes to etl_calls.py.
The baseline is the proof that Phase 4 preserves behavior.
"""
import os
import sys
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
    print("Cannot capture baseline without database access")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

print("=" * 70)
print("PHASE 4 BASELINE CAPTURE")
print(f"Timestamp: {datetime.utcnow().isoformat()}")
print("=" * 70)
print()

# The reconciliation query from the spec
query = """
SELECT
    source,
    COUNT(*) AS call_count,
    COUNT(DISTINCT deal_id) AS deals_with_calls,
    COUNT(*) FILTER (WHERE summary LIKE '%Summary failed%') AS failed_summaries,
    COUNT(*) FILTER (WHERE summary IS NULL OR length(summary) < 50) AS empty_summaries
FROM calls
GROUP BY source
ORDER BY source;
"""

try:
    # Get all calls and aggregate in Python
    # PostgREST doesn't support FILTER clauses, so we do it client-side
    all_calls = sb.table('calls').select('source,deal_id,summary').execute().data

    # Aggregate by source
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

    # Convert to rows format
    rows = []
    for source in sorted(stats.keys()):
        rows.append({
            'source': source,
            'call_count': stats[source]['call_count'],
            'deals_with_calls': len(stats[source]['deals']),
            'failed_summaries': stats[source]['failed_summaries'],
            'empty_summaries': stats[source]['empty_summaries']
        })

    # Print baseline table
    print("BASELINE CALL COUNTS (before ETL rewrite):")
    print()
    print(f"{'Source':<15} {'Calls':<10} {'Deals':<10} {'Failed':<10} {'Empty':<10}")
    print("-" * 70)

    for row in rows:
        source = row.get('source', 'unknown')
        call_count = row.get('call_count', 0)
        deals = row.get('deals_with_calls', 0)
        failed = row.get('failed_summaries', 0)
        empty = row.get('empty_summaries', 0)

        print(f"{source:<15} {call_count:<10} {deals:<10} {failed:<10} {empty:<10}")

    print()
    print("=" * 70)
    print("BASELINE CAPTURED")
    print("=" * 70)
    print()
    print("This baseline will be compared against post-rewrite counts to verify")
    print("Phase 4 preserves behavior (same counts ± new calls since baseline).")
    print()

    # Save baseline to file for comparison
    import json
    baseline_file = Path(__file__).parent / 'phase4_baseline.json'
    with open(baseline_file, 'w') as f:
        json.dump({
            'timestamp': datetime.utcnow().isoformat(),
            'rows': rows
        }, f, indent=2)

    print(f"Baseline saved to: {baseline_file}")

except Exception as e:
    print(f"ERROR capturing baseline: {e}")
    print()
    print("Cannot proceed to Phase 4 without baseline.")
    print("The reconciliation table is mandatory - not optional.")
    sys.exit(1)
