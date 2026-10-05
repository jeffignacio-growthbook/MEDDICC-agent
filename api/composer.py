"""
Plan-then-verify compositional layer.

Triggered when the assessor returns scope_mismatch — the question requires
combining outputs from multiple existing primitives that a single handler
can't produce as-asked.

Three-step lifecycle:
  1. decompose_question() — LLM breaks the question into named sub-parts,
     each mapped to an *existing* primitive handler (no new logic invented).
  2. plan_to_clarification_message() — plain Slack text showing the plan
     before execution, so the user can confirm or redirect.
  3. verify_plan_result() — checks that stated totals reconcile with parts;
     loops back to clarification on failure, never delivers a wrong answer.

All functions are pure (except decompose_question, which calls the LLM).
No new calculation logic is introduced here — sub-parts map to named
primitives and the word "_computed" marks arithmetic over those results.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AVAILABLE PRIMITIVES — derived, not hand-maintained
#
# This used to be a hardcoded list baked into _DECOMPOSE_PROMPT below, kept
# in sync with api/agent_loop.py::KNOWN_PRIMITIVES (the set run_agent_loop
# will actually accept for call_primitive) by hand. It drifted: this list
# named "query_rep_scorecard" (no such handler ever existed — the closest
# thing, scripts/rep_scorecard.py::assess_rep_scorecard, is an internal
# helper of query_quarter_health, never its own primitive) and omitted
# "query_rep_attainment" (the real, registered handler for quota-attainment
# questions). A plan naming the fake primitive sent run_agent_loop's
# call_primitive() to a name that doesn't exist, which fell back to a raw
# fetch_data/filter_table sum over deals.deal_value — see
# tests/test_composer_primitive_drift.py for the reconciliation that found
# this ("who's on track to hit quota?" producing $349,375/23% instead of
# the correct $520,060/33.6%).
#
# Fix: generate the prompt's primitive list from the SAME source
# api/agent_loop.py::KNOWN_PRIMITIVES already derives from
# (HANDLER_DESCRIPTIONS minus _NON_PRIMITIVE_INTENTS) — one registry, not
# two lists that can drift apart. A curated one-liner is kept for the
# handful of primitives most relevant to composer plans (same ones the
# original hand-written list covered, with the fake entry removed and
# query_rep_attainment added); any other primitive in KNOWN_PRIMITIVES gets
# a one-line description derived from its real HANDLER_DESCRIPTIONS entry.

# Curated one-liners for the primitives composer plans reach for most often.
# Anything in KNOWN_PRIMITIVES but not listed here still appears in the
# prompt — see _derive_description() below — just without hand-tuned prose.
_CURATED_PRIMITIVE_DESCRIPTIONS: dict[str, str] = {
    "query_pipeline_coverage": "active deal ARR vs quota for a period",
    "query_path_to_target": "remaining gap to close and pace",
    "query_waterfall": "bookings waterfall by category/week",
    "query_pipeline_movement": "deal stage change events in a window",
    "query_deals_at_risk": "at-risk deals with weak MEDDICC signals",
    "query_quarter_health": "composite quarter health summary",
    "query_win_loss": "win/loss reason breakdown",
    "query_rep_attainment": "rep-level quota attainment — won revenue vs target",
    "query_stage_lag": "time-in-stage distribution",
    "query_qualification_rate": "meeting-to-qualified crossing rate",
    "query_coaching_priorities": "coaching priorities — reps/deals needing attention",
}

# Sentinel values that may appear in the prompt's primitive list but are NOT
# themselves governed primitives, so they are never checked for
# getattr(handlers, name) callability and never asserted to be in
# KNOWN_PRIMITIVES (tests/test_composer_primitive_drift.py documents this).
_PRIMITIVE_LIST_SENTINELS: frozenset[str] = frozenset({"dynamic_query", "_computed"})


def _derive_description(name: str, handler_descriptions: dict) -> str:
    """One-line description for a primitive not in the curated map above.

    Takes HANDLER_DESCRIPTIONS[name] (full classifier-facing prose, often
    several sentences) and reduces it to a single short line: the first
    sentence, truncated, with newlines collapsed.
    """
    raw = (handler_descriptions.get(name) or "").replace("\n", " ")
    raw = " ".join(raw.split())  # collapse repeated whitespace
    first_sentence = raw.split(". ")[0].strip()
    if not first_sentence:
        first_sentence = f"see handler {name}"
    if len(first_sentence) > 110:
        first_sentence = first_sentence[:107].rstrip() + "..."
    return first_sentence


def _build_available_primitives_block() -> str:
    """Build the prompt's "AVAILABLE PRIMITIVES" lines from
    agent_loop.KNOWN_PRIMITIVES — the SAME governed set run_agent_loop's
    call_primitive() will accept — instead of a separately hand-maintained
    list. Every primitive named here is therefore guaranteed callable and
    guaranteed non-fake; the only two extra entries are the explicit
    sentinels "dynamic_query" (last-resort fallback) and "_computed"
    (arithmetic over other sub-parts), both documented as such and excluded
    from the drift test's callability check.
    """
    from api.agent_loop import KNOWN_PRIMITIVES
    from api.router import HANDLER_DESCRIPTIONS

    lines = []
    for name in sorted(KNOWN_PRIMITIVES):
        desc = _CURATED_PRIMITIVE_DESCRIPTIONS.get(name) or _derive_description(
            name, HANDLER_DESCRIPTIONS
        )
        lines.append(f"  {name:<30} - {desc}")
    lines.append(f"  {'dynamic_query':<30} - anything not covered above (last resort)")
    lines.append(f"  {'_computed':<30} - arithmetic over other sub-part results")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DECOMPOSE prompt

_DECOMPOSE_PROMPT = """You are a query planner for a CRO analytics system.

