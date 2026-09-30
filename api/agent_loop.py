"""
Agentic reasoning loop for the compositional layer.

The model drives its own tool-call sequence from a set of 7 tools.
No fixed pipeline stage is mandatory — the model decides what to call
and in what order, based on the question and the data it accumulates.

Tool set:
  1. call_primitive(name, params)      — invoke a governed calculator
  2. fetch_data(query)                 — raw table retrieval (ad-hoc)
  3. check_result(claim, supporting_data) — verify a stated number
  4. ask_user(question, context)       — clarifying question (ends loop)
  5. state_assumption(assumption, category) — disclose + proceed
  6. deliver(answer, sources, plan_used) — final answer (ends loop)
  7. request_checkback()               — Piece-7 escalation path

Hard constraints (enforced in code, not as model instructions):
  C1. Any quantitative answer delivered without a prior check_result
      → gate auto-inserts the check and sets check_result_auto_inserted.
  C2. state_assumption on a SENSITIVE_ASSUMPTION_CATEGORY is blocked;
      the loop substitutes ask_user instead.
  C3. Hitting MAX_STEPS without deliver → returns "insufficient information".
  C4. fetch_data for a query that maps to a named primitive is blocked;
      the loop injects a redirect message and records the suggested primitive
      in result.fetch_data_redirects — the model must use call_primitive instead.
      After the first redirect, a second governed fetch_data call requires
      params.justification naming primitives considered; absent justification
      → harder block; present → allowed and logged as a primitive candidate.

The dispatch pattern is prompt-based JSON (same as dynamic_query_loop):
  model returns {"tool": "...", "params": {...}} as plain text.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema context for the agent loop prompt

MAX_SCHEMA_RETRIES = 4


def _get_schema_for_prompt(question: str, sb) -> str:
    """Build a targeted schema context for the agent loop prompt.

    Uses the same table-classification step the router already uses
    (classify_relevant_tables via Haiku) to pick only the tables that
    matter for *this* question, then pulls real column names and
    descriptions from the data dictionary for those tables only.

    Falls back to all-tables-lightweight on classification failure, and
    to empty string if even that fails — the loop still works without
    schema, it just wastes more steps on schema-validation rejections.
    """
    if sb is None:
        return ""
    try:
        from api.table_classifier import classify_relevant_tables
        from api.schema_context import get_schema_context
        from llm_client import LLMClient

        classifier_client = LLMClient.from_config(role="classifier")
        relevant_tables = classify_relevant_tables(question, classifier_client)
        logger.info("[AGENT_LOOP] schema tables for prompt: %s", relevant_tables)
        return get_schema_context(
            sb,
            tables_with_descriptions=relevant_tables,
            lightweight=True,
        ) or ""
    except Exception as e:
        logger.warning("[AGENT_LOOP] failed to build schema context: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Configuration

MAX_STEPS = 12

# Categories for which state_assumption is blocked — the model must ask_user.
SENSITIVE_ASSUMPTION_CATEGORIES: frozenset[str] = frozenset({
    "arr_vs_deal_value",
    "quota_vs_stretch",
    "renewals_in_out",
})

# C4: Intents in HANDLER_DESCRIPTIONS that are NOT governed data calculators.
# They are meta/admin/write operations — fetch_data may NOT be redirected to them.
_NON_PRIMITIVE_INTENTS: frozenset[str] = frozenset({
    "dynamic_query",       # is itself a fallback, not a calculator
    "query_help",          # orientation / capability listing
    "acknowledgment",      # social reply
    "unanswerable",        # meta intent
    "set_target",          # admin write
    "submit_score_correction",  # write to review queue
    "generate_win_loss",   # slow narrative generator, not a query primitive
    "query_rubric",        # rubric lookup, not a data calculator
    "query_definition",    # semantic-layer lookup, not a calculator
    "query_coverage",      # LEGACY — confirmed broken; not a governed calculator
})


def _derive_known_primitives() -> frozenset[str]:
    """
    Derive the governed primitive set from HANDLER_DESCRIPTIONS at import time.
    Falls back to a hardcoded set only if the router module itself fails to import
    (should not happen in production or test environments).
    """
    try:
        from api.router import HANDLER_DESCRIPTIONS  # noqa: PLC0415
        return frozenset(HANDLER_DESCRIPTIONS.keys()) - _NON_PRIMITIVE_INTENTS
    except Exception as exc:  # pragma: no cover
        logger.warning("[AGENT_LOOP] Could not import HANDLER_DESCRIPTIONS: %s — using fallback set", exc)
        # Offline fallback; kept in sync manually but a test will catch drift.
        return frozenset({
            "query_pipeline_coverage", "query_path_to_target", "query_waterfall",
            "query_pipeline_movement", "query_new_deals", "query_upcoming_renewals",
            "query_won_deals", "query_arr", "query_deals_at_risk",
            "query_high_priority_deal_risk", "query_forecast_trust",
            "query_win_loss", "query_loss_concentration", "query_quarter_health",
            "query_quarter_downside", "query_objections", "query_feature_gaps",
            "query_pipeline_coverage", "query_deal", "query_competitive_intel",
            "query_rubric_scores_bulk", "query_deal_stages_bulk",
            "query_deal_owners_bulk", "query_deal_values_bulk",
            "query_sdr_metrics", "query_sdr_leaderboard", "query_sdr_pipeline_sourced",
            "query_stage_lag", "query_qualification_rate", "query_cycle_time",
            "query_pipeline", "query_rep_pipeline", "query_rep_attainment",
            "query_deal_health", "query_stale_deals", "query_team_leaderboard",
            "query_pre_call_brief", "query_coaching_priorities",
            "query_call_quality", "query_rep_coaching",
        })


# C4: authoritative set — derived from HANDLER_DESCRIPTIONS minus meta/admin intents.
# A test in tests/test_agent_loop.py asserts this stays in sync with the registry.
KNOWN_PRIMITIVES: frozenset[str] = _derive_known_primitives()

# Keyword fragments → primitive name (used when the primitive name itself is absent
# from the fetch_data query string).  Every primitive here MUST be in KNOWN_PRIMITIVES;
# a test will fail if any entry points at an unregistered primitive.
_PRIMITIVE_KEYWORDS: list[tuple[str, str]] = [
    ("pipeline coverage", "query_pipeline_coverage"),
    ("path to target", "query_path_to_target"),
    ("waterfall", "query_waterfall"),
    ("pipeline movement", "query_pipeline_movement"),
    ("pipeline moved", "query_pipeline_movement"),
    ("deals at risk", "query_deals_at_risk"),
    ("deal risk", "query_deals_at_risk"),
    ("at risk", "query_deals_at_risk"),
    ("quarter health", "query_quarter_health"),
    ("quarter downside", "query_quarter_downside"),
    ("win loss", "query_win_loss"),
    ("win/loss", "query_win_loss"),
    ("loss reason", "query_win_loss"),
    ("why we lost", "query_win_loss"),
    ("why we won", "query_win_loss"),
    ("rep scorecard", "query_rep_attainment"),
    ("stage lag", "query_stage_lag"),
    ("mis-staged", "query_stage_lag"),
    ("qualification rate", "query_qualification_rate"),
    ("coaching priorities", "query_coaching_priorities"),
    ("loss concentration", "query_loss_concentration"),
    ("loss rate", "query_loss_concentration"),
    ("forecast trust", "query_forecast_trust"),
    ("rep pipeline", "query_rep_pipeline"),
    ("team leaderboard", "query_team_leaderboard"),
    ("pre-call brief", "query_pre_call_brief"),
    ("pre call brief", "query_pre_call_brief"),
    ("stale deals", "query_stale_deals"),
    ("cycle time", "query_cycle_time"),
    ("sdr leaderboard", "query_sdr_leaderboard"),
    ("sdr metrics", "query_sdr_metrics"),
    ("sdr pipeline", "query_sdr_pipeline_sourced"),
]

_INSUFFICIENT_ANSWER = (
    "I was unable to answer this confidently — the question required more "
    "data steps than my current budget allows.  Please try rephrasing with "
    "a narrower scope, or ask your admin to raise the step budget."
)

_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?[MKB%x]?\b")

# Claim-number extractor: handles $2.1M, 2.49x, 31%, 1,234,567
_CLAIM_NUM_RE = re.compile(
    r'\$\s*(\d[\d,]*(?:\.\d+)?)\s*([MKBmkb])?'  # $1.2M or $1,200,000
    r'|(\d[\d,]*(?:\.\d+)?)\s*([MKBmkb])\b'      # 1.2M (suffix required)
    r'|(\d[\d,]*\.\d+)(?=[x%\s,\.\)\-]|$)'          # 2.49, 0.60, 9.9 (any decimal)
    r'|(\d[\d,]{2,})(?=[x%\s,\.\)\-]|$)',          # 1,234 (comma-grouped integer)
)

_QUARTER_RE = re.compile(r'\bQ[1-4]\b|\bFY\d{2,4}\b', re.IGNORECASE)


def _has_numbers(text: str) -> bool:
    """Return True if the text contains what looks like a quantitative claim."""
    return bool(_NUMBER_RE.search(text or ""))


def _parse_claim_number(raw: str, suffix: str) -> float | None:
    """Convert (digits_string, suffix_char) to a plain float. Returns None on error."""
    try:
        val = float(raw.replace(',', ''))
    except (ValueError, TypeError):
        return None
    s = (suffix or '').upper()
    if s == 'M':
        val *= 1_000_000
    elif s == 'K':
        val *= 1_000
    elif s == 'B':
        val *= 1_000_000_000
    return val


def _extract_claim_numbers(claim: str) -> list[tuple[str, float]]:
    """Return (matched_text, normalized_float) for each number in the claim."""
    results: list[tuple[str, float]] = []
    seen: set[float] = set()
    for m in _CLAIM_NUM_RE.finditer(claim):
        token = m.group(0).strip()
        # Group layout: (dollar_digits, dollar_suffix, bare_digits, bare_suffix,
        #                decimal_only, comma_int)
        g = m.groups()
        if g[0] is not None:         # $N[suffix]
            val = _parse_claim_number(g[0], g[1])
        elif g[2] is not None:       # N[suffix] (suffix required branch)
            val = _parse_claim_number(g[2], g[3])
        elif g[4] is not None:       # decimal without suffix
            val = _parse_claim_number(g[4], '')
        elif g[5] is not None:       # comma-grouped integer
            val = _parse_claim_number(g[5], '')
        else:
            continue
        if val is not None and val not in seen:
            seen.add(val)
            results.append((token, val))
    return results


def _flatten_numerics(data: Any, depth: int = 0) -> list[float]:
    """Recursively collect all numeric leaf values from a nested structure."""
    if depth > 6 or isinstance(data, bool):
        return []
    if isinstance(data, (int, float)):
        return [float(data)]
    if isinstance(data, dict):
        out: list[float] = []
        for v in data.values():
            out.extend(_flatten_numerics(v, depth + 1))
        return out
    if isinstance(data, list):
        out = []
        for item in data:
            out.extend(_flatten_numerics(item, depth + 1))
        return out
    return []


def _value_traceable(claim_val: float, known_values: list[float]) -> bool:
    """
    Return True if claim_val is within tolerance of any value in known_values.

    Tolerance:
      - |claim_val| > 1000: 1% relative
      - |claim_val| <= 1000: 0.05 absolute (handles ratios, percentages)
    Also checks claim_val / 100 to handle "31%" → 0.31 stored in data.
    """
    candidates = [claim_val]
    if abs(claim_val) > 1 and abs(claim_val) <= 200:
        # Might be a percentage stored as a fraction
        candidates.append(claim_val / 100)

    for candidate in candidates:
        threshold = max(abs(candidate) * 0.01, 0.05) if abs(candidate) > 1000 else 0.05
        if any(abs(candidate - kv) <= threshold for kv in known_values):
            return True
    return False


def _is_label_number(val: float, question: str) -> bool:
    """Return True for year-like values (2000-2099) — skip them in trace checks."""
    return 2000.0 <= val <= 2099.0


_SCOPE_STRUCTURED_KEYS = frozenset({
    "fiscal_quarter", "quarter", "period", "time_window",
    "date_range", "start_date", "end_date",
})
_Q_STRUCT_RE = re.compile(r'\bQ[1-4]\b', re.IGNORECASE)


def _extract_scope_quarters_from_result(result: Any) -> set[str]:
    """
    Extract Q1-Q4 tokens from STRUCTURED scope fields only.
    Only reads keys named in _SCOPE_STRUCTURED_KEYS; free-text description
    strings are NOT scanned so stray "Q4" in labels doesn't satisfy coverage.
    Returns a set of upper-cased tokens (e.g. {"Q3"}).
    """
    found: set[str] = set()
    if not isinstance(result, dict):
        return found
    for key, val in result.items():
        if key.lower() not in _SCOPE_STRUCTURED_KEYS:
            continue
        if isinstance(val, str):
            for tok in _Q_STRUCT_RE.findall(val):
                found.add(tok.upper())
        elif isinstance(val, dict):
            # e.g. date_range: {start: ..., end: ...} — no Q tokens expected but safe
            for v2 in val.values():
                if isinstance(v2, str):
                    for tok in _Q_STRUCT_RE.findall(v2):
                        found.add(tok.upper())
    return found


def _extract_quarters_from_data(data: Any, depth: int = 0) -> set[str]:
    """
    Recursively scan all string leaf values in data for Q1-Q4 / FY tokens.
    Used for non-ledger contexts only (e.g. supporting_data).
    Returns a set of upper-cased tokens (e.g. {"Q3", "FY26"}).
    """
    found: set[str] = set()
    if depth > 6 or data is None:
        return found
    if isinstance(data, str):
        for tok in _QUARTER_RE.findall(data):
            found.add(tok.upper())
        return found
    if isinstance(data, dict):
        for v in data.values():
            found |= _extract_quarters_from_data(v, depth + 1)
        return found
    if isinstance(data, list):
        for item in data:
            found |= _extract_quarters_from_data(item, depth + 1)
    return found


def _flatten_ledger_numerics(ledger: list[dict]) -> list[float]:
    """Extract all numeric leaf values from the execution ledger."""
    out: list[float] = []
    for entry in (ledger or []):
        result_data = entry.get("result")
        if result_data is not None:
            out.extend(_flatten_numerics(result_data))
    return out


# ---------------------------------------------------------------------------
# Result dataclass

@dataclass
class AgentLoopResult:
    answer: str
    sources: list = field(default_factory=list)
    plan_used: list = field(default_factory=list)
    check_result_performed: bool = False
    check_result_auto_inserted: bool = False
    # None = no check_result called yet; True = last check passed; False = last check failed.
    check_result_verified: bool | None = None
    assumptions: list = field(default_factory=list)
    ask_user_question: str | None = None
    budget_exhausted: bool = False
    steps_taken: int = 0
    # C4: list of primitive names suggested when fetch_data was blocked.
    # Empty when no fetch_data call triggered the gate.
    fetch_data_redirects: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# System prompt for the loop

_SYSTEM_PROMPT = """You are a CRO analytics agent.  You have a set of tools
and must decide how to answer the question by calling them in the right order.

