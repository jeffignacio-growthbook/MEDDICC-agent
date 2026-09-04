"""
Wave 5c — Failure Resolution Tracking

fallback_log captures trigger and fast_path_attempted.
When a failure gets fixed, close the loop so the log becomes
a record of what actually goes wrong here.
"""
from typing import Optional, Dict, List
from datetime import datetime, timedelta


def mark_failure_resolved(
    sb,
    failure_id: int,
    resolution_type: str,
    resolution_notes: str
) -> bool:
    """
    Mark a fallback failure as resolved.

    Args:
        sb: Supabase client
        failure_id: ID from fallback_log
        resolution_type: One of:
            - 'handler_added' - New handler created to answer this
            - 'semantic_fact_added' - Context updated (config/context.yaml)
            - 'data_fixed' - Underlying data issue corrected
            - 'question_clarified' - User rephrased, now answerable
            - 'out_of_scope' - Confirmed not in agent's scope
        resolution_notes: How it was fixed

    Returns:
        True if updated successfully
    """
    valid_types = [
        'handler_added',
        'semantic_fact_added',
        'data_fixed',
        'question_clarified',
        'out_of_scope'
    ]

    if resolution_type not in valid_types:
        raise ValueError(f"resolution_type must be one of {valid_types}")

    update = {
        'resolved': True,
        'resolved_at': datetime.utcnow().isoformat(),
        'resolution_type': resolution_type,
        'resolution_notes': resolution_notes
    }

    result = sb.table('fallback_log') \
        .update(update) \
        .eq('id', failure_id) \
        .execute()

    return bool(result.data)


def find_similar_unresolved_failures(
    sb,
    question: str,
    handler_attempted: Optional[str] = None,
    lookback_days: int = 90
) -> List[Dict]:
    """
    Find similar unresolved failures in fallback_log.

    Useful when fixing a failure - find all similar ones to bulk-resolve.

    Args:
        sb: Supabase client
        question: Question text to match (fuzzy)
        handler_attempted: Filter by specific handler
        lookback_days: How far back to search

    Returns:
        List of unresolved failure records
    """
    cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat()

    query = sb.table('fallback_log') \
        .select('id,question,trigger,fast_path_attempted,created_at') \
        .eq('resolved', False) \
        .gte('created_at', cutoff)

    if handler_attempted:
        query = query.eq('fast_path_attempted', handler_attempted)

    result = query.execute()

    if not result.data:
        return []

    # Fuzzy match on question text
    matches = []
    question_lower = question.lower()
    question_words = set(question_lower.split())

    for record in result.data:
        record_question = record['question'].lower()
        record_words = set(record_question.split())

        # Jaccard similarity
        intersection = question_words & record_words
        union = question_words | record_words

        if len(union) > 0:
            similarity = len(intersection) / len(union)
            if similarity > 0.3:  # 30% word overlap
                matches.append(record)

    return matches


def get_resolution_stats(sb, days: int = 30) -> Dict:
    """
    Get statistics on failure resolution.

    Returns metrics like:
        - Total failures in period
        - Resolved count and %
        - Breakdown by resolution_type
        - Top unresolved patterns

    Useful for understanding what improvements had the biggest impact.
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    # Get all failures in period
    all_failures = sb.table('fallback_log') \
        .select('id,resolved,resolution_type,trigger,fast_path_attempted') \
        .gte('created_at', cutoff) \
        .execute()

    if not all_failures.data:
        return {
            'total_failures': 0,
            'resolved_count': 0,
            'resolution_rate': 0,
            'by_resolution_type': {},
            'by_trigger': {}
        }

    total = len(all_failures.data)
    resolved = [f for f in all_failures.data if f.get('resolved')]
    resolved_count = len(resolved)

    # Breakdown by resolution type
    by_type = {}
    for f in resolved:
        rtype = f.get('resolution_type', 'unknown')
        by_type[rtype] = by_type.get(rtype, 0) + 1

    # Breakdown by original trigger
    by_trigger = {}
    for f in all_failures.data:
        trigger = f.get('trigger', 'unknown')
        by_trigger[trigger] = by_trigger.get(trigger, 0) + 1

    return {
        'total_failures': total,
        'resolved_count': resolved_count,
        'resolution_rate': resolved_count / total if total > 0 else 0,
        'by_resolution_type': by_type,
        'by_trigger': by_trigger,
        'unresolved_count': total - resolved_count
    }


def bulk_resolve_similar(
    sb,
    question_pattern: str,
    resolution_type: str,
    resolution_notes: str,
    handler_filter: Optional[str] = None
) -> int:
    """
    Bulk-resolve similar failures.

    Useful after fixing a systemic issue (e.g., added new handler,
    fixed data quality issue).

    Returns count of failures marked resolved.
    """
    similar = find_similar_unresolved_failures(
        sb,
        question_pattern,
        handler_attempted=handler_filter
    )

    count = 0
    for failure in similar:
        success = mark_failure_resolved(
            sb,
            failure['id'],
            resolution_type,
            resolution_notes
        )
        if success:
            count += 1

    return count


# Examples from debugging session that should have been resolved
EXAMPLE_RESOLUTIONS = [
    {
        'failure': 'renewals went $733K → $5.2M → $1.59M',
        'question': 'How much expansion ARR is in the renewal pipeline?',
        'resolution_type': 'semantic_fact_added',
        'resolution_notes': 'Updated config: renewals use renewal_revenue field, not new_arr',
        'handler': 'query_renewals'
    },
    {
        'failure': 'Christian attainment returned empty',
        'question': 'How is Christian tracking?',
        'resolution_type': 'data_fixed',
        'resolution_notes': 'Fixed email mismatch: christian@ vs christian.liebenow@ in rep_targets',
        'handler': 'query_rep_attainment'
    },
    {
        'failure': 'What is our pipeline this quarter? (ambiguous)',
        'question': 'what is our pipeline this quarter?',
        'resolution_type': 'handler_added',
        'resolution_notes': 'Added quarter resolution to query_pipeline handler',
        'handler': 'query_pipeline'
    },
    {
        'failure': '42 unanswered "which of those are at risk?" questions',
        'question': 'which of those are at risk?',
        'resolution_type': 'semantic_fact_added',
        'resolution_notes': 'Thread context now preserved, pronoun resolution works',
        'handler': 'query_deals_at_risk'
    }
]
