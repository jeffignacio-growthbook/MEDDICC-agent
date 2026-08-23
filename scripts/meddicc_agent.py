"""
MEDDICC Agent - Generator/Evaluator Loop

Generates MEDDICC analyses using Claude Sonnet 4.5 with iterative refinement
via Claude Haiku evaluator and reflection gate.
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict, Optional
from anthropic import Anthropic

# Add scripts directory to path for LLMClient
sys.path.insert(0, str(Path(__file__).parent))
from llm_client import LLMClient


def load_claude_md() -> str:
    """Load current CLAUDE.md instructions."""
    prompts_dir = Path(__file__).parent.parent / "prompts"
    claude_md_path = prompts_dir / "CLAUDE.md"

    with open(claude_md_path, 'r') as f:
        return f.read()


def load_evaluator_rubric() -> str:
    """Load evaluator rubric."""
    prompts_dir = Path(__file__).parent.parent / "prompts"
    rubric_path = prompts_dir / "evaluator_rubric.md"

    with open(rubric_path, 'r') as f:
        return f.read()


# Component label (as it appears in the generated markdown) → score key.
# Mirrors hubspot_deals._extract_scores_from_analysis so the values pinned here
# are exactly the values every downstream consumer parses back out of the draft.
_PIN_COMPONENTS = [
    ("Metrics", "metrics"),
    ("Economic Buyer", "economic_buyer"),
    ("Decision Criteria", "decision_criteria"),
    ("Decision Process", "decision_process"),
    ("Identified Pain", "pain"),
    ("Champion", "champion"),
    ("Competition", "competition"),
]


# Tolerant of markdown format variation between iterations: **Score**: 5/10,
# **Score:** 5/10, Score: 5 / 10, etc. \D*? absorbs any asterisks/colon/space
# between "Score" and the number. MUST match hubspot_deals._extract_scores_from_
# analysis so the pinned value equals the value every downstream consumer reads.
_SCORE_RE = r'Score\D*?(\d+)\s*/\s*10'


def _extract_component_scores(md: str) -> dict:
    """Parse each component's 'Score: N/10' from the analysis markdown."""
    import re
    out = {}
    for label, key in _PIN_COMPONENTS:
        m = re.search(rf'{re.escape(label)}.*?{_SCORE_RE}', md, re.DOTALL | re.IGNORECASE)
        out[key] = int(m.group(1)) if m else None
    return out


def _pin_score_lines(md: str, pinned: dict):
    """Rewrite each component's Score to the pinned iteration-1 value. Returns
    (new_md, mismatches) — mismatches lists components that could NOT be set to
    the pinned value (a drift the caller must catch, so a two-provenance artifact
    can never be stored silently)."""
    import re
    new_md = md
    for label, key in _PIN_COMPONENTS:
        target = pinned.get(key)
        if target is None:
            continue
        # Capture everything up to the number, the number, then the '/10' tail
        # (spaces allowed), and replace only the number.
        pat = rf'({re.escape(label)}.*?Score\D*?)(\d+)(\s*/\s*10)'
        new_md = re.subn(
            pat, lambda m, t=target: f"{m.group(1)}{t}{m.group(3)}",
            new_md, count=1, flags=re.DOTALL | re.IGNORECASE)[0]
    after = _extract_component_scores(new_md)
    mismatches = [key for _label, key in _PIN_COMPONENTS
                  if pinned.get(key) is not None and after.get(key) != pinned.get(key)]
    return new_md, mismatches


