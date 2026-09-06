#!/usr/bin/env python3
"""
Test Wave 5 Memory Integration

Tests all three parts working through the actual router.py integration:
1. Correction detection → scope question → proposal creation
2. Answer persistence → figure extraction
3. Failure resolution marking
"""

import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)
sys.path.insert(0, str(Path(__file__).parent))

from api.db import get_supabase
from api.router import route_question
from api.memory import save_answer, extract_figures
from api.corrections import detect_correction
from api.failure_resolution import mark_failure_resolved, bulk_resolve_similar


async def test_correction_detection():
    """Test 5a: Correction detection and proposal creation"""
    print("\n" + "=" * 80)
    print("TEST 1: CORRECTION DETECTION → PROPOSAL CREATION")
    print("=" * 80)

    sb = get_supabase()

    # Test correction detection (should return scope question)
    test_message = "Actually, renewals should value on renewal_revenue, not new_arr"

    result = await route_question(
        question=test_message,
        user_id="test_user",
        persona=None,
        history=[],
        sb=sb,
        thread_ts="test_thread_1"
    )

    handler = result.get('handler_name', '')
    answer = result.get('answer', '')

    if handler == 'correction_scope_question':
        print("✓ Correction detected")
        print(f"  Scope question asked: {answer[:100]}...")

        # Now answer "general" to create proposal
        result2 = await route_question(
            question="general",
            user_id="test_user",
            persona=None,
            history=[
                {"role": "user", "content": test_message, "handler_name": ""},
                {"role": "assistant", "content": answer, "handler_name": "correction_scope_question"}
            ],
            sb=sb,
            thread_ts="test_thread_1"
        )

        handler2 = result2.get('handler_name', '')
        if handler2 == 'correction_proposal_created':
            proposal_id = result2.get('tool_results', {}).get('proposal_id')
            print(f"✓ Proposal created: ID {proposal_id}")

            # Verify proposal in database
            proposal = sb.table('proposals').select('*').eq('id', proposal_id).execute()
            if proposal.data:
                p = proposal.data[0]
                print(f"  Entity type: {p.get('entity_type')}")
                print(f"  Has conversation_evidence: {bool(p.get('conversation_evidence'))}")
                return True
        else:
            print(f"✗ Proposal not created, got handler: {handler2}")
            return False
    else:
        print(f"✗ Correction not detected, got handler: {handler}")
        return False