A question arrived that a single data handler cannot answer as-asked.
Your job is to break it into named sub-questions, each mapped to ONE
existing primitive from the list below. Do not invent new calculations.
Arithmetic over the sub-part results (e.g. ratio = A / B) is marked
with primitive "_computed".

AVAILABLE PRIMITIVES (map sub-parts only to these, or "_computed"):
{available_primitives}

Question: {question}
Handler that was tried (inadequate): {handler_used}

Respond with JSON only, no markdown:
{{
  "question": "<the original question, verbatim>",
  "explanation": "<one sentence: why this question needs multiple parts>",
  "sub_parts": [
    {{
      "name": "<short snake_case label>",
      "primitive": "<one of the primitives above>",
      "rationale": "<one sentence: what this part fetches or computes>"
    }}
  ]
}}

Rules:
- Use 2–4 sub-parts. More than 4 means you're over-decomposing.
- _computed parts must reference earlier sub-part names in their rationale.
- Never invent column names, table names, or SQL — only primitive names.
- If you cannot map a sub-part to any primitive, use "dynamic_query".
"""


# ---------------------------------------------------------------------------
# decompose_question()

async def decompose_question(
    question: str,
    handler_used: str,
    tool_results: dict,
    client: Any,
) -> dict:
    """
    Ask the LLM to break the question into sub-parts, each mapped to an
    existing primitive. Returns a plan dict.

    On any failure, returns a minimal plan with a single dynamic_query part
    so the caller always has something actionable.
    """
    try:
        resp = client.complete(
            max_tokens=600,
            system="Respond with valid JSON only. No markdown.",
            messages=[{"role": "user", "content":
                _DECOMPOSE_PROMPT.format(
                    question=question,
                    handler_used=handler_used,
                    available_primitives=_build_available_primitives_block(),
                )}]
        )
        plan = _extract_json(resp.text)
        if plan and _valid_plan(plan):
            return plan
        logger.warning("[COMPOSER] decompose returned invalid plan, using fallback")
    except Exception as e:
        logger.error(f"[COMPOSER] decompose_question failed: {e}")

    # Fallback — always actionable
    return {
        "question": question,
        "explanation": (
            "The question needs multiple data sources to answer correctly."
        ),
        "sub_parts": [
            {
                "name": "full_answer",
                "primitive": "dynamic_query",
                "rationale": (
                    f"Answer the full question via dynamic query because "
                    f"{handler_used} was insufficient."
                ),
            }
        ],
    }


# ---------------------------------------------------------------------------
# plan_to_clarification_message()

def plan_to_clarification_message(plan: dict) -> str:
    """
    Convert a decomposed plan into a plain-language Slack message asking
    the user to confirm before execution.
    """
    if not plan:
        return "I need to look up a few things to answer that — can you confirm this is about the current quarter?"

    question = plan.get("question", "your question")
    explanation = plan.get("explanation", "")
    sub_parts = plan.get("sub_parts") or []

    lines = []
    if explanation:
        lines.append(explanation)
    lines.append("")
    lines.append("To answer this correctly I'll need to pull:")
    for i, part in enumerate(sub_parts, 1):
        name = part.get("name", "").replace("_", " ")
        rationale = part.get("rationale", "")
        lines.append(f"  {i}. *{name}* — {rationale}")

    lines.append("")
    lines.append("Shall I go ahead? (Reply *yes* to run, or rephrase if this isn't what you meant.)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# verify_plan_result()

def verify_plan_result(plan: dict, parts_results: dict) -> tuple[bool, str]:
    """
    Check that the plan's results are internally consistent.
    Specifically: any sub-part marked primitive="_computed" that states
    a sum of other parts must reconcile (within 1%).

    Returns (ok: bool, reason: str).
    Never raises.
    """
    try:
        if not plan or not parts_results:
            return True, "no verification needed (empty plan or results)"
        ok, note = _sub_parts_sum_check(plan, parts_results)
        if not ok:
            return False, note
        return True, "verified"
    except Exception as e:
        logger.error(f"[COMPOSER] verify_plan_result error: {e}")
        return True, f"verification skipped: {e}"


def _sub_parts_sum_check(plan: dict, results: dict) -> tuple[bool, str]:
    """
    For each _computed sub-part whose rationale mentions 'A + B + ...',
    extract the referenced part names, sum their 'total' values from results,
    and compare to the _computed part's total.

    Returns (ok, note). Note is empty string when ok.
    Never raises.
    """
    try:
        if not plan or not results:
            return True, ""
        sub_parts = plan.get("sub_parts") or []
        # Index non-computed totals
        totals: dict[str, float] = {}
        for part in sub_parts:
            name = part.get("name", "")
            prim = part.get("primitive", "")
            if prim == "_computed":
                continue
            r = (results or {}).get(name, {})
            if isinstance(r, dict):
                v = r.get("total") or r.get("total_arr") or r.get("target")
                if isinstance(v, (int, float)):
                    totals[name] = float(v)

        # Check _computed parts
        for part in sub_parts:
            if part.get("primitive") != "_computed":
                continue
            name = part.get("name", "")
            rationale = part.get("rationale", "").lower()
            r = (results or {}).get(name, {})
            if not isinstance(r, dict):
                continue
            stated = r.get("total") or r.get("total_arr")
            if not isinstance(stated, (int, float)):
                continue
            # Only attempt sum-check for additive relationships.
            # A rationale that uses "/" or "*" references part names in the
            # text without implying their values should be summed — treating
            # coverage_ratio = pipeline / target as a sum would always flag
            # a false mismatch.  Skip verification for non-additive rationales.
            if "+" not in rationale:
                continue
            # Find referenced part names in rationale
            refs = [p["name"] for p in sub_parts
                    if p.get("primitive") != "_computed"
                    and p.get("name", "") in rationale]
            if not refs:
                continue
            if not all(ref in totals for ref in refs):
                continue
            computed = sum(totals[ref] for ref in refs)
            if computed == 0:
                continue
            ratio = abs(stated - computed) / abs(computed)
            if ratio > 0.01:
                return False, (
                    f"sum mismatch: {name} states {stated:,.0f} but "
                    f"{'+'.join(refs)} sums to {computed:,.0f} "
                    f"(diff {ratio*100:.1f}%)"
                )
        return True, ""
    except Exception as e:
        return True, f"sum check skipped: {e}"


# ---------------------------------------------------------------------------
# Pending-plan state (stored in thread history alongside pending_clarification)

PENDING_PLAN_ROLE = "pending_plan"


def make_pending_plan_entry(plan: dict, clarification_msg: str) -> dict:
    """Build the thread-history entry for a pending plan."""
    return {
        "role": PENDING_PLAN_ROLE,
        "content": json.dumps({
            "plan": plan,
            "clarification_msg": clarification_msg,
        }),
    }


def make_plan_cancelled_entry(clarification_msg: str = "cancelled") -> dict:
    """
    Build a plan-cancelled marker entry for thread history.
    plan=None signals 'no active plan' to find_pending_plan().
    Emitted by the router on any non-affirmation reply to a pending plan.
    """
    return {
        "role": PENDING_PLAN_ROLE,
        "content": json.dumps({
            "plan": None,
            "clarification_msg": clarification_msg,
        }),
    }


def find_pending_plan(history: list) -> dict | None:
    """
    Return the most-recent active pending_plan entry from thread history,
    or None.

    An entry with plan=None is a cancellation marker — it means no plan is
    active. find_pending_plan returns None in that case so the router does
    not attempt to execute a stale plan.
    """
    for entry in reversed(history or []):
        if entry.get("role") == PENDING_PLAN_ROLE:
            try:
                parsed = json.loads(entry["content"])
            except Exception:
                return None
            # plan=None is a cancellation marker — treat as no active plan
            if parsed.get("plan") is None:
                return None
            return parsed
    return None


def reply_affirms_plan(reply: str) -> bool:
    """Return True if the user's reply is a plain affirmation of the plan."""
    normalized = (reply or "").strip().lower()
    affirmations = {
        "yes", "y", "yeah", "yep", "yup", "sure", "go ahead",
        "go", "run it", "do it", "proceed", "ok", "okay", "sounds good",
    }
    return normalized in affirmations or normalized.startswith("yes")


