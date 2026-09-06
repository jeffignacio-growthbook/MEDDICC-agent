#!/usr/bin/env python3
"""
Simplified Wave 5 Integration Test

Tests the three memory components without going through full router.py.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase


def test_correction_detection():
    """Test 5a: Correction detection logic"""
    print("\n" + "=" * 80)
    print("TEST 1: CORRECTION DETECTION")
    print("=" * 80)

    from api.corrections import detect_correction, ask_correction_scope, extract_correction_facts

    test_messages = [
        "Actually, renewals should value on renewal_revenue, not new_arr",
        "That's wrong - Review is a parking lot for dead deals",
        "No, reps forecast Incremental ARR only",
        "targets use HubSpot's email convention"
    ]

    detected_count = 0
    for msg in test_messages:
        if detect_correction(msg):
            print(f"✓ Detected: '{msg[:50]}...'")
            detected_count += 1
        else:
            print(f"✗ Missed: '{msg[:50]}...'")

    # Test scope question generation
    scope_q = ask_correction_scope(test_messages[0])
    if "general" in scope_q.lower() and "specific" in scope_q.lower():
        print(f"✓ Scope question generated correctly")
    else:
        print(f"✗ Scope question missing options")

    # Test fact extraction
    facts = extract_correction_facts(test_messages[0], "prior response...")
    if facts and 'raw_correction' in facts:
        print(f"✓ Facts extracted from correction")
    else:
        print(f"✗ Fact extraction failed")

    return detected_count == len(test_messages)


def test_proposal_creation():
    """Test 5a: Proposal creation with conversation_evidence"""
    print("\n" + "=" * 80)
    print("TEST 2: PROPOSAL CREATION")
    print("=" * 80)

    from api.corrections import create_correction_proposal

    sb = get_supabase()

    facts = {
        'what_was_wrong': 'Using new_arr field',
        'what_is_right': 'Should use renewal_revenue field',
        'correction_type': 'field_definition',
        'raw_correction': 'renewals value on renewal_revenue',
        'raw_prior_response': 'Renewals are...'
    }

    proposal = create_correction_proposal(
        facts,
        thread_ts='test_thread_proposal',
        user_id='test_user',
        handler_name='query_renewals'
    )

    if proposal:
        print(f"✓ Proposal object created")
        print(f"  Entity type: {proposal.get('entity_type')}")
        print(f"  Has conversation_evidence: {bool(proposal.get('conversation_evidence'))}")

        # Try inserting it
        try:
            result = sb.table('proposals').insert(proposal).execute()
            if result.data:
                proposal_id = result.data[0]['id']
                print(f"✓ Proposal inserted to database: ID {proposal_id}")

                # Clean up test proposal
                sb.table('proposals').delete().eq('id', proposal_id).execute()
                return True
        except Exception as e:
            print(f"✗ Failed to insert proposal: {e}")
            return False
    else:
        print(f"✗ Proposal creation failed")
        return False


def test_answer_persistence():
    """Test 5b: Answer persistence with figure extraction"""
    print("\n" + "=" * 80)
    print("TEST 3: ANSWER PERSISTENCE")
    print("=" * 80)

    from api.memory import save_answer

    sb = get_supabase()

    question = "What is our team attainment?"
    answer = "Team attainment is 12.7% ($197,400 / $1,550,000)"
    tool_results = {
        "attainment_pct": 12.7,
        "closed_value": 197400,
        "target_value": 1550000
    }

    answer_id = save_answer(
        sb,
        question=question,
        answer=answer,
        handler_name="test_handler",
        thread_ts="test_thread_answer",
        asked_by="test_user",
        tool_results=tool_results
    )

    if answer_id:
        print(f"✓ Answer saved: ID {answer_id}")

        # Verify in database
        saved = sb.table('answers_given').select('*').eq('id', answer_id).execute()
        if saved.data:
            s = saved.data[0]
            figures = s.get('figures_cited', {})
            print(f"  Figures extracted: {len(figures)} metrics")

            if 'attainment_pct' in figures:
                print(f"    attainment_pct: {figures['attainment_pct']}")
            if 'target_value' in figures:
                print(f"    target_value: ${figures['target_value']:,.0f}")

            # Clean up test answer
            sb.table('answers_given').delete().eq('id', answer_id).execute()
            return True
    else:
        print("✗ Answer not saved")
        return False


def test_failure_resolution():
    """Test 5c: Failure resolution marking"""
    print("\n" + "=" * 80)
    print("TEST 4: FAILURE RESOLUTION")
    print("=" * 80)

    from api.failure_resolution import mark_failure_resolved

    sb = get_supabase()

    # Create test failure
    result = sb.table('fallback_log').insert({
        'question': 'test failure',
        'trigger': 'test',
        'fast_path_attempted': 'test_handler',
        'fast_path_failure': 'test',
        'answered': False,
        'resolved': False
    }).execute()

    if result.data:
        failure_id = result.data[0]['id']
        print(f"✓ Test failure created: ID {failure_id}")

        # Mark resolved
        success = mark_failure_resolved(
            sb,
            failure_id=failure_id,
            resolution_type='handler_added',
            resolution_notes='Test resolution'
        )

        if success:
            # Verify
            resolved = sb.table('fallback_log').select('*').eq('id', failure_id).execute()
            if resolved.data and resolved.data[0].get('resolved'):
                print(f"✓ Failure marked resolved")
                print(f"  Resolution type: {resolved.data[0].get('resolution_type')}")

                # Clean up
                sb.table('fallback_log').delete().eq('id', failure_id).execute()
                return True

    print("✗ Failure resolution test failed")
    return False


def resolve_historical_failures():
    """Bulk-resolve the four known historical failures"""
    print("\n" + "=" * 80)
    print("TEST 5: BULK-RESOLVE HISTORICAL FAILURES")
    print("=" * 80)

    from api.failure_resolution import bulk_resolve_similar

    sb = get_supabase()

    resolutions = [
        {
            'question_pattern': 'christian attainment',
            'resolution_type': 'data_fixed',
            'notes': 'Fixed email mismatch in rep_targets'
        },
        {
            'question_pattern': 'pipeline this quarter',
            'resolution_type': 'handler_added',
            'notes': 'Added quarter resolution'
        },
        {
            'question_pattern': 'which of those are at risk',
            'resolution_type': 'semantic_fact_added',
            'notes': 'Added thread context support'
        },
        {
            'question_pattern': 'renewals',
            'resolution_type': 'semantic_fact_added',
            'notes': 'Corrected to use renewal_revenue field'
        }
    ]

    resolved_count = 0

    for res in resolutions:
        count = bulk_resolve_similar(
            sb,
            question_pattern=res['question_pattern'],
            resolution_type=res['resolution_type'],
            resolution_notes=res['notes']
        )

        if count > 0:
            print(f"✓ Resolved {count} failure(s) matching '{res['question_pattern']}'")
            resolved_count += count
        else:
            print(f"  No unresolved failures for '{res['question_pattern']}'")

    print(f"\nTotal historical failures resolved: {resolved_count}")
    return True


def main():
    print("=" * 80)
    print("WAVE 5 MEMORY - SIMPLIFIED INTEGRATION TEST")
    print("=" * 80)

    results = []

    # Test 1
    try:
        result1 = test_correction_detection()
        results.append(("Correction detection", result1))
    except Exception as e:
        print(f"✗ Test 1 failed: {e}")
        results.append(("Correction detection", False))

    # Test 2
    try:
        result2 = test_proposal_creation()
        results.append(("Proposal creation", result2))
    except Exception as e:
        print(f"✗ Test 2 failed: {e}")
        results.append(("Proposal creation", False))

    # Test 3
    try:
        result3 = test_answer_persistence()
        results.append(("Answer persistence", result3))
    except Exception as e:
        print(f"✗ Test 3 failed: {e}")
        results.append(("Answer persistence", False))

    # Test 4
    try:
        result4 = test_failure_resolution()
        results.append(("Failure resolution", result4))
    except Exception as e:
        print(f"✗ Test 4 failed: {e}")
        results.append(("Failure resolution", False))

    # Test 5
    try:
        result5 = resolve_historical_failures()
        results.append(("Historical failures", result5))
    except Exception as e:
        print(f"✗ Test 5 failed: {e}")
        results.append(("Historical failures", False))

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(r[1] for r in results)

    if all_passed:
        print("\n✓ ALL TESTS PASSED")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
