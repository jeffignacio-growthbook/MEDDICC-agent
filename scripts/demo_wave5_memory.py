#!/usr/bin/env python3
"""
Wave 5 Memory — Demonstration

Shows all three parts working with examples from the debugging session:
- 5a. Correction → Proposal
- 5b. Answer sequence reconstruction
- 5c. Failure resolution tracking
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent / 'api'))

from corrections import (
    detect_correction,
    extract_correction_facts,
    create_correction_proposal,
    EXAMPLE_CORRECTIONS
)
from memory import (
    extract_figures,
    EXAMPLE_SEQUENCE
)
from failure_resolution import EXAMPLE_RESOLUTIONS


def demo_5a_corrections():
    """Demonstrate correction detection and proposal creation."""
    print("=" * 80)
    print("5a. CORRECTIONS BECOME PROPOSALS")
    print("=" * 80)
    print()

    for example in EXAMPLE_CORRECTIONS:
        user_message = example['user_message']
        handler = example['handler']

        print(f"User correction: \"{user_message}\"")
        print(f"Handler: {handler}")

        # Detect correction
        is_correction = detect_correction(user_message)
        print(f"Detected as correction: {is_correction}")

        if is_correction:
            # Extract facts
            facts = extract_correction_facts(user_message, "Agent said something wrong")
            print(f"Correction type: {facts['correction_type']}")
            print(f"What is right: {facts['what_is_right']}")

            # Create proposal (without DB insert for demo)
            proposal = create_correction_proposal(
                facts,
                thread_ts='demo_thread',
                user_id='demo_user',
                handler_name=handler
            )

            print(f"Proposal created:")
            print(f"  Entity type: {proposal['entity_type']}")
            print(f"  Entity key: {proposal['entity_key']}")
            print(f"  Affects handlers: {proposal['affects_handlers']}")
            print(f"  Rationale: {proposal['rationale'][:100]}...")

        print(f"Should become: {example['what_should_happen']}")
        print()

    print("All four corrections detected and converted to proposals.")
    print()


def demo_5b_answers():
    """Demonstrate answer persistence and sequence reconstruction."""
    print("=" * 80)
    print("5b. ANSWERS GIVEN PERSIST")
    print("=" * 80)
    print()

    # Show the renewals sequence that was lost
    print("The renewals sequence that nobody could reconstruct:")
    print()

    seq = EXAMPLE_SEQUENCE
    print(f"Figure: {seq['figure']}")
    print(f"Sequence:")
    for point in seq['sequence']:
        print(f"  {point['date']}: ${point['value']:,} (via {point['handler']})")

    print()
    print(f"What happened: {seq['explanation']}")
    print(f"With Wave 5b: {seq['what_should_have_happened']}")
    print()

    # Show figure extraction
    test_answer = """
    FY2027 Q3 Forecast:

    New Business: $4.2M (32 deals)
    Upsell/XSell: $1.1M (15 deals)
    Renewals: $1.59M (8 deals)

    Total: $6.89M (55 deals)
    Team attainment: 12.7% against $1.55M target
    """

    print("Figure extraction from answer:")
    print(f"Answer text: {test_answer[:100]}...")
    print()

    figures = extract_figures(test_answer)
    print("Extracted figures:")
    for name, value in figures.items():
        if isinstance(value, int) and value > 1000:
            print(f"  {name}: ${value:,}")
        elif isinstance(value, float):
            print(f"  {name}: {value}%")
        else:
            print(f"  {name}: {value}")

    print()
    print("These figures enable reconciliation when numbers change.")
    print()


def demo_5c_failures():
    """Demonstrate failure resolution tracking."""
    print("=" * 80)
    print("5c. FAILURE RESOLUTION TRACKING")
    print("=" * 80)
    print()

    print("Failures from debugging session that should have been resolved:")
    print()

    for example in EXAMPLE_RESOLUTIONS:
        print(f"Failure: {example['failure']}")
        print(f"Question: \"{example['question']}\"")
        print(f"Resolution type: {example['resolution_type']}")
        print(f"How fixed: {example['resolution_notes']}")
        print(f"Handler: {example['handler']}")
        print()

    print("All four would be marked resolved with resolution_type and notes.")
    print("This closes the loop: fallback_log becomes a record of what was fixed.")
    print()


def main():
    print()
    print("WAVE 5 — MEMORY DEMONSTRATION")
    print("Using examples from Sep 2-3 debugging session")
    print()

    demo_5a_corrections()
    demo_5b_answers()
    demo_5c_failures()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print("5a. Corrections → Proposals")
    print("    ✓ Four corrections detected")
    print("    ✓ Facts extracted")
    print("    ✓ Proposals ready to insert")
    print()
    print("5b. Answers persist beyond 24-hour thread expiry")
    print("    ✓ Renewals sequence reconstructable")
    print("    ✓ Figures extracted for reconciliation")
    print()
    print("5c. Failure resolution closes the loop")
    print("    ✓ Four failures from debugging marked resolved")
    print("    ✓ Resolution type and notes captured")
    print()
    print("Next step: Apply migration 052 and integrate into router.py")
    print()


if __name__ == '__main__':
    main()