def build_initial_messages(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    previous_feedback: Optional[str] = None,
    pinned_scores: Optional[dict] = None
) -> list:
    """Build initial messages for generator."""

    # Format cumulative state
    cumulative_json = json.dumps(cumulative_state, indent=2)

    # Format deal context
    deal_props = deal_context.get('deal', {}).get('properties', {})
    company_props = deal_context.get('company', {}).get('properties', {}) if deal_context.get('company') else {}
    contacts = deal_context.get('contacts', [])

    # Safe ARR formatting (handle string values from HubSpot)
    arr_value = deal_props.get('incremental_arr', deal_props.get('amount', 0))
    try:
        arr_formatted = f"{float(arr_value):,.0f}"
    except (ValueError, TypeError):
        arr_formatted = str(arr_value)

    # Stage is deliberately EXCLUDED (Part 3): it is stale often enough to
    # corrupt the score, and the score must stay independent of stage so the
    # stage-vs-score hygiene comparison isn't circular.
    deal_info = f"""**Company**: {company_props.get('name', 'Unknown')}
**ARR**: ${arr_formatted}
**Close Date**: {deal_props.get('closedate', 'Unknown')}
**Contacts**: {len(contacts)} contacts associated"""

    # Build user message.
    # The score is a pure function of the call evidence + deal facts. ALL calls
    # (oldest → newest) are the evidence; the prior state is passed for change
    # description ONLY and must not move the score.
    user_content = f"""# All Calls for This Deal (oldest → newest)

SCORE EVERY MEDDICC COMPONENT ONLY FROM THE EVIDENCE IN THESE CALLS, plus the
deal facts below. Read all of them before scoring.

{call_summary}

---

# Prior MEDDICC State (previous run) — CONTEXT FOR CHANGE ONLY

This is last night's output. It is provided ONLY so you can describe what has
changed since then. It MUST NOT influence the scores. Score each component
fresh from the calls above as if you had never seen this. Do not anchor to,
average with, or defer to these numbers.

```json
{cumulative_json}
```

---

# Deal Context (from HubSpot)

{deal_info}

---

Generate a MEDDICC analysis following the format in your instructions."""

    if previous_feedback:
        user_content += f"""

---

# EVALUATOR FEEDBACK - PLEASE ADDRESS

The previous analysis failed evaluation. You must fix these issues:

{previous_feedback}

Regenerate the analysis addressing all the feedback above."""

    # Score-of-record is pinned to iteration 1 (FIX_MEDDICC_SCORING_PIPELINE):
    # regeneration exists to improve the WRITE-UP, never to re-derive numbers.
    # The evaluator only sees the draft (not independent evidence) and its
    # feedback is prescriptive about scores — obeying it made a temperature-0
    # score a function of the evaluator's objections, and moved components
    # across band boundaries (metrics 6→7, champion 5→2) between iterations.
    # So the locked values are listed explicitly and stated LAST, overriding any
    # score argument in the feedback above; the evidence must justify THESE
    # numbers, not argue for different ones. (Mirrors the Part-4 "score first,
    # then write the explanation" rule, now enforced across iterations too.)
    if pinned_scores:
        locked = "\n".join(
            f"- {label}: {pinned_scores[key]}/10"
            for label, key in _PIN_COMPONENTS if pinned_scores.get(key) is not None)
        user_content += f"""

---

# COMPONENT SCORES ARE FINAL — DO NOT CHANGE ANY NUMBER

These scores were decided on the first pass and are LOCKED. Reproduce every
Score line EXACTLY as below — do not raise or lower any of them, even if the
evaluator feedback argues otherwise:

{locked}

Your ONLY job now is to make the Evidence and Next Steps for each component
specific, actionable, and CONSISTENT WITH ITS LOCKED SCORE. If the feedback
says a score "should" be different, do NOT change the number — instead make the
evidence for the locked number clearer. The explanation serves the score; the
score never moves to match the explanation."""

    return [{"role": "user", "content": user_content}]