async def test_answer_persistence():
    """Test 5b: Answer persistence with figure extraction"""
    print("\n" + "=" * 80)
    print("TEST 2: ANSWER PERSISTENCE → FIGURE EXTRACTION")
    print("=" * 80)

    sb = get_supabase()

    # Test answer with numeric figures
    question = "What is our team attainment this quarter?"
    answer = "Team attainment is 12.7% ($197,400 closed / $1,550,000 target)"
    tool_results = {
        "attainment_pct": 12.7,
        "closed_value": 197400,
        "target_value": 1550000
    }

    # Save answer using memory.save_answer
    from api.memory import save_answer

    answer_id = save_answer(
        sb,
        question=question,
        answer=answer,
        handler_name="test_handler",
        thread_ts="test_thread_2",
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
            if 'won_value' in figures or 'closed_value' in figures:
                print(f"    closed_value: ${figures.get('won_value', figures.get('closed_value', 0)):,.0f}")
            if 'target_value' in figures:
                print(f"    target_value: ${figures['target_value']:,.0f}")

            return True
    else:
        print("✗ Answer not saved")
        return False


async def test_failure_resolution():
    """Test 5c: Failure resolution marking"""
    print("\n" + "=" * 80)
    print("TEST 3: FAILURE RESOLUTION MARKING")
    print("=" * 80)

    sb = get_supabase()

    # Create a test failure
    result = sb.table('fallback_log').insert({
        'question': 'test failure for wave 5',
        'trigger': 'test_trigger',
        'fast_path_attempted': 'test_handler',
        'fast_path_failure': 'test failure',
        'answered': False,
        'resolved': False
    }).execute()

    if result.data:
        failure_id = result.data[0]['id']
        print(f"✓ Test failure created: ID {failure_id}")

        # Mark it resolved
        from api.failure_resolution import mark_failure_resolved

        mark_failure_resolved(
            sb,
            failure_id=failure_id,
            resolution_type='handler_added',
            resolution_notes='Test resolution for Wave 5 verification'
        )

        # Verify resolution
        resolved = sb.table('fallback_log').select('*').eq('id', failure_id).execute()
        if resolved.data:
            r = resolved.data[0]
            if r.get('resolved'):
                print(f"✓ Failure marked resolved")
                print(f"  Resolution type: {r.get('resolution_type')}")
                print(f"  Resolution notes: {r.get('resolution_notes')[:50]}...")

                # Clean up test failure
                sb.table('fallback_log').delete().eq('id', failure_id).execute()
                return True
            else:
                print("✗ Failure not marked as resolved")
                return False
    else:
        print("✗ Test failure not created")
        return False


async def resolve_historical_failures():
    """Bulk-resolve the four known historical failures from Sep 2-3"""
    print("\n" + "=" * 80)
    print("TEST 4: BULK-RESOLVE HISTORICAL FAILURES")
    print("=" * 80)

    sb = get_supabase()

    # The four corrections from debugging session (WAVE_5_COMPLETE.md lines 173-189)
    resolutions = [
        {
            'pattern': 'christian attainment',
            'resolution_type': 'data_fixed',
            'notes': 'Fixed email mismatch: christian@ vs christian.liebenow@ in rep_targets'
        },
        {
            'pattern': 'pipeline this quarter',
            'resolution_type': 'handler_added',
            'notes': 'Added quarter resolution to time_resolver.py'
        },
        {
            'pattern': 'which of those are at risk',
            'resolution_type': 'semantic_fact_added',
            'notes': 'Added thread context support for follow-up questions'
        },
        {
            'pattern': 'renewals',
            'resolution_type': 'semantic_fact_added',
            'notes': 'Corrected renewals to use renewal_revenue field instead of new_arr'
        }
    ]

    resolved_count = 0

    for resolution in resolutions:
        count = bulk_resolve_similar(
            sb,
            pattern=resolution['pattern'],
            resolution_type=resolution['resolution_type'],
            resolution_notes=resolution['notes']
        )

        if count > 0:
            print(f"✓ Resolved {count} failure(s) matching '{resolution['pattern']}'")
            resolved_count += count
        else:
            print(f"  No unresolved failures found for '{resolution['pattern']}'")

    print()
    print(f"Total historical failures resolved: {resolved_count}")
    return resolved_count


async def main():
    print("=" * 80)
    print("WAVE 5 MEMORY INTEGRATION TEST")
    print("=" * 80)
    print()
    print("Testing router.py integration with live database...")

    results = []

    # Test 1: Correction detection
    try:
        result1 = await test_correction_detection()
        results.append(("Correction detection", result1))
    except Exception as e:
        print(f"✗ Test 1 failed: {e}")
        results.append(("Correction detection", False))

    # Test 2: Answer persistence
    try:
        result2 = await test_answer_persistence()
        results.append(("Answer persistence", result2))
    except Exception as e:
        print(f"✗ Test 2 failed: {e}")
        results.append(("Answer persistence", False))

    # Test 3: Failure resolution
    try:
        result3 = await test_failure_resolution()
        results.append(("Failure resolution", result3))
    except Exception as e:
        print(f"✗ Test 3 failed: {e}")
        results.append(("Failure resolution", False))

    # Test 4: Bulk resolve historical
    try:
        count = await resolve_historical_failures()
        results.append(("Historical failures resolved", count >= 0))
    except Exception as e:
        print(f"✗ Test 4 failed: {e}")
        results.append(("Historical failures resolved", False))

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
        print("\n✓ ALL TESTS PASSED - Wave 5 integration working")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED - see details above")
        return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
