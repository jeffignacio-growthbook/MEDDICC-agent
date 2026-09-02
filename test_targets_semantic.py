#!/usr/bin/env python3
"""Test that targets are loaded into semantic context."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

from utils import build_semantic_context

def main():
    """Test semantic context includes targets."""
    context = build_semantic_context()

    print("Semantic Context Build Test")
    print("=" * 70)
    print()

    # Check for targets section
    if "## Sales Targets" in context:
        print("✓ Sales Targets section present")
    else:
        print("✗ Sales Targets section missing")
        return

    # Check for team total
    if "$1,550,000" in context:
        print("✓ Team total found ($1,550,000)")
    else:
        print("✗ Team total missing")

    # Check for gap to plan frame
    if "Gap to Plan Frame" in context:
        print("✓ Gap to plan frame present")
    else:
        print("✗ Gap to plan frame missing")

    # Check for required pipeline guidance
    if "measured_conversion_rate" in context:
        print("✓ Required pipeline formula present")
    else:
        print("✗ Required pipeline formula missing")

    # Check for non-quota roles
    if "cary.rakin@growthbook.io" in context:
        print("✓ Non-quota roles (AMs) listed")
    else:
        print("✗ Non-quota roles missing")

    # Check for James Shannon note
    if "corrected from 250000" in context:
        print("✓ James Shannon mid-quarter correction noted")
    else:
        print("✗ James Shannon correction note missing")

    # Check for Marcel ramp notation
    if "ramp" in context.lower():
        print("✓ Marcel Geldner ramp quota noted")
    else:
        print("✗ Marcel ramp notation missing")

    print()
    print("=" * 70)
    print("Targets section preview:")
    print("=" * 70)
    print()

    # Extract and show targets section
    if "## Sales Targets" in context:
        start_idx = context.index("## Sales Targets")
        # Find next section or end
        remaining = context[start_idx:]
        next_section = remaining.find("\n##", 1)
        if next_section > 0:
            targets_section = remaining[:next_section]
        else:
            targets_section = remaining

        print(targets_section[:1000])
        if len(targets_section) > 1000:
            print(f"\n... (truncated, {len(targets_section)} total chars)")

if __name__ == '__main__':
    main()
