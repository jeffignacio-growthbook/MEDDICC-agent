"""
Aggregation-completeness verification — a mandatory code-level gate,
not a prompt instruction.

The two historical incidents this closes are already documented, in
prose form, inside api/router.py's synthesis prompts (the "CRITICAL
AGGREGATION RULE" block in dynamic_query_loop):

  - MISSING WEEK: an answer anchored on the most recent week only,
    dropping earlier weeks' activity from a stated total or breakdown.
    Prompt-level fix: "Report data from EVERY row/week/segment... NEVER
    anchor on subset."
  - MISSING SEGMENT: an answer stated "Aug 28: -$20K" when the real
    week-28 activity was "$20K won + $100K lost" (net -$80K) in a
    DIFFERENT segment than the one the answer implicitly anchored on —
    the $100K simply never made it into the stated figure. Prompt-level
    fix: "Break down by component before stating totals... don't drop
    $100K from another segment."

Both fixes were prompt instructions asking the model to be more
careful — the same category of fix as asking a model not to narrate a
scratchpad (see api/snapshot_diff.py's module docstring for why that
class of fix doesn't hold up). verify_aggregation_completeness() closes
this at the code level instead: given the rows actually retrieved and
whatever totals the model's draft answer stated, it recomputes the real
sum per stated category and compares — deterministically, the same
"catch it in code, not in the model's discipline" pattern already
proven for snapshot diffing.

extract_stated_totals_from_answer() is the companion, best-effort
extraction step that turns a model's free-text answer into the
{category: amount} structure this function consumes — regex-based,
same rigor level as the existing _extract_dated_claims() in
api/router.py, not a full NLP parse. The core, precisely-testable
primitive is verify_aggregation_completeness() itself; the extraction
step is what makes wiring it into the live loop possible.
"""
import re
from typing import Any, Dict, List, Optional

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_CATEGORY_ALIASES = {"total", "overall", "grand total", "grand_total"}

# Preferred numeric columns to sum when the caller doesn't specify one —
# real column names from waterfall_weekly/deals_snapshot (net_change is
# waterfall_weekly's own precomputed weekly net, the exact field the
# "missing week"/"missing segment" incidents were about).
_PREFERRED_VALUE_COLUMNS = [
    "net_change", "deal_value", "won_value", "lost_value", "arr_usd", "amount", "value",
]


def _label_matches_row_value(label: str, value: Any) -> bool:
    """True if `label` (a category name from the model's stated
    breakdown, e.g. 'Aug 28' or 'Enterprise') identifies the same
    category as a row's field value (e.g. a week_ending of
    '2026-08-28' or a segment of 'Enterprise')."""
    if value is None:
        return False
    label_norm = label.strip().lower()
    value_str = str(value).strip().lower()
    if label_norm == value_str:
        return True
    # "Aug 28" / "Aug. 28" against an ISO date "2026-08-28".
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})$", label.strip())
    if m:
        month_num = _MONTH_ABBR.get(m.group(1).lower()[:3])
        day = int(m.group(2))
        date_m = re.match(r"^\d{4}-(\d{2})-(\d{2})", value_str)
        if month_num and date_m and int(date_m.group(1)) == month_num and int(date_m.group(2)) == day:
            return True
    return False


def _infer_value_column(rows: List[dict]) -> Optional[str]:
    """Pick the numeric column to sum when the caller doesn't specify
    one. Prefers known value-like column names (real names from
    waterfall_weekly/deals_snapshot); falls back to the single numeric
    column if there's exactly one candidate, since a genuinely
    unambiguous shape shouldn't require the caller to name the column
    just to be safe."""
    if not rows:
        return None
    keys = set()
    for r in rows:
        if isinstance(r, dict):
            keys.update(r.keys())
    numeric_keys = [
        k for k in keys
        if any(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) for r in rows)
        and all(r.get(k) is None or (isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool))
                for r in rows)
    ]
    for preferred in _PREFERRED_VALUE_COLUMNS:
        if preferred in numeric_keys:
            return preferred
    if len(numeric_keys) == 1:
        return numeric_keys[0]
    return None


