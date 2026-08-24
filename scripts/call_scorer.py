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
SCORER_VERSION = "phase1-percall-v3-twopass"

COMPONENT_LABELS = {k: label for label, k in COMPONENTS}

# Two passes. Prompt-level "return null when a call says nothing" does NOT make a
# model abstain — handed a rich transcript and a seven-field form, it fills every
# field (empirically: null never fired on Livesport across two prompt revisions).
# So abstention is its own step: PASS 1 SELECTS the components this call
# materially advances (a selection task, which models DO abstain on); PASS 2
# scores ONLY those. Everything unselected is null by construction, not by the
# model's willingness to say null.

GATE_SYSTEM_PROMPT = """\
You are given ONE sales call (transcript or summary) and nothing else. Your only
job is to decide which of the seven MEDDICC components THIS call MATERIALLY
ADVANCES — i.e. this call adds specific, new, substantive evidence about the
component, not just a passing mention or a restatement.

The seven components (use these exact keys):
  metrics             — quantified business impact / value metrics
  economic_buyer      — who controls budget; confirmed authority; buyer-owned approval steps
  decision_criteria   — the stated requirements / evaluation criteria
  decision_process    — timeline, stakeholders, approval steps
  pain                — the problem, its urgency and business impact
  champion            — a person taking internal action to advance the deal
  competition         — competitors, incumbent tools, evaluation status

Return a JSON array of the component keys this call materially advances, and
NOTHING else. Example: ["pain", "metrics", "competition"]

Be strict. MOST calls advance only ONE to FOUR components. A narrow call (a
pricing negotiation, a technical deep-dive) advances very few. If the call only
mentions a component in passing, or merely repeats something without adding new
evidence, DO NOT include it. An empty array [] is valid if the call advances
nothing. Do not consider the deal's pipeline stage.
"""

SCORE_SYSTEM_PROMPT = """\
You are given ONE sales call and a specific list of MEDDICC components that this
call materially advances. Score ONLY those components, 0-10, each with evidence
(a direct quote or specific fact FROM THIS CALL). Judge only what THIS call
establishes — you have no prior calls.

Return a JSON object whose keys are exactly the components you were asked to
score, each {"score": <1-10 integer>, "evidence": "<quote/fact from this call>"}.
No other keys, no prose, no markdown fences.

RULES
- Default to the LOWER score on ambiguity. Enthusiasm without specifics = 1/10.
- Score Champion and Economic Buyer on what the buyer DOES, not how they FELT.
  A contact who sounds excited but owns no internal next step is Champion 1-2.
- Do NOT consider the deal's pipeline stage; it is not provided and must not be inferred.

SCORING CALIBRATION
Metrics:            9-10 quantified metric; 7-8 clear business impact; 5-6 pain mentioned not quantified; 3-4 vague; 1-2 barely.
Economic Buyer:     9-10 direct engagement + budget authority confirmed; 7-8 named + budget holder confirmed; 5-6 role unclear on budget; 3-4 generic "leadership"; 1-2 name/title only.
Decision Criteria:  9-10 formal criteria/scorecard; 7-8 key criteria stated; 5-6 some criteria incomplete; 3-4 vague requirements; 1-2 barely.
Decision Process:   9-10 full timeline + stakeholders + approvals; 7-8 timeline and key stakeholders; 5-6 timeline OR stakeholders; 3-4 vague timing; 1-2 barely.
Identified Pain:    9-10 specific urgent pain w/ impact + timeline; 7-8 clear pain w/ context; 5-6 pain not urgent/specific; 3-4 generic interest; 1-2 barely.
Champion:           9-10 active internal selling / business case; 7-8 facilitating access, owns next steps; 5-6 engaged not selling; 3-4 responsive but passive; 1-2 no owned internal action.
Competition:        9-10 full landscape + eval status + our differentiation; 7-8 current tool + limitations; 5-6 competitor mentioned, limited detail; 3-4 vague "other tools"; 1-2 barely.
"""


