#!/usr/bin/env python3
"""
Per-call MEDDICC scorer (PROGRESSIVE_SCORING_SPEC, Phase 1).

Score ONE call in isolation: "what did THIS call establish about each of the
seven MEDDICC components?" Return a 0-10 score with evidence, or null when the
call is silent on a component. A later call supersedes an earlier one at the
roll-up (most-recent-non-null), so a single call is a smaller, better-posed
question than "what do four calls establish about seven components?".

Design constraints (from the spec, enforced here):
  - One call per pass. This module never batches calls into one prompt.
  - Null when a call says nothing about a component — never zero, never a guess.
  - Evidence (a quote/fact from THIS call) accompanies every non-null score.
  - Stage NEVER enters the scoring prompt; it applies only at the reporting
    layer. deal_context carries company identity, nothing stage-derived.
  - Temperature 0, via LLMClient.complete (extra_body mechanism).

The calibration bands and the "score on action, not sentiment / default to the
lower score on ambiguity" rules are lifted verbatim from prompts/CLAUDE.md so a
per-call score is anchored to the same rubric as the batch scorer. The batch
scorer's carry-forward / cumulative-state language is deliberately omitted —
there is no prior state in a single-call pass.
"""
import json
import re

# (label in prose, canonical bare key) — identical to meddicc_agent._PIN_COMPONENTS
# and the component_scores JSONB keys (migrations/003).
COMPONENTS = [
    ("Metrics", "metrics"),
    ("Economic Buyer", "economic_buyer"),
    ("Decision Criteria", "decision_criteria"),
    ("Decision Process", "decision_process"),
    ("Identified Pain", "pain"),
    ("Champion", "champion"),
    ("Competition", "competition"),
]
COMPONENT_KEYS = [k for _, k in COMPONENTS]

# Bump when the prompt/rubric changes so a re-backfill can find stale rows.
SCORER_VERSION = "phase1-percall-v2"

SINGLE_CALL_SYSTEM_PROMPT = """\
You score a SINGLE sales call against the seven MEDDICC components. You are given
one call (a transcript or its summary) and nothing else. Judge only what THIS
call establishes — you have no prior calls and no cumulative state.

Return a JSON object and nothing else, with exactly these seven keys:
  metrics, economic_buyer, decision_criteria, decision_process, pain,
  champion, competition
Each value is an object: {"score": <0-10 integer or null>, "evidence": <string or null>}.

RULES
- Score a component ONLY if THIS call MATERIALLY ADVANCES it — i.e. this call adds
  specific new evidence about it. If the call is silent on a component, OR only
  references it in passing without adding substantive evidence beyond a mention,
  return {"score": null, "evidence": null}. A passing mention is not an advance.
- NULL IS THE COMMON CASE. Most calls advance only ONE to FOUR of the seven
  components; the rest are null. A narrow call — a pricing negotiation, a technical
  deep-dive — legitimately establishes almost nothing about the others. If you find
  yourself scoring five, six, or seven components, you are over-scoring: re-check
  which ones this call ACTUALLY advanced with new evidence, and null the rest.
- Do NOT re-score a component this call merely confirms or repeats from a presumed
  earlier discussion. You have no prior calls; score only what THIS call newly
  establishes. Old evidence surviving is the roll-up's job, not yours — when in
  doubt, null.
- NEVER return 0 to mean "not discussed"; 0 is not a valid score. Use null. Do not guess.
- Every non-null score MUST carry evidence: a direct quote or a specific fact FROM
  THIS CALL. No specific evidence from this call → the score is null.
- Default to the LOWER score on ambiguity. Enthusiasm without specifics = 1/10.
- Score Champion and Economic Buyer on what the buyer DOES, not how they FELT.
  A contact who sounds excited but owns no internal next step is Champion 1-2, not higher.
- Do NOT consider the deal's pipeline stage; it is not provided and must not be inferred.

SCORING CALIBRATION (per component, when the call DOES address it)
Metrics:            9-10 quantified metric; 7-8 clear business impact; 5-6 pain mentioned not quantified; 3-4 vague; 1-2 barely.
Economic Buyer:     9-10 direct engagement + budget authority confirmed; 7-8 named + budget holder confirmed; 5-6 role unclear on budget; 3-4 generic "leadership"; 1-2 name/title only.
Decision Criteria:  9-10 formal criteria/scorecard; 7-8 key criteria stated; 5-6 some criteria incomplete; 3-4 vague requirements; 1-2 barely.
Decision Process:   9-10 full timeline + stakeholders + approvals; 7-8 timeline and key stakeholders; 5-6 timeline OR stakeholders; 3-4 vague timing; 1-2 barely.
Identified Pain:    9-10 specific urgent pain w/ impact + timeline; 7-8 clear pain w/ context; 5-6 pain not urgent/specific; 3-4 generic interest; 1-2 barely.
Champion:           9-10 active internal selling / business case; 7-8 facilitating access, owns next steps; 5-6 engaged not selling; 3-4 responsive but passive; 1-2 no owned internal action.
Competition:        9-10 full landscape + eval status + our differentiation; 7-8 current tool + limitations; 5-6 competitor mentioned, limited detail; 3-4 vague "other tools"; 1-2 barely.

Output the JSON object only. No prose, no markdown fences.
"""