def verify_aggregation_completeness(retrieved_rows: List[dict], stated_totals: Dict[str, float],
                                     value_column: Optional[str] = None,
                                     tolerance: float = 0.5) -> dict:
    """
    Recompute the real sum per stated category from `retrieved_rows` and
    compare against `stated_totals` — deterministically, in code.

    Args:
        retrieved_rows: the actual rows the loop retrieved (e.g. from
            waterfall_weekly or deals_snapshot).
        stated_totals: {category_label: numeric_value} the model's draft
            answer claims — e.g. {"Aug 28": -20000.0} or
            {"total": 120000.0}. "total"/"overall"/"grand total" (case-
            insensitive) is treated as a claim about ALL retrieved rows
            combined; any other label is matched against each row's
            field values (see _label_matches_row_value) to find which
            rows that category refers to.
        value_column: the numeric column to sum. Auto-detected from
            common names (net_change, deal_value, won_value, ...) when
            not given — see _infer_value_column().
        tolerance: absolute difference below which a stated figure and
            the real sum are considered a match (rounding/formatting
            noise, e.g. "$75K" rounding an exact $74,850).

    Returns:
        {"match": True} when nothing to check (no rows, no stated
            totals, no numeric column found — verification degrades to
            "nothing to disprove," not a false alarm) or every stated
            category matches its real sum within tolerance.
        {"match": False, "discrepancy": {"category": label, "stated": X,
            "actual_sum": Y, "missing_rows": [...]}, "all_discrepancies":
            [...]}: "discrepancy" is the first mismatch found (stable,
            sorted by category label) for a caller that just wants one
            headline figure to build a retry message from; "missing_rows"
            is every row that category matched, so a resynthesis retry
            can show the model exactly what it needs to account for
            rather than just naming a number. "all_discrepancies" carries
            every mismatched category, not only the first, for a caller
            that wants the complete picture.
    """
    if not retrieved_rows or not stated_totals:
        return {"match": True}

    column = value_column or _infer_value_column(retrieved_rows)
    if not column:
        return {"match": True}

    discrepancies = []
    for label in sorted(stated_totals.keys()):
        stated_value = stated_totals[label]
        if label.strip().lower() in _CATEGORY_ALIASES:
            matching_rows = retrieved_rows
        else:
            matching_rows = [
                r for r in retrieved_rows
                if isinstance(r, dict) and any(_label_matches_row_value(label, v) for v in r.values())
            ]
            if not matching_rows:
                # This label doesn't correspond to any retrieved row at
                # all — nothing to recompute it against, so this isn't a
                # completeness gap this function can speak to.
                continue

        actual_sum = sum(
            (r.get(column) or 0) for r in matching_rows if isinstance(r, dict)
        )
        if abs(actual_sum - stated_value) > tolerance:
            discrepancies.append({
                "category": label,
                "stated": stated_value,
                "actual_sum": actual_sum,
                "missing_rows": matching_rows,
            })

    if not discrepancies:
        return {"match": True}

    return {
        "match": False,
        "discrepancy": discrepancies[0],
        "all_discrepancies": discrepancies,
    }


# Primary regex: match dollar amounts with explicit $ sign (most reliable)
_AMOUNT_WITH_DOLLAR_RE = re.compile(
    r"([+-]?)\$([\d][\d,]*(?:\.\d+)?)\s*([KkMm])?\s*(won|lost)?", re.IGNORECASE
)

# Fallback regex: bare numbers (no $) - ONLY used when $ sign not found
# and we have strong context (e.g., immediately after "total:" or "total is")
_BARE_NUMBER_RE = re.compile(
    r"([+-]?)([\d][\d,]*(?:\.\d+)?)\s*([KkMm])?\s*(won|lost)?", re.IGNORECASE
)

# Legacy name for backwards compatibility - now points to $ -required version
_AMOUNT_RE = _AMOUNT_WITH_DOLLAR_RE


def _amount_to_number(sign: str, digits: str, mult: Optional[str], verb: Optional[str]) -> float:
    value = float(digits.replace(",", ""))
    if mult:
        value *= {"k": 1_000, "m": 1_000_000}[mult.lower()]
    if verb and verb.lower() == "lost":
        value = -abs(value)
    elif sign == "-":
        value = -abs(value)
    return value


def _format_agg_number(value: float) -> str:
    """Format a number with commas and appropriate decimal places for aggregation display."""
    if value == int(value):
        # Whole number - no decimals
        return f"{value:,.0f}"
    else:
        # Has decimals - show 2 decimal places
        return f"{value:,.2f}"