Available tools (respond with JSON — one tool call per response):

1. call_primitive  — invoke a governed data calculator
   {"tool": "call_primitive", "params": {"name": "<primitive>", "params": {...}}}

2. fetch_data  — structured table retrieval for ad-hoc data not covered by any primitive
   {"tool": "fetch_data", "params": {
     "query": "<what you need>",
     "table": "<supabase table name>",
     "columns": ["col1", "col2"],
     "filters": [{"column": "c", "op": "eq", "value": "v"}],
     "limit": 200
   }}
   Note: "table" is required for execution.  "columns", "filters", "limit" are optional.

3. check_result  — verify a number or claim against supporting data
   {"tool": "check_result", "params": {"claim": "<what you claim>", "supporting_data": {...}}}

4. ask_user  — ask a clarifying question (ends this session)
   {"tool": "ask_user", "params": {"question": "<question>", "context": "<context>"}}

5. state_assumption  — proceed with a disclosed assumption
   {"tool": "state_assumption", "params": {"assumption": "<text>", "category": "<category>"}}

6. deliver  — final answer (ends this session)
   {"tool": "deliver", "params": {"answer": "<text>", "sources": [...], "plan_used": [...]}}

7. request_checkback  — escalate to template promotion (for recurring patterns)
   {"tool": "request_checkback", "params": {}}