def generate(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    previous_feedback: Optional[str],
    claude_md: str,
    client: LLMClient,
    tracker=None,
    company: str = '',
    pinned_scores: Optional[dict] = None
) -> str:
    """
    Generate MEDDICC analysis using Claude Sonnet 4.6.

    Handles potential tool calls in inner loop.
    """
    messages = build_initial_messages(
        call_summary,
        cumulative_state,
        deal_context,
        previous_feedback,
        pinned_scores
    )

    # Inner tool loop (though MEDDICC generation shouldn't need tools)
    while True:
        response = client.complete(
            messages=messages,
            system=claude_md,
            max_tokens=4000,
            temperature=0,  # scoring must be deterministic, not a sample
        )

        if tracker:
            tracker.record(response,
                          model=client.model,
                          role="generator",
                          company=company)

        # Check stop reason
        if response.stop_reason == 'end_turn':
            # LLMResponse.text already contains the extracted text
            return response.text

        elif response.stop_reason == 'tool_use':
            # Handle tool calls (shouldn't happen for MEDDICC, but just in case)
            # Add assistant message (provider-agnostic)
            messages.append(response.as_assistant_message())

            # Add tool results - access raw.content for Anthropic content blocks
            tool_results = []
            if hasattr(response.raw, 'content'):
                for block in response.raw.content:
                    if hasattr(block, 'type') and block.type == 'tool_use':
                        # Reject tool use for MEDDICC
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Tool use not supported for MEDDICC analysis. Please generate the analysis directly."
                        })

            messages.append({"role": "user", "content": tool_results})

        else:
            # Max tokens or other stop reason - use response.text directly
            if not response.text:
                return "[Generation error: no text content returned]"

            return response.text


def _salvage_evaluation(content: str, err: str) -> dict:
    """Recover a usable evaluation from malformed evaluator JSON.

    The evaluator (Haiku) sometimes emits a long `required_changes` string with
    unescaped double quotes, which breaks json.loads. `pass` is a bare boolean
    (never quote-broken) so it recovers cleanly; `required_changes` is captured
    tolerantly — everything from its opening quote to the last quote before the
    closing brace/comma, embedded quotes and all — so the REAL critique is fed
    back to the generator instead of a generic 'parse error' placeholder.
    """
    import re
    passed = False
    m = re.search(r'"pass"\s*:\s*(true|false)', content, re.IGNORECASE)
    if m:
        passed = m.group(1).lower() == "true"

    required = None
    m = re.search(r'"required_changes"\s*:\s*"(.*)"\s*[,}]', content, re.DOTALL)
    if m:
        required = m.group(1).strip()

    def _list(key):
        mm = re.search(rf'"{key}"\s*:\s*\[(.*?)\]', content, re.DOTALL)
        if not mm:
            return []
        return [x.strip().strip('"\'') for x in mm.group(1).split(",") if x.strip()]

    return {
        "pass": passed,
        # Never leave this empty on a fail — the loop needs real feedback.
        "required_changes": required or (
            "Evaluator JSON was unparseable and no critique could be salvaged; "
            "regenerate for clarity and valid structure."),
        "iteration_failures": _list("iteration_failures") or (
            [] if passed else ["evaluator_json_salvaged"]),
        "components_weak": _list("components_weak"),
        "components_strong": _list("components_strong"),
        "proposed_instruction": None,
        "salvaged": True,          # marker so callers/telemetry can see it
        "parse_error": err,
        "raw_content": content[:4000],
    }


def evaluate(
    draft: str,
    call_summary: str,
    cumulative_state: dict,
    rubric: str,
    client: LLMClient,
    tracker=None,
    company: str = ''
) -> dict:
    """
    Evaluate MEDDICC analysis using Claude Haiku.

    Returns evaluation result with pass/fail and feedback.
    """
    # Use the provided evaluator client (Haiku)

    cumulative_json = json.dumps(cumulative_state, indent=2)

    evaluation_prompt = f"""# Generated MEDDICC Analysis to Evaluate

{draft}

---

# Recent Call Summary (source material)

{call_summary}

---

# Cumulative MEDDICC State (historical context)

```json
{cumulative_json}
```

---

Evaluate this analysis against the rubric.

CRITICAL: Return ONLY a valid JSON object. Do NOT include any explanatory text, markdown formatting, or commentary. Start your response with {{ and end with }}. The JSON must be valid and parseable."""

    response = client.complete(
        messages=[{"role": "user", "content": evaluation_prompt}],
        system=rubric + "\n\nIMPORTANT: You must return ONLY valid JSON. No "
               "explanations, no markdown, no text outside the JSON object. "
               "Inside \"required_changes\", do NOT use the double-quote "
               "character — quote any phrase with single quotes ' instead — "
               "and keep it under ~1500 characters. Unescaped double quotes "
               "are the #1 cause of invalid evaluator JSON.",
        max_tokens=4000,
        temperature=0,  # evaluator gates `passed` and drives regeneration —
                        # its variance would leak back into the score
    )

    if tracker:
        tracker.record(response,
                      model=client.model,
                      role="evaluator",
                      company=company)

    # Extract JSON from response
    content = response.text

    try:
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        # Find JSON object boundaries (handle text before/after JSON)
        if '{' in content and '}' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            content = content[start:end]

        evaluation = json.loads(content)

        # Validate structure
        required_keys = ['pass', 'required_changes', 'iteration_failures',
                        'components_weak', 'components_strong', 'proposed_instruction']

        for key in required_keys:
            if key not in evaluation:
                evaluation[key] = None if key in ['required_changes', 'proposed_instruction'] else []

        return evaluation

    except json.JSONDecodeError as e:
        # SALVAGE rather than discard. The evaluator's own verbose critiques
        # break json.loads (unescaped double quotes inside required_changes,
        # ~2KB in). The old path replaced the real critique with a generic
        # "Evaluator parse error" string — so the regeneration loop ran on
        # meaningless feedback, defeating the coaching gate it exists to serve
        # (and, worse, still perturbed scores). Recover pass + the actual
        # critique text with tolerant regex so the loop gets the real feedback.
        print(f"⚠️  Evaluator JSON invalid ({e}); salvaging pass + required_changes")
        return _salvage_evaluation(content, str(e))


