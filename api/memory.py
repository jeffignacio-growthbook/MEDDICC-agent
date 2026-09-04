"""
Wave 5b — Answers Given Persistence

Thread history expires after 24 hours. This module persists answers
so "you told me $733K last week" is answerable and changing numbers
can be reconciled.
"""
import re
import json
from typing import Dict, List, Optional
from datetime import datetime


def extract_figures(answer_text: str) -> Dict:
    """
    Extract numerical figures from an answer for later reconciliation.

    Returns dict of figure_name → value for key metrics.
    Examples:
        "$14.8M total ARR" → {"total_arr": 14800000}
        "127 deals" → {"deal_count": 127}
        "12.7% attainment" → {"attainment_pct": 12.7}
    """
    figures = {}

    # Currency values (e.g., $14.8M, $733K, $1.59M)
    currency_pattern = r'\$([0-9,.]+)([KMB])?'
    for match in re.finditer(currency_pattern, answer_text):
        value_str = match.group(1).replace(',', '')
        multiplier_str = match.group(2)

        value = float(value_str)
        if multiplier_str == 'K':
            value *= 1000
        elif multiplier_str == 'M':
            value *= 1000000
        elif multiplier_str == 'B':
            value *= 1000000000

        # Try to find context (what this number represents)
        # Look 20 chars before and after
        start = max(0, match.start() - 20)
        end = min(len(answer_text), match.end() + 20)
        context = answer_text[start:end].lower()

        if 'renewal' in context or 'renew' in context:
            figures['renewal_value'] = int(value)
        elif 'pipeline' in context or 'total' in context:
            figures['pipeline_value'] = int(value)
        elif 'forecast' in context:
            figures['forecast_value'] = int(value)
        elif 'won' in context or 'closed' in context:
            figures['won_value'] = int(value)
        elif 'arr' in context:
            figures['arr_value'] = int(value)

    # Deal counts (e.g., "127 deals", "3 out of 432 deals")
    deal_count_pattern = r'(\d+)\s+deals?'
    for match in re.finditer(deal_count_pattern, answer_text, re.IGNORECASE):
        count = int(match.group(1))
        # Look for context
        start = max(0, match.start() - 30)
        context = answer_text[start:match.start()].lower()

        if 'commit' in context:
            figures['commit_deal_count'] = count
        elif 'no arr' in context or 'missing' in context:
            figures['missing_arr_count'] = count
        elif 'at risk' in context or 'at-risk' in context:
            figures['at_risk_count'] = count
        else:
            figures['deal_count'] = count

    # Percentages (e.g., "12.7%", "22.4%", "77% GRR")
    percentage_pattern = r'(\d+\.?\d*)\s*%'
    for match in re.finditer(percentage_pattern, answer_text):
        pct = float(match.group(1))
        # Look for context
        start = max(0, match.start() - 30)
        end = min(len(answer_text), match.end() + 20)
        context = answer_text[start:end].lower()

        if 'attainment' in context:
            figures['attainment_pct'] = pct
        elif 'grr' in context or 'retention' in context:
            figures['grr_pct'] = pct
        elif 'conversion' in context or 'win rate' in context:
            figures['conversion_pct'] = pct

    # Targets (e.g., "target: $250K", "quota: $300K")
    target_pattern = r'(?:target|quota):\s*\$([0-9,.]+)([KMB])?'
    for match in re.finditer(target_pattern, answer_text, re.IGNORECASE):
        value_str = match.group(1).replace(',', '')
        multiplier_str = match.group(2)

        value = float(value_str)
        if multiplier_str == 'K':
            value *= 1000
        elif multiplier_str == 'M':
            value *= 1000000

        figures['target_value'] = int(value)

    return figures


