"""
Intent router for CRO Slack Agent.
Classifies incoming questions with Haiku, dispatches to handlers,
generates answers with Sonnet, verifies numbers with Haiku.
"""

import json
import os
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from llm_client import LLMClient
from api.db import get_supabase, log_unanswered, is_admin, get_prior_entities, get_api_history
from api import handlers

# Configure logging for Railway (stderr is better captured than stdout)
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("cro_agent")
logger.info("[STARTUP] Phase G.2 robust router with evaluation loop loaded")

FOLLOWUP_PRONOUNS = [
    "which of those", "which of them", "which of these",
    "of those", "of them", "of these",
    "those deals", "them deals", "these deals",
    "are those", "are they", "are them",
    "do those", "do they",
    "from those", "from them",
    "for those", "for them", "for these",
    "those", "these", "them", "they", "it",
    "that deal", "that one", "this deal",
    "the ones", "the same", "same deals",
    "any of those", "any of these",
]

NEW_DISCOVERY_SIGNALS = [
    # Phrasing that means "ignore known entities, find a NEW set"
    # Should NOT trigger entity-scoped bypass even if entities exist in thread
    "instead", "other deals", "different", "besides",
    "not in", "excluding", "new list", "all deals",
    "everything", "start over",
]

# Maps question keywords to bulk handler names for entity-scoped queries
# Handler descriptions - single source of truth for both INTENT_PROMPT and entity-scope classification
HANDLER_DESCRIPTIONS = {
    "query_waterfall": "pipeline movement, new/won/lost this week/quarter",
    "query_pipeline_movement": (
        "Historical pipeline movement, stage composition over time, "
        "deal-level stage changes, and the coverage curve by week — read "
        "from the reconstructed weekly deals_snapshot series (FY2026 Q3 "
        "onward). COUNT-based only (no dollar figures). Set params.view: "
        "'movement' for week-over-week counts in/out by stage, 'composition' "
        "for the stage-by-week grid, 'deal_changes' for which deals moved/"
        "advanced/regressed/left, 'curve' for deal count by week-of-quarter, "
        "'stage_deals' to list the deals currently in a named stage (set "
        "params.stage). Examples: 'how has pipeline moved over the last four "
        "weeks?' (movement), 'what's the stage breakdown this quarter versus "
        "last?' (composition), 'which deals moved stage since last week?' "
        "(deal_changes), 'show me the coverage curve for FY2027 Q2' (curve), "
        "'which deals are in Discovery?' (stage_deals, stage='Discovery')"
    ),
    "query_new_deals": "which deals were created, added to pipeline, or started in a time window",
    "query_won_deals": "which deals did we ALREADY win/close (past tense), retrospective wins/bookings. NOT future close dates.",
    "query_arr": "ARR by customer, total ARR",
    "query_deals_at_risk": "weak MEDDICC scores, deals at risk, champion gaps",
    "query_win_loss": "why deals were won/lost, narratives",
    "query_objections": "objections by category/stage/trend",
    "query_feature_gaps": "feature gaps by severity/competitor",
    "query_coverage": "pipeline coverage vs target, quota attainment",
    "query_deal": "deep dive on a specific company's deal",
    "query_rubric": "general scoring questions like \"what does a 6 mean for champion?\"",
    "generate_win_loss": "full narrative for a specific closed deal (slow)",
    "query_competitive_intel": "competitive intelligence: which companies mentioned DIY/build-it-themselves, named competitors showing up in calls, build-vs-buy signals, what alternatives prospects are evaluating",
    "set_target": "admin: set quota or target (requires auth)",
    "query_rubric_scores_bulk": "MEDDICC component scores for a known set of deals",
    "query_deal_stages_bulk": "current stage for a known set of deals",
    "query_deal_owners_bulk": "owner/rep for a known set of deals",
    "query_deal_values_bulk": "ARR/deal value for a known set of deals",
    "query_sdr_metrics": """SDR/BDR activity metrics for an individual rep — calls made, voicemails, call volume.
Use when asking about a specific SDR's activity, call counts, or outbound effort.
Examples: 'how is Jake tracking this month', 'show me Jake's calls',
'what are Jake's metrics for August', 'how many dials did Jake make this week'""",
    "query_sdr_leaderboard": "SDR/BDR team activity overview — calls and voicemails across all SDRs. Use for team-wide SDR activity or comparing SDR performance.",
    "query_sdr_pipeline_sourced": "Pipeline sourced by SDRs/BDRs — deals attributed to an SDR via the configured attribution field or current ownership. Use when asking about SDR-sourced pipeline, BDR contribution, or meetings that converted to opportunities.",
    "query_rep_pipeline": (
        "Active pipeline for a specific AE — all their open deals with "
        "value, stage, close date, and MEDDICC score. Use when asking about "
        "a rep's deals, pipeline, or book of business. Examples: "
        "'show me Christian's pipeline', 'what deals does Cary own?', "
        "'show me Scott's deals closing this quarter'"
    ),
    "query_rep_attainment": (
        "Quota attainment for one or all AEs — won revenue vs target. "
        "Use when asking who is on track, above/below quota, or how the "
        "team is tracking to number. Examples: 'who is on track to hit quota?', "
        "'show me Q3 attainment by rep', 'who is furthest from their number?', "
        "'which reps are above 50% to quota?'"
    ),
    "query_deal_health": (
        "MEDDICC health filter — deals with weak scores, missing components, "
        "or specific qualification gaps. Use when asking about risky deals, "
        "deals with no champion, or deals missing a specific MEDDICC component. "
        "Examples: 'show me Christian's weakest deals', "
        "'which deals have no economic buyer?', "
        "'show me deals closing this month with a score below 5', "
        "'show me deals where pain is identified but metrics are not'"
    ),
    "query_stale_deals": (
        "Deals with no recent activity or past their close date. Use when "
        "asking about stuck deals, deals that haven't moved, or deals past "
        "close date. Examples: 'which deals have been stuck for 30 days?', "
        "'show me deals past their close date', "
        "'which of Cary's deals haven't moved?', "
        "'show me deals stuck in Technical Evaluation'"
    ),
    "query_team_leaderboard": (
        "Full AE team ranking across pipeline, attainment, MEDDICC quality, "
        "and deals won. Use for team-wide comparison questions. Examples: "
        "'show me the team leaderboard', 'who is carrying the team?', "
        "'rank the AEs by pipeline', 'who has the most pipeline this quarter?'"
    ),
    "query_pre_call_brief": (
        "Pre-call intelligence brief for a specific deal — current MEDDICC "
        "scores with weakest components, last call summaries, open objections, "
        "and focus questions based on what's missing. Use when someone asks to "
        "be prepped for a call, wants a brief before a meeting, or asks what to "
        "focus on in an upcoming call. Examples: 'prep me for my Skyscanner call', "
        "'quick brief on the Stone deal', 'what should I focus on with IKEA?'"
    ),
    "query_coaching_priorities": (
        "Which deals and reps need coaching attention — missing economic buyer, "
        "weak champion, no recent call activity, unaddressed objections, or strong "
        "MEDDICC score with no movement. Use for 1:1 prep, coaching reviews, or "
        "pipeline health checks. Examples: 'which reps need coaching this week?', "
        "'prep me for my 1:1 with Christian', 'show me deals with no champion', "
        "'which of James's deals haven't had a call in 3 weeks?'"
    ),
    "query_call_quality": (
        "Review what happened on a specific call or assess discovery quality "
        "patterns across a rep or the team. Not roleplay — looks back at real "
        "call summaries and scores them against discovery rubric. Examples: "
        "'how did the last Skyscanner call go?', 'where is Christian weak in "
        "discovery?', 'show me the team's discovery quality this month', "
        "'what happened on James's Stone call?'"
    ),
    "dynamic_query": "question requires combining data from multiple tables or filters not covered by the precomputed handlers above. Use when no other handler fits but the data likely exists in Supabase.",
    "query_help": (
        "The person is orienting, not asking a data question — a greeting, "
        "asking what the assistant can do, asking what they should ask, or "
        "recovering from a bad answer. Set params.help_category to one of: "
        "'greeting' (hi, hey, hello, morning, yo, sup, hi Claude), "
        "'capability' (what can you do, how does this work, who are you, "
        "what is this, help, /help), "
        "'prompt_seeking' (what should I ask you, give me examples, where do "
        "I start, I don't know what to ask, how do I use this), "
        "'recovery' (that didn't work, that's not what I asked, I don't "
        "understand, try again, what?). "
        "DO NOT use query_help when a greeting is followed by a real question "
        "('hi, how's the Acme deal?') — route on the question. DO NOT use it "
        "for 'help me [do a real thing]' ('help me prep for Acme', 'help me "
        "understand this deal') — those are task requests (e.g. "
        "query_pre_call_brief / query_deal)."
    ),
    "acknowledgment": (
        "A social acknowledgment or sign-off with no request behind it — "
        "'thanks', 'thank you', 'got it', 'ok', 'okay', 'cool', 'great', "
        "'nice', 'bye', 'see ya'. Return a one-line reply; do NOT list "
        "capabilities. Not to be confused with 'ok what about Q2?' which "
        "carries a real follow-up question."
    ),
    "unanswerable": "question cannot be answered with available data",
}