_LABEL_LINE_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9 ,'\-]{0,40}?):\s*([^\n]+?)(?=(?:,\s*[A-Za-z][\w ,'\-]{0,40}?:|\n|$))"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _extract_total(answer_text: str) -> Optional[float]:
    """The first dollar amount in any sentence that mentions "total" —
    sentence-scoped (not a fixed character window) so ordinary phrasing
    ("Total pipeline movement this period was $20K.") isn't missed just
    because there are more than a few words between "total" and the
    figure.

    FIX (2026-09-14): Original regex had optional $ sign (\$?), matching
    ANY bare number — so "Jan 2025 to Date... Total: $6.8M" extracted
    2025.0 (the year) instead of $6.8M. Now searches for $ amounts first
    (most reliable), only falling back to bare numbers when:
    1. No $ amount found in the sentence, AND
    2. The bare number appears immediately after "total" + connector
       (e.g., "Total: 1500000" or "Total is 1.5M")
    This prevents extracting years, deal counts, or other stray digits.
    """
    for sentence in _SENTENCE_SPLIT_RE.split(answer_text):
        if re.search(r"\btotal\b", sentence, re.IGNORECASE):
            # PHASE 1: Look for explicit dollar amount ($ sign required)
            m = _AMOUNT_WITH_DOLLAR_RE.search(sentence)
            if m and m.group(2):
                return _amount_to_number(*m.groups())

            # PHASE 2: Only if no $ amount found, check for bare number
            # after "total" + connector word/punctuation, allowing intervening
            # words like "Total ARR pipeline is 4" or "Total movement was 11"
            # Allowed patterns:
            #   "Total: 1.5M" (immediate)
            #   "Total is 1.5M" (immediate)
            #   "Total ARR pipeline is 1.5M" (with words between)
            #   "Total movement this period was 1.5M" (with words between)
            context_match = re.search(
                r'\btotal\b(?:[^.!?:]*?)(?::|is|was|of)\s*([+-]?[\d][\d,]*(?:\.\d+)?)\s*([KkMm])?\b',
                sentence,
                re.IGNORECASE
            )
            if context_match:
                sign = ""
                digits = context_match.group(1)
                mult = context_match.group(2)
                verb = None  # No won/lost in this context
                return _amount_to_number(sign, digits, mult, verb)

    return None


def extract_stated_totals_from_answer(answer_text: str) -> Dict[str, float]:
    """
    Best-effort extraction of {category_label: stated_amount} from a
    model's free-text answer — regex-based, matching the exact format
    the synthesis prompt's own "CRITICAL AGGREGATION RULE" instructs the
    model to use ("Aug 17: $75K lost, Aug 24: $0, Aug 28: $20K won +
    $100K lost"). Not a general NLP parse — same rigor level as the
    existing _extract_dated_claims() in api/router.py. Returns {} when
    nothing recognizable is found (never raises).

    A line with multiple dollar amounts (e.g. "$20K won + $100K lost")
    is netted into one signed total for that category, since that's the
    unit verify_aggregation_completeness() compares against a single
    recomputed row-sum.
    """
    if not answer_text:
        return {}
    stated: Dict[str, float] = {}

    total_value = _extract_total(answer_text)
    if total_value is not None:
        stated["total"] = total_value

    for label, rest in _LABEL_LINE_RE.findall(answer_text):
        label = label.strip()
        if label.lower() in _CATEGORY_ALIASES:
            continue
        amounts = [m for m in _AMOUNT_RE.findall(rest) if m[1]]
        if not amounts:
            continue
        stated[label] = sum(_amount_to_number(*a) for a in amounts)

    return stated


