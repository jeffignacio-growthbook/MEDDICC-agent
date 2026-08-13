"""
Intent router for CRO Slack Agent.
Classifies incoming questions with Haiku, dispatches to handlers,
generates answers with Sonnet, verifies numbers with Haiku.
"""

import json
import os
import logging
import anthropic
from api.db import get_supabase, log_unanswered, is_admin
from api import handlers

# Configure logging for Railway (stderr is better captured than stdout)
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("cro_agent")
logger.info("[STARTUP] Phase G.2 robust router with evaluation loop loaded")

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
  query_rubric          - general scoring questions like "what does a 6 mean for champion?"
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

SYNTHESIS_SYSTEM_PROMPT = """You answer RevOps questions
for a B2B SaaS CRO in Slack.

FORMATTING (Slack-native):
- Never use markdown tables. Use bullet lists.
- Bold with *asterisks*, not **double**
- Deal format: • *Company* — $Value | Stage | Close | Score
- 5-8 lines max. Lead with the direct answer.
- End with one actionable insight when relevant.
- Never invent numbers. Use $ and K/M suffixes.

When data includes band_description and next_steps,
format coaching as:
  *[Component]: [Score]/10 — [band_description]*
  Next step: [next_steps]

When data includes deal_specific_next_steps, reference
those directly rather than generic rubric guidance."""

DYNAMIC_SYSTEM_PROMPT = """CRITICAL: Respond with ONLY a JSON object. No prose,
no explanation, no markdown. Your entire response must
be valid JSON starting with {{ and ending with }}.
Either a tool call: {{"tool": "...", "params": {{...}}}}
Or your final answer: {{"answer": "..."}}
Nothing else.

You answer RevOps questions for a B2B SaaS CRO using query tools.
You have access to tools that read Supabase tables.

{schema_context}

TOOLS YOU CAN CALL:
  filter_table(table, columns, filters, limit, order_by)
  join_tables(primary_table, primary_key, joined_table,
              foreign_key, primary_filters, joined_columns, limit)
  aggregate_results(data, group_by, aggregations)
    - aggregations MUST be a dict, not a list
    - CORRECT: {{"deal_value": "sum", "deal_id": "count"}}
    - WRONG: [{{"column": "deal_value", "agg": "sum"}}]
  compare_periods(table, column, agg, period_a, period_b,
                  date_column)

RULES:
- Only use column names that appear in the schema above
- Filters: [["operator", "column", "value"], ...]
  operators: eq neq gt gte lt lte like ilike is_ in_
- Maximum 5 tool calls per question
- If data genuinely doesn't exist, say so plainly
- Never invent numbers

QUERY EFFICIENCY:
When filtering on analysis scores (champion_score, overall_score, etc.),
always query the analyses table FIRST to get matching deal_ids, then look
up those specific deals. Never fetch all deals and then filter on analyses
— it hits the token budget.

ANSWER FORMATTING (for final {{"answer": "..."}} only):
When you have enough data to answer, format for Slack:
- Use bullet points (•) not markdown tables (| col | col |)
- Bold company names with *asterisks*
- Deal format: • *Company* — $Value | Stage | Date | Score X/10
- Keep to 5-8 lines max
- Lead with direct answer, then supporting detail
- End with one actionable insight if relevant

RESPONSE FORMAT (pure JSON, nothing else):
{{"tool": "filter_table", "params": {{...}}}}
OR
{{"answer": "your answer here"}}
"""

def _extract_json(text: str) -> dict | None:
    """Extract first JSON object from text, even if wrapped in prose or markdown."""
    import re
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip markdown fences
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                return json.loads(block)
            except Exception:
                continue
    # Find outermost { ... } in prose
    matches = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}', text, re.DOTALL)
    for m in sorted(matches, key=len, reverse=True):
        try:
            return json.loads(m)
        except Exception:
            continue
    return None

def _summarize_accumulated(data: dict) -> str:
    """Summarize accumulated tool results for budget overflow message."""
    parts = []
    for key, result in data.items():
        rows = result.get("rows", [])
        if rows:
            parts.append(f"{len(rows)} rows from {result.get('table', key)}")
    return "; ".join(parts) if parts else "no data found"