# ══════════════════════════════════════════════════════════════
# HELP / GREETING — persona-aware orientation
# ══════════════════════════════════════════════════════════════
# Example questions for query_help are ASSEMBLED FROM THE HANDLER REGISTRY,
# never hardcoded as prose. Each entry keys a real handler in
# HANDLER_DESCRIPTIONS to one example phrasing and the persona buckets it
# suits. A hardcoded help list goes stale the moment a handler is renamed and
# nothing catches it; the tests in eval_help_handler.py assert every example
# still maps to a registered handler (down, never up — same ratchet discipline
# as the analytics ledgers).
#
# Persona buckets: 'rep' (individual contributor / AE), 'leadership'
# (CRO / VP / sales leadership), 'admin' (both + data-health). role_group maps:
# ic→rep; sales_leadership/executive→leadership; operational→leadership;
# unknown/other→rep+leadership (general); is_admin(user_id)→adds admin.
HELP_EXAMPLES = {
    # handler_name: {"example": str, "personas": [buckets]}
    "query_pre_call_brief":  {"example": "Prep me for my call with [company]",
                              "personas": ["rep"]},
    "query_deal":            {"example": "How's the [company] deal looking?",
                              "personas": ["rep"]},
    "query_deal_health":     {"example": "Which of my deals need attention?",
                              "personas": ["rep"]},
    "query_objections":      {"example": "What objections came up on my last call?",
                              "personas": ["rep"]},
    "query_coverage":        {"example": "Where's the pipeline for this quarter?",
                              "personas": ["leadership"]},
    "query_stale_deals":     {"example": "Which deals are stale?",
                              "personas": ["leadership"]},
    "query_rep_attainment":  {"example": "How's the team tracking to forecast?",
                              "personas": ["leadership"]},
    "query_team_leaderboard":{"example": "Who has the weakest qualification depth?",
                              "personas": ["leadership"]},
    # Admin data-health — no dedicated precomputed handler; routes via the
    # registered dynamic_query intent.
    "dynamic_query":         {"example": "Which deals are missing values or a close date?",
                              "personas": ["admin"]},
}


def _help_persona_tags(persona: dict, user_id: str) -> list:
    """Persona buckets whose examples this viewer should see."""
    role_group = (persona or {}).get("role_group")
    if role_group == "ic":
        tags = ["rep"]
    elif role_group in ("sales_leadership", "executive", "operational"):
        tags = ["leadership"]
    else:  # unknown / other → general set
        tags = ["rep", "leadership"]
    if is_admin(user_id):
        # Admin sees both plus data-health, deduped, order preserved.
        for t in ("rep", "leadership", "admin"):
            if t not in tags:
                tags.append(t)
    return tags


def _select_help_examples(tags: list, limit: int = 4) -> list:
    """Assemble example questions from the handler registry, filtered by
    persona bucket, in registry order, capped. Never hardcoded prose."""
    picked = []
    for name, meta in HELP_EXAMPLES.items():
        if any(t in meta["personas"] for t in tags):
            picked.append((name, meta["example"]))
        if len(picked) >= limit:
            break
    return picked


def build_help_response(help_category: str, persona: dict, user_id: str,
                        history: list) -> str:
    """Persona- and thread-aware orientation. Ends open, never terminal.

    Shape: one line on what it is → 3-4 example questions → one line inviting
    a follow-up. capability skips the welcome; prompt_seeking leads with the
    examples; recovery acknowledges the miss first; a returning thread gets a
    shorter version than first contact.
    """
    tags = _help_persona_tags(persona, user_id)
    examples = _select_help_examples(tags)
    example_lines = "\n".join(f"• {ex}" for _, ex in examples)

    # Unknown persona is a first-class case — say so, do not pretend a mapping.
    unknown_prefix = ""
    if not persona:
        unknown_prefix = ("I don't have you mapped to a role yet, so I'll answer "
                          "generally. Ask Jeff to add you and I can tailor this "
                          "to your deals.\n\n")

    returning = bool(history)  # prior turns in this thread → reconnection
    invite = "\nOr just describe what you're looking at."

    if help_category == "acknowledgment":  # defensive; normally handled separately
        return "👍"

    if help_category == "capability":
        # Direct answer, skip the welcome.
        body = ("I answer RevOps questions from your CRM data — pipeline, deals, "
                "MEDDICC health, forecast, objections, and rep activity. "
                "For example:\n" + example_lines)
        return unknown_prefix + body + invite

    if help_category == "prompt_seeking":
        # Lead with concrete examples — highest intent.
        body = ("Here's where people usually start:\n" + example_lines)
        return unknown_prefix + body + invite

    if help_category == "recovery":
        # Acknowledge the miss first, then orient.
        body = ("Sorry — let me reset. I answer questions from your CRM data. "
                "A few that tend to work:\n" + example_lines)
        return unknown_prefix + body + invite

    # greeting (default)
    if returning:
        # Reconnection — short, not the full orientation.
        body = ("Welcome back. Ask me anything about your deals or pipeline — "
                "for example:\n" + example_lines)
    else:
        body = ("Hi — I'm your RevOps assistant. I answer questions from your "
                "CRM data: pipeline, deals, MEDDICC health, forecast, and rep "
                "activity. A few things you can ask:\n" + example_lines)
    return unknown_prefix + body + invite


# Bulk handlers that can operate on entity scopes (deal_ids from prior context)
ENTITY_SCOPE_BULK_HANDLERS = [
    "query_deals_at_risk",
    "query_rubric_scores_bulk",
    "query_objections",
    "query_deal_stages_bulk",
    "query_deal_owners_bulk",
    "query_deal_values_bulk",
    "query_team_leaderboard",
    "query_rep_attainment",
    "query_coaching_priorities",
]

def has_followup_pronoun(question: str) -> bool:
    """Detect if question references prior answer entities."""
    q = question.lower()
    return any(p in q for p in FOLLOWUP_PRONOUNS)

def build_entity_hint(entities: dict) -> str:
    """Build a context hint for the intent classifier."""
    if not entities:
        return ""
    names = entities.get("company_names", [])[:10]
    ids   = entities.get("deal_ids", [])[:10]
    parts = []
    if names:
        parts.append(f"companies: {', '.join(names)}")
    if ids and not names:
        parts.append(f"deal_ids: {', '.join(str(i) for i in ids)}")
    return (f"\nThe user is asking a follow-up about "
            f"these specific entities from the prior answer: "
            f"{'; '.join(parts)}")

def should_use_entity_scope(question: str, prior_entities: dict) -> bool:
    """
    Decide whether to bypass discovery and query directly
    against known entities from the thread.

    Returns True when:
    - prior_entities has deal_ids
    - entities are not stale (< 30 minutes old)
    - question does not contain a NEW_DISCOVERY_SIGNAL
    """
    from datetime import datetime, timezone, timedelta

    if not prior_entities or not prior_entities.get("deal_ids"):
        return False

    # Check staleness: entities older than 30 minutes force rediscovery
    if prior_entities.get("resolved_at"):
        try:
            resolved_at = datetime.fromisoformat(
                prior_entities["resolved_at"].replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - resolved_at
            if age > timedelta(minutes=30):
                logger.info(f"[ENTITY_SCOPE] entities stale "
                           f"({age.total_seconds():.0f}s old), "
                           f"forcing rediscovery")
                return False
        except Exception as e:
            logger.warning(f"[ENTITY_SCOPE] failed to parse "
                          f"resolved_at: {e}")

    q_lower = question.lower()
    if any(sig in q_lower for sig in NEW_DISCOVERY_SIGNALS):
        return False
    return True

def classify_entity_scope_handler(question: str, entity_context: str, client) -> str | None:
    """
    Use Haiku to classify which bulk handler should handle this entity-scoped question.

    Args:
        question: User question
        entity_context: Description of prior entities (e.g., "3 deals from prior answer")
        client: Anthropic client

    Returns:
        Handler name from ENTITY_SCOPE_BULK_HANDLERS, or None if no match
    """
    import logging
    logger = logging.getLogger(__name__)

    # Build handler summary for entity-scope bulk handlers only
    bulk_handlers_lines = []
    for name in ENTITY_SCOPE_BULK_HANDLERS:
        desc = HANDLER_DESCRIPTIONS.get(name)
        if not desc:
            logger.warning(f"[CLASSIFIER] no description for handler {name} — omitting from classifier prompt")
            continue
        bulk_handlers_lines.append(f"  {name:25s} - {desc}")

    bulk_handlers_text = "\n".join(bulk_handlers_lines)

    prompt = f"""You have prior context about specific deals from a previous answer.
The user is asking a follow-up question about those deals.

{entity_context}

Question: {question}

Which bulk handler should answer this question?

Available handlers:
{bulk_handlers_text}

Reply with ONLY the handler name, or "none" if the question doesn't match any handler.
No explanation, no JSON."""

    try:
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )

        handler_name = response.text.strip()

        # Validate it's a known bulk handler
        if handler_name in ENTITY_SCOPE_BULK_HANDLERS:
            logger.info(f"[ENTITY_SCOPE] classified '{question[:50]}...' → {handler_name}")
            return handler_name
        elif handler_name.lower() == "none":
            logger.info(f"[ENTITY_SCOPE] no bulk handler matched question")
            return None
        else:
            logger.warning(f"[ENTITY_SCOPE] Haiku returned unknown handler: {handler_name}")
            return None

    except Exception as e:
        logger.error(f"[ENTITY_SCOPE] classification failed: {e}")
        return None