def verify_total_placement(
    retrieved_rows: List[dict],
    retry_answer_text: str,
    corrected_total: float,
    value_column: Optional[str] = None,
    tolerance: float = 0.5
) -> dict:
    """
    Second-order verification after forced resynthesis for aggregation
    mismatch: checks whether the corrected total was placed CORRECTLY
    in the retry answer, or misplaced as an individual line-item value.

    STRUCTURAL CHECK (not text pattern matching):
    If any individual line-item value in the retry answer equals the
    corrected TOTAL (within tolerance), this is implausible — one deal
    matching the grand total across hundreds of deals is a near-certain
    sign the model spliced the corrected total into the wrong location.

    This is the primitive-level gate that protects EVERY handler and
    EVERY dynamic_query call from the Creative CX-style corruption
    (where a $6.89M total for 354 deals was attached to a single
    company instead of the summary line).

    Args:
        retrieved_rows: the actual rows retrieved (e.g. deals, waterfall)
        retry_answer_text: the model's answer AFTER forced resynthesis
        corrected_total: the total value we handed to the model
        value_column: numeric column to compare against (auto-detected if None)
        tolerance: absolute difference threshold

    Returns:
        {"placement_ok": True} if no individual value matches total
        {"placement_ok": False, "suspect_value": X, "actual_total": Y,
         "likely_corruption": "...message..."} if misplacement detected
    """
    if not retrieved_rows or not retry_answer_text:
        return {"placement_ok": True}

    # Extract all dollar amounts from retry answer (individual values, not just total)
    all_amounts = []
    for match in _AMOUNT_WITH_DOLLAR_RE.finditer(retry_answer_text):
        if match.group(2):  # Has digit group
            value = _amount_to_number(*match.groups())
            all_amounts.append(value)

    if not all_amounts:
        return {"placement_ok": True}

    # Count how many times the corrected total appears in the answer
    matches_count = sum(1 for amount in all_amounts if abs(amount - corrected_total) <= tolerance)

    # SIGNAL 1: Multiple occurrences (definite corruption)
    if matches_count > 1:
        # The corrected total appears multiple times - at least one must be misplaced
        # (If the answer has both "Creative CX: $6.89M" AND "Total: $6.89M",
        #  the Creative CX line is the corruption)
        return {
            "placement_ok": False,
            "suspect_value": corrected_total,
            "actual_total": corrected_total,
            "matches_count": matches_count,
            "likely_corruption": (
                f"Corrected total ${corrected_total:,.2f} appears {matches_count} times "
                f"in retry answer (expected once, in summary line only). This is "
                f"implausible - the same value appearing as both an individual "
                f"line-item AND the grand total across {len(retrieved_rows)} rows "
                f"is a near-certain sign of misplacement (total spliced into "
                f"wrong location in addition to correct total line)."
            )
        }

    # SIGNAL 2: Single occurrence, but in suspicious context (line item, not summary)
    if matches_count == 1:
        # Find the ONE match and check its IMMEDIATE context (same line only)
        # If it appears next to a company/deal name (not a total-indicator phrase),
        # that's implausible: no single deal should equal aggregate of 100+ deals
        for match in _AMOUNT_WITH_DOLLAR_RE.finditer(retry_answer_text):
            if match.group(2):
                value = _amount_to_number(*match.groups())
                if abs(value - corrected_total) <= tolerance:
                    # Found the match - extract the LINE it's on (not 80 chars back)
                    # Find the start of the line (search backwards for newline)
                    line_start = retry_answer_text.rfind('\n', 0, match.start()) + 1
                    line_end = retry_answer_text.find('\n', match.end())
                    if line_end == -1:
                        line_end = len(retry_answer_text)
                    line = retry_answer_text[line_start:line_end]

                    # Check if THIS LINE contains company/deal name pattern
                    # Pattern: Capital letter + words + colon/dash IMMEDIATELY before $
                    import re as re_module
                    # Look for pattern at start of line, before the dollar amount
                    dollar_pos_in_line = match.start() - line_start
                    prefix = line[:dollar_pos_in_line]

                    # Check last 50 chars before $ for company name pattern
                    check_prefix = prefix[-50:] if len(prefix) > 50 else prefix
                    company_pattern = r'([A-Z][A-Za-z0-9\s&,\.]+?)(?::|\s—|\s-)\s*$'
                    context_match = re_module.search(company_pattern, check_prefix)

                    if context_match:
                        label = context_match.group(1).strip().lower()
                        # Exclude total-indicator phrases
                        TOTAL_INDICATORS = {"total", "overall", "grand", "sum", "net", "aggregate"}
                        if not any(indicator in label for indicator in TOTAL_INDICATORS):
                            # Suspicious: appears next to specific entity name, not summary
                            return {
                                "placement_ok": False,
                                "suspect_value": corrected_total,
                                "actual_total": corrected_total,
                                "matches_count": 1,
                                "suspicious_context": label,
                                "likely_corruption": (
                                    f"Corrected total ${corrected_total:,.2f} appears next to "
                                    f"specific entity name '{context_match.group(1).strip()}' "
                                    f"rather than in a summary/total line. This is implausible - "
                                    f"a single deal/company matching the aggregate total across "
                                    f"{len(retrieved_rows)} rows is a near-certain sign of "
                                    f"misplacement (model replaced line item instead of adding "
                                    f"separate summary)."
                                )
                            }
                    break  # Found and checked the one match

    # Total appears 0 times, or 1 time in valid context - OK
    return {"placement_ok": True}
