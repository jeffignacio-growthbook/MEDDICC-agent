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

def load_thread(sb: Client, thread_ts: str) -> list:
    """
    Load last 3 Q&A pairs (6 messages) for this thread.
    Returns empty list if thread not found or expired.
    """
    try:
        r = sb.table("conversation_threads")\
              .select("history")\
              .eq("thread_ts", thread_ts)\
              .execute()
        if r.data:
            hist = r.data[0].get("history", [])
            # Parse JSON string to list if needed
            if isinstance(hist, str):
                hist = json.loads(hist)
            return hist[-6:]  # last 3 Q&A pairs (6 messages)
    except Exception:
        pass
    return []

def save_thread(sb: Client, thread_ts: str, channel: str,
                history: list, question: str, answer: str):
    """
    Append Q&A to thread history. Expire after 24h.
    Keeps rolling window of last 3 Q&A pairs.
    """
    history = history[-6:]  # keep rolling window
    history += [
        {"role": "user",      "content": question},
        {"role": "assistant", "content": answer},
    ]
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=24)

    sb.table("conversation_threads").upsert({
        "thread_ts":   thread_ts,
        "channel_id":  channel,
        "history":     json.dumps(history),
        "last_active": now.isoformat(),
        "expires_at":  expires_at.isoformat(),
    }, on_conflict="thread_ts").execute()

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