def log_entity_scope_pattern(question: str, handler_name: str,
                             entity_count: int, quality_score: str, sb) -> None:
    """
    Log successful entity-scope routing pattern for analysis and handler generation.

    Task G.8.4: Track which questions route successfully to build pattern library.
    """
    try:
        # Convert quality evaluation to numeric score
        quality_map = {"good": 0.9, "partial": 0.7, "empty": 0.0}
        score = quality_map.get(quality_score, 0.5)

        sb.table("entity_scope_patterns").insert({
            "question": question,
            "handler_name": handler_name,
            "entity_count": entity_count,
            "quality_score": score
        }).execute()
    except Exception as e:
        # Don't fail the request if pattern logging fails
        import logging
        logging.getLogger(__name__).warning(
            f"[ENTITY_SCOPE] Failed to log pattern: {e}")

async def route_entity_scoped_question(
        question: str, prior_entities: dict, sb, client) -> tuple[dict, str] | None:
    """
    Use LLM classification to match question to a bulk handler and execute it against
    known deal_ids without running dynamic_query_loop discovery.

    Returns (tool_results, handler_name) if a matching handler exists
    and returns non-empty results, or None if no handler matches.
    Caller runs normal synthesis (Step 6) on the tool_results.
    """
    from api.evaluator import evaluate_result
    from api import handlers
    from api.time_resolver import resolve_time_window
    import logging
    logger = logging.getLogger(__name__)

    deal_ids = prior_entities["deal_ids"]
    entity_context = f"Prior context: {len(deal_ids)} deals from previous answer"

    # All handlers (both pre-G.6 and new bulk handlers) need time_window
    # Pre-G.6 handlers require it; new bulk handlers ignore it
    default_tw = resolve_time_window({"period": "current_quarter"})

    # Classify which handler to use (LLM-based, replaces keyword matching)
    handler_name = classify_entity_scope_handler(question, entity_context, client)

    if not handler_name:
        return None

    # Execute the classified handler
    handler_fn = getattr(handlers, handler_name, None)
    if not handler_fn:
        logger.warning(f"[ENTITY_SCOPE] handler {handler_name} not found in handlers module")
        return None

    try:
        result = await handler_fn(
            {"deal_ids": deal_ids, "time_window": default_tw}, sb)
        evaluation = evaluate_result(result, handler_name)

        if evaluation != "empty":
            logger.info(f"[ENTITY_SCOPE] {handler_name} (quality={evaluation})")
            # Task G.8.4: Log successful pattern for analysis
            log_entity_scope_pattern(
                question, handler_name, len(deal_ids), evaluation, sb)
            return (result, handler_name)
        else:
            logger.info(f"[ENTITY_SCOPE] {handler_name} returned empty")
            return None

    except Exception as e:
        logger.error(f"[ENTITY_SCOPE] handler {handler_name} raised: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def build_intent_prompt(today: str, current_quarter: str, history: str, question: str, roster_text: str = "") -> str:
    """Build INTENT_PROMPT from HANDLER_DESCRIPTIONS (single source of truth)."""
    handlers_text = "\n".join([
        f"  {name:25s} - {desc}"
        for name, desc in HANDLER_DESCRIPTIONS.items()
    ])

    roster_section = ""
    if roster_text:
        roster_section = f"""
**Team Roster (for name→email resolution):**
{roster_text}

When question mentions a first name (e.g. "Jake", "Jennifer"), look up their
email in the roster above and use it in rep_email or sdr_email parameters.
"""

    return f"""Classify this Slack question into one of
these handler types. Reply with JSON only.

Handlers:
{handlers_text}

{roster_section}
Required JSON:
{{
  "handler": "<handler_name>",
  "params": {{
    "time_window": {{
      "period": "current_quarter|current_month|previous_month|current_week|last_N_days|specific",
      "start": "YYYY-MM-DD or null",
      "end":   "YYYY-MM-DD or null"
    }},
    "company": "<company name or null>",
    "rep_email": "<email or null>",
    "sdr_email": "<SDR/BDR email for query_sdr_metrics or null>",
    "role": "ae|am|null",
    "metric": "new_arr|expansion_arr|total_arr|null",
    "target_value": "<number or null>",
    "entity_name": "<rep/team name for set_target or null>",
    "period_label": "Q3_FY2027 or null",
    "search_term": "<specific competitor/term for query_competitive_intel or null>",
    "view": "<for query_pipeline_movement: movement|composition|deal_changes|curve|stage_deals, else null>",
    "fiscal_quarter": "<for query_pipeline_movement: 'FY2027 Q2' style label, or null for current>",
    "weeks": "<for query_pipeline_movement composition: integer count of recent weeks, or null>",
    "stage": "<for query_pipeline_movement stage_deals: stage name like 'Discovery', else null>",
    "close_date_scope": "<for query_pipeline_movement: 'current_quarter' to reconcile against a CRM board filtered by close date, else null (default all)>",
    "help_category": "<for query_help ONLY: greeting|capability|prompt_seeking|recovery, else null>"
  }},
  "unanswerable_reason": "no_data|out_of_scope|ambiguous|null",
  "confidence": 0.0-1.0
}}

Orientation vs. data questions (weigh the WHOLE message, not a prefix):
  - A greeting followed by a real question routes on the QUESTION
    ("hi, how's the Acme deal?" → query_deal), never query_help.
  - "help me [do a real thing]" is a task ("help me prep for Acme" →
    query_pre_call_brief), never query_help.
  - Bare social acknowledgments/sign-offs ("thanks", "ok", "cool", "bye")
    → acknowledgment, NOT query_help. But "ok, what about Q2?" carries a
    real follow-up → route on that.

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

# ══════════════════════════════════════════════════════════════
# REPORT SHAPES — Reusable structure declarations
# ══════════════════════════════════════════════════════════════
# Handlers can optionally declare which shape(s) their data fits.
# Synthesis adapts emphasis based on shape + question framing.

REPORT_SHAPES = {
    "snapshot": {
        "order": ["headline_number", "breakdown", "flags", "bottom_line"],
        "description": ("point-in-time state — a total, a breakdown by category, "
                       "what needs attention")
    },
    "trend": {
        "order": ["headline_change", "detail_by_period", "context", "bottom_line"],
        "description": ("movement over time — what changed, by how much, "
                       "is that good or bad")
    },
    "risk_alert": {
        "order": ["count_at_risk", "named_examples", "common_pattern", "bottom_line"],
        "description": ("a filtered list of concerning items — lead with how many, "
                       "name a few, note the pattern")
    },
    "comparison": {
        "order": ["headline_comparison", "breakdown_by_entity", "outliers", "bottom_line"],
        "description": ("ranking or comparing across reps/segments/deals — "
                       "who's ahead, who's behind, why")
    },
}

SYNTHESIS_SYSTEM_PROMPT = """You answer RevOps questions
for a B2B SaaS CRO in Slack.

VOICE — You are reporting as a VP of RevOps briefing a CRO or CEO.
Write the way that role writes:

- Lead with the number that matters most. State it first, then support it.
  Never bury the headline under context.
- Flag risk explicitly. A concerning number sitting quietly inside a list
  is a failure to communicate it — call it out.
- Close with one sentence of judgment: are we on track, and why. Not a
  restatement of the data — an actual read on it.
- Be concise. A VP's Slack update is scannable in 15 seconds, not a
  report to read end to end.

Example — a snapshot-shaped answer done well:

📊 *Current Pipeline — $14.4M across 144 deals*

*By Stage:*
• Discovery — 20 deals, $2.0M
• Scoping — 30 deals, $3.5M
• Technical Evaluation — 40 deals, $5.0M
• Negotiating — 25 deals, $2.9M

⚠️ *Needs Attention:* 12 deals missing ARR (incl. Company A, Company B...);
8 deals flagged at-risk (weak champion or economic buyer signals).

Bottom line: pipeline is healthy in volume but ARR hygiene is lagging — get
the 12 unvalued deals updated before they skew the forecast.

REASONING AGAINST DATA:
When answering, reason about the question against the data
— don't just report what fields are populated.

- If the question asks about X but the data contains Y
  which is semantically related, surface it:
  "No exact mentions of X, but we found related signals:
   [specific examples with company names]"
- Never say "zero mentions" or "no data" if the data
  contains semantically adjacent signals. "Have we seen
  DIY alternatives?" should surface "in-house platform"
  and "build vs buy" mentions even if "DIY" doesn't appear
  verbatim.
- If data is genuinely absent, say so plainly and suggest
  what related data does exist.

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

**Team roster (for name-to-email matching):**
{roster_text}

When user asks about "Jake" or "Jennifer" or any first name, match by name
to email in the roster above. Use the email in your WHERE clause, not the name.

Example:
  Question: "how is Jake tracking this month"
  → WHERE owner_email = 'jake.stangl@growthbook.io'
  (don't do: WHERE owner_name ilike '%jake%')

{schema_context}

TOOLS YOU CAN CALL:
  filter_table(table, columns, filters, limit, order_by)
  join_tables(primary_table, primary_key, joined_table,
              foreign_key, primary_filters, joined_columns, limit)
  aggregate_results(data, group_by, aggregations)
    data: list of dicts from a previous filter_table result,
          OR the string key "step_N" to reference a prior
          tool result (e.g. "step_0" for the first result)
    group_by: column name to group by
    aggregations: dict of {{"column": "sum"|"count"|"avg"}}
    Example: aggregate_results(
      data="step_1",
      group_by="owner_email",
      aggregations={{"deal_value": "sum", "deal_id": "count"}}
    )
  compare_periods(table, column, agg, period_a, period_b,
                  date_column)

RULES:
- Only use column names that appear in the schema above
- Filters: [["operator", "column", "value"], ...]
  operators: eq neq gt gte lt lte like ilike is_ in_
- Maximum 5 tool calls per question
- If data genuinely doesn't exist, say so plainly
- Never invent numbers

DATES: Always use the exact time_window dates provided
in the question context. Never compute your own fiscal
quarters — the resolved start/end dates are always given.

QUERY EFFICIENCY:
When filtering on analysis scores (champion_score, overall_score, etc.),
always query the analyses table FIRST to get matching deal_ids, then look
up those specific deals. Never fetch all deals and then filter on analyses
— it hits the token budget.

EFFICIENCY: For questions that need data from two
tables filtered together (e.g. deals in a specific
stage WITH a specific score), use join_tables in ONE
call rather than filter_table twice then aggregate.

Example for 'deals in Technical Evaluation with low
economic buyer score':
join_tables(
  primary_table='deals',
  primary_key='deal_id',
  joined_table='analyses',
  foreign_key='deal_id',
  primary_filters=[
    ['eq', 'stage', 'presentationscheduled'],
    ['eq', 'deal_status', 'active']
  ],
  joined_columns=['economic_buyer_score',
                  'overall_score', 'component_details'],
  limit=50
)
Then filter the joined rows in memory for low scores.

RANKING QUERIES: For 'strongest/weakest/highest/lowest'
questions about scores, ALWAYS:
1. Query analyses first with score threshold filter
   (not all 1800 deals)
2. Get the top 10-20 by score using limit parameter
3. Then look up company names for just those deal_ids
Never fetch all active deals first — analyses table
has scores, use it as the primary filter.

Example for 'strongest decision process':
Step 1: filter_table(analyses, columns=[deal_id,
  decision_process_score], filters=[], limit=20,
  order_by='decision_process_score DESC')
Step 2: filter_table(deals, columns=[deal_id,
  company_name, deal_value, owner_email, stage],
  filters=[['in_', 'deal_id', <step_1_ids>]])
Step 3: synthesize

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
    text = text.strip()
    # Try direct parse first (handles newlines in values)
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
    # Find outermost { } — use a proper JSON decoder
    # that handles nested quotes, not regex
    for start in range(len(text)):
        if text[start] == '{':
            for end in range(len(text), start, -1):
                if text[end-1] == '}':
                    try:
                        return json.loads(text[start:end])
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

def _extract_rows_from_accumulated(accumulated_data: dict, mode: str = "entity_extraction", sb=None) -> dict:
    """
    Extract rows from accumulated_data for entity context or synthesis.

    Args:
        accumulated_data: {"step_0": {...}, "step_1": {...}}
        mode: "entity_extraction" or "synthesis"
        sb: Supabase client (required for entity_extraction mode)

    Returns dict with "rows" key for extract_entity_context().

    Modes:
    - "entity_extraction": Prefer steps with entity ID columns (from entity_registry)
    - "synthesis": Return last step with data (for aggregates/rollups)
    """
    logger.info(f"[EXTRACT] mode={mode}, accumulated_data keys={list(accumulated_data.keys())}")

    if not accumulated_data:
        logger.info(f"[EXTRACT] empty accumulated_data, returning empty dict")
        return {}

    if mode == "synthesis":
        # Synthesis mode: return last step with data (current behavior)
        step_keys = sorted(accumulated_data.keys(), reverse=True)
        for step_key in step_keys:
            step_data = accumulated_data.get(step_key, {})
            rows = step_data.get("rows", [])
            if rows:
                logger.info(f"[EXTRACT] synthesis mode: returning {len(rows)} rows from {step_key}")
                return {"rows": rows, "table": step_data.get("table", "unknown")}
        return {}

    # Entity extraction mode: prefer entity-bearing steps
    # Load entity registry to know which columns are entity IDs
    entity_id_columns = set()
    if sb:
        try:
            result = sb.table("entity_registry").select("id_column").execute()
            entity_id_columns = {row["id_column"] for row in result.data}
            logger.info(f"[EXTRACT] entity ID columns from registry: {entity_id_columns}")
        except Exception as e:
            logger.warning(f"[EXTRACT] failed to load entity_registry: {e}")

    # Scan steps in reverse order, looking for entity-bearing rows
    step_keys = sorted(accumulated_data.keys(), reverse=True)
    entity_bearing_steps = []

    for step_key in step_keys:
        step_data = accumulated_data.get(step_key, {})
        rows = step_data.get("rows", [])

        if not rows:
            continue

        # Check if rows contain any registered entity ID columns
        if rows and isinstance(rows, list) and len(rows) > 0:
            first_row = rows[0]
            if isinstance(first_row, dict):
                row_columns = set(first_row.keys())
                matching_entities = row_columns & entity_id_columns

                if matching_entities:
                    entity_bearing_steps.append((step_key, step_data, matching_entities))
                    logger.info(f"[EXTRACT] {step_key}: {len(rows)} rows with entities {matching_entities}")
                else:
                    logger.info(f"[EXTRACT] {step_key}: {len(rows)} rows, no entity columns")

    # Return most recent entity-bearing step
    if entity_bearing_steps:
        step_key, step_data, entities = entity_bearing_steps[0]  # Already sorted reverse
        rows = step_data.get("rows", [])
        logger.info(f"[EXTRACT] returning {len(rows)} rows from {step_key} (has entities: {entities})")
        return {"rows": rows, "table": step_data.get("table", "unknown")}

    # Fallback: no entity-bearing steps found, return last step with data
    for step_key in step_keys:
        step_data = accumulated_data.get(step_key, {})
        rows = step_data.get("rows", [])
        if rows:
            logger.info(f"[EXTRACT] fallback: returning {len(rows)} rows from {step_key} (no entities found)")
            return {"rows": rows, "table": step_data.get("table", "unknown")}

    logger.info(f"[EXTRACT] no rows found in any step, returning empty dict")
    return {}

async def _run_precomputed_handler(handler_fn, handler_name, params, sb):
    """
    Execute a precomputed handler and classify its result quality.

    Returns (tool_results, result_quality, failure_reason).

    `failure_reason` is a SHORT technical string naming why the handler did not
    produce a usable answer — an exception repr on a raise, or the handler's own
    error/"no data" message otherwise. It is carried into the dynamic fallback
    so the fallback message can say what fell through (see PART 1 of
    FIX_DYNAMIC_FALLBACK_PATTERN). It is technical, for the log — never shown
    verbatim to the user.

    Logs the concrete failure, not just the routing bucket:
      - a handler that RAISES logs the exception + traceback, then → 'error'
      - a handler that RETURNS {"error": ...} or empty logs the reason
        alongside the quality bucket.

    Before this, query_rep_pipeline returning
    {"error": "owner_email required ..."} logged only
    "[HANDLER] query_rep_pipeline → error" — the real cause was invisible,
    and it took a downstream crash in the fallback path to surface it.
    """
    from api.evaluator import evaluate_result

    try:
        tool_results = await handler_fn(params, sb)
    except Exception as e:
        import traceback
        print(f"[HANDLER ERROR] {handler_name}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        return {}, "error", f"{type(e).__name__}: {e}"

    result_quality = evaluate_result(tool_results, handler_name)

    reason = ""
    if result_quality in ("error", "empty") and isinstance(tool_results, dict):
        reason = tool_results.get("error") or ""
    if not reason and result_quality in ("error", "empty"):
        reason = f"handler returned {result_quality} result"
    suffix = f" ({reason})" if reason else ""
    print(f"[HANDLER] {handler_name} → {result_quality}{suffix}", flush=True)
    return tool_results, result_quality, reason


async def dynamic_query_loop(question, history, params,
                              sb, client,
                              hint: str = "",
                              roster_text: str = "",
                              classifier_client=None,
                              origin_handler: str = "",
                              origin_reason: str = "") -> dict:
    """
    Multi-turn tool-calling loop for novel questions.
    Agent calls tools until it has enough data to answer.
    Capped at 5 iterations and a token budget.

    Returns {"answer": str, "tool_results": dict, "answered": bool}.
      - answered=True  → the loop produced a real, data-backed answer.
      - answered=False → the loop gave up (budget / repetition / exhausted).
        `answer` is then a PLAIN diagnostic naming what fell through; the
        technical detail is in the [FALLBACK] log line, not the reply. The
        caller decides whether to surface it. Sniffing the answer text for
        "couldn't" is no longer how the caller tells these apart.

    `origin_handler` / `origin_reason` name the precomputed handler that fell
    through to here and why (PART 1). Empty when the loop was entered directly
    (a `dynamic_query` intent), i.e. this IS the primary path, not a fallback.
    """
    from api.schema_context import get_schema_context
    from api.table_classifier import classify_relevant_tables
    from api import tools as T

    # Hybrid schema: classify relevant tables for full descriptions.
    # Table classification is a cheap Haiku task, so use the dedicated
    # classifier client when the caller supplies one; fall back to the
    # generator client passed in as `client` so this can never NameError.
    # (Before the LLMClient refactor this referenced a `classifier_client`
    # that no longer existed in this scope — a hard crash in the fallback path.)
    relevant_tables = classify_relevant_tables(
        question, classifier_client or client)
    logger.info(f"[SCHEMA] Relevant tables for full descriptions: {relevant_tables}")

    schema = get_schema_context(sb, tables_with_descriptions=relevant_tables)
    system = DYNAMIC_SYSTEM_PROMPT.format(
        schema_context=schema,
        roster_text=roster_text
    )

    # Build question with time window and optional hint
    history_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-4:]
        if m["role"] in ("user", "assistant")
    ]

    messages = [
        *history_messages,
        {"role": "user",
         "content": f"Question: {question}\n\n"
                    f"Time context: {params['time_window']['label']} "
                    f"= {params['time_window']['start']} to "
                    f"{params['time_window']['end']}\n\n"
                    f"{f'Context: {hint}' if hint else ''}"}
    ]
    accumulated_data = {}
    executed_tools = []  # Track tool calls to detect near-duplicates
    TOKEN_BUDGET = 20000  # ~$0.20 at Sonnet pricing - complex joins need headroom
    tokens_used = 0
    MAX_ITERATIONS = 5
    # PART 2b: repetition / no-progress detection. A duplicate tool call, a
    # parse failure, or a tool that returns zero new rows are all "no progress".
    # Two in a row means the loop is stuck — end it and answer from what exists,
    # rather than spend the rest of the budget rediscovering nothing.
    no_progress_streak = 0

    # Friendlier names for the handful of handlers that most often fall through,
    # so the user-facing diagnostic says what was being attempted in plain terms
    # (no handler identifiers, no "KeyError"). Technical detail stays in the log.
    _FRIENDLY_HANDLER = {
        "query_rep_pipeline": "looking up a rep's pipeline",
        "query_rubric_scores_bulk": "pulling MEDDICC scores for a named deal",
        "query_deal_stages_bulk": "looking up deal stages",
        "query_deal_owners_bulk": "looking up deal owners",
        "query_deal_values_bulk": "looking up deal values",
        "query_deal": "opening a specific deal",
        "query_deal_health": "checking deal health for a rep",
        "query_stale_deals": "finding a rep's stale deals",
        "query_sdr_metrics": "pulling an SDR's activity metrics",
    }

    def _fallback_log(reason_tag):
        """Greppable structured line for every give-up (PART 1)."""
        logger.info(
            f"[FALLBACK] handler={origin_handler or 'dynamic_query'} "
            f"reason={origin_reason or reason_tag} "
            f"question={question!r}"
        )

    def _diagnostic_answer(tail):
        """PLAIN user-facing sentence — names what fell through, no jargon."""
        if origin_handler:
            what = _FRIENDLY_HANDLER.get(
                origin_handler, "answering that the usual way")
            lead = (f"I couldn't answer that through the usual path — "
                    f"{what} didn't return what it needed")
        else:
            lead = "I searched the data directly for this"
        return (f"{lead}, and the fallback search {tail}. "
                f"Try naming a specific deal or rep, or narrowing the "
                f"question to a shorter time range.")

    def _give_up(reason_tag, tail):
        """Return an answered=False result with a plain diagnostic + log."""
        _fallback_log(reason_tag)
        return {
            "answer": _diagnostic_answer(tail),
            "tool_results": _extract_rows_from_accumulated(
                accumulated_data, sb=sb),
            "answered": False,
        }

    def _finalize_from_data(reason_tag):
        """PART 2b: stop looping and answer from data already gathered.

        One forced synthesis call (no further tools) if there is data and a
        little budget left; otherwise a plain diagnostic. Either way the loop
        ends here instead of burning the rest of the budget."""
        tr = _extract_rows_from_accumulated(accumulated_data, sb=sb)
        has_rows = bool(tr.get("rows"))
        # No data at all → nothing to synthesise from.
        if not has_rows:
            return _give_up(reason_tag, "ran out of room before it found anything")
        # No budget for one more call → answer with what we can describe.
        est = len(system) // 4 + sum(
            len(str(m.get('content', ''))) // 4 for m in messages) + 600
        if tokens_used + est > TOKEN_BUDGET:
            _fallback_log(reason_tag)
            return {"answer": _diagnostic_answer(
                        "gathered partial data but ran out of budget to "
                        "assemble it"),
                    "tool_results": tr, "answered": False}
        try:
            synth = client.complete(
                messages=messages + [{"role": "user", "content":
                    "Stop calling tools. Using ONLY the data already gathered "
                    f"above, answer this question now: {question}\n"
                    'Respond as {"answer": "..."}. If the gathered data genuinely '
                    'cannot answer it, still respond as {"answer": "..."} and say '
                    "plainly what is missing."}],
                system=system, max_tokens=600)
            parsed2 = _extract_json(synth.text)
            if parsed2 and parsed2.get("answer"):
                logger.info(f"[LOOP] finalized from gathered data "
                            f"(reason={reason_tag})")
                return {"answer": parsed2["answer"],
                        "tool_results": tr, "answered": True}
        except Exception:
            pass
        return _give_up(reason_tag, "could not turn the partial data into an answer")

    EVAL_PROMPT = """Score this answer 0-1:
  1.0 = fully answers with specific data
  0.7 = partially answers, some specifics
  0.4 = answers adjacent question
  0.0 = no substantive data

Question: {question}
Answer: {answer}

Reply with JSON only: {{"score": 0.8, "missing": "..."}}"""

    for iteration in range(MAX_ITERATIONS):
        # Predictive budget check BEFORE making call
        # Estimate: current system + messages + 800 output
        estimated_input = len(system) // 4 + sum(len(str(m.get('content', ''))) // 4 for m in messages)
        estimated_call_tokens = estimated_input + 800
        projected_total = tokens_used + estimated_call_tokens

        if projected_total > TOKEN_BUDGET:
            partial = _summarize_accumulated(accumulated_data)
            logger.info(f"[LOOP] declining iteration {iteration} - would exceed budget "
                       f"(used={tokens_used}, projected={projected_total}, budget={TOKEN_BUDGET}, "
                       f"partial={partial})")
            return _give_up("budget_exhausted",
                            "ran out of budget before it could finish")

        resp = client.complete(
            messages=messages,
            system=system,
            max_tokens=800,
        )
        tokens_used += resp.input_tokens + resp.output_tokens

        # Post-call verification (should never trigger if prediction is accurate)
        if tokens_used > TOKEN_BUDGET:
            partial = _summarize_accumulated(accumulated_data)
            logger.info(f"[LOOP] budget exceeded after "
                        f"{iteration+1} iterations, tokens={tokens_used}, "
                        f"partial={partial}")
            return _give_up("budget_exhausted",
                            "ran out of budget before it could finish")

        raw = resp.text.strip()

        # DEBUG: Log raw response
        logger.info(f"[LOOP iter={iteration}] raw response: {raw[:200]}")

        parsed = _extract_json(raw)

        # DEBUG: Log parsed result
        logger.info(f"[LOOP iter={iteration}] parsed={parsed is not None} "
                    f"tool={parsed.get('tool') if parsed else 'none'} "
                    f"has_answer={'answer' in (parsed or {})}")

        if not parsed:
            # Check if model gave prose answer directly
            stripped = raw.strip()
            if (stripped and
                not stripped.startswith('{') and
                not stripped.startswith('```') and
                len(stripped) > 50 and
                'tool' not in stripped[:20].lower()):
                # Treat as direct prose answer
                logger.info(f"[LOOP iter={iteration}] prose answer detected")
                # Extract rows from accumulated data for entity context
                tool_results = _extract_rows_from_accumulated(accumulated_data, sb=sb)
                return {"answer": stripped, "tool_results": tool_results,
                        "answered": True}
            # Otherwise log parse failure as before
            logger.info(f"[LOOP] JSON parse failed, raw={raw[:300]}")
            # PART 2b: a parse failure is no forward progress. Two in a row and
            # we stop, rather than keep spending the budget on malformed calls.
            no_progress_streak += 1
            if no_progress_streak >= 2:
                return _finalize_from_data("no_progress")
            continue

        if "answer" in parsed:
            # Evaluate answer quality with Haiku
            try:
                eval_resp = client.complete(
                    messages=[{"role": "user", "content":
                        EVAL_PROMPT.format(question=question, answer=parsed["answer"])
                    }],
                    max_tokens=100
                )
                eval_result = _extract_json(eval_resp.text)
                score = eval_result.get("score", 0.5) if eval_result else 0.5
                if score < 0.7 and iteration < MAX_ITERATIONS - 1:
                    missing = eval_result.get("missing", "more specifics") if eval_result else "more specifics"
                    messages.append({"role": "user",
                        "content": f"Score: {score:.1f}/1. Missing: {missing}. Improve with more specific data."})
                    continue
            except Exception:
                pass
            # Extract rows from accumulated data for entity context
            logger.info(f"[ANSWER] extracting entity context from accumulated_data with keys: {list(accumulated_data.keys())}")
            tool_results = _extract_rows_from_accumulated(accumulated_data, sb=sb)
            logger.info(f"[ANSWER] extracted tool_results with {len(tool_results.get('rows',[]))} rows")
            return {"answer": parsed["answer"], "tool_results": tool_results,
                    "answered": True}

        tool_name = parsed.get("tool", "")
        tool_params = parsed.get("params", {})

        # Check for near-duplicate tool calls
        # Near-duplicate: same (tool, table, columns, filters), ignoring limit
        is_duplicate = False
        if tool_name in ["filter_table", "join_tables"]:
            # Normalize columns (can be list or comma-separated string)
            cols = tool_params.get("columns") or []
            if isinstance(cols, str):
                cols = [c.strip() for c in cols.split(",") if c.strip()]
            cols_key = str(sorted(cols))

            # Normalize filters (can be list or None)
            filters = tool_params.get("filters") or []
            if not isinstance(filters, list):
                filters = []
            filters_key = str(sorted(filters, key=str))

            # Normalize table names (handle both filter_table and join_tables)
            if tool_name == "filter_table":
                table_key = str(tool_params.get("table", ""))
            else:  # join_tables
                # Include both primary and joined table
                primary = tool_params.get("primary_table", "")
                joined = tool_params.get("joined_table", "")
                table_key = f"{primary}+{joined}"

            tool_signature = (tool_name, table_key, cols_key, filters_key)

            for prev_sig, prev_iter in executed_tools:
                if prev_sig == tool_signature:
                    logger.info(f"[LOOP iter={iteration}] duplicate tool call detected "
                               f"(same as iteration {prev_iter})")
                    is_duplicate = True
                    break

            if not is_duplicate:
                executed_tools.append((tool_signature, iteration))

        if is_duplicate:
            # PART 2b: a duplicate is a stall signal, not something to nudge
            # past. The model already has this data. First duplicate: tell it
            # to use what it has and let it try once more. Second no-progress
            # step (another duplicate, a parse fail, or a zero-row tool call):
            # stop and answer from what exists — do NOT keep spending budget
            # re-emitting a query whose result is already in hand.
            no_progress_streak += 1
            if no_progress_streak >= 2:
                return _finalize_from_data("duplicate_tool_call")
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user",
                "content": f"You already queried this in iteration {prev_iter}. "
                          f"Do not repeat it. Using the data already in "
                          f"step_{prev_iter}, either answer now as "
                          '{"answer": "..."} or make ONE different query that '
                          "adds missing data."})
            continue  # one chance to recover; next stall ends the loop

        tool_fn = {
            "filter_table": T.filter_table,
            "join_tables": T.join_tables,
            "aggregate_results": T.aggregate_results,
            "compare_periods": T.compare_periods,
        }.get(tool_name)

        if not tool_fn:
            logger.info(f"[LOOP iter={iteration}] unknown tool requested: {tool_name!r}")
            return _finalize_from_data(f"unknown_tool:{tool_name}")

        if tool_name == "aggregate_results":
            data = tool_params.get("data", [])
            if isinstance(data, str):
                # Agent passed a key reference like "step_0"
                data = accumulated_data.get(data, {}).get("rows", [])
            elif not isinstance(data, list):
                data = []
            tool_params["data"] = data
            result = await tool_fn(**tool_params)
        elif tool_name == "compare_periods":
            result = await tool_fn(sb, **tool_params)
        else:
            result = await tool_fn(sb, **tool_params)

        # DEBUG: Log tool execution result
        logger.info(f"[TOOL] {tool_name} rows={len(result.get('rows',[]))} "
                    f"error={result.get('error','none')}")

        accumulated_data[f"step_{iteration}"] = result
        row_count = len(result.get("rows", []))
        logger.info(f"[STORE] saved step_{iteration} with {row_count} rows, "
                    f"accumulated_data now has keys: {list(accumulated_data.keys())}")

        # PART 2b: a tool call that returns zero rows is no forward progress.
        # Two no-progress steps in a row end the loop.
        if row_count == 0:
            no_progress_streak += 1
            if no_progress_streak >= 2:
                return _finalize_from_data("no_new_data")
        else:
            no_progress_streak = 0

        messages.append({"role": "assistant", "content": raw})
        # PART 2a: after every tool result, ask the model DIRECTLY whether the
        # question can now be answered. `has_answer` was never true because
        # nothing ever made "answer now if you can" an explicit instruction —
        # the model kept calling tools. Make the stop criterion explicit so the
        # loop ends the moment the data is sufficient.
        messages.append({"role": "user",
            "content": f"Tool result: {json.dumps(result, default=str)[:3000]}\n\n"
                       f"Can you now answer the question "
                       f"\"{question}\" from the data gathered so far? "
                       'If yes, respond with {"answer": "..."} now. '
                       "Only call another tool if essential data is still "
                       "missing — do not re-run a query you have already run."})

    logger.info(f"[LOOP] iterations exhausted after "
                f"{MAX_ITERATIONS} iterations, tokens={tokens_used}")
    return _finalize_from_data("iterations_exhausted")

