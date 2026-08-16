"""
Database helper functions for CRO Slack Agent.
All functions use Supabase client to read/write conversation state,
quota targets, and unanswered query logs.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

_sb = None

def get_supabase() -> Client:
    """Singleton Supabase client."""
    global _sb
    if _sb is None:
        _sb = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"]
        )
    return _sb


def unpack_jsonb(value, default=None):
    """
    Safely unpack a Supabase JSONB column that may be
    returned as a string, dict, list, or None.
    Prevents AttributeError crashes from iterating
    unparsed JSON strings.

    Usage:
        data = unpack_jsonb(row.get("component_details"), {})
        items = unpack_jsonb(row.get("key_factors"), [])
    """
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default if default is not None else {}
    return default if default is not None else {}


# Valid Anthropic message roles
VALID_ROLES = {"user", "assistant"}

# Entity context role - stored in history but never sent to Anthropic
ENTITY_ROLE = "entity_context"

# Result cache reference role - stored in history but never sent to Anthropic
CACHE_ROLE = "result_cache_ref"

# TTL for cached result payloads (matches G.6 entity staleness guard)
CACHE_TTL_MINUTES = 30

# Handlers that legitimately never carry entities (follow-ups meaningless)
# Keep this list SMALL - handlers that COULD support follow-ups should get
# cache_payload instead of a whitelist entry
AGGREGATE_HANDLERS = {"query_rubric"}


def extract_entity_context(tool_results: dict) -> dict:
    """
    Extract structured entities (deal_ids, company_names)
    from a handler's tool results for use in follow-up
    pronoun resolution.

    Returns a dict with deal_ids and company_names lists.
    Empty lists if no entities found.
    """
    import logging
    logger = logging.getLogger(__name__)

    entities = {"deal_ids": [], "company_names": []}

    logger.info(f"[ENTITY_EXTRACT] tool_results keys: {list(tool_results.keys())}")

    # Row-based handlers (query_new_deals, filter_table, etc.)
    rows = tool_results.get("rows", [])

    # Structured handlers return named keys - check ALL list-valued keys
    # instead of hardcoded subset (fixes waterfall, scores, stages, etc.)
    if not rows:
        for key, value in tool_results.items():
            if isinstance(value, list) and value:
                # Found a list - check if it contains dicts with entity fields
                first_item = value[0] if value else None
                if isinstance(first_item, dict) and \
                   (first_item.get("deal_id") or first_item.get("company_name")):
                    rows = value
                    logger.info(f"[ENTITY_EXTRACT] using '{key}' list with {len(rows)} items")
                    break

    if not rows:
        logger.info(f"[ENTITY_EXTRACT] no entity-bearing lists found")

    for r in rows[:20]:  # cap at 20 entities
        if isinstance(r, dict):
            if r.get("deal_id"):
                entities["deal_ids"].append(r["deal_id"])
            if r.get("company_name"):
                entities["company_names"].append(
                    r["company_name"])

    # Also check nested deal structures
    deal = tool_results.get("deal", {})
    if isinstance(deal, dict) and deal.get("deal_id"):
        if deal["deal_id"] not in entities["deal_ids"]:
            entities["deal_ids"].append(deal["deal_id"])
        if (deal.get("company_name") and
                deal["company_name"] not in
                entities["company_names"]):
            entities["company_names"].append(
                deal["company_name"])

    logger.info(f"[ENTITY_EXTRACT] extracted {len(entities['deal_ids'])} deal_ids, "
                f"{len(entities['company_names'])} company_names")
    return entities


# ══════════════════════════════════════════════════════════════
# RESULT CACHE LAYER (G.7)
# ══════════════════════════════════════════════════════════════

def make_result_key(thread_ts: str, handler_name: str, question: str) -> str:
    """
    Deterministic key so the same question in the same thread
    overwrites rather than accumulating rows.

    Uses SHA256 hash to keep keys compact while avoiding collisions.
    """
    import hashlib
    raw = f"{thread_ts}:{handler_name}:{question}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"rc_{digest}"


def save_result_cache(sb: Client, thread_ts: str, handler_name: str,
                      question: str, payload: dict) -> str | None:
    """
    Store a full result payload for later retrieval.
    Returns the result_key, or None if nothing worth caching.

    Only caches when payload actually contains row data —
    don't fill the table with empty aggregates.

    IMPORTANT: Uses timedelta for expiry, NOT modular arithmetic.
    Prior bug: now.replace(hour=(now.hour+24)%24) is no-op at hour 23.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Count rows across all list-valued keys
    row_count = 0
    for v in payload.values():
        if isinstance(v, list):
            row_count += len(v)

    if row_count == 0:
        return None

    key = make_result_key(thread_ts, handler_name, question)
    # CORRECT expiry computation using timedelta
    expires = datetime.now(timezone.utc) + timedelta(minutes=CACHE_TTL_MINUTES)

    sb.table("result_cache").upsert({
        "result_key":   key,
        "thread_ts":    thread_ts,
        "handler_name": handler_name,
        "question":     question[:500],  # Truncate long questions
        "payload":      json.dumps(payload),  # JSONB storage
        "row_count":    row_count,
        "expires_at":   expires.isoformat(),
    }, on_conflict="result_key").execute()

    logger.info(f"[CACHE] stored {row_count} rows under {key} "
                f"(handler={handler_name}, ttl={CACHE_TTL_MINUTES}m)")
    return key


