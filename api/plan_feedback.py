"""
Piece 7: feedback, template promotion, and handler-promotion flagging
for the compositional layer.

Lifecycle:
  1. After Piece 6 delivers a composed answer, the caller appends
     checkback_prompt() and stores a pending_checkback entry in thread history.
  2. On the next turn, route_question() detects the reply via reply_to_checkback()
     and records a confirmation or rejection.
  3. Feedback is keyed by plan_signature — structure only, no values.
  4. After PROMOTION_THRESHOLD independent confirmations (distinct question
     instances), the plan is promoted to a reusable template and flagged for
     handler review.
  5. Templates are structure-only: future matching questions re-run
     Execute/Verify fresh through Pieces 4-6.  Stored values are never served.

Three non-negotiable invariants:
  A. plan_signature captures structure only — question text and values are
     never included.
  B. confirmed=False rows never contribute to the confirmation count.
     Rejections for one plan never affect a different plan's count.
  C. Promotion sets flagged_for_handler_review=True in plan_templates —
     no code automatically promotes a plan to a real handler.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Confirmation threshold before a plan is promoted to a reusable template
# and flagged for handler review.  The value is intentionally named here —
# pending a real calibration decision from production data — so it changes in
# exactly one place.  Spec requires N >= 3.
PROMOTION_THRESHOLD = 3

PENDING_CHECKBACK_ROLE = "pending_checkback"

_CHECKBACK_PROMPT = (
    "\n\n---\n"
    "_Was this the right answer? Reply **yes** or **no** so I can learn._"
)

# ---------------------------------------------------------------------------
# plan_signature and question_hash

def plan_signature(plan: dict) -> str:
    """
    Stable 16-char hex hash of the plan's STRUCTURE — which named sub-parts
    map to which primitives — ignoring question text, rationale prose, and
    all runtime values.

    Sorting makes the signature order-independent: two decompositions of
    "equivalent" questions that produce the same (name, primitive) pairs in
    different orders get the same signature.
    """
    if not plan or not isinstance(plan, dict):
        return ""
    sub_parts = plan.get("sub_parts") or []
    pairs = sorted(
        (p.get("name", ""), p.get("primitive", ""))
        for p in sub_parts
        if isinstance(p, dict)
    )
    key = json.dumps(pairs, separators=(",", ":"))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def question_hash(question: str) -> str:
    """Stable 16-char hex hash of a normalized question, for deduplication."""
    normalized = " ".join((question or "").lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Check-back prompt

def checkback_prompt() -> str:
    return _CHECKBACK_PROMPT


# ---------------------------------------------------------------------------
# Thread history entries

def make_pending_checkback_entry(
    plan: dict,
    question: str,
    thread_id: str,
) -> dict:
    """
    Build the thread-history entry for a pending check-back.
    Stores the plan structure so that maybe_promote_template() has it on
    confirmation without a second DB lookup.
    """
    return {
        "role": PENDING_CHECKBACK_ROLE,
        "content": json.dumps({
            "plan_signature": plan_signature(plan),
            "question_hash": question_hash(question),
            "question": question,
            "thread_id": thread_id,
            "plan": plan,
        }),
    }


def find_pending_checkback(history: list) -> dict | None:
    """Return the most-recent pending_checkback entry from thread history, or None."""
    for entry in reversed(history or []):
        if entry.get("role") == PENDING_CHECKBACK_ROLE:
            try:
                return json.loads(entry["content"])
            except Exception:
                return None
    return None


# ---------------------------------------------------------------------------
# Reply classification

_CONFIRMATIONS = frozenset({
    "yes", "y", "yeah", "yep", "yup", "correct", "that's right",
    "thats right", "right", "exactly", "perfect",
    "yes that's right", "yes that's correct", "confirmed",
})

_REJECTIONS = frozenset({
    "no", "n", "nope", "wrong", "not right", "that's wrong", "thats wrong",
    "incorrect", "not correct", "not what i wanted", "no that's wrong",
    "no thats wrong", "no that's not right", "no thats not right",
})


def reply_to_checkback(reply: str) -> str | None:
    """
    Classify a user reply to a check-back prompt.

    Returns:
      'confirmed'  — user affirms the answer was correct
      'rejected'   — user says the answer was wrong
      None         — not a check-back response; treat as new question
    """
    normalized = (reply or "").strip().lower()
    if normalized in _CONFIRMATIONS or normalized.startswith("yes"):
        return "confirmed"
    if normalized in _REJECTIONS or normalized.startswith("no"):
        return "rejected"
    return None


# ---------------------------------------------------------------------------
# Feedback recording

def record_feedback(
    sb: Any,
    plan_sig: str,
    q_hash: str,
    question: str,
    thread_id: str,
    confirmed: bool,
) -> None:
    """
    Write one feedback row to plan_feedback.
    Never raises — DB failures are logged and silently swallowed so a
    feedback-write failure never breaks the primary answer delivery path.
    """
    try:
        sb.table("plan_feedback").insert({
            "plan_signature": plan_sig,
            "question_hash": q_hash,
            "question_text": question[:500],
            "thread_id": thread_id,
            "confirmed": confirmed,
        }).execute()
    except Exception as e:
        logger.error(f"[PLAN_FEEDBACK] failed to record feedback: {e}")


def get_confirmation_count(sb: Any, plan_sig: str) -> int:
    """
    Count distinct question instances that confirmed this plan signature.
    Deduplication: same question_hash counts as exactly 1, regardless of
    how many times the same question was confirmed.
    confirmed=False rows are excluded entirely.
    """
    try:
        rows = (
            sb.table("plan_feedback")
            .select("question_hash")
            .eq("plan_signature", plan_sig)
            .eq("confirmed", True)
            .execute()
        )
        return len({r["question_hash"] for r in (rows.data or [])})
    except Exception as e:
        logger.error(f"[PLAN_FEEDBACK] failed to count confirmations: {e}")
        return 0


# ---------------------------------------------------------------------------
# Template promotion

def maybe_promote_template(sb: Any, plan: dict, plan_sig: str) -> bool:
    """
    If this plan has reached PROMOTION_THRESHOLD independent confirmations,
    upsert it as a promoted template in plan_templates and set
    flagged_for_handler_review=True.

    Returns True if promoted (or already promoted).  Never raises.

    Invariant C: promotion is a flag for human review only.  No code path
    here auto-creates a handler — it sets a DB column that a human reads in
    Supabase Studio and decides whether to build a dedicated handler.
    """
    try:
        count = get_confirmation_count(sb, plan_sig)
        if count < PROMOTION_THRESHOLD:
            return False
        sb.table("plan_templates").upsert(
            {
                "plan_signature": plan_sig,
                "plan_json": json.dumps(plan),
                "confirmation_count": count,
                "flagged_for_handler_review": True,
            },
            on_conflict="plan_signature",
        ).execute()
        logger.info(
            f"[PLAN_FEEDBACK] plan {plan_sig!r} promoted to template "
            f"({count} confirmations) — flagged for handler review"
        )
        return True
    except Exception as e:
        logger.error(f"[PLAN_FEEDBACK] promotion check failed: {e}")
        return False


def find_template(sb: Any, plan_sig: str) -> dict | None:
    """
    Return the promoted plan STRUCTURE for this signature, or None.

    Invariant F: the returned dict contains only sub_parts structure — the
    caller must always re-run Execute/Verify fresh.  Stored answer values
    must never be served; the caller is responsible for using sub_parts
    only and discarding any other keys.
    """
    try:
        rows = (
            sb.table("plan_templates")
            .select("plan_json")
            .eq("plan_signature", plan_sig)
            .execute()
        )
        if rows.data:
            return json.loads(rows.data[0]["plan_json"])
        return None
    except Exception as e:
        logger.error(f"[PLAN_FEEDBACK] template lookup failed: {e}")
        return None