async def route_question(question: str, user_id: str,
                          persona: dict = None,
                          history: list = None, sb = None,
                          thread_ts: str = "") -> dict:
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

    # Classifier and synthesis use different models
    classifier_client = LLMClient.from_config(role="classifier")
    generator_client = LLMClient.from_config(role="generator")
    today  = date.today().isoformat()
    cq     = current_quarter_label()

    # Log persona
    if persona:
        logger.info(f"[PERSONA] {persona.get('name')} ({persona.get('role')}) — {persona.get('email')}")
    else:
        logger.warning(f"[PERSONA] Unknown user {user_id} (no persona)")

    # Load team roster for name disambiguation in dynamic queries
    team_roster = sb.table("user_personas").select("name,email,role").execute()
    roster_text = "\n".join([
        f"- {r['name']} — {r['email']} ({r['role']})"
        for r in (team_roster.data or [])
    ])

    # ── -1. Entity-scope check (structural bypass) ───
    # Check if thread has known entities BEFORE pronoun matching
    prior_entities = get_prior_entities(history)
    skip_normal_routing = False
    tool_results = {}
    handler_name = ""
    result_quality = "empty"
    is_slow = False
    intent_resp = None  # Only assigned in normal routing path
    # Only fully populated in normal routing; the entity-scope and cache-
    # fallback paths skip classification, so without this default the retry
    # path (dynamic_query_loop(params=params)) hits UnboundLocalError — and a
    # bare {} would then KeyError on params['time_window'] inside the loop.
    # Seed a resolved current-quarter window so the retry path runs end to end.
    params = {"time_window": resolve_time_window({})}

    if should_use_entity_scope(question, prior_entities):
        logger.info(f"[ENTITY_SCOPE] using "
                    f"{len(prior_entities['deal_ids'])} "
                    f"known deal_ids, bypassing discovery")
        entity_match = await route_entity_scoped_question(
            question, prior_entities, sb, classifier_client)
        if entity_match is not None:
            tool_results, handler_name = entity_match
            result_quality = "good"
            skip_normal_routing = True
            # Skip to synthesis with these tool_results
        else:
            # No matching bulk handler, fall through to normal routing
            logger.info("[ENTITY_SCOPE] no matching bulk handler, "
                        "falling through to normal routing")

    # ── G.7 cache fallback — only when no usable entity IDs ──
    # Prefer entity_context (live re-query) over stale cache
    if not skip_normal_routing and has_followup_pronoun(question):
        from api.db import load_result_cache
        cached = load_result_cache(sb, thread_ts) if thread_ts else None
        if cached:
            logger.info("[CACHE] answering follow-up from cached payload "
                       "(no entity IDs available)")
            tool_results = cached
            handler_name = "cached_result"
            result_quality = "good"
            skip_normal_routing = True

    # ── 0. Pronoun resolution (fallback path) ────────
    # This now serves as backup when entity-scope didn't match
    if not skip_normal_routing:
        entity_params  = {}

        if has_followup_pronoun(question):
            prior_entities = get_prior_entities(history)
            if prior_entities:
                entity_params = {
                    "deal_ids":      prior_entities.get("deal_ids", []),
                    "company_names": prior_entities.get(
                        "company_names", []),
                }
                logger.info(f"[CONTEXT] pronoun detected, "
                            f"resolved {len(entity_params['deal_ids'])} "
                            f"deal_ids from prior turn")

            # ── 1. Classify ──────────────────────────────────
        intent_resp = classifier_client.complete(
            messages=[{"role": "user", "content":
                build_intent_prompt(
                    today=today,
                    current_quarter=cq,
                    history=json.dumps(get_api_history(history)[-4:]),
                    question=question,
                    roster_text=roster_text,
                ) + build_entity_hint(prior_entities)
            }],
            system="Respond with valid JSON only. No markdown, "
                   "no backticks, no explanation.",
            max_tokens=300
        )
        try:
            intent = _extract_json(intent_resp.text)
        except Exception:
            _log_unanswered(sb, question, user_id, "ambiguous")
            return {"answer":
                "I couldn't understand that question. Try asking "
                "about pipeline, deals, coverage, objections, "
                "or feature gaps.",
                "handler_name": "parse_failure",
                "tool_results": {}}

        handler_name = intent.get("handler", "unanswerable")
        params = intent.get("params", {})
        params["time_window"] = resolve_time_window(
            params.get("time_window", {}))

        # Inject prior entity context for pronoun follow-ups
        if entity_params:
            params["deal_ids"]      = entity_params["deal_ids"]
            params["company_names"] = entity_params["company_names"]

        confidence = intent.get("confidence", 0.5)

        print(f"[INTENT] handler={handler_name} "
              f"confidence={confidence:.2f}", flush=True)

        # ── 1b. Greeting / help / acknowledgment (orientation, no data) ──
        # Short-circuit BEFORE the data handler + synthesis path: these carry
        # no numbers to synthesize or verify. Persona- and thread-aware.
        if handler_name == "acknowledgment":
            logger.info(f"[HELP] category=acknowledgment user={user_id}")
            return {"answer": "👍 Anytime — just say the word when you need "
                              "something.",
                    "handler_name": "acknowledgment", "tool_results": {}}

        if handler_name == "query_help":
            help_category = (params.get("help_category")
                             or "capability")  # default if classifier omitted it
            # Cheap signal for whether orientation lands: the category now, and
            # the next turn's [INTENT] line is what they asked next. No new table.
            logger.info(f"[HELP] category={help_category} user={user_id} "
                        f"persona={(persona or {}).get('role_group', 'unknown')} "
                        f"returning={bool(history)}")
            return {"answer": build_help_response(
                        help_category, persona, user_id, history),
                    "handler_name": "query_help",
                    "help_category": help_category,
                    "tool_results": {}}

        # ── 2. Auth check ─────────────────────────────────
        if handler_name == "set_target":
            if not is_admin(user_id):
                return {"answer":
                    "Only admins can update targets. "
                    "Ask Jeff or Ryan.",
                    "handler_name": "set_target",
                    "tool_results": {}}

        # ── 3. Try precomputed handler ────────────────────
        tool_results = {}
        result_quality = "empty"
        handler_failure_reason = ""  # PART 1: carried into the fallback
        is_slow = handler_name == "generate_win_loss"

        if handler_name == "unanswerable":
            result_quality = "unanswerable"

        elif handler_name != "dynamic_query":
            handler_fn = getattr(handlers, handler_name, None)
            if handler_fn:
                tool_results, result_quality, handler_failure_reason = \
                    await _run_precomputed_handler(
                        handler_fn, handler_name, params, sb)

        # ── 4. Dynamic fallback ───────────────────────────
        if result_quality in ("empty", "error") \
           and confidence >= 0.5 \
           and handler_name not in ("unanswerable", "set_target"):

            print(f"[ROUTING] dynamic fallback "
                  f"(quality={result_quality})", flush=True)
            hint = extract_missing_hint(tool_results, handler_name)
            dynamic_result = await dynamic_query_loop(
                question=question,
                history=history,
                params=params,
                sb=sb,
                client=generator_client,
                hint=hint,
                roster_text=roster_text,
                classifier_client=classifier_client,
                origin_handler=handler_name,          # PART 1
                origin_reason=handler_failure_reason,  # PART 1
            )
            dynamic_answer = dynamic_result.get("answer", "")
            dynamic_tool_results = dynamic_result.get("tool_results", {})
            # PART 1/2: trust the loop's explicit `answered` flag rather than
            # sniffing the text for "couldn't". A real answer is returned as
            # before; a give-up surfaces the DIAGNOSTIC message (which names
            # what fell through) instead of the generic "no data" reply below.
            if dynamic_result.get("answered"):
                return {"answer": dynamic_answer,
                        "needs_ack": is_slow,
                        "tool_results": dynamic_tool_results,
                        "handler_name": f"{handler_name}_dynamic_fallback"}
            if dynamic_answer:
                _log_unanswered(sb, question, user_id, "fallback_exhausted")
                return {"answer": dynamic_answer,
                        "needs_ack": is_slow,
                        "tool_results": dynamic_tool_results,
                        "handler_name": f"{handler_name}_dynamic_fallback"}

        # Handle direct dynamic_query intent
        if handler_name == "dynamic_query":
            print(f"[ROUTING] dynamic_query (direct)", flush=True)
            dynamic_result = await dynamic_query_loop(
                question=question,
                history=history,
                params=params,
                sb=sb,
                client=generator_client,
                hint="",
                roster_text=roster_text,
                classifier_client=classifier_client,
            )
            return {"answer": dynamic_result.get("answer", ""),
                    "needs_ack": is_slow,
                    "tool_results": dynamic_result.get("tool_results", {}),
                    "handler_name": "dynamic_query"}

        # ── 5. Honest "no data" ───────────────────────────
        if result_quality in ("empty", "error", "unanswerable"):
            reason = intent.get("unanswerable_reason",
                                "no_data")
            _log_unanswered(sb, question, user_id, reason)
            return {"answer":
                "I don't have data to answer that yet. "
                "I've logged the question — it may be something "
                "we can add to the data layer.",
                "handler_name": handler_name,
                "tool_results": {}}

    # ── 6. Synthesize ─────────────────────────────────
    answer_resp = generator_client.complete(
        messages=[
            *[{"role": m["role"], "content": m["content"]}
              for m in history[-4:]
              if m.get("role") in ("user", "assistant")],
            {"role": "user",
             "content": f"Question: {question}\n\n"
                        f"Data:\n"
                        f"{json.dumps(tool_results, indent=2, default=str)[:3000]}"}
        ],
        system=build_synthesis_prompt(persona),
        max_tokens=600
    )
    raw_answer = answer_resp.text.strip()

    # ── 7. Verify ─────────────────────────────────────
    verify_resp = classifier_client.complete(
        messages=[{"role": "user", "content":
            VERIFY_PROMPT.format(
                question=question,
                answer=raw_answer,
                tool_results=json.dumps(
                    tool_results, default=str)[:2000],
            )
        }],
        system="Respond with only the verified answer text. "
               "No JSON, no explanation.",
        max_tokens=600
    )
    verified = verify_resp.text.strip()

    # ── 8. Correctness assessment + retry loop ───────────
    from api.assessor import (assess_correctness,
                               should_retry,
                               build_retry_context)

    MAX_RETRIES = 2
    retry_count = 0
    tokens_used = 0
    if intent_resp is not None:
        tokens_used += (intent_resp.input_tokens +
                       intent_resp.output_tokens)
    tokens_used += (answer_resp.input_tokens +
                   answer_resp.output_tokens +
                   verify_resp.input_tokens +
                   verify_resp.output_tokens)

    while retry_count <= MAX_RETRIES:
        assessment = await assess_correctness(
            question=question,
            handler_used=handler_name,
            tool_results=tool_results,
            answer=verified,
            client=classifier_client,
            budget_used=tokens_used * 0.000003,
            # approximate cost: tokens × $3/1M
        )

        tone_score = assessment.get('tone_score', 0.0)
        tone_issue = assessment.get('tone_issue')

        logger.info(f"[ASSESS] score={assessment.get('score', 0):.2f} "
              f"issue={assessment.get('issue')} "
              f"tone_score={tone_score:.2f} "
              f"tone_issue={tone_issue or 'none'} "
              f"retry={retry_count}")

        # TONE RETRY DECISION: Log only, no retry (Phase G.9 Task 4 option a)
        # Low tone_score should NOT trigger retry — that path re-runs data
        # gathering, which is the wrong tool for a phrasing problem.
        # Establish the metric first, look at it after a week of real traffic,
        # decide if re-synthesis is warranted.
        # A separate cheap re-synthesis-only retry (same data, rewrite) could
        # be added later if the data shows it's needed.

        if assessment.get("correct", True) or \
           not should_retry(assessment, retry_count):
            break

        # ── Guided retry ──────────────────────────────────
        retry_count += 1
        retry_context = build_retry_context(assessment, question)

        print(f"[RETRY {retry_count}] {retry_context[:100]}",
              flush=True)

        # Try the suggested handler first
        suggested = assessment.get("suggested_handler")
        if suggested and suggested != handler_name:
            handler_fn = getattr(handlers, suggested, None)
            if handler_fn:
                try:
                    tool_results = await handler_fn(params, sb)
                    handler_name = suggested
                except Exception as e:
                    print(f"[RETRY] handler failed: {e}",
                          flush=True)
                    tool_results = {}

        # If no suggested handler or it failed, try dynamic
        if not tool_results or not tool_results.get("rows",
            tool_results.get("deal")):
            dynamic_result = await dynamic_query_loop(
                question=question,
                history=history,
                params=params,
                sb=sb,
                client=generator_client,
                hint=retry_context,
                roster_text=roster_text,
                classifier_client=classifier_client,
            )
            # dynamic_query_loop returns {"answer", "tool_results", "answered"}
            dynamic_answer = dynamic_result.get("answer", "")
            dynamic_tool_results = dynamic_result.get("tool_results", {})
            if dynamic_result.get("answered"):
                # Log the learning note before returning
                _log_learning(sb, question, handler_name,
                             assessment, retry_count)
                return {"answer": dynamic_answer,
                        "needs_ack": is_slow,
                        "tool_results": dynamic_tool_results,
                        "handler_name": f"{handler_name}_retry_dynamic"}
            break

        # Re-synthesize with the new tool results
        answer_resp = generator_client.complete(
            messages=[
                *[{"role": m["role"], "content": m["content"]}
                  for m in history[-4:]
                  if m.get("role") in ("user", "assistant")],
                {"role": "user",
                 "content": f"Question: {question}\n\n"
                            f"Context: {retry_context}\n\n"
                            f"Data:\n{json.dumps(tool_results, indent=2, default=str)[:3000]}"}
            ],
            system=build_synthesis_prompt(persona),
            max_tokens=600
        )
        verified = answer_resp.text.strip()

    # ── 9. Log learning note (win or lose) ────────────────
    _log_learning(sb, question, handler_name,
                 assessment, retry_count)

    return {"answer": verified, "needs_ack": is_slow,
            "tool_results": tool_results,
            "handler_name": handler_name}