# ---------------------------------------------------------------------------
# Helpers

def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                return json.loads(block)
            except Exception:
                continue
    for start in range(len(text)):
        if text[start] == '{':
            for end in range(len(text), start, -1):
                if text[end - 1] == '}':
                    try:
                        return json.loads(text[start:end])
                    except Exception:
                        continue
    return None


def _valid_plan(plan: dict) -> bool:
    """Basic structural check on a decomposed plan.

    Also rejects a plan naming a primitive outside the governed set (defense
    in depth against the LLM hallucinating a primitive name despite the
    prompt only listing real ones — see _build_available_primitives_block).
    A plan with one bad sub-part is rejected wholesale so decompose_question
    falls back to its dynamic_query-only plan rather than silently dropping
    the bad sub-part and running an incomplete one.
    """
    if not isinstance(plan, dict):
        return False
    sub_parts = plan.get("sub_parts")
    if not isinstance(sub_parts, list) or not sub_parts:
        return False
    try:
        from api.agent_loop import KNOWN_PRIMITIVES
        allowed = KNOWN_PRIMITIVES | _PRIMITIVE_LIST_SENTINELS
    except Exception:
        allowed = None  # import failure — skip the allow-list check, not structure
    for part in sub_parts:
        if not isinstance(part, dict):
            return False
        if not part.get("name") or not part.get("primitive"):
            return False
        if allowed is not None and part["primitive"] not in allowed:
            logger.warning(
                "[COMPOSER] plan named primitive %r outside KNOWN_PRIMITIVES — "
                "rejecting plan",
                part["primitive"],
            )
            return False
    return True
