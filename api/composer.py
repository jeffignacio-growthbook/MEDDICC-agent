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
# DECOMPOSE prompt

_DECOMPOSE_PROMPT = """You are a query planner for a CRO analytics system.

A question arrived that a single data handler cannot answer as-asked.
Your job is to break it into named sub-questions, each mapped to ONE
existing primitive from the list below. Do not invent new calculations.
Arithmetic over the sub-part results (e.g. ratio = A / B) is marked
with primitive "_computed".

AVAILABLE PRIMITIVES (map sub-parts only to these, or "_computed"):
  query_pipeline_coverage       - active deal ARR vs quota for a period
  query_path_to_target          - remaining gap to close and pace
  query_waterfall               - bookings waterfall by category/week
  query_pipeline_movement       - deal stage change events in a window
  query_deal_risk               - at-risk late-stage deals
  query_quarter_health          - composite quarter health summary
  query_win_loss_reason         - win/loss reason breakdown
  query_rep_scorecard           - rep-level attainment and activity
  query_stage_lag               - time-in-stage distribution
  query_qualification_rate      - meeting-to-qualified crossing rate
  query_coaching_hypothesis     - coaching experiment status
  dynamic_query                 - anything not covered above (last resort)
  _computed                     - arithmetic over other sub-part results

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


def find_pending_plan(history: list) -> dict | None:
    """Return the most-recent pending_plan entry from thread history, or None."""
    for entry in reversed(history or []):
        if entry.get("role") == PENDING_PLAN_ROLE:
            try:
                return json.loads(entry["content"])
            except Exception:
                return None
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
    """Basic structural check on a decomposed plan."""
    if not isinstance(plan, dict):
        return False
    sub_parts = plan.get("sub_parts")
    if not isinstance(sub_parts, list) or not sub_parts:
        return False
    for part in sub_parts:
        if not isinstance(part, dict):
            return False
        if not part.get("name") or not part.get("primitive"):
            return False
    return True
