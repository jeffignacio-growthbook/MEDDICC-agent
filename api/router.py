"""
Intent router for CRO Slack Agent.
Classifies incoming questions with Haiku, dispatches to handlers,
generates answers with Sonnet, verifies numbers with Haiku.
"""

import json
import os
import anthropic
from api.db import get_supabase, log_unanswered, is_admin
from api import handlers

INTENT_PROMPT = """Classify this Slack question into one of
these handler types. Reply with JSON only.

Handlers:
  query_waterfall       - pipeline movement, new/won/lost this week/quarter
  query_new_deals       - which deals were created, added to pipeline, or started in a time window
  query_arr             - ARR by customer, total ARR
  query_deals_at_risk   - weak MEDDICC scores, deals at risk, champion gaps
  query_win_loss        - why deals were won/lost, narratives
  query_objections      - objections by category/stage/trend
  query_feature_gaps    - feature gaps by severity/competitor
  query_coverage        - pipeline coverage vs target, quota attainment
  query_deal            - deep dive on a specific company's deal
  generate_win_loss     - full narrative for a specific closed deal (slow)
  set_target            - admin: set quota or target (requires auth)
  unanswerable          - question cannot be answered with available data

Required JSON:
{{
  "handler": "<handler_name>",
  "params": {{
    "time_window": {{
      "period": "current_quarter|current_week|last_N_days|specific",
      "start": "YYYY-MM-DD or null",
      "end":   "YYYY-MM-DD or null"
    }},
    "company": "<company name or null>",
    "rep_email": "<email or null>",
    "role": "ae|am|null",
    "metric": "new_arr|expansion_arr|total_arr|null",
    "target_value": "<number or null>",
    "entity_name": "<rep/team name for set_target or null>",
    "period_label": "Q3_FY2027 or null",
    "is_slow": false
  }},
  "unanswerable_reason": "no_data|out_of_scope|ambiguous|null",
  "confidence": 0.0-1.0
}}

For time windows, use the fiscal calendar:
  FY starts February. Q1=Feb-Apr, Q2=May-Jul,
  Q3=Aug-Oct, Q4=Nov-Jan.
  Today is {today}. Current quarter: {current_quarter}.

Conversation history (for follow-up context):
{history}

Question: {question}"""

VERIFY_PROMPT = """You generated this answer to a Slack
question. Verify that every number in the answer comes
directly from the tool results below. If any number was
invented or inferred without data support, rewrite the
sentence to either use the actual data or remove the claim.

Question: {question}
Your answer: {answer}
Tool results: {tool_results}

Reply with the verified answer only — no commentary.
If the answer is already fully supported, repeat it
unchanged."""

async def route_question(question: str, user_id: str,
                          history: list, sb) -> dict:
    """
    Full routing pipeline:
    1. Classify intent with Haiku
    2. Resolve time window
    3. Check admin auth for write commands
    4. Mark slow queries for ack
    5. Dispatch to handler
    6. Generate answer with Sonnet
    7. Verify numbers with Haiku
    8. Return result with answer and needs_ack flag
    """
    from datetime import date
    from api.time_resolver import resolve_time_window, current_quarter_label

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today  = date.today().isoformat()
    cq     = current_quarter_label()

    # 1. Classify intent
    intent_resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content":
            INTENT_PROMPT.format(
                today=today,
                current_quarter=cq,
                history=json.dumps(history[-4:]),
                question=question,
            )
        }]
    )
    try:
        # Strip markdown code fences if present
        raw_text = intent_resp.content[0].text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]  # Remove ```json
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]  # Remove ```
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]  # Remove trailing ```
        intent = json.loads(raw_text.strip())
    except Exception as e:
        # Log the actual error for debugging
        print(f"❌ Intent classification failed: {e}")
        print(f"   Raw response: {intent_resp.content[0].text[:500]}")
        log_unanswered(sb, question, user_id, "", "", "ambiguous")
        return {"answer": (
            "Sorry, I couldn't understand that question. "
            "Try asking about pipeline, coverage, deal risk, "
            "objections, or feature gaps."
        )}

    handler_name = intent.get("handler", "unanswerable")
    params = intent.get("params", {})
    params["time_window"] = resolve_time_window(
        params.get("time_window", {}))

    # 2. Auth check for write commands
    if handler_name == "set_target" and not is_admin(user_id):
        return {"answer": (
            "Only admins can update targets. "
            "Ask Jeff or Ryan to set this."
        )}

    # 3. Mark slow queries for ack
    is_slow = handler_name in ("generate_win_loss",) \
              or params.get("is_slow", False)
    result = {"needs_ack": is_slow}

    # 4. Dispatch to handler
    handler_fn = getattr(handlers, handler_name, None)
    if not handler_fn or handler_name == "unanswerable":
        reason = intent.get("unanswerable_reason", "out_of_scope")
        log_unanswered(sb, question, user_id, "", "", reason)
        return {"answer": (
            "I don't have data to answer that yet. "
            "I've logged the question — it may be something "
            "we can add to the data layer."
        )}

    tool_results = await handler_fn(params, sb)

    # 5. Generate answer with Sonnet
    answer_resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=(
            "You answer RevOps questions for a B2B SaaS CRO. "
            "Be concise — 2-5 sentences or a short bulleted "
            "list. Never invent numbers. If data is missing "
            "say so plainly. Use $ and K/M suffixes."
        ),
        messages=[
            *[{"role": m["role"], "content": m["content"]}
              for m in history[-4:]],
            {"role": "user", "content":
                f"Question: {question}\n\n"
                f"Data:\n{json.dumps(tool_results, indent=2)}"
            }
        ]
    )
    raw_answer = answer_resp.content[0].text.strip()

    # 6. Verify numbers against tool results
    verify_resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content":
            VERIFY_PROMPT.format(
                question=question,
                answer=raw_answer,
                tool_results=json.dumps(tool_results),
            )
        }]
    )
    verified_answer = verify_resp.content[0].text.strip()

    result["answer"] = verified_answer
    return result
