#!/usr/bin/env python3
"""
Wave 1: Read the Logs

Three tables have evidence — learning_log, unanswered_queries, entity_scope_patterns.
This produces a ranked list of what to fix based on actual failures.
"""

import os
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from supabase import create_client


def main():
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("="*80)
    print("WAVE 1: READ THE LOGS — Evidence Analysis")
    print("="*80)
    print()

    # ==========================================================================
    # 1. LEARNING_LOG — Imperfect answers by issue type
    # ==========================================================================
    print("1. LEARNING_LOG — Imperfect Answers")
    print("-"*80)

    try:
        learning = sb.table('learning_log').select('*').execute()

        if not learning.data:
            print("⚠️  learning_log is empty")
        else:
            issue_counts = defaultdict(lambda: {
                'total': 0,
                'retry_succeeded': 0,
                'handlers': defaultdict(int)
            })

            for row in learning.data:
                issue = row.get('issue_type') or 'UNKNOWN'
                handler = row.get('handler_used') or 'UNKNOWN'
                retry = row.get('retry_succeeded', False)

                issue_counts[issue]['total'] += 1
                issue_counts[issue]['handlers'][handler] += 1
                if retry:
                    issue_counts[issue]['retry_succeeded'] += 1

            print(f"{'Issue Type':<35} {'Count':>8} {'Retries OK':>12} {'Top Handler':<20}")
            print("-"*80)

            for issue in sorted(issue_counts.keys(), key=lambda i: issue_counts[i]['total'], reverse=True):
                total = issue_counts[issue]['total']
                retries = issue_counts[issue]['retry_succeeded']
                handlers = issue_counts[issue]['handlers']
                top_handler = max(handlers.items(), key=lambda x: x[1])[0] if handlers else 'N/A'

                print(f"{issue:<35} {total:>8} {retries:>12} {top_handler:<20}")

            print()
            print(f"Total imperfect answers logged: {len(learning.data)}")

    except Exception as e:
        print(f"⚠️  Could not read learning_log: {e}")

    print()
    print()

    # ==========================================================================
    # 2. UNANSWERED_QUERIES — Questions that fell through
    # ==========================================================================
    print("2. UNANSWERED_QUERIES — Questions That Failed")
    print("-"*80)

    try:
        unanswered = sb.table('unanswered_queries').select('*').execute()

        if not unanswered.data:
            print("⚠️  unanswered_queries is empty")
        else:
            # Group by reason
            reason_groups = defaultdict(list)
            for row in unanswered.data:
                reason = row.get('reason') or 'UNKNOWN'
                question = row.get('question') or ''
                reason_groups[reason].append(question)

            print(f"{'Reason':<50} {'Count':>8}")
            print("-"*80)

            for reason in sorted(reason_groups.keys(), key=lambda r: len(reason_groups[r]), reverse=True):
                count = len(reason_groups[reason])
                print(f"{reason:<50} {count:>8}")

            print()
            print("Top 10 most-asked unanswered questions:")
            print("-"*80)

            question_counts = defaultdict(int)
            for row in unanswered.data:
                q = row.get('question') or ''
                question_counts[q] += 1

            for q, count in sorted(question_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                print(f"  [{count}x] {q[:70]}")

    except Exception as e:
        print(f"⚠️  Could not read unanswered_queries: {e}")

    print()
    print()

    # ==========================================================================
    # 3. ENTITY_SCOPE_PATTERNS — Follow-up resolution
    # ==========================================================================
    print("3. ENTITY_SCOPE_PATTERNS — Follow-up Resolution")
    print("-"*80)

    try:
        patterns = sb.table('entity_scope_patterns').select('*').execute()

        if not patterns.data:
            print("⚠️  entity_scope_patterns is empty")
        else:
            handler_counts = defaultdict(int)
            for row in patterns.data:
                handler = row.get('handler_name') or 'UNKNOWN'
                handler_counts[handler] += 1

            print(f"{'Resolved Handler':<35} {'Count':>8}")
            print("-"*80)

            for handler in sorted(handler_counts.keys(), key=lambda h: handler_counts[h], reverse=True):
                print(f"{handler:<35} {handler_counts[handler]:>8}")

            print()
            print("Sample question patterns:")
            print("-"*80)

            for row in patterns.data[:10]:
                q = (row.get('question') or '')[:55]
                handler = row.get('handler_name') or 'UNKNOWN'
                count = row.get('entity_count', 0)
                print(f"  \"{q}\" → {handler} ({count} entities)")

    except Exception as e:
        print(f"⚠️  Could not read entity_scope_patterns: {e}")

    print()
    print()
    print("="*80)
    print("Next: Triage each issue into semantics / routing / code destinations")
    print("="*80)


if __name__ == '__main__':
    main()