async def dynamic_query_loop(question, history, params,
                              sb, client,
                              hint: str = "") -> str:
    """
    Multi-turn tool-calling loop for novel questions.
    Agent calls tools until it has enough data to answer.
    Capped at 5 iterations and $0.08 token budget.
    """
    from api.schema_context import get_schema_context
    from api import tools as T

    schema = get_schema_context(sb)
    system = DYNAMIC_SYSTEM_PROMPT.format(schema_context=schema)

    # Build question with optional hint
    question_with_hint = question
    if hint:
        question_with_hint = f"{question}\nContext: {hint}"

    messages = [
        *[{"role": m["role"], "content": m["content"]}
          for m in history[-4:]
          if m["role"] in ("user", "assistant")],
        {"role": "user", "content": question_with_hint}
    ]
    accumulated_data = {}
    TOKEN_BUDGET = 15000  # ~$0.15 at Sonnet pricing
    tokens_used = 0
    MAX_ITERATIONS = 5
    EVAL_PROMPT = """Score this answer 0-1:
  1.0 = fully answers with specific data
  0.7 = partially answers, some specifics
  0.4 = answers adjacent question
  0.0 = no substantive data

Question: {question}
Answer: {answer}

Reply with JSON only: {{"score": 0.8, "missing": "..."}}"""

    for iteration in range(MAX_ITERATIONS):
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=system,
            messages=messages,
        )
        tokens_used += resp.usage.input_tokens + resp.usage.output_tokens

        if tokens_used > TOKEN_BUDGET:
            partial = _summarize_accumulated(accumulated_data)
            logger.info(f"[LOOP] fallback to unanswerable after "
                        f"{iteration+1} iterations, tokens={tokens_used}")
            return (f"Hit query budget with partial data: {partial}. "
                   f"Try a more specific question.")

        raw = resp.content[0].text.strip()

        # DEBUG: Log raw response
        logger.info(f"[LOOP iter={iteration}] raw response: {raw[:200]}")

        parsed = _extract_json(raw)

        # DEBUG: Log parsed result
        logger.info(f"[LOOP iter={iteration}] parsed={parsed is not None} "
                    f"tool={parsed.get('tool') if parsed else 'none'} "
                    f"has_answer={'answer' in (parsed or {})}")

        if not parsed:
            logger.info(f"[LOOP] JSON parse failed, raw={raw[:300]}")
            return (f"I couldn't parse my own response as JSON. "
                   f"This question may be too complex for dynamic querying. "
                   f"Raw response: {raw[:200]}")

        if "answer" in parsed:
            # Evaluate answer quality with Haiku
            try:
                eval_resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=100,
                    messages=[{"role": "user", "content":
                        EVAL_PROMPT.format(question=question, answer=parsed["answer"])
                    }]
                )
                eval_result = _extract_json(eval_resp.content[0].text)
                score = eval_result.get("score", 0.5) if eval_result else 0.5
                if score < 0.7 and iteration < MAX_ITERATIONS - 1:
                    missing = eval_result.get("missing", "more specifics") if eval_result else "more specifics"
                    messages.append({"role": "user",
                        "content": f"Score: {score:.1f}/1. Missing: {missing}. Improve with more specific data."})
                    continue
            except Exception:
                pass
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

        # DEBUG: Log tool execution result
        logger.info(f"[TOOL] {tool_name} rows={len(result.get('rows',[]))} "
                    f"error={result.get('error','none')}")

        accumulated_data[f"step_{iteration}"] = result
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user",
            "content": f"Tool result: {json.dumps(result, default=str)[:3000]}"})

    logger.info(f"[LOOP] fallback to unanswerable after "
                f"{MAX_ITERATIONS} iterations, tokens={tokens_used}")
    return ("I couldn't fully answer this question within the allowed steps. "
            "The data exists but requires a more complex analysis. "
            "Try breaking it into simpler questions.")

