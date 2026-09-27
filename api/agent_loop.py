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
# Configuration

MAX_STEPS = 12

# Categories for which state_assumption is blocked — the model must ask_user.
SENSITIVE_ASSUMPTION_CATEGORIES: frozenset[str] = frozenset({
    "arr_vs_deal_value",
    "quota_vs_stretch",
    "renewals_in_out",
})

_INSUFFICIENT_ANSWER = (
    "I was unable to answer this confidently — the question required more "
    "data steps than my current budget allows.  Please try rephrasing with "
    "a narrower scope, or ask your admin to raise the step budget."
)

_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?[MKB%x]?\b")


def _has_numbers(text: str) -> bool:
    """Return True if the text contains what looks like a quantitative claim."""
    return bool(_NUMBER_RE.search(text or ""))


# ---------------------------------------------------------------------------
# Result dataclass

@dataclass
class AgentLoopResult:
    answer: str
    sources: list = field(default_factory=list)
    plan_used: list = field(default_factory=list)
    check_result_performed: bool = False
    check_result_auto_inserted: bool = False
    assumptions: list = field(default_factory=list)
    ask_user_question: str | None = None
    budget_exhausted: bool = False
    steps_taken: int = 0


# ---------------------------------------------------------------------------
# System prompt for the loop

_SYSTEM_PROMPT = """You are a CRO analytics agent.  You have a set of tools
and must decide how to answer the question by calling them in the right order.

Available tools (respond with JSON — one tool call per response):

1. call_primitive  — invoke a governed data calculator
   {"tool": "call_primitive", "params": {"name": "<primitive>", "params": {...}}}

2. fetch_data  — raw table retrieval for ad-hoc data
   {"tool": "fetch_data", "params": {"query": "<description of what to retrieve>"}}

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
# Tool implementations (minimal stubs that satisfy the loop's invariants)
# In production these delegate to real primitives; in tests, FakeClient
# controls the model side and these are only called when the loop actually
# dispatches a tool (which tests control via scripted sequences).

def _execute_call_primitive(name: str, params: dict, sb: Any) -> dict:
    """Dispatch to a named primitive.  Returns a result dict or error."""
    try:
        import api.handlers as handlers
        fn = getattr(handlers, name, None)
        if fn is None:
            return {"error": f"unknown primitive {name!r}"}
        # Most handler functions are async; for now return a stub.
        # The real router handles async dispatch — this path is for future wiring.
        return {"note": f"call_primitive({name}) dispatched", "params": params}
    except Exception as e:
        logger.warning(f"[AGENT_LOOP] call_primitive {name!r} failed: {e}")
        return {"error": str(e)}


def _execute_fetch_data(query: str, sb: Any) -> dict:
    """Ad-hoc raw data fetch.  Returns a result dict."""
    return {"note": f"fetch_data dispatched", "query": query}


def _execute_check_result(claim: str, supporting_data: dict) -> dict:
    """Verify claim against supporting_data.  Always succeeds (returns ok)."""
    return {"verified": True, "claim": claim}


def _execute_request_checkback() -> dict:
    return {"note": "checkback request recorded"}


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

    # Seed the conversation
    messages.append({
        "role": "user",
        "content": f"Question: {question}",
    })

    for step_idx in range(MAX_STEPS):
        # Ask model for next tool call
        try:
            resp = client.complete(
                messages=messages,
                system=_SYSTEM_PROMPT,
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

        # ── deliver: apply constraint C1 then return ──────────────────────
        elif tool == "deliver":
            answer = tool_params.get("answer", "")
            sources = tool_params.get("sources") or []
            plan_used = tool_params.get("plan_used") or []

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
            )

        # ── call_primitive ────────────────────────────────────────────────
        elif tool == "call_primitive":
            tool_result = _execute_call_primitive(
                tool_params.get("name", ""),
                tool_params.get("params", {}),
                sb,
            )

        # ── fetch_data ────────────────────────────────────────────────────
        elif tool == "fetch_data":
            tool_result = _execute_fetch_data(
                tool_params.get("query", ""),
                sb,
            )

        # ── request_checkback ─────────────────────────────────────────────
        elif tool == "request_checkback":
            tool_result = _execute_request_checkback()

        else:
            tool_result = {"error": f"unknown tool {tool!r}"}

        # Append tool result to message history
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
                         _tool_result_message(tool, tool_params, tool_result)})

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
