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


def extract_entity_context(tool_results: dict) -> dict:
    """
    Extract structured entities (deal_ids, company_names)
    from a handler's tool results for use in follow-up
    pronoun resolution.

    Returns a dict with deal_ids and company_names lists.
    Empty lists if no entities found.
    """
    entities = {"deal_ids": [], "company_names": []}

    # Row-based handlers (query_new_deals, filter_table, etc.)
    rows = tool_results.get("rows", [])

    # Structured handlers return named keys
    if not rows:
        for key in ("new_deals", "losses", "wins",
                    "deals_at_risk", "arr_by_customer"):
            candidate = tool_results.get(key, [])
            if isinstance(candidate, list) and candidate:
                rows = candidate
                break

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

    return entities


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
                tool_results: dict = None):
    """Append Q&A + optional entity context to thread."""
    history = history[-6:]  # rolling window

    # Extract entities from tool results if provided
    entities = {}
    if tool_results:
        entities = extract_entity_context(tool_results)

    history += [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]

    # Store entity context as separate entry if entities found
    if entities.get("deal_ids") or entities.get(
            "company_names"):
        history.append({
            "role": ENTITY_ROLE,
            "content": json.dumps(entities),
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
