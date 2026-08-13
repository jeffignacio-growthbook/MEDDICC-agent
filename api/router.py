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
  dynamic_query         - question requires combining data from multiple tables
                          or filters not covered by the precomputed handlers
                          above. Use when no other handler fits but the data
                          likely exists in Supabase.
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

DYNAMIC_SYSTEM_PROMPT = """You answer RevOps questions for a
B2B SaaS CRO using query tools. You have access to tools
that read Supabase tables.

{schema_context}

TOOLS YOU CAN CALL (return JSON with "tool" and "params"):
  filter_table(table, columns, filters, limit, order_by)
  join_tables(primary_table, primary_key, joined_table,
              foreign_key, primary_filters, joined_columns, limit)
  aggregate_results(data, group_by, aggregations)
  compare_periods(table, column, agg, period_a, period_b,
                  date_column)

RULES:
- Only use column names that appear in the schema above
- Filters: [["operator", "column", "value"], ...]
  operators: eq neq gt gte lt lte like ilike is_ in_
- Maximum 5 tool calls per question
- If data genuinely doesn't exist, say so plainly
- Never invent numbers

To call a tool, respond with JSON:
{{"tool": "filter_table", "params": {{...}}}}
When you have enough data to answer, respond with:
{{"answer": "your answer here"}}
"""

async def dynamic_query_loop(question, history, params,
                              sb, client) -> str:
    """
    Multi-turn tool-calling loop for novel questions.
    Agent calls tools until it has enough data to answer.
    Capped at 5 iterations to prevent runaway cost.
    """
    from api.schema_context import get_schema_context
    from api import tools as T

    schema = get_schema_context(sb)
    system = DYNAMIC_SYSTEM_PROMPT.format(schema_context=schema)
    messages = [
        *[{"role": m["role"], "content": m["content"]}
          for m in history[-4:]
          if m["role"] in ("user", "assistant")],
        {"role": "user", "content": question}
    ]
    accumulated_data = {}

    for iteration in range(5):
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=system,
            messages=messages,
        )
        raw = resp.content[0].text.strip()
        try:
            parsed = json.loads(raw)
        except Exception:
            return raw

        if "answer" in parsed:
            return parsed["answer"]

        tool_name = parsed.get("tool", "")
        tool_params = parsed.get("params", {})

        tool_fn = {
            "filter_table": T.filter_table,
            "join_tables": T.join_tables,
            "aggregate_results": T.aggregate_results,
            "compare_periods": T.compare_periods,
        }.get(tool_name)

        if not tool_fn:
            return (f"I tried to use an unknown tool ({tool_name}). "
                    f"I can't answer this question with available data.")

        if tool_name == "aggregate_results":
            data_key = tool_params.pop("data_key",
                                       list(accumulated_data)[-1]
                                       if accumulated_data else "")
            tool_params["data"] = accumulated_data.get(
                data_key, {}).get("rows", [])
            result = await tool_fn(**tool_params)
        elif tool_name == "compare_periods":
            result = await tool_fn(sb, **tool_params)
        else:
            result = await tool_fn(sb, **tool_params)

        accumulated_data[f"step_{iteration}"] = result
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user",
            "content": f"Tool result: {json.dumps(result, default=str)[:3000]}"})

    return ("I couldn't fully answer this question within the allowed steps. "
            "The data exists but requires a more complex analysis. "
            "Try breaking it into simpler questions.")

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

    # 4.5. Dynamic query path for novel questions
    if (handler_name == "dynamic_query" or
        (not tool_results.get("rows") and
         not tool_results.get("waterfall") and
         not tool_results.get("arr_by_customer") and
         intent.get("confidence", 0) >= 0.6 and
         handler_name not in ("unanswerable", "set_target"))):

        answer = await dynamic_query_loop(
            question=question,
            history=history,
            params=params,
            sb=sb,
            client=client,
        )
        result["answer"] = answer
        result["tool_results"] = {"dynamic_query": True}
        return result

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