async def route_question(question: str, user_id: str,
                          history: list, sb) -> dict:
    """
    Robust question routing with inner evaluation loop.

    Flow:
      1. Classify intent (Haiku, cheap)
      2. Auth check for write commands
      3. Try precomputed handler
      4. Evaluate result quality
      5. Dynamic fallback if needed
      6. Honest "no data" if both fail
      7. Synthesize answer (Sonnet)
      8. Verify numbers against tool results (Haiku)
    """
    from datetime import date
    from api.time_resolver import resolve_time_window, current_quarter_label
    from api.evaluator import evaluate_result, extract_missing_hint

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    today  = date.today().isoformat()
    cq     = current_quarter_label()

    # ── 1. Classify ──────────────────────────────────
    intent_resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system="Respond with valid JSON only. No markdown, "
               "no backticks, no explanation.",
        messages=[{"role": "user", "content":
            INTENT_PROMPT.format(
                today=today,
                current_quarter=cq,
                history=json.dumps(
                    [m for m in history[-4:]
                     if m.get("role") in ("user","assistant")]),
                question=question,
            )
        }]
    )
    try:
        intent = _extract_json(intent_resp.content[0].text)
    except Exception:
        _log_unanswered(sb, question, user_id, "ambiguous")
        return {"answer":
            "I couldn't understand that question. Try asking "
            "about pipeline, deals, coverage, objections, "
            "or feature gaps."}

    handler_name = intent.get("handler", "unanswerable")
    params = intent.get("params", {})
    params["time_window"] = resolve_time_window(
        params.get("time_window", {}))
    confidence = intent.get("confidence", 0.5)

    print(f"[INTENT] handler={handler_name} "
          f"confidence={confidence:.2f}", flush=True)

    # ── 2. Auth check ─────────────────────────────────
    if handler_name == "set_target":
        if not is_admin(user_id):
            return {"answer":
                "Only admins can update targets. "
                "Ask Jeff or Ryan."}

    # ── 3. Try precomputed handler ────────────────────
    tool_results = {}
    result_quality = "empty"
    is_slow = handler_name == "generate_win_loss"

    if handler_name == "unanswerable":
        result_quality = "unanswerable"

    elif handler_name != "dynamic_query":
        handler_fn = getattr(handlers, handler_name, None)
        if handler_fn:
            try:
                tool_results = await handler_fn(params, sb)
                result_quality = evaluate_result(
                    tool_results, handler_name)
                print(f"[HANDLER] {handler_name} → "
                      f"{result_quality}", flush=True)
            except Exception as e:
                import traceback
                print(f"[HANDLER ERROR] {handler_name}: {e}",
                      flush=True)
                print(traceback.format_exc(), flush=True)
                result_quality = "error"

    # ── 4. Dynamic fallback ───────────────────────────
    if result_quality in ("empty", "error") \
       and confidence >= 0.5 \
       and handler_name not in ("unanswerable", "set_target"):

        print(f"[ROUTING] dynamic fallback "
              f"(quality={result_quality})", flush=True)
        hint = extract_missing_hint(tool_results, handler_name)
        dynamic_answer = await dynamic_query_loop(
            question=question,
            history=history,
            params=params,
            sb=sb,
            client=client,
            hint=hint,
        )
        if dynamic_answer and \
           "don't have data" not in dynamic_answer.lower() and \
           "couldn't" not in dynamic_answer.lower():
            return {"answer": dynamic_answer,
                    "needs_ack": is_slow}

    # Handle direct dynamic_query intent
    if handler_name == "dynamic_query":
        print(f"[ROUTING] dynamic_query (direct)", flush=True)
        dynamic_answer = await dynamic_query_loop(
            question=question,
            history=history,
            params=params,
            sb=sb,
            client=client,
            hint="",
        )
        return {"answer": dynamic_answer, "needs_ack": is_slow}

    # ── 5. Honest "no data" ───────────────────────────
    if result_quality in ("empty", "error", "unanswerable"):
        reason = intent.get("unanswerable_reason",
                            "no_data")
        _log_unanswered(sb, question, user_id, reason)
        return {"answer":
            "I don't have data to answer that yet. "
            "I've logged the question — it may be something "
            "we can add to the data layer."}

    # ── 6. Synthesize ─────────────────────────────────
    answer_resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=SYNTHESIS_SYSTEM_PROMPT,
        messages=[
            *[{"role": m["role"], "content": m["content"]}
              for m in history[-4:]
              if m.get("role") in ("user", "assistant")],
            {"role": "user",
             "content": f"Question: {question}\n\n"
                        f"Data:\n"
                        f"{json.dumps(tool_results, indent=2, default=str)[:3000]}"}
        ]
    )
    raw_answer = answer_resp.content[0].text.strip()

    # ── 7. Verify ─────────────────────────────────────
    verify_resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system="Respond with only the verified answer text. "
               "No JSON, no explanation.",
        messages=[{"role": "user", "content":
            VERIFY_PROMPT.format(
                question=question,
                answer=raw_answer,
                tool_results=json.dumps(
                    tool_results, default=str)[:2000],
            )
        }]
    )
    verified = verify_resp.content[0].text.strip()

    return {"answer": verified, "needs_ack": is_slow}


# Helper to keep route_question() clean
def _log_unanswered(sb, question, user_id, reason):
    try:
        log_unanswered(sb, question, user_id, "", "", reason)
    except Exception:
        pass
