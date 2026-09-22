#!/usr/bin/env python3
"""
TEST 0z - Structural gate: no overly-broad substring/containment matching
in routing or filter logic without a governed whitelist.

MOTIVATING INCIDENTS (2026-09-21/22):

1. dimension_resolver.py (commit 47e0963): _country_candidates() had an
   always-return fallback that matched ANY term (including "EMEA" and
   "enterprise") as a potential country filter via exact-match fallback.
   Fixed by removing the fallback and only matching governed values from
   _COUNTRY_ALIASES.

2. router.py (commit c794f31): Bug #3 fix initially used bare substring
   matching `[qcol for qcol in cols if term in qcol or qcol in term]`
   to resolve classifier's "no country field" errors. Caused 6/6 false
   positives when classifier used common words (date → close_date/
   create_date, count → company_country, id → deal_id/pipeline_id, etc.).
   Fixed by replacing with governed _COLUMN_ALIASES dict (country →
   company_country), exact match only, no substring fallback.

RECURRING PATTERN:
Broadening a matcher to fix a false negative (Q6 "show EMEA by country"
returning unanswerable) without checking what it now incorrectly accepts
(short/common words accidentally matching unrelated columns).

THIS CHECK:
Flags the SPECIFIC dangerous pattern: list comprehensions doing bidirectional
substring matching like `[x for x in cols if term in x or x in term]` which
was the exact form used in both incidents. This is narrow and precise - it
will NOT flag legitimate membership checks, semantic matching, or other "in"
uses. Only flags the specific anti-pattern that caused tonight's bugs.

ALLOWLIST PATTERN (what's safe):
- dimension_resolver.py's _COUNTRY_ALIASES / _REGION_ALIASES pattern
- router.py's _COLUMN_ALIASES pattern (added in Bug #3 fix)
- Exact match first, then governed alias lookup, NO substring fallback
"""

import re
from pathlib import Path

# Files where routing/filtering logic lives
ROUTING_FILES = [
    "api/router.py",
    "api/dimension_resolver.py",
    "api/handlers.py",
]

# The EXACT dangerous pattern from tonight's incidents (slightly generalized)
# Matches: [X for X in Y if TERM in X or X in TERM]
# This is bidirectional substring matching in a list comprehension
DANGEROUS_PATTERN = re.compile(
    r'\[.*?\s+for\s+(\w+)\s+in\s+.*?\s+if\s+.*?\s+in\s+\1\s+or\s+\1\s+in\s+.*?\]',
    re.IGNORECASE
)

# Known instances (these exist and are reviewed)
KNOWN_INSTANCES = {
    # None currently - the bug was fixed! If a new one appears, it should fail CI.
}


def _scan_for_dangerous_substring_pattern():
    """
    Scan for the SPECIFIC dangerous pattern: bidirectional substring
    matching in list comprehensions, like:
        [qcol for qcol in queryable_cols if col_term in qcol or qcol in col_term]

    This is the exact pattern from tonight's two incidents.
    """
    found = {}

    for rel_path in ROUTING_FILES:
        path = Path(rel_path)
        if not path.exists():
            continue

        text = path.read_text()
        lines = text.split("\n")

        for i, line in enumerate(lines, 1):
            # Skip comments
            if line.strip().startswith("#"):
                continue

            # Look for the dangerous pattern
            if DANGEROUS_PATTERN.search(line):
                key = (path.name, i, line.strip()[:100])
                found[key] = line.strip()

    return found


def test_no_new_bare_substring_matching():
    """
    Structural gate: flags new instances of the SPECIFIC anti-pattern
    from tonight's incidents (bidirectional substring matching in list
    comprehensions).

    This is NARROW and PRECISE - it only catches the exact dangerous form,
    not every "in" check in the codebase.
    """
    found = _scan_for_dangerous_substring_pattern()

    unreviewed = []
    for key in found.keys():
        if key not in KNOWN_INSTANCES:
            filename, line_num, snippet = key
            unreviewed.append((filename, line_num, snippet))

    if unreviewed:
        msg = (
            f"🚨 Found {len(unreviewed)} instance(s) of the DANGEROUS "
            f"bidirectional substring matching pattern:\n\n"
        )
        for filename, line_num, snippet in unreviewed:
            msg += f"  {filename}:{line_num}\n  {snippet}\n\n"

        msg += (
            "This is the EXACT pattern that caused two bugs tonight:\n"
            "  - dimension_resolver.py commit 47e0963\n"
            "  - router.py commit c794f31\n\n"
            "Pattern: [X for X in collection if term in X or X in term]\n\n"
            "This causes false positives when 'term' is a short/common word:\n"
            "  - 'count' matches 'company_country', 'won_deal_count'\n"
            "  - 'date' matches 'close_date', 'create_date'\n"
            "  - 'id' matches 'deal_id', 'pipeline_id'\n\n"
            "FIX: Use the governed-alias pattern instead:\n"
            "  1. Create a whitelist dict (e.g., _COLUMN_ALIASES)\n"
            "  2. Check exact match first: if term in collection\n"
            "  3. Then check whitelist: elif term in aliases\n"
            "  4. NO substring fallback\n\n"
            "See dimension_resolver.py's _COUNTRY_ALIASES or router.py's\n"
            "_COLUMN_ALIASES (commit c794f31) for the correct pattern."
        )
        raise AssertionError(msg)

    print(f"✓ No dangerous bidirectional substring matching found")
    print("  (Checked for pattern: [X for X in Y if term in X or X in term])")


if __name__ == "__main__":
    test_no_new_bare_substring_matching()
    print("\n✅ TEST 0z: Bare substring matching gate passed")