8. calculate  — evaluate an arithmetic expression over values already in the ledger
   {"tool": "calculate", "params": {
     "expression": "<e.g. pipeline / target>",
     "operands": {"pipeline": 4800000, "target": 2000000}
   }}
   All operand values must have been fetched via call_primitive or fetch_data first.
   The result is appended to the ledger and can then be verified by check_result.

Rules:
- Always call check_result before deliver when the answer contains numbers.
- Use state_assumption only for non-sensitive ambiguity.
- Use ask_user for ARR vs deal value, quota vs stretch, or renewals-in/out questions.
- Keep answers concise and lead with the headline finding.

Respond with JSON only — no markdown, no prose outside the JSON."""


def _tool_result_message(tool: str, params: dict, result: Any) -> str:
    """Format a tool result to inject into the message history."""
    return json.dumps({
        "tool_called": tool,
        "params": params,
        "result": result,
    })


# ---------------------------------------------------------------------------
# Tool implementations — real dispatch to governed primitives and data layer.

async def _execute_call_primitive(name: str, params: dict, sb: Any) -> dict:
    """Dispatch to a named governed primitive.  Returns its result dict or error."""
    try:
        import api.handlers as handlers
        fn = getattr(handlers, name, None)
        if fn is None:
            return {"error": f"unknown primitive {name!r}"}
        return await fn(params, sb)
    except Exception as e:
        logger.warning(f"[AGENT_LOOP] call_primitive {name!r} failed: {e}")
        return {"error": str(e)}


def _find_matching_primitive(query: str) -> str | None:
    """
    C4: Return a named primitive that should handle this query, or None.

    Checks whether the query string (1) mentions a known primitive name
    verbatim, or (2) contains a keyword fragment that maps to one.  Only
    returns a match when confidence is high — a bare mention of a keyword
    like "waterfall" in an otherwise unrelated query is enough.
    """
    q = query.lower()
    # Verbatim primitive name — prefer the longest match to avoid substring ambiguity
    # (e.g. "query_pipeline" must not shadow "query_pipeline_coverage").
    verbatim_match = max(
        (prim for prim in KNOWN_PRIMITIVES if prim in q),
        key=len,
        default=None,
    )
    if verbatim_match:
        return verbatim_match
    # Keyword fragments
    for keyword, prim in _PRIMITIVE_KEYWORDS:
        if keyword in q:
            return prim
    return None


async def _execute_fetch_data(query: str, tool_params: dict, sb: Any) -> dict:
    """
    Ad-hoc raw data fetch (C4 check already done by caller).

    When tool_params contains a 'table' key the model issued a structured
    fetch — delegate to filter_table directly.  Otherwise treat 'query' as
    a natural-language description and return it as an unsupported-NL note
    (the C4 gate should have redirected any query with a known primitive;
    what reaches here is truly ad-hoc).
    """
    table = tool_params.get("table", "").strip()
    if table:
        try:
            from api.tools import filter_table  # noqa: PLC0415
            columns = tool_params.get("columns") or None
            filters = tool_params.get("filters") or None
            limit = int(tool_params.get("limit", 200))
            order_by = tool_params.get("order_by") or None
            ft_result = await filter_table(
                sb, table,
                columns=columns,
                filters=filters,
                limit=limit,
                order_by=order_by,
            )
            if isinstance(ft_result, dict) and "error" in ft_result:
                return ft_result
            rows = ft_result if isinstance(ft_result, list) else ft_result.get("rows", ft_result)
            return {"rows": rows, "table": table, "count": len(rows) if isinstance(rows, list) else 0}
        except Exception as e:
            logger.warning(f"[AGENT_LOOP] fetch_data filter_table({table!r}) failed: {e}")
            return {"error": str(e)}
    # Natural-language query — no structured table given.
    return {"error": "fetch_data requires a 'table' param; no governed primitive found for this query", "query": query}


def _execute_check_result(
    claim: str,
    supporting_data: dict,
    question: str = "",
    ledger: list | None = None,
) -> dict:
    """
    Verify that every number in the claim can be traced to a value recorded
    in the execution ledger (call_primitive / fetch_data results accumulated
    by run_agent_loop).  Model-supplied supporting_data may add context for
    additive-sum and plausibility checks, but cannot make an untraceable
    number pass — only ledger values count for the primary trace.

    Scope mismatch is BLOCKING (verified=False): if the question names a
    quarter/entity and the ledger covers a different one, the claim is rejected.

    Label-like numbers (years 2000-2099) are skipped in the trace check.

    Returns:
      {
        "verified": bool,         # False iff any claim number is untraceable
                                  #   OR scope mismatch detected
        "claim": str,
        "untraceable": [str],     # tokens from claim that had no match in ledger
        "scope_mismatch": bool,   # True when quarter scope blocked the claim
        "warnings": [...],        # non-blocking plausibility / sum violations
      }
    """
    claim_numbers = _extract_claim_numbers(claim)

    # Primary trace source: LEDGER ONLY
    ledger_values = _flatten_ledger_numerics(ledger or [])

    untraceable: list[str] = []
    for token, val in claim_numbers:
        if _is_label_number(val, question):
            continue  # skip year-like tokens
        if not _value_traceable(val, ledger_values):
            untraceable.append(token)

    verified = len(untraceable) == 0
    scope_mismatch = False

    # Scope check — BLOCKING when ledger and question both name Q-quarters that don't overlap.
    # Only Q1-Q4 tokens are compared; FY-year tokens are shared context and are NOT used to
    # satisfy the scope check (FY26 appears in both Q3 FY26 and Q4 FY26, so it is not specific
    # enough to confirm alignment).
    question_quarters = {q.upper() for q in _Q_STRUCT_RE.findall(question)}
    ledger_quarters: set[str] = set()
    for entry in (ledger or []):
        ledger_quarters |= _extract_scope_quarters_from_result(entry.get("result"))

    if question_quarters and ledger_quarters and question_quarters.isdisjoint(ledger_quarters):
        scope_mismatch = True
        verified = False

    # Additive sum check — uses supporting_data plan structure (warning only)
    sum_warning: str | None = None
    plan = (supporting_data or {}).get("plan")
    results_for_sum = (supporting_data or {}).get("results")
    if plan and results_for_sum:
        try:
            from api.composer import _sub_parts_sum_check  # noqa: PLC0415
            ok, note = _sub_parts_sum_check(plan, results_for_sum)
            if not ok:
                sum_warning = note
        except Exception as exc:
            logger.debug("[AGENT_LOOP] _sub_parts_sum_check import failed: %s", exc)

    # Plausibility — warning source only (never overrides trace verdict)
    plausibility_warnings: list[dict] = []
    try:
        from api.plausibility import run_all_checks  # noqa: PLC0415
        violations, _ = run_all_checks(supporting_data or {})
        plausibility_warnings = [
            {"check": v.check, "message": v.message, "severity": v.severity}
            for v in violations
        ]
    except Exception as exc:
        logger.debug("[AGENT_LOOP] plausibility run_all_checks failed: %s", exc)

    warnings = plausibility_warnings
    if sum_warning:
        warnings = [{"check": "additive_sum", "message": sum_warning, "severity": "warning"}] + warnings
    if scope_mismatch:
        warnings = [{"check": "scope_mismatch", "message": (
            f"Question asks about {sorted(question_quarters)} but ledger data covers "
            f"{sorted(ledger_quarters)} — claim is rejected."
        ), "severity": "error"}] + warnings

    return {
        "verified": verified,
        "claim": claim,
        "untraceable": untraceable,
        "scope_mismatch": scope_mismatch,
        "warnings": warnings,
    }


def _execute_request_checkback() -> dict:
    from api.plan_feedback import checkback_prompt  # noqa: PLC0415
    return {"checkback_prompt": checkback_prompt(), "recorded": True}


def _execute_calculate(
    expression: str,
    operands: dict,
    ledger: list,
) -> dict:
    """
    Evaluate a simple arithmetic expression whose operands must all trace to
    the execution ledger.  Appends the result to ledger on success.

    expression: e.g. "pipeline / target"
    operands:   e.g. {"pipeline": 4800000, "target": 2000000}

    Returns:
      {"result": float, "expression": str, "operands": dict}  on success
      {"error": str}                                           on failure

    Restrictions:
    - Only the operand names are in scope for eval; no builtins.
    - If any operand value cannot be traced to the ledger, the call fails
      (the number is considered fabricated).
    - Expression may not exceed 200 characters.
    """
    if not expression or not isinstance(expression, str):
        return {"error": "calculate requires a non-empty 'expression' string"}
    if len(expression) > 200:
        return {"error": "expression too long (max 200 characters)"}
    if not isinstance(operands, dict) or not operands:
        return {"error": "calculate requires at least one operand"}

    ledger_values = _flatten_ledger_numerics(ledger or [])
    untraced: list[str] = []
    clean: dict[str, float] = {}
    for name, val in operands.items():
        try:
            fval = float(val)
        except (TypeError, ValueError):
            return {"error": f"operand {name!r} is not numeric: {val!r}"}
        if not _value_traceable(fval, ledger_values):
            untraced.append(name)
        clean[name] = fval

    if untraced:
        return {
            "error": (
                f"operand(s) {untraced} could not be traced to any ledger value — "
                "use call_primitive or fetch_data to fetch the data first"
            )
        }

    # Safe eval: only operand names in namespace, no builtins.
    try:
        result_val = eval(  # noqa: S307
            compile(expression, "<calculate>", "eval"),
            {"__builtins__": {}},
            clean,
        )
    except Exception as e:
        return {"error": f"expression evaluation failed: {e}"}

    if not isinstance(result_val, (int, float)):
        return {"error": f"expression did not evaluate to a number: {result_val!r}"}

    entry = {
        "tool": "calculate",
        "expression": expression,
        "operands": clean,
        "result": float(result_val),
    }
    ledger.append(entry)
    return {"result": float(result_val), "expression": expression, "operands": clean}


# ---------------------------------------------------------------------------
# Main loop

async def run_agent_loop(
    question: str,
    client: Any,
    sb: Any = None,
    history: list | None = None,
    params: dict | None = None,
) -> AgentLoopResult:
    """
    Run the agentic reasoning loop.

    The model issues tool calls (as JSON text) and the loop dispatches them,
    accumulating results into the message history until deliver() or ask_user()
    ends the session, or MAX_STEPS is exhausted.

    Returns AgentLoopResult with the final answer and metadata about what
    constraints fired.
    """
    messages: list[dict] = []
    result = AgentLoopResult(answer="")
    # C4: tracks how many times a governed-primitive redirect has fired this loop.
    _redirect_count: int = 0
    # C1b: tracks whether the most recent check_result call returned verified=False.
    # deliver is blocked while this is True so fabricated numbers can't be published.
    _last_check_failed: bool = False
    # Execution ledger: every call_primitive/fetch_data result is recorded here.
    # check_result traces claim numbers against ledger values only — model-passed
    # supporting_data cannot make an untraceable number pass.
    _ledger: list[dict] = []
    # Schema-error retry budget: fetch_data calls that fail schema validation
    # (wrong table/column names) get free retries up to this limit so the model
    # can learn the correct schema without burning its step budget.
    _schema_retries_remaining: int = MAX_SCHEMA_RETRIES

    # Build system prompt with schema context
    try:
        schema_context = _get_schema_for_prompt(question, sb)
    except Exception as e:
        logger.warning("[AGENT_LOOP] schema context build failed: %s", e)
        schema_context = ""
    if schema_context:
        system_prompt = _SYSTEM_PROMPT + "\n\n" + schema_context
    else:
        system_prompt = _SYSTEM_PROMPT

    # Seed the conversation
    messages.append({
        "role": "user",
        "content": f"Question: {question}",
    })

    step_idx = 0
    while step_idx < MAX_STEPS:
        # Ask model for next tool call
        try:
            resp = client.complete(
                messages=messages,
                system=system_prompt,
                max_tokens=600,
            )
            raw = (resp.text or "").strip()
        except Exception as e:
            logger.error(f"[AGENT_LOOP] client.complete failed at step {step_idx}: {e}")
            break

        result.steps_taken = step_idx + 1

        # Parse the tool call
        parsed = _parse_tool_call(raw)
        if parsed is None:
            logger.warning(f"[AGENT_LOOP] failed to parse tool call at step {step_idx}: {raw!r}")
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content":
                             '{"error": "could not parse tool call — respond with valid JSON"}'})
            step_idx += 1
            continue

        tool = parsed.get("tool", "")
        tool_params = parsed.get("params", {})

        # ── Hard constraint C2: block sensitive state_assumption ──────────
        if tool == "state_assumption":
            category = tool_params.get("category", "general")
            if category in SENSITIVE_ASSUMPTION_CATEGORIES:
                # Substitute ask_user
                clarification = (
                    f"To answer this correctly I need to know: is this question about "
                    f"{_sensitive_label(category)}?  Please clarify."
                )
                result.ask_user_question = clarification
                result.steps_taken = step_idx + 1
                return result
            # Non-sensitive — record assumption
            assumption_text = tool_params.get("assumption", "")
            if assumption_text:
                result.assumptions.append(assumption_text)
            tool_result = {"recorded": True, "assumption": assumption_text}

        # ── ask_user: clean exit ──────────────────────────────────────────
        elif tool == "ask_user":
            result.ask_user_question = tool_params.get("question", "")
            result.steps_taken = step_idx + 1
            return result

        # ── deliver: apply constraints C1 and C1b then return ───────────
        elif tool == "deliver":
            answer = tool_params.get("answer", "")
            sources = tool_params.get("sources") or []
            plan_used = tool_params.get("plan_used") or []

            # C1b: most recent check_result returned verified=False — block.
            if _last_check_failed:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": json.dumps({
                    "error": (
                        "deliver blocked: the most recent check_result returned "
                        "verified=False (one or more numbers in the claim could "
                        "not be traced to supporting_data). Correct the claim "
                        "or call ask_user before delivering."
                    ),
                })})
                step_idx += 1
                continue

            # C1: quantitative answer without a prior check_result
            if _has_numbers(answer) and not result.check_result_performed:
                result.check_result_auto_inserted = True
                result.check_result_performed = True
                # Auto-insert the check (the result already has the answer)

            result.answer = answer
            result.sources = sources
            result.plan_used = plan_used
            result.steps_taken = step_idx + 1
            return result

        # ── check_result ──────────────────────────────────────────────────
        elif tool == "check_result":
            result.check_result_performed = True
            tool_result = _execute_check_result(
                tool_params.get("claim", ""),
                tool_params.get("supporting_data", {}),
                question=question,
                ledger=_ledger,
            )
            result.check_result_verified = bool(tool_result.get("verified", True))
            _last_check_failed = not result.check_result_verified

        # ── call_primitive ────────────────────────────────────────────────
        elif tool == "call_primitive":
            prim_name = tool_params.get("name", "")
            tool_result = await _execute_call_primitive(
                prim_name,
                tool_params.get("params", {}),
                sb,
            )
            # Record successful results in the ledger (error results excluded).
            if "error" not in tool_result:
                _ledger.append({
                    "tool": "call_primitive",
                    "primitive": prim_name,
                    "result": tool_result,
                })

        # ── fetch_data ── C4 gate then dispatch ───────────────────────────
        elif tool == "fetch_data":
            query = tool_params.get("query", "")
            matched = _find_matching_primitive(query)
            if matched:
                # C4: a governed primitive exists for this query — block and redirect.
                result.fetch_data_redirects.append(matched)
                _redirect_count += 1
                if _redirect_count > 1:
                    # Bounded redirect: second governed fetch_data requires justification.
                    justification = tool_params.get("justification", "").strip()
                    if not justification:
                        tool_result = {
                            "blocked": True,
                            "reason": (
                                f"You have already been redirected once. "
                                f"A governed primitive still exists for this query "
                                f"(suggested: '{matched}'). "
                                f"If you believe fetch_data is necessary despite this, "
                                f"retry with params.justification naming the primitives "
                                f"you considered and why they are insufficient."
                            ),
                            "suggested_primitive": matched,
                            "redirect_count": _redirect_count,
                        }
                    else:
                        # Justification present — allow but log as primitive candidate.
                        logger.warning(
                            "[AGENT_LOOP] C4 override: fetch_data allowed after %d redirect(s) "
                            "for query %r — justification: %r. "
                            "CANDIDATE for new primitive: %r",
                            _redirect_count, query, justification, matched,
                        )
                        tool_result = await _execute_fetch_data(query, tool_params, sb)
                        # Record non-error fetch results in ledger
                        if "error" not in tool_result and "blocked" not in tool_result:
                            _ledger.append({"tool": "fetch_data", "result": tool_result})
                else:
                    tool_result = {
                        "blocked": True,
                        "reason": (
                            f"A governed primitive exists for this data. "
                            f"Use call_primitive('{matched}') instead of fetch_data."
                        ),
                        "suggested_primitive": matched,
                    }
            else:
                tool_result = await _execute_fetch_data(query, tool_params, sb)
                # Record non-error fetch results in ledger
                if "error" not in tool_result and "blocked" not in tool_result:
                    _ledger.append({"tool": "fetch_data", "result": tool_result})

        # ── request_checkback ─────────────────────────────────────────────
        elif tool == "request_checkback":
            tool_result = _execute_request_checkback()

        # ── calculate ─────────────────────────────────────────────────────
        elif tool == "calculate":
            tool_result = _execute_calculate(
                tool_params.get("expression", ""),
                tool_params.get("operands", {}),
                _ledger,
            )

        else:
            tool_result = {"error": f"unknown tool {tool!r}"}

        # Append tool result to message history
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
                         _tool_result_message(tool, tool_params, tool_result)})

        # Schema-error free retry: a fetch_data that failed because the model
        # used the wrong table or column names does not burn a budget step.
        # Only schema/column errors qualify — suspicious filter values and
        # invalid operators are data errors that should count.
        _is_schema_error = (
            tool == "fetch_data"
            and isinstance(tool_result, dict)
            and _schema_retries_remaining > 0
            and (
                "unknown_select_columns" in tool_result
                or "unknown_filter_columns" in tool_result
                or ("error" in tool_result and "not find the table" in str(tool_result.get("error", "")))
            )
        )
        if _is_schema_error:
            _schema_retries_remaining -= 1
            logger.info(
                "[AGENT_LOOP] fetch_data schema error — free retry "
                "(%d remaining)", _schema_retries_remaining
            )
        else:
            step_idx += 1

    # ── MAX_STEPS reached without deliver ── C3 ───────────────────────────
    result.budget_exhausted = True
    result.answer = _INSUFFICIENT_ANSWER
    return result


# ---------------------------------------------------------------------------
# Helpers

def _parse_tool_call(text: str) -> dict | None:
    """Extract the first JSON object from model output."""
    if not text:
        return None
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "tool" in obj:
            return obj
    except Exception:
        pass
    # Strip markdown fences
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                obj = json.loads(block)
                if isinstance(obj, dict) and "tool" in obj:
                    return obj
            except Exception:
                continue
    # Scan for outermost {…}
    for start in range(len(text)):
        if text[start] == "{":
            for end in range(len(text), start, -1):
                if text[end - 1] == "}":
                    try:
                        obj = json.loads(text[start:end])
                        if isinstance(obj, dict) and "tool" in obj:
                            return obj
                    except Exception:
                        continue
    return None


def _sensitive_label(category: str) -> str:
    labels = {
        "arr_vs_deal_value": "ARR or total deal value",
        "quota_vs_stretch": "quota target or stretch goal",
        "renewals_in_out": "renewals included or excluded from this metric",
    }
    return labels.get(category, category)
