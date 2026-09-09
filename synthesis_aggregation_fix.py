"""
Synthesis Aggregation Fix - Implementation

Three-part fix for synthesis under-representation bug:
1. Explicit aggregation instruction in prompt
2. Post-generation verification
3. Data-completeness claim validation
"""

# FIX 1: Enhanced synthesis prompt (replaces lines 2198-2204)
SYNTHESIS_PROMPT_ENHANCED = """Tool result: {tool_result}

CRITICAL AGGREGATION RULE - READ CAREFULLY:
When answering questions about activity "over time" or "by dimension":
- You MUST report data from EVERY row/week/segment in the retrieved results
- NEVER anchor on a subset (most recent week, one segment, etc.)
- NEVER sample or summarize without explicitly stating ALL components

Examples of CORRECT aggregation:
✅ "Aug 17: $75K lost, Aug 24: $0, Aug 28: $20K won + $100K lost = -$80K net"
✅ "By segment: Enterprise $0, Mid-Market +$20K, SMB -$100K, Unknown $0"

Examples of INCORRECT (anchoring/sampling):
❌ "Aug 28: -$20K Mid-Market" (drops SMB -$100K from same week)
❌ "Recent weeks show $0 activity" (drops Aug 28 $120K from earlier in period)

If you state a total or period summary, it must equal the sum of ALL retrieved rows.
If you cannot verify completeness, do NOT claim "partial week" or "pending" -
just state what you have: "Retrieved N rows showing X activity"

Can you now answer the question "{question}" from the data gathered so far?
If yes, respond with {{"answer": "..."}} now.
Only call another tool if essential data is still missing."""

# FIX 2: Post-generation verification
def verify_synthesis_aggregation(answer_text: str, accumulated_data: dict,
                                question: str) -> dict:
    """
    Verify synthesis correctly aggregated retrieved data.

    Returns:
        {"verified": bool, "issues": list, "corrections": dict}
    """
    import re
    from collections import defaultdict

    issues = []
    corrections = {}

    # Extract all numeric values from answer
    # Pattern: $X, $XK, $XM, Xk, Xm
    amount_pattern = r'\$?([\d,]+\.?\d*)\s*([KkMm])?'
    stated_amounts = []

    for match in re.finditer(amount_pattern, answer_text):
        value_str = match.group(1).replace(',', '')
        multiplier = match.group(2)

        try:
            value = float(value_str)
            if multiplier and multiplier.lower() == 'k':
                value *= 1000
            elif multiplier and multiplier.lower() == 'm':
                value *= 1000000
            stated_amounts.append(value)
        except ValueError:
            continue

    # Calculate actual totals from accumulated_data
    actual_totals = defaultdict(float)

    for key, data in accumulated_data.items():
        if not key.startswith("step_"):
            continue

        rows = data.get("rows", [])
        if not rows:
            continue

        # Sum common aggregation columns
        for row in rows:
            for col in ['won_value', 'lost_value', 'new_pipeline_value',
                       'net_change', 'deal_value', 'incremental_arr']:
                val = row.get(col)
                if val is not None:
                    actual_totals[col] += val

    # Check: If actual_totals exist but no amounts in answer
    if actual_totals and not stated_amounts:
        issues.append("synthesis_missing_numbers")
        corrections["note"] = "Answer should include specific $ amounts from data"

    # Check: If question asks about specific time period
    time_keywords = ['week', 'month', 'quarter', 'last', 'this', 'over']
    is_time_question = any(kw in question.lower() for kw in time_keywords)

    if is_time_question and accumulated_data:
        # Check if answer breaks down by time period
        date_patterns = [r'\d{4}-\d{2}-\d{2}', r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+']
        has_date_breakdown = any(re.search(p, answer_text) for p in date_patterns)

        if not has_date_breakdown:
            issues.append("time_question_without_breakdown")
            corrections["note"] = "Time-range question should show week-by-week or period breakdown"

    # Check: "partial" or "pending" claims
    completeness_claims = ['partial', 'pending', 'incomplete', 'not yet']
    has_completeness_claim = any(claim in answer_text.lower() for claim in completeness_claims)

    if has_completeness_claim:
        issues.append("unverified_completeness_claim")
        corrections["note"] = "Claims about data completeness should be verified against row counts"

    verified = len(issues) == 0

    return {
        "verified": verified,
        "issues": issues,
        "corrections": corrections,
        "stated_amounts": stated_amounts,
        "actual_totals": dict(actual_totals)
    }


# FIX 3: Data-completeness claim validator
def validate_completeness_claims(answer_text: str, accumulated_data: dict,
                                expected_dimensions: dict = None) -> dict:
    """
    Validate any "partial week" or "pending" claims against actual row counts.

    Args:
        answer_text: The synthesized answer
        accumulated_data: Retrieved data
        expected_dimensions: Optional dict like {"segments": 4, "regions": 5}

    Returns:
        {"valid": bool, "claims_found": list, "actual_counts": dict}
    """
    claims_found = []
    actual_counts = {}

    # Scan for completeness claims
    completeness_patterns = [
        (r'partial week', 'partial_week'),
        (r'pending.*close', 'pending_close'),
        (r'remaining.*pending', 'remaining_pending'),
        (r'incomplete.*data', 'incomplete_data'),
    ]

    for pattern, claim_type in completeness_patterns:
        if re.search(pattern, answer_text, re.IGNORECASE):
            claims_found.append(claim_type)

    if not claims_found:
        return {"valid": True, "claims_found": [], "actual_counts": {}}

    # If claims exist, verify against actual data
    for key, data in accumulated_data.items():
        if not key.startswith("step_"):
            continue

        rows = data.get("rows", [])

        # Count by dimension
        if rows and isinstance(rows[0], dict):
            for dim in ['segment', 'region', 'week_ending']:
                if dim in rows[0]:
                    unique_vals = set(r.get(dim) for r in rows if r.get(dim))
                    actual_counts[dim] = len(unique_vals)

    # Validate against expected
    valid = True
    if expected_dimensions:
        for dim, expected_count in expected_dimensions.items():
            actual_count = actual_counts.get(dim, 0)
            if actual_count >= expected_count:
                # We have all expected values - "partial" claim is incorrect
                valid = False

    return {
        "valid": valid if claims_found else True,
        "claims_found": claims_found,
        "actual_counts": actual_counts,
        "expected_dimensions": expected_dimensions or {}
    }


# Example usage in dynamic_query_loop:
"""
# After line 2204, before returning answer:

verification = verify_synthesis_aggregation(
    answer_text=parsed["answer"],
    accumulated_data=accumulated_data,
    question=question
)

if not verification["verified"]:
    logger.warning(f"[SYNTHESIS_VERIFICATION] Failed: {verification['issues']}")
    # Could retry synthesis with stronger instruction, or return with warning

completeness_check = validate_completeness_claims(
    answer_text=parsed["answer"],
    accumulated_data=accumulated_data,
    expected_dimensions={"segment": 4}  # If querying waterfall
)

if not completeness_check["valid"]:
    logger.warning(f"[COMPLETENESS_CLAIM] Invalid claims: {completeness_check['claims_found']}")
"""