def reflect(
    evaluation: dict,
    iterations: int,
    passed: bool,
    tracker=None,
    company: str = ''
) -> dict:
    """
    Reflection gate: decide if this execution should generate a learning.

    Most runs should return no_learning. That is the correct default.

    Returns reflection result with outcome and root_cause.
    """
    # Use classifier client (Haiku) for reflection
    client = LLMClient.from_config("classifier")

    system_prompt = """You are a reflection gate for a MEDDICC analysis agent.
Decide whether this execution should generate a learning entry.

Rules:
- If the agent passed on the first iteration with no issues: outcome = no_learning
- If failure was caused by missing data, bad transcript, customer anomaly,
  or model limitation: outcome = no_learning
- If failure was likely caused by an instruction gap in CLAUDE.md that a
  better instruction could have prevented: outcome = observation or candidate
- candidate requires clear, specific evidence the instruction would generalize
- observation means worth tracking but needs more evidence across multiple companies
- Code or API errors: outcome = bug
- CLAUDE.md format/structure issues: outcome = prompt_issue

Additionally, evaluate the evaluator rubric itself.
If the agent failed (passed == false or iterations > 1):
  - Which specific criterion name caused the failure?
  - Was that criterion appropriate given the available call data?
  - If not appropriate, what should it say instead?
If the agent passed on first try, set criterion_fired to null.

Return ONLY valid JSON:
{
  "outcome": "no_learning | observation | candidate | bug | prompt_issue",
  "root_cause": "instruction_gap | missing_data | customer_anomaly | model_limitation | edge_case | no_failure",
  "claude_md_would_help": true | false,
  "reasoning": "one sentence max",
  "rubric_observation": {
    "criterion_fired": "criterion name or null",
    "was_appropriate": true | false,
    "suggested_change": "proposed new wording or null"
  }
}"""

    reflection_input = {
        "evaluation": evaluation,
        "iterations": iterations,
        "passed": passed
    }

    user_message = f"""Execution summary:
{json.dumps(reflection_input, indent=2)}

Should this generate a learning entry? Return ONLY valid JSON."""

    try:
        response = client.complete(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            max_tokens=500
        )

        if tracker:
            tracker.record(response,
                          model=client.model,
                          role="reflection",
                          company=company)

        content = response.text

        # Extract JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        if '{' in content and '}' in content:
            start = content.find('{')
            end = content.rfind('}') + 1
            content = content[start:end]

        reflection = json.loads(content)

        # Validate required keys
        required = ['outcome', 'root_cause', 'claude_md_would_help', 'reasoning', 'rubric_observation']
        for key in required:
            if key not in reflection:
                raise ValueError(f"Missing required key: {key}")

        return reflection

    except Exception as e:
        print(f"⚠️  Reflection parse failed: {e}")
        # Default to no_learning on parse error
        return {
            "outcome": "no_learning",
            "root_cause": "parse_error",
            "claude_md_would_help": False,
            "reasoning": "Reflection parse failed",
            "rubric_observation": {
                "criterion_fired": None,
                "was_appropriate": False,
                "suggested_change": None
            }
        }


