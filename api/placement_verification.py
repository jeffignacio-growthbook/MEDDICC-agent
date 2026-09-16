"""
Reusable placement-plausibility check for corrected values in resynthesized answers.

2026-09-15: Extracted from aggregation_verification.py's verify_total_placement()
to make the two-signal corruption check (duplicate occurrence + single-occurrence
context check) available to any primitive that hands a corrected value to the
model for resynthesis — not just aggregation verification.

The check:
- SIGNAL 1: Corrected value appears MULTIPLE times in answer (definite corruption)
- SIGNAL 2: Corrected value appears ONCE, but in suspicious context (e.g., next to
  an entity name rather than a summary/total line)

Any primitive that forces a retry with a corrected value (dimension filters,
snapshot anchors, aggregation totals, etc.) can call verify_corrected_value_
placement() to detect if the model misplaced that value somewhere wrong.
"""
import re
from typing import List, Dict, Any, Optional


# Matches dollar amounts: $123.45M, $1.2B, $500K, $12,345.67
# Groups: (negative sign if present, digit sequence, decimal if present, suffix)
_AMOUNT_WITH_DOLLAR_RE = re.compile(
    r'\$\s*(-?\s*)([\d,]+)(\.\d+)?\s*([KkMmBb])?'
)


def _amount_to_number(neg: str, digits: str, decimal: str, suffix: str) -> float:
    """Convert regex-matched amount parts to float."""
    value = float(digits.replace(',', '') + (decimal or ''))
    if suffix:
        multipliers = {'K': 1_000, 'k': 1_000, 'M': 1_000_000, 'm': 1_000_000,
                       'B': 1_000_000_000, 'b': 1_000_000_000}
        value *= multipliers.get(suffix, 1)
    return -value if neg.strip() else value


def verify_corrected_value_placement(
    retry_answer_text: str,
    corrected_value: float,
    row_count: int,
    tolerance: float = 0.5,
    entity_type: str = "row"
) -> dict:
    """
    Check if a corrected value handed to the model for resynthesis was
    placed CORRECTLY in the retry answer, or misplaced as an individual
    line-item value.

    STRUCTURAL CHECK (not text pattern matching):
    If the corrected value appears multiple times, or appears once but
    next to an entity name (not a total/summary indicator), this is
    implausible — one item matching the corrected aggregate value is a
    near-certain sign of misplacement (model spliced the value into the
    wrong location).

    This is the reusable primitive-level gate extracted from
    aggregation_verification.py (2026-09-15) to protect ANY primitive
    that forces resynthesis with a corrected value — not just
    aggregation checks.

    Args:
        retry_answer_text: the model's answer AFTER forced resynthesis
        corrected_value: the value we handed to the model
        row_count: number of underlying rows (for context in error message)
        tolerance: absolute difference threshold for numeric comparison
        entity_type: what kind of entities are being aggregated (for messages)

    Returns:
        {"placement_ok": True} if no misplacement detected
        {"placement_ok": False, "suspect_value": X, "likely_corruption": "..."}
            if misplacement detected
    """
    if not retry_answer_text:
        return {"placement_ok": True}

    # Extract all dollar amounts from retry answer
    all_amounts = []
    for match in _AMOUNT_WITH_DOLLAR_RE.finditer(retry_answer_text):
        if match.group(2):  # Has digit group
            value = _amount_to_number(*match.groups())
            all_amounts.append(value)

    if not all_amounts:
        return {"placement_ok": True}

    # Count how many times the corrected value appears in the answer
    matches_count = sum(
        1 for amount in all_amounts
        if abs(amount - corrected_value) <= tolerance
    )

    # SIGNAL 1: Multiple occurrences (definite corruption)
    if matches_count > 1:
        return {
            "placement_ok": False,
            "suspect_value": corrected_value,
            "matches_count": matches_count,
            "likely_corruption": (
                f"Corrected value ${corrected_value:,.2f} appears {matches_count} "
                f"times in retry answer (expected once, in summary line only). "
                f"This is implausible - the same value appearing as both an "
                f"individual line-item AND the total/summary across {row_count} "
                f"{entity_type}{'s' if row_count != 1 else ''} is a near-certain "
                f"sign of misplacement (value spliced into wrong location in "
                f"addition to correct summary line)."
            )
        }

    # SIGNAL 2: Single occurrence, but in suspicious context
    if matches_count == 1:
        # Find the ONE match and check its IMMEDIATE context (same line only)
        for match in _AMOUNT_WITH_DOLLAR_RE.finditer(retry_answer_text):
            if match.group(2):
                value = _amount_to_number(*match.groups())
                if abs(value - corrected_value) <= tolerance:
                    # Found the match - extract the LINE it's on
                    line_start = retry_answer_text.rfind('\n', 0, match.start()) + 1
                    line_end = retry_answer_text.find('\n', match.end())
                    if line_end == -1:
                        line_end = len(retry_answer_text)
                    line = retry_answer_text[line_start:line_end]

                    # Check if THIS LINE contains entity name pattern
                    # Pattern: Capital letter + words + colon/dash before $
                    dollar_pos_in_line = match.start() - line_start
                    prefix = line[:dollar_pos_in_line]
                    check_prefix = prefix[-50:] if len(prefix) > 50 else prefix

                    entity_pattern = r'([A-Z][A-Za-z0-9\s&,\.]+?)(?::|\s—|\s-)\s*$'
                    context_match = re.search(entity_pattern, check_prefix)

                    if context_match:
                        label = context_match.group(1).strip().lower()
                        # Exclude total-indicator phrases
                        TOTAL_INDICATORS = {
                            "total", "overall", "grand", "sum", "net", "aggregate"
                        }
                        if not any(indicator in label for indicator in TOTAL_INDICATORS):
                            # Suspicious: appears next to specific entity, not summary
                            return {
                                "placement_ok": False,
                                "suspect_value": corrected_value,
                                "matches_count": 1,
                                "suspicious_context": label,
                                "likely_corruption": (
                                    f"Corrected value ${corrected_value:,.2f} appears "
                                    f"next to specific entity name "
                                    f"'{context_match.group(1).strip()}' rather than "
                                    f"in a summary/total line. This is implausible - "
                                    f"a single {entity_type} matching the corrected "
                                    f"aggregate across {row_count} {entity_type}{'s' if row_count != 1 else ''} "
                                    f"is a near-certain sign of misplacement (model "
                                    f"replaced line item instead of adding separate "
                                    f"summary)."
                                )
                            }
                    break  # Found and checked the one match

    # Value appears 0 times, or 1 time in valid context - OK
    return {"placement_ok": True}
