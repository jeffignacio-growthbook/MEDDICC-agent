#!/usr/bin/env python3
"""
Analyze logged entity-scope patterns to identify candidates for new handlers.

Task G.8.5: When patterns repeat frequently, they become candidates for
dedicated handler generation.

Usage:
    python scripts/analyze_entity_patterns.py --min-frequency 5
    python scripts/analyze_entity_patterns.py --handler query_objections
    python scripts/analyze_entity_patterns.py --recent 7  # last 7 days
"""

import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from api.db import get_supabase

def analyze_patterns(min_frequency=3, handler_filter=None, recent_days=None):
    """Analyze entity-scope patterns to find recurring questions."""
    sb = get_supabase()

    # Build query
    query = sb.table("entity_scope_patterns").select("*")

    if handler_filter:
        query = query.eq("handler_name", handler_filter)

    if recent_days:
        cutoff = datetime.now() - timedelta(days=recent_days)
        query = query.gte("asked_at", cutoff.isoformat())

    # Only successful patterns (quality >= 0.7)
    query = query.gte("quality_score", 0.7)

    result = query.execute()
    patterns = result.data

    if not patterns:
        print("No patterns found matching criteria")
        return

    print(f"\n{'='*80}")
    print(f"ENTITY-SCOPE PATTERN ANALYSIS")
    print(f"{'='*80}\n")
    print(f"Total patterns: {len(patterns)}")

    # Group by handler
    by_handler = {}
    for p in patterns:
        handler = p["handler_name"]
        by_handler.setdefault(handler, []).append(p)

    print(f"\nPatterns by handler:")
    for handler in sorted(by_handler.keys()):
        count = len(by_handler[handler])
        avg_quality = sum(p["quality_score"] for p in by_handler[handler]) / count
        print(f"  {handler:30s} {count:4d} patterns  (avg quality: {avg_quality:.2f})")

    # Find frequent question patterns (normalize by lowercasing and stripping)
    question_freq = Counter()
    for p in patterns:
        # Normalize question for comparison
        normalized = p["question"].lower().strip()
        question_freq[normalized] += 1

    print(f"\n{'='*80}")
    print(f"FREQUENT PATTERNS (frequency >= {min_frequency})")
    print(f"{'='*80}\n")

    frequent = [(q, count) for q, count in question_freq.items() if count >= min_frequency]
    if not frequent:
        print(f"No patterns with frequency >= {min_frequency}")
        print(f"Try lowering --min-frequency threshold\n")
        return

    for question, count in sorted(frequent, key=lambda x: x[1], reverse=True):
        # Find which handler(s) this routes to
        handlers_used = set()
        for p in patterns:
            if p["question"].lower().strip() == question:
                handlers_used.add(p["handler_name"])

        handlers_str = ", ".join(sorted(handlers_used))
        print(f"[{count:3d}x] {question[:60]}")
        print(f"       → {handlers_str}\n")

    # Suggest new handlers for high-frequency patterns
    print(f"{'='*80}")
    print(f"HANDLER GENERATION CANDIDATES")
    print(f"{'='*80}\n")

    candidates = [q for q, count in frequent if count >= min_frequency * 2]
    if candidates:
        print(f"These {len(candidates)} patterns appear >= {min_frequency * 2} times")
        print(f"and may benefit from dedicated handlers:\n")
        for question in candidates[:5]:  # Top 5
            count = question_freq[question]
            print(f"  [{count:3d}x] {question[:70]}")
        print()
    else:
        print(f"No high-frequency patterns found (threshold: {min_frequency * 2})")
        print(f"Current patterns need more usage data.\n")

def main():
    parser = argparse.ArgumentParser(
        description="Analyze entity-scope routing patterns"
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=3,
        help="Minimum frequency to flag as recurring pattern (default: 3)"
    )
    parser.add_argument(
        "--handler",
        help="Filter to specific handler name"
    )
    parser.add_argument(
        "--recent",
        type=int,
        help="Only analyze patterns from last N days"
    )
    args = parser.parse_args()

    try:
        analyze_patterns(
            min_frequency=args.min_frequency,
            handler_filter=args.handler,
            recent_days=args.recent
        )
    except Exception as e:
        print(f"ERROR: {e}")
        print("\nMake sure migration 027 has been applied:")
        print("  psql $SUPABASE_DB_URL -f scripts/migrations/027_entity_scope_patterns.sql")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