def run_agent(
    call_summary: str,
    cumulative_state: dict,
    deal_context: dict,
    claude_md: str = None,
    rubric: str = None,
    max_iterations: int = 3,
    tracker=None,
    company: str = ''
) -> dict:
    """
    Run MEDDICC agent with generator/evaluator loop.

    Returns final analysis with evaluation metadata.
    """
    # Create role-specific clients
    generator_client = LLMClient.from_config("generator")
    evaluator_client = LLMClient.from_config("evaluator")

    # Load prompts if not provided
    if claude_md is None:
        claude_md = load_claude_md()

    if rubric is None:
        rubric = load_evaluator_rubric()

    # Outer loop: max 3 iterations
    previous_feedback = None
    draft = None
    evaluation = None
    pinned_scores = None   # locked to iteration 1's component scores (below)

    for iteration in range(1, max_iterations + 1):
        print(f"  Iteration {iteration}/{max_iterations}...")

        # Generate analysis. From iteration 2 on, pinned_scores carries the
        # iteration-1 numbers so regeneration refines prose without moving them.
        draft = generate(
            call_summary,
            cumulative_state,
            deal_context,
            previous_feedback,
            claude_md,
            generator_client,
            tracker,
            company,
            pinned_scores
        )

        # Lock the score-of-record to iteration 1 — the only regime the
        # determinism work characterised. Later iterations may improve the
        # write-up but must not move these numbers.
        if iteration == 1:
            pinned_scores = _extract_component_scores(draft)
            missing = [k for _l, k in _PIN_COMPONENTS if pinned_scores.get(k) is None]
            if missing:
                print(f"  ⚠️  pin: iteration-1 score not found for {missing} "
                      "(those components won't be pinned)")

        # Evaluate analysis
        evaluation = evaluate(
            draft,
            call_summary,
            cumulative_state,
            rubric,
            evaluator_client,
            tracker,
            company
        )

        # Check if passed
        if evaluation['pass']:
            print(f"  ✓ Passed on iteration {iteration}")
            break

        # Extract feedback for next iteration
        previous_feedback = evaluation.get('required_changes')
        failures = evaluation.get('iteration_failures', [])
        print(f"  ✗ Failed iteration {iteration}: {len(failures)} issues")

        # Debug: show rejection details
        print(f"     Quality score: {evaluation.get('quality_score', 'N/A')}/100")
        if failures:
            print(f"     Failed criteria: {', '.join(failures)}")
        if evaluation.get('required_changes'):
            print(f"     Changes needed: {evaluation.get('required_changes', '')[:200]}")

    # Hard guarantee: if we regenerated, the stored draft's Score lines must
    # equal iteration 1's, whatever the model wrote. The prompt asks it to keep
    # them; this enforces it so an LLM drift can't silently ship a two-provenance
    # artifact (iteration-3 narrative under iteration-1 numbers that don't match).
    scores_pinned = False
    pin_mismatches = []
    if iteration > 1 and pinned_scores and any(v is not None for v in pinned_scores.values()):
        draft, pin_mismatches = _pin_score_lines(draft, pinned_scores)
        scores_pinned = True
        if pin_mismatches:
            # Could not force these components to the pinned value — surface it
            # loudly rather than store a contradictory artifact.
            print(f"  ⚠️  pin: FAILED to lock {pin_mismatches} to iteration-1 "
                  "values; stored draft may not match the pinned scores")
        else:
            print(f"  ✓ scores pinned to iteration 1 across {iteration} iterations")

    # Run reflection gate to decide if this should generate a learning
    passed = evaluation['pass'] if evaluation else False
    reflection = reflect(evaluation, iteration, passed, tracker, company)

    # Return final result with reflection
    return {
        'draft': draft,
        'evaluation': evaluation,
        'iterations': iteration,
        'passed': passed,
        'pinned_scores': pinned_scores,
        'scores_pinned': scores_pinned,
        'pin_mismatches': pin_mismatches,
        'outcome': reflection['outcome'],
        'root_cause': reflection['root_cause'],
        'rubric_observation': reflection.get('rubric_observation', {}),
        'model_used': {
            'generator': 'claude-sonnet-4-5-20250929',
            'evaluator': 'claude-haiku-4-5-20251001',
            'reflector': 'claude-haiku-4-5-20251001'
        }
    }