def save_answer(
    sb,
    question: str,
    answer: str,
    handler_name: str,
    thread_ts: Optional[str] = None,
    asked_by: Optional[str] = None,
    tool_results: Optional[Dict] = None
) -> int:
    """
    Save an answer to answers_given table.

    Args:
        sb: Supabase client
        question: The question asked
        answer: The answer provided
        handler_name: Which handler produced this answer
        thread_ts: Slack thread timestamp (if applicable)
        asked_by: Slack user_id or 'calibration_runner'
        tool_results: Dict with 'rows', 'table', etc.

    Returns:
        ID of inserted row
    """
    # Extract figures for reconciliation
    figures_cited = extract_figures(answer)

    # Extract metadata from tool_results
    tables_queried = []
    row_count = None

    if tool_results:
        if 'table' in tool_results:
            tables_queried = [tool_results['table']]
        elif 'tables' in tool_results:
            tables_queried = tool_results['tables']

        if 'rows' in tool_results:
            if isinstance(tool_results['rows'], list):
                row_count = len(tool_results['rows'])
            elif isinstance(tool_results['rows'], int):
                row_count = tool_results['rows']

    record = {
        'question': question,
        'answer': answer[:10000],  # Truncate very long answers
        'figures_cited': figures_cited,
        'handler_name': handler_name,
        'thread_ts': thread_ts,
        'asked_by': asked_by,
        'tables_queried': tables_queried,
        'row_count': row_count
    }

    result = sb.table('answers_given').insert(record).execute()

    if result.data:
        return result.data[0]['id']
    return None


def get_prior_answers(
    sb,
    question_pattern: str,
    limit: int = 5
) -> List[Dict]:
    """
    Retrieve prior answers matching a question pattern.

    Enables "you told me $733K last week" type queries and
    reconciliation when numbers change.

    Args:
        sb: Supabase client
        question_pattern: Search pattern (uses text search)
        limit: Max results to return

    Returns:
        List of dicts with question, answer, figures_cited, answered_at
    """
    # Use Postgres text search
    result = sb.table('answers_given') \
        .select('question,answer,figures_cited,handler_name,answered_at') \
        .textSearch('question', question_pattern) \
        .order('answered_at', desc=True) \
        .limit(limit) \
        .execute()

    return result.data if result.data else []


def reconcile_figure_change(
    sb,
    figure_name: str,
    old_value: float,
    new_value: float,
    question: str
) -> Optional[str]:
    """
    Generate explanation for why a figure changed.

    Looks at prior answers for the same question and shows the sequence.

    Example:
        renewals $733K → $5.2M → $1.59M
        Reason: Changed from new_arr to renewal_revenue field

    Returns explanation string or None if no prior answers found.
    """
    # Get prior answers for similar questions
    prior = get_prior_answers(sb, question, limit=10)

    if not prior:
        return None

    # Extract the figure sequence
    sequence = []
    for ans in reversed(prior):  # Oldest to newest
        figures = ans.get('figures_cited', {})
        if figure_name in figures:
            sequence.append({
                'value': figures[figure_name],
                'date': ans['answered_at'][:10],
                'handler': ans['handler_name']
            })

    if len(sequence) < 2:
        return None

    # Build explanation
    explanation_parts = [
        f"This figure has changed {len(sequence)} times:"
    ]

    for i, point in enumerate(sequence):
        value_str = f"${point['value']:,.0f}" if point['value'] > 1000 else f"{point['value']:.1f}%"
        explanation_parts.append(
            f"  {i+1}. {point['date']}: {value_str} (via {point['handler']})"
        )

    explanation_parts.append(
        f"\nCheck proposals table for corrections that might explain the change."
    )

    return '\n'.join(explanation_parts)


# Example: The renewals sequence that nobody could reconstruct
EXAMPLE_SEQUENCE = {
    'figure': 'renewal_value',
    'sequence': [
        {'date': '2026-09-02', 'value': 733000, 'handler': 'query_renewals'},
        {'date': '2026-09-02', 'value': 5200000, 'handler': 'query_renewals'},
        {'date': '2026-09-02', 'value': 1590000, 'handler': 'query_renewals'},
    ],
    'explanation': 'Changed from new_arr to renewal_revenue field after correction',
    'what_should_have_happened': 'With answers_given, reconstruction is automatic'
}