def load_result_cache(sb: Client, thread_ts: str) -> dict | None:
    """
    Retrieve the most recent non-expired cached payload for a thread.
    Returns the payload dict, or None.

    Uses unpack_jsonb() because JSONB columns can come back as str or dict.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        now_iso = datetime.now(timezone.utc).isoformat()

        # Query for non-expired cache entries in this thread
        result = sb.table("result_cache")\
            .select("result_key,handler_name,question,payload,row_count,created_at,expires_at")\
            .eq("thread_ts", thread_ts)\
            .gt("expires_at", now_iso)\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()

        if not result.data:
            logger.info(f"[CACHE] no live cache for thread {thread_ts}")
            return None

        hit = result.data[0]
        logger.info(f"[CACHE] hit {hit['result_key']} — "
                   f"{hit['row_count']} rows from handler={hit['handler_name']}")

        # unpack_jsonb handles both string and dict JSONB returns
        return unpack_jsonb(hit.get("payload"))

    except Exception as e:
        logger.error(f"[CACHE] load failed: {e}")
        return None


def load_thread(sb: Client, thread_ts: str) -> list:
    """Load last 3 Q&A pairs. Filters out entity_context
    role — those are for local use only, not Anthropic."""
    try:
        r = sb.table("conversation_threads")\
              .select("history")\
              .eq("thread_ts", thread_ts)\
              .execute()
        if r.data:
            hist = unpack_jsonb(r.data[0].get("history"), [])
            # Keep entity_context in the full history
            # (used by get_prior_entities below)
            return hist[-9:]  # 3 Q&A pairs + entity entries
    except Exception:
        pass
    return []

def save_thread(sb: Client, thread_ts: str, channel: str,
                history: list, question: str, answer: str,
                tool_results: dict, handler_name: str = "unknown"):
    """Append Q&A + optional entity context to thread.

    Args:
        tool_results: REQUIRED - must pass {} explicitly for paths with no data.
                     Making this required (no default) turns silent omissions
                     into immediate TypeErrors.
        handler_name: Handler that produced this answer, for negative-case logging.
    """
    import logging
    logger = logging.getLogger(__name__)

    history = history[-6:]  # rolling window

    # ═══════════════════════════════════════════════════════════════
    # CRITICAL: Strip cache_payload BEFORE any synthesis-facing use
    # ═══════════════════════════════════════════════════════════════
    # Failure mode is SILENT AND EXPENSIVE: if cache_payload leaks into
    # synthesis, full deal rows go into the prompt (3-5K wasted tokens).
    # Nothing in current logging would catch it. Assert + size log required.

    cache_payload = tool_results.pop("cache_payload", None)

    # LOAD-BEARING ASSERTION: verify strip succeeded
    assert "cache_payload" not in tool_results, \
        "cache_payload leaked into synthesis path"

    # Size log: makes leaks VISIBLE in Railway without needing a test
    synth_size = len(json.dumps(tool_results, default=str))
    logger.info(f"[SYNTH] tool_results ~{synth_size} chars (handler={handler_name})")
    if synth_size > 20000:
        logger.warning(f"[SYNTH] oversized synthesis payload {synth_size} chars "
                      f"for handler={handler_name} — check for cache_payload leak "
                      f"or unbounded rows")

    # Extract entities from BOTH synthesis dict AND cache_payload
    # (aggregate handlers now yield deal_ids via cache_payload)
    entities = {}
    if tool_results:
        logger.info(f"[SAVE_THREAD] extracting entities from tool_results")
        entities = extract_entity_context(tool_results)

    if cache_payload:
        logger.info(f"[SAVE_THREAD] extracting entities from cache_payload")
        cache_entities = extract_entity_context(cache_payload)
        # Merge cache entities into main entity dict
        for deal_id in cache_entities.get("deal_ids", []):
            if deal_id not in entities.get("deal_ids", []):
                entities.setdefault("deal_ids", []).append(deal_id)
        for company_name in cache_entities.get("company_names", []):
            if company_name not in entities.get("company_names", []):
                entities.setdefault("company_names", []).append(company_name)

    if not tool_results and not cache_payload:
        logger.info(f"[SAVE_THREAD] empty tool_results (handler={handler_name})")

    # Check extraction success BEFORE modifying history
    has_entities = bool(entities.get("deal_ids") or entities.get("company_names"))
    has_tool_data = bool(tool_results) and any(
        isinstance(v, list) and v for v in tool_results.values())

    # LOUD negative-case warning: tool_results had data but extraction got ZERO entities
    # Exclude handlers that legitimately never carry entities
    if (handler_name not in AGGREGATE_HANDLERS
        and has_tool_data and not has_entities):
        logger.warning(f"[ENTITY] save_thread stored ZERO entities "
                      f"for handler={handler_name} despite non-empty tool_results "
                      f"— keys: {list(tool_results.keys())}")

    history += [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]

    # Store entity context as separate entry if entities found
    if has_entities:
        # Add timestamp for staleness checking
        entities["resolved_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"[SAVE_THREAD] saving entity_context: "
                   f"{len(entities.get('deal_ids', []))} deal_ids, "
                   f"{len(entities.get('company_names', []))} company_names")
        history.append({
            "role": ENTITY_ROLE,
            "content": json.dumps(entities),
            "turn": len(history),
        })
    else:
        logger.info(f"[SAVE_THREAD] no entities to save (handler={handler_name})")

    # Store result cache payload if one exists
    if cache_payload:
        result_key = save_result_cache(sb, thread_ts, handler_name, question, cache_payload)
        if result_key:
            # Append cache reference to history (filtered from API calls like ENTITY_ROLE)
            history.append({
                "role": CACHE_ROLE,
                "content": result_key,
                "turn": len(history),
            })

    now = datetime.now(timezone.utc)
    sb.table("conversation_threads").upsert({
        "thread_ts":   thread_ts,
        "channel_id":  channel,
        "history":     json.dumps(history),
        "last_active": now.isoformat(),
        "expires_at":  (now + timedelta(hours=24)).isoformat(),
    }, on_conflict="thread_ts").execute()

def get_api_history(history: list) -> list:
    """
    Filter history for Anthropic API calls.
    Removes entity_context entries — these are internal only.
    """
    return [m for m in history
            if m.get("role") in ("user", "assistant")]


def get_prior_entities(history: list) -> dict:
    """
    Extract the most recent entity_context from history.
    Returns {"deal_ids": [...], "company_names": [...]}
    or empty dict if no prior entities found.
    """
    for msg in reversed(history):
        if msg.get("role") == ENTITY_ROLE:
            content = msg.get("content", "{}")
            try:
                return (json.loads(content)
                        if isinstance(content, str)
                        else content)
            except Exception:
                pass
    return {}


def log_unanswered(sb: Client, question: str, user_id: str,
                    channel: str, thread_ts: str,
                    reason: str):
    """
    Log a question the agent couldn't answer.
    Reasons: 'no_data' | 'out_of_scope' | 'ambiguous'
    """
    sb.table("unanswered_queries").insert({
        "question":   question,
        "asked_by":   user_id,
        "channel_id": channel,
        "thread_ts":  thread_ts,
        "reason":     reason,
    }).execute()

def is_admin(user_id: str) -> bool:
    """
    Check if user_id is in config admin list.
    Returns False if config not found or user not in list.
    """
    try:
        import yaml
        from pathlib import Path
        cfg_path = Path(__file__).parent.parent / "config" / "client.yaml"
        cfg = yaml.safe_load(open(cfg_path))
        admins = (cfg.get("admin", {})
                     .get("slack_user_ids", []))
        return user_id in admins
    except Exception:
        return False