# Helper to keep route_question() clean
def _log_unanswered(sb, question, user_id, reason):
    try:
        log_unanswered(sb, question, user_id, "", "", reason)
    except Exception:
        pass


def _log_learning(sb, question, handler, assessment,
                  retries_used):
    """Log the assessment for the weekly learning report."""
    try:
        note = assessment.get("learning_note")
        issue = assessment.get("issue")
        suggested_fix = assessment.get("suggested_handler")
        retry_succeeded = assessment.get("correct", False)

        if not note and not issue:
            return

        sb.table("learning_log").insert({
            "question":  question,
            "handler_used": handler,
            "issue_type": issue,
            "suggested_fix": suggested_fix or note,
            "retry_succeeded": retry_succeeded,
            "retries_used": retries_used,
        }).execute()
    except Exception as e:
        print(f"[LEARNING] log failed: {e}", flush=True)

# ============================================================================
# PERSONA-AWARE VOICE BLOCKS
# ============================================================================

_VOICE_BASE = """You are a CRO's revenue intelligence agent.
Answer questions using ONLY the data from tool_results below.
Never invent numbers. If data doesn't exist, say so plainly.

CRITICAL SLACK FORMATTING:
- Bold: *single asterisks* only. Never **double**.
- No markdown tables. Use bullet lists: • metric: *value*
- No ## headers. Use *bold label* on its own line.
- Null/missing values: write _not available_ not **null** or None
- Data gaps: write _(data gap — explanation)_ in italics
- Never write variable names or code syntax (held = null → "unknown outcome")
"""

