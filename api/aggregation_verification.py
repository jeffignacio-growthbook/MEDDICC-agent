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


_AMOUNT_RE = re.compile(
    r"([+-]?)\$?([\d][\d,]*(?:\.\d+)?)\s*([KkMm])?\s*(won|lost)?", re.IGNORECASE
)


def _amount_to_number(sign: str, digits: str, mult: Optional[str], verb: Optional[str]) -> float:
    value = float(digits.replace(",", ""))
    if mult:
        value *= {"k": 1_000, "m": 1_000_000}[mult.lower()]
    if verb and verb.lower() == "lost":
        value = -abs(value)
    elif sign == "-":
        value = -abs(value)
    return value


_LABEL_LINE_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9 ,'\-]{0,40}?):\s*([^\n]+?)(?=(?:,\s*[A-Za-z][\w ,'\-]{0,40}?:|\n|$))"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _extract_total(answer_text: str) -> Optional[float]:
    """The first dollar amount in any sentence that mentions "total" —
    sentence-scoped (not a fixed character window) so ordinary phrasing
    ("Total pipeline movement this period was $20K.") isn't missed just
    because there are more than a few words between "total" and the
    figure."""
    for sentence in _SENTENCE_SPLIT_RE.split(answer_text):
        if re.search(r"\btotal\b", sentence, re.IGNORECASE):
            m = _AMOUNT_RE.search(sentence)
            if m and m.group(2):
                return _amount_to_number(*m.groups())
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