def _company_header(deal_context):
    if deal_context:
        company = (deal_context.get("company") or deal_context.get("company_name") or "").strip()
        if company:
            return f"Company: {company}\n\n"
    return ""


def build_gate_messages(call_text, deal_context=None):
    return [{
        "role": "user",
        "content": (
            f"{_company_header(deal_context)}Which MEDDICC components does this call "
            f"materially advance? Return the JSON array only.\n\n=== CALL ===\n{call_text}"
        ),
    }]


def build_score_messages(call_text, components, deal_context=None):
    keys = ", ".join(components)
    return [{
        "role": "user",
        "content": (
            f"{_company_header(deal_context)}Score ONLY these components for this call: "
            f"{keys}. Return the JSON object with exactly those keys.\n\n=== CALL ===\n{call_text}"
        ),
    }]


def _parse_advanced(text):
    """Parse PASS 1's JSON array into a list of valid component keys (order
    preserved, de-duped, unknown keys dropped). Tolerant of fences/prose."""
    if not text:
        return []
    obj = _extract_json_value(text, "[", "]")
    if not isinstance(obj, list):
        return []
    seen, out = set(), []
    for item in obj:
        k = str(item).strip().lower()
        if k in COMPONENT_KEYS and k not in seen:
            seen.add(k)
            out.append(k)
    return out


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
    """First balanced {...} object in text, JSON-parsed. Returns None on failure."""
    obj = _extract_json_value(text, "{", "}")
    return obj if isinstance(obj, dict) else None


def _extract_json_value(text, open_ch="{", close_ch="}"):
    """First balanced JSON value delimited by open_ch/close_ch, parsed. Handles
    ```json fences and trailing commentary. Returns the parsed value or None."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find(open_ch)
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        if t[i] == open_ch:
            depth += 1
        elif t[i] == close_ch:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except Exception:
                    return None
    return None


def score_call(call_text, deal_context=None, client=None):
    """Score one call in two passes (see the GATE/SCORE prompts above):
      1. SELECT the components this call materially advances.
      2. SCORE only those; everything else is null by construction.

    Returns:
        {"components": {key: {"score": int|None, "evidence": str|None}},
         "advanced": [keys selected in pass 1],
         "model": str, "input_tokens": int, "output_tokens": int}
    Raises ValueError on empty input (a call with no text cannot be scored —
    that is an 'unavailable' condition the caller handles, not a null score)."""
    if not call_text or not call_text.strip():
        raise ValueError("score_call: empty call_text")
    if client is None:
        from llm_client import LLMClient
        client = LLMClient.from_config("generator")

    components = {k: {"score": None, "evidence": None} for k in COMPONENT_KEYS}
    tok_in = tok_out = 0
    model = None

    # PASS 1 — selection (abstention happens here, not in the scoring pass).
    gate = client.complete(
        messages=build_gate_messages(call_text, deal_context),
        system=GATE_SYSTEM_PROMPT,
        max_tokens=200,
        temperature=0,
    )
    tok_in += getattr(gate, "input_tokens", 0) or 0
    tok_out += getattr(gate, "output_tokens", 0) or 0
    model = getattr(gate, "model", None)
    advanced = _parse_advanced(gate.text)

    # PASS 2 — score only the selected components.
    if advanced:
        score = client.complete(
            messages=build_score_messages(call_text, advanced, deal_context),
            system=SCORE_SYSTEM_PROMPT,
            max_tokens=1200,
            temperature=0,
        )
        tok_in += getattr(score, "input_tokens", 0) or 0
        tok_out += getattr(score, "output_tokens", 0) or 0
        model = getattr(score, "model", None) or model
        parsed = parse_call_scores(score.text)
        # Keep only the selected components; a stray extra key from pass 2 is ignored.
        for k in advanced:
            components[k] = parsed[k]

    return {
        "components": components,
        "advanced": advanced,
        "model": model,
        "input_tokens": tok_in,
        "output_tokens": tok_out,
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