def build_messages(call_text, deal_context=None):
    """User message for one call. deal_context is company identity only — never
    stage, which would corrupt the score."""
    company = ""
    if deal_context:
        company = (deal_context.get("company") or deal_context.get("company_name") or "").strip()
    header = f"Company: {company}\n\n" if company else ""
    return [{
        "role": "user",
        "content": (
            f"{header}Score this single call. Return the JSON object described in "
            f"your instructions — seven keys, each {{score, evidence}}, null where "
            f"the call is silent.\n\n=== CALL ===\n{call_text}"
        ),
    }]


def _coerce_score(v):
    """0-10 int, or None. Rejects out-of-range and non-numeric; 'null'/'' → None.
    A bare 0 is treated as None: the rubric forbids 0-means-not-discussed, so a 0
    is a model slip for null, not a real score."""
    if v is None:
        return None
    if isinstance(v, bool):  # guard: bool is an int subclass
        return None
    if isinstance(v, str):
        v = v.strip()
        if v == "" or v.lower() == "null":
            return None
        try:
            v = float(v)
        except ValueError:
            return None
    if isinstance(v, float):
        if v != v:  # NaN
            return None
        v = int(round(v))
    if isinstance(v, int):
        if v <= 0:
            return None
        return v if 0 <= v <= 10 else None
    return None


def _coerce_evidence(v, score):
    if score is None:
        return None
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_call_scores(text):
    """Parse the model's JSON into {key: {"score": int|None, "evidence": str|None}}
    for all seven components. Tolerant of code fences and trailing prose; any
    component the model omits or malforms becomes null (safe: null = 'said
    nothing'). Never raises."""
    out = {k: {"score": None, "evidence": None} for k in COMPONENT_KEYS}
    if not text:
        return out
    obj = _extract_json_object(text)
    if not isinstance(obj, dict):
        return out
    for key in COMPONENT_KEYS:
        cell = obj.get(key)
        if isinstance(cell, dict):
            score = _coerce_score(cell.get("score"))
            out[key] = {"score": score, "evidence": _coerce_evidence(cell.get("evidence"), score)}
        else:
            # Some models emit a bare number/null instead of {score, evidence}.
            score = _coerce_score(cell)
            out[key] = {"score": score, "evidence": None}
    return out


def _extract_json_object(text):
    """First balanced {...} object in text, JSON-parsed. Handles ```json fences
    and trailing commentary. Returns None on failure."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        c = t[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except Exception:
                    return None
    return None


def score_call(call_text, deal_context=None, client=None):
    """Score one call. Returns:
        {"components": {key: {"score": int|None, "evidence": str|None}},
         "model": str, "input_tokens": int, "output_tokens": int}
    Raises ValueError on empty input (a call with no text cannot be scored —
    that is an 'unavailable' condition the caller handles, not a null score)."""
    if not call_text or not call_text.strip():
        raise ValueError("score_call: empty call_text")
    if client is None:
        from llm_client import LLMClient
        client = LLMClient.from_config("generator")
    resp = client.complete(
        messages=build_messages(call_text, deal_context),
        system=SINGLE_CALL_SYSTEM_PROMPT,
        max_tokens=1500,
        temperature=0,  # per-call scoring is deterministic, not a sample
    )
    return {
        "components": parse_call_scores(resp.text),
        "model": getattr(resp, "model", None),
        "input_tokens": getattr(resp, "input_tokens", 0) or 0,
        "output_tokens": getattr(resp, "output_tokens", 0) or 0,
    }


def roll_up(scored_calls):
    """Deal-level roll-up: the most-recent-non-null call score per component.

    scored_calls: iterable of {"call_id", "call_date", "components": {key:{score,evidence}}}.
    Sorted here by call_date ascending; a later call supersedes an earlier one,
    so regression is possible (a champion leaving lowers the score) — there is no
    max() floor. A component null in every call rolls up to null.

    Returns {key: {"score", "evidence", "call_id", "call_date"}} with full
    provenance; score is None (and call_id/date None) if no call scored it.
    """
    rolled = {k: {"score": None, "evidence": None, "call_id": None, "call_date": None}
              for k in COMPONENT_KEYS}
    ordered = sorted(scored_calls, key=lambda r: (r.get("call_date") or ""))
    for row in ordered:
        comps = row.get("components") or {}
        for key in COMPONENT_KEYS:
            cell = comps.get(key) or {}
            if cell.get("score") is not None:
                rolled[key] = {
                    "score": cell["score"],
                    "evidence": cell.get("evidence"),
                    "call_id": row.get("call_id"),
                    "call_date": row.get("call_date"),
                }
    return rolled


def rollup_total(rolled):
    """Sum of non-null rolled component scores (the /70 headline). Null
    components contribute nothing."""
    return sum(v["score"] for v in rolled.values() if v.get("score") is not None)


def to_score_row(call_id, deal_id, call_date, result, text_source):
    """Build a call_scores row (matching migration 043) from a score_call result."""
    comps = result["components"]
    evidence = {k: comps[k]["evidence"] for k in COMPONENT_KEYS
                if comps[k]["score"] is not None and comps[k]["evidence"]}
    return {
        "call_id": str(call_id),
        "deal_id": str(deal_id) if deal_id else None,
        "call_date": call_date,
        "metrics_score": comps["metrics"]["score"],
        "economic_buyer_score": comps["economic_buyer"]["score"],
        "decision_criteria_score": comps["decision_criteria"]["score"],
        "decision_process_score": comps["decision_process"]["score"],
        "pain_score": comps["pain"]["score"],
        "champion_score": comps["champion"]["score"],
        "competition_score": comps["competition"]["score"],
        "evidence": json.dumps(evidence) if evidence else None,
        "text_source": text_source,
        "model": result.get("model") or "unknown",
        "scorer_version": SCORER_VERSION,
    }