if __name__ == "__main__":
    # Test with sample data
    test_call_summary = """# Technical Deep Dive - Acme Corp
Date: 2026-07-25 | Duration: 45m

## Summary
Deep dive with Sarah Chen (VP Engineering) and Mark Liu (Tech Lead). Covered SDK quality, visual editor requirements, and SSO/SAML needs. Mark very excited about our SDK vs LaunchDarkly. Sarah mentioned John Torres (CFO) makes final vendor decisions. Budget approved for $100k solution if ROI is clear.

## Keywords
SDK quality, visual editor, experimentation, SSO, SAML, budget approval

## Action Items
- Create POC environment for Mark's team
- Schedule CFO meeting with John Torres
- Provide security questionnaire responses"""

    test_cumulative_state = {
        "company": "Acme Corp",
        "calls_reviewed": 2,
        "meddicc_state": {
            "metrics": {
                "status": "identified",
                "evidence": "Sarah mentioned $500k annual loss from failed experiments in Call #1",
                "score": 8
            },
            "economic_buyer": {
                "status": "identified",
                "evidence": "John Torres (CFO) confirmed as final decision maker",
                "score": 9
            },
            "decision_criteria": {
                "status": "partial",
                "evidence": "Need visual editor, SSO/SAML mentioned but not fully detailed",
                "score": 5
            },
            "decision_process": {
                "status": "partial",
                "evidence": "CFO approval needed for >$50k, timeline Q4 planning in September",
                "score": 6
            },
            "identified_pain": {
                "status": "identified",
                "evidence": "Feature flagging complexity and LaunchDarkly pricing frustration",
                "score": 8
            },
            "champion": {
                "status": "partial",
                "evidence": "Mark Liu (Tech Lead) very excited, but not confirmed as champion",
                "score": 5
            },
            "competition": {
                "status": "identified",
                "evidence": "Currently using LaunchDarkly, frustrated with pricing",
                "score": 8
            }
        },
        "key_context": "Mid-stage technical evaluation with strong champion (Mark) and identified economic buyer (John Torres CFO). Clear pain around LaunchDarkly cost and complexity."
    }

    test_deal_context = {
        "deal": {
            "properties": {
                "dealname": "Acme Corp - Feature Flags",
                "dealstage": "presentationscheduled",
                "incremental_arr": "95000",
                "closedate": "2026-09-15"
            }
        },
        "company": {
            "properties": {
                "name": "Acme Corp",
                "domain": "acme.com",
                "numberofemployees": "250"
            }
        },
        "contacts": [
            {"properties": {"firstname": "Sarah", "lastname": "Chen", "jobtitle": "VP Engineering"}},
            {"properties": {"firstname": "Mark", "lastname": "Liu", "jobtitle": "Tech Lead"}},
            {"properties": {"firstname": "John", "lastname": "Torres", "jobtitle": "CFO"}}
        ]
    }

    print("=" * 80)
    print("TESTING MEDDICC AGENT")
    print("=" * 80)

    result = run_agent(
        call_summary=test_call_summary,
        cumulative_state=test_cumulative_state,
        deal_context=test_deal_context
    )

    print("\n" + "=" * 80)
    print("FINAL RESULT")
    print("=" * 80)
    print(f"Iterations: {result['iterations']}")
    print(f"Passed: {result['passed']}")
    print(f"Weak components: {result['evaluation'].get('components_weak', [])}")
    print(f"Strong components: {result['evaluation'].get('components_strong', [])}")

    print("\n" + "=" * 80)
    print("GENERATED ANALYSIS")
    print("=" * 80)
    print(result['draft'])
    print("=" * 80)