_VOICE_BLOCKS = {
    "executive": """
You're answering for {name_or_role} (executive level).
- Lead with the strategic implication, then the number
- Frame metrics as "we" not "the team" — they own the outcome
- Include year-over-year context when relevant
- Skip tactical detail unless asked — executives want signal, not noise
- Use confidence qualifiers when data has gaps ("based on available data...")

Example: "Pipeline is up 23% since last quarter to $2.1M — puts us on track 
for the $8M annual target assuming Q4 conversion holds at 28%."
""",

    "sales_leadership": """
You're answering for {name_or_role} (sales leadership).
- Start with team performance against target
- Include rep-level breakdown when relevant to the question
- Highlight both wins and gaps — they need to coach both
- Assume they know the process — skip basics like "MEDDICC means..."
- Use manager framing: "Your team closed...", "Jennifer's pipeline..."

Example: "Team is at 78% of Q3 quota with 6 weeks left. Jennifer and 
Scott are on track (95%+), but Jake H needs 3 more deals to hit his number."
""",

    "operational": """
You're answering for {name_or_role} (RevOps/Ops).
- Include data quality notes when relevant ("12 deals missing close dates")
- Explain calculation methodology if non-obvious
- Flag edge cases or exceptions in the data
- Use precise terminology — "weighted forecast" not "pipeline guess"
- Okay to include caveats: "Note: this excludes renewal pipeline"

Example: "Weighted forecast is $1.2M (85% × commit + 65% × most_likely). 
Note: 3 deals in commit stage have no MEDDICC scores yet — may be over-forecasted."
""",

    "ic": """
You're answering for {name_or_role} (IC / individual contributor).
- Get straight to the number — no preamble
- Include your own deals first if the question is about "my" or "I"
- Use plain language, not executive jargon
- One-sentence answers when possible
- Offer next steps only if directly relevant

Example: "You have 4 deals in proposal stage, total value $240K. Acme Corp 
is your strongest (champion score 8/10), but TechStart needs an economic buyer."
""",

    "other": """
You're answering for a revenue team member.
- Be clear and direct
- Include brief context for metrics that might not be familiar
- Use "the team" framing rather than "we" unless role is known
- One paragraph maximum unless the question asks for detail

Example: "The sales team closed 12 deals this quarter for $890K in new ARR. 
That's 89% of the quarterly target."
"""
}

def build_synthesis_prompt(persona: dict) -> str:
    """Build persona-aware synthesis system prompt."""
    role_group = (persona or {}).get("role_group", "other")
    block = _VOICE_BLOCKS.get(role_group, _VOICE_BLOCKS["other"])
    
    name = (persona or {}).get("name", "")
    title = (persona or {}).get("title", "")
    
    if name:
        name_or_role = name
    elif title:
        name_or_role = f"a {title}"
    else:
        name_or_role = "a revenue team member"
    
    block = block.replace("{name_or_role}", name_or_role)
    return _VOICE_BASE + "\n" + block

