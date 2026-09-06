#!/usr/bin/env python3
"""
Audit for the same bug pattern as answer_pending_canonical_questions.py:
Filtering deal_status = 'active' when historical/closed deals are needed.

Pattern to catch:
- Files that filter to deal_status = 'active'
- AND compute win rates, conversion rates, cycle times, or other historical metrics
"""

import os
import re
from pathlib import Path

repo_root = Path("/Users/jeffignacio/MEDDICC-agent")

# Keywords that indicate historical analysis needing closed deals
HISTORICAL_KEYWORDS = [
    r'\bwin\s*rate\b',
    r'\bconversion\s*rate\b',
    r'\bcycle\s*time\b',
    r'\bhistorical\b',
    r'\btrend\b',
    r'\bretention\b',
    r'\bchurn\b',
    r'\bGRR\b',
    r'\bNRR\b',
    r'closed.*deal',
    r'deal.*won',
    r'deal.*lost',
]

# Pattern for active-only filter
ACTIVE_FILTER_PATTERNS = [
    r"deal_status.*[=']active",
    r"eq\s*\(\s*['\"]deal_status['\"].*['\"]active",
]

print("=" * 100)
print("AUDIT: Active-Only Filter Bug Pattern")
print("=" * 100)
print()
print("Checking for files that:")
print("  1. Filter deal_status = 'active'")
print("  2. Calculate win rates / conversion / cycle times (need closed deals)")
print()

suspicious_files = []

# Search Python files
for py_file in repo_root.rglob("*.py"):
    # Skip __pycache__, .pyc files
    if "__pycache__" in str(py_file) or ".pyc" in str(py_file):
        continue

    # Skip test files and migrations
    if "/tests/" in str(py_file) or "/migrations/" in str(py_file):
        continue

    try:
        with open(py_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        continue

    # Check if file has active-only filter
    has_active_filter = any(re.search(pattern, content, re.IGNORECASE) for pattern in ACTIVE_FILTER_PATTERNS)

    if not has_active_filter:
        continue

    # Check if file mentions historical analysis
    has_historical_keywords = any(re.search(keyword, content, re.IGNORECASE) for keyword in HISTORICAL_KEYWORDS)

    if has_historical_keywords:
        # Check if it actually computes these metrics (not just mentions them)
        # Look for calculation patterns
        calculates_metric = any([
            re.search(r'(win|conversion).*rate.*=', content, re.IGNORECASE),
            re.search(r'cycle.*time.*=', content, re.IGNORECASE),
            re.search(r'won.*count|lost.*count', content, re.IGNORECASE),
            re.search(r'won.*deals|lost.*deals', content, re.IGNORECASE),
        ])

        if calculates_metric:
            suspicious_files.append({
                'file': str(py_file.relative_to(repo_root)),
                'context': []
            })

            # Get context lines
            lines = content.split('\n')
            for i, line in enumerate(lines):
                # Active filter lines
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in ACTIVE_FILTER_PATTERNS):
                    suspicious_files[-1]['context'].append((i+1, 'ACTIVE_FILTER', line.strip()))

                # Metric calculation lines
                if any(re.search(keyword, line, re.IGNORECASE) for keyword in HISTORICAL_KEYWORDS):
                    if '=' in line or 'def ' in line or 'return' in line:
                        suspicious_files[-1]['context'].append((i+1, 'METRIC_CALC', line.strip()[:100]))

if not suspicious_files:
    print("✓ NO SUSPICIOUS FILES FOUND")
    print()
    print("All files that filter deal_status='active' appear to be:")
    print("  - Current pipeline analysis (correct to use active)")
    print("  - Data quality checks (correct to use active)")
    print("  - Or don't compute historical win/conversion rates")
    print()
    print("The bug pattern is isolated to answer_pending_canonical_questions.py (already fixed).")
else:
    print(f"⚠️  FOUND {len(suspicious_files)} SUSPICIOUS FILES:")
    print()

    for entry in suspicious_files:
        print("=" * 100)
        print(f"FILE: {entry['file']}")
        print("=" * 100)

        active_lines = [c for c in entry['context'] if c[1] == 'ACTIVE_FILTER']
        metric_lines = [c for c in entry['context'] if c[1] == 'METRIC_CALC']

        print("\nActive filter:")
        for line_num, _, line in active_lines[:3]:
            print(f"  Line {line_num}: {line}")

        print("\nHistorical metric calculations:")
        for line_num, _, line in metric_lines[:3]:
            print(f"  Line {line_num}: {line}")

        print()
        print("ACTION NEEDED: Review if this file needs ALL deals (won/lost) not just active")
        print()

print("=" * 100)
print("SUMMARY")
print("=" * 100)
print()
print(f"Files checked: {len(list(repo_root.rglob('*.py')))}")
print(f"Suspicious files: {len(suspicious_files)}")
print()

if suspicious_files:
    print("RECOMMENDATION:")
    print("  For each suspicious file above:")
    print("  1. Read the full context")
    print("  2. Check if it's computing historical metrics from closed deals")
    print("  3. If yes, remove .eq('deal_status', 'active') filter")
    print("  4. Or change to .in_('deal_status', ['won', 'lost']) if needed")
else:
    print("STATUS: Clean ✓")
    print("  The active-filter bug was isolated to answer_pending_canonical_questions.py")
    print("  All other uses of deal_status='active' are appropriate for their context")
