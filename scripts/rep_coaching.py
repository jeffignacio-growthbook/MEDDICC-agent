#!/usr/bin/env python3
"""
Rep Coaching Assessor — per-deal diagnostic for actionable coaching moments.

Answers: "What should a manager coach this rep on, based on this specific
deal's most recent call?" Composes three criteria into a single per-deal
coaching judgment:

  Criterion A: Did the rep advance a weak-and-concerning MEDDICC component
               during the most recent transcript-scored call (diff-against-
               roll-up logic: call_scorer.roll_up(), stage_scoring_expectations
               concerning_threshold, call_scores.evidence).

  Criterion B: Did discovery questions map to stage_focus_questions for the
               weak components, and for Champion specifically, did the rep
               attempt to elicit champion_behavior_criteria's genuine_champion
               signals (LLM read via Haiku of transcript against reference lists).

  Criterion C: Talk-time/question-share diagnostic from coaching_talk_ratio.py
               (Apollo-sourced calls only, explicitly source_not_supported for
               Fireflies/Gong).

Design decisions (confirmed 2026-09-19):
  - Hard transcript gate: only produce coaching judgment for deals with at
    least one call_scores row where text_source='transcript'. Zero transcripts
    → insufficient_data/no_transcript_available, not fabricated.
  - Permanent coverage disclosure: embed query_coaching_transcript_coverage()
    sentence unconditionally in every output (not conditional on gate firing).
  - Criterion C is diagnostic-only (no pass/fail threshold), permanently
    labeled as such. Fireflies/Gong explicitly return source_not_supported
    within this deal's output, never silently omitted.

Read-only. No writes.
"""
import sys
from pathlib import Path
from datetime import date
from typing import Optional, Dict, Any
import logging

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))

logger = logging.getLogger(__name__)

# Import after path setup
from analytics.forecast_analyses import query_coaching_transcript_coverage
from field_semantics import stage_bucket
from rubric import band_label
from call_scorer import roll_up, COMPONENT_KEYS, COMPONENT_LABELS
from llm_client import LLMClient
import yaml
import json


def _load_stage_scoring_expectations():
    """Load stage_scoring_expectations from coaching_client.yaml."""
    config_path = REPO_ROOT / "config" / "coaching_client.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"coaching_client.yaml not found at {config_path}")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("stage_scoring_expectations", {})


def _compute_weak_components(sb, deal_id: str, target_call_id: str,
                              target_call_date: str) -> Dict[str, Any]:
    """Step 0 (shared): identify weak-and-concerning components for this deal.

    Args:
        sb: Supabase client
        deal_id: Deal to assess
        target_call_id: The most recent transcript-scored call (from Step 2)
        target_call_date: Date of the target call

    Returns:
        {"stage_bucket": str,
         "pre_call_rollup": {component: {score, evidence, call_id, call_date}},
         "weak_components": [component_key, ...],
         "component_bands": {component_key: band_label_result}}
    """
    from supabase_client import select_all

    # 1. Get deal's current stage
    deal = sb.table("deals").select("stage").eq("deal_id", str(deal_id)).execute()
    if not deal.data:
        raise ValueError(f"Deal {deal_id} not found in deals table")
    stage = deal.data[0].get("stage")
    bucket = stage_bucket(stage) if stage else "unknown"

    # 2. Load stage scoring expectations
    expectations = _load_stage_scoring_expectations()
    stage_expectations = expectations.get(bucket, {})

    # 3. Get all call_scores for this deal BEFORE the target call
    all_calls = select_all(
        sb, "call_scores",
        columns="call_id,deal_id,call_date,text_source,"
                "metrics_score,economic_buyer_score,decision_criteria_score,"
                "decision_process_score,pain_score,champion_score,competition_score,"
                "evidence",
        filters=[("eq", "deal_id", str(deal_id))]
    )

    # Filter to calls before the target call (exclude target call itself)
    pre_calls = [c for c in all_calls
                 if c.get("call_date") and c["call_date"] < target_call_date]

    # 4. Transform call_scores rows into format for roll_up()
    scored_calls = []
    for row in pre_calls:
        components = {
            "metrics": {"score": row.get("metrics_score"),
                        "evidence": (row.get("evidence") or {}).get("metrics")},
            "economic_buyer": {"score": row.get("economic_buyer_score"),
                               "evidence": (row.get("evidence") or {}).get("economic_buyer")},
            "decision_criteria": {"score": row.get("decision_criteria_score"),
                                  "evidence": (row.get("evidence") or {}).get("decision_criteria")},
            "decision_process": {"score": row.get("decision_process_score"),
                                 "evidence": (row.get("evidence") or {}).get("decision_process")},
            "pain": {"score": row.get("pain_score"),
                     "evidence": (row.get("evidence") or {}).get("pain")},
            "champion": {"score": row.get("champion_score"),
                         "evidence": (row.get("evidence") or {}).get("champion")},
            "competition": {"score": row.get("competition_score"),
                            "evidence": (row.get("evidence") or {}).get("competition")},
        }
        scored_calls.append({
            "call_id": row["call_id"],
            "call_date": row.get("call_date"),
            "components": components
        })

    # 5. Compute pre-call baseline via roll_up()
    pre_call_rollup = roll_up(scored_calls)

    # 6. Band each component and flag weak-and-concerning ones
    weak_components = []
    component_bands = {}
    for comp_key in COMPONENT_KEYS:
        score = pre_call_rollup[comp_key]["score"]
        band_result = band_label(comp_key, score)
        component_bands[comp_key] = band_result

        # Check if this component is weak-and-concerning for this stage
        comp_label = COMPONENT_LABELS[comp_key]
        comp_expectations = stage_expectations.get(comp_label, {})
        concerning_threshold = comp_expectations.get("concerning_threshold")

        if concerning_threshold and band_result["band"] != "unread":
            # Component is concerning if its band matches or is worse than threshold
            # Band order: red < yellow < green
            band_order = {"red": 0, "yellow": 1, "green": 2}
            component_band_order = band_order.get(band_result["band"], -1)
            threshold_band_order = band_order.get(concerning_threshold, -1)

            if component_band_order >= 0 and threshold_band_order >= 0:
                if component_band_order <= threshold_band_order:
                    weak_components.append(comp_key)

    return {
        "stage_bucket": bucket,
        "pre_call_rollup": pre_call_rollup,
        "weak_components": weak_components,
        "component_bands": component_bands
    }


def _assess_criterion_a(sb, deal_id: str, target_call_id: str,
                        weak_components: list, pre_call_rollup: Dict,
                        component_bands: Dict) -> Dict[str, Any]:
    """Criterion A: Did the rep advance any weak-and-concerning component
    during the most recent transcript-scored call?

    Args:
        sb: Supabase client
        deal_id: Deal being assessed
        target_call_id: The most recent transcript-scored call
        weak_components: List of component keys that are weak-and-concerning
        pre_call_rollup: Pre-call MEDDICC baseline (from Step 0)
        component_bands: Pre-call band labels (from Step 0)

    Returns:
        {"advancements": [{component, prior_band, this_call_band, advanced, evidence}, ...],
         "note": str}
    """
    # Get the target call's call_scores row
    target_call = sb.table("call_scores").select(
        "call_id,metrics_score,economic_buyer_score,decision_criteria_score,"
        "decision_process_score,pain_score,champion_score,competition_score,evidence"
    ).eq("call_id", target_call_id).execute()

    if not target_call.data:
        return {
            "status": "insufficient_data",
            "reason": "target_call_not_in_call_scores",
            "note": f"Target call {target_call_id} not found in call_scores table"
        }

    target_row = target_call.data[0]

    # If no weak components, return empty list (not an error)
    if not weak_components:
        return {
            "advancements": [],
            "note": ("No weak-and-concerning components identified at this deal's "
                     "current stage — nothing for the rep to advance.")
        }

    # For each weak component, check if this call advanced it
    advancements = []
    band_order = {"red": 0, "yellow": 1, "green": 2, "unread": -1}

    for comp_key in weak_components:
        # Get this call's score for this component
        score_field = f"{comp_key}_score"
        this_call_score = target_row.get(score_field)

        # Band this call's score
        this_call_band_result = band_label(comp_key, this_call_score)
        this_call_band = this_call_band_result["band"]

        # Get prior band
        prior_band = component_bands[comp_key]["band"]

        # Check if band improved
        prior_order = band_order.get(prior_band, -1)
        this_call_order = band_order.get(this_call_band, -1)

        # Advanced if: non-null score AND band improved
        advanced = (this_call_score is not None and
                    this_call_order > prior_order)

        # Get evidence
        evidence = (target_row.get("evidence") or {}).get(comp_key)

        advancements.append({
            "component": comp_key,
            "component_label": COMPONENT_LABELS[comp_key],
            "prior_band": prior_band,
            "this_call_band": this_call_band,
            "this_call_score": this_call_score,
            "advanced": advanced,
            "evidence": evidence
        })

    return {
        "advancements": advancements,
        "note": ("Criterion A evaluates whether the rep advanced weak-and-concerning "
                 "MEDDICC components during the most recent call.")
    }


def _assess_criterion_b(sb, deal_id: str, target_call_id: str,
                        weak_components: list, stage_bucket: str) -> Dict[str, Any]:
    """Criterion B: Did the rep ask discovery questions mapped to stage_focus_questions,
    and for Champion specifically, attempt to elicit genuine_champion signals?

    Args:
        sb: Supabase client
        deal_id: Deal being assessed
        target_call_id: The most recent transcript-scored call
        weak_components: List of component keys that are weak-and-concerning
        stage_bucket: Stage bucket from Step 0

    Returns:
        {"question_mapping": [{component, question_asked, evidence_quote_or_absence_note}, ...],
         "note": str}
    """
    from supabase_client import select_all

    # If no weak components, return empty list
    if not weak_components:
        return {
            "question_mapping": [],
            "note": ("No weak-and-concerning components to assess for discovery "
                     "question mapping.")
        }

    # Get the target call's transcript
    transcript_row = sb.table("call_transcripts").select(
        "call_id,transcript,transcript_quality"
    ).eq("call_id", target_call_id).execute()

    if not transcript_row.data:
        return {
            "status": "insufficient_data",
            "reason": "transcript_not_found",
            "note": f"Transcript for call {target_call_id} not found in call_transcripts"
        }

    row = transcript_row.data[0]
    transcript = row.get("transcript")
    quality = row.get("transcript_quality")

    if not transcript or quality not in ["full", "partial"]:
        return {
            "status": "insufficient_data",
            "reason": "transcript_unusable",
            "note": f"Transcript quality '{quality}' not usable for question mapping"
        }

    # Load stage_focus_questions and champion_behavior_criteria
    config_path = REPO_ROOT / "config" / "coaching_client.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    stage_questions = config.get("stage_focus_questions", {}).get(stage_bucket, {})
    champion_criteria = config.get("champion_behavior_criteria", {})
    genuine_signals = champion_criteria.get("genuine_champion", {}).get("signals", [])

    # Assess each weak component
    question_mapping = []
    llm = LLMClient.from_config("assessor")  # Haiku for classification

    for comp_key in weak_components:
        comp_label = COMPONENT_LABELS[comp_key]
        questions = stage_questions.get(comp_label, [])

        if not questions:
            question_mapping.append({
                "component": comp_key,
                "component_label": comp_label,
                "question_asked": None,
                "evidence_quote_or_absence_note": (
                    f"No stage_focus_questions defined for {comp_label} at "
                    f"{stage_bucket} stage")
            })
            continue

        # Build LLM prompt - constrained to THIS list, not inventing
        # TRANSCRIPT LIMIT: 100k chars (captures 100% of avg 31k-char transcript,
        # uses only 12.5% of Haiku's 200k-token/~800k-char input capacity).
        # Previous 8k limit dropped 74.5% of content, silently cutting late-call
        # champion elicitation attempts and closing questions - exactly the signals
        # Criterion B needs to detect.
        prompt = f"""You are analyzing a sales call transcript to determine if the sales rep asked discovery questions for the "{comp_label}" component.

Here are the EXACT questions we're looking for (from our coaching framework for {stage_bucket} stage):
{chr(10).join(f'- {q}' for q in questions)}

TRANSCRIPT:
{transcript[:100000]}

YOUR TASK:
Did the rep ask a question that is substantively equivalent to ANY of the questions listed above? Answer in JSON format:

{{
  "question_asked": true/false,
  "evidence_quote_or_absence_note": "If true: direct quote from transcript showing the question. If false: brief note explaining the absence (e.g., 'Rep never addressed {comp_label} topic')"
}}

IMPORTANT:
- Only return true if the rep asked something substantively equivalent to one of the LISTED questions above
- Do NOT invent your own idea of a good question - stick to the provided list
- Return the actual quote from the transcript as evidence if found
- Be precise: paraphrase doesn't count unless the substance matches"""

        # Champion-specific: also check for genuine_champion signals
        if comp_key == "champion" and genuine_signals:
            prompt += f"""

ADDITIONAL CHECK FOR CHAMPION:
Also assess whether the rep attempted to elicit ANY of these genuine champion behaviors:
{chr(10).join(f'- {s}' for s in genuine_signals)}

In your response, if the rep asked about champion behaviors (e.g., "Would you be comfortable introducing me to the EB?"), note that in the evidence."""

        # Call LLM with graceful error handling
        try:
            response = llm.call([{"role": "user", "content": prompt}])
            result_text = response.text.strip()

            # Parse JSON response
            # Try to extract JSON from markdown code fence if present
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            result = json.loads(result_text)

            question_mapping.append({
                "component": comp_key,
                "component_label": comp_label,
                "question_asked": result.get("question_asked"),
                "evidence_quote_or_absence_note": result.get("evidence_quote_or_absence_note", "")
            })

        except json.JSONDecodeError as e:
            logger.warning(f"[REP_COACHING] Criterion B: JSON parse failed for {comp_label}: {e}")
            question_mapping.append({
                "component": comp_key,
                "component_label": comp_label,
                "question_asked": None,
                "evidence_quote_or_absence_note": (
                    f"LLM response parsing failed: {str(e)[:100]}")
            })
        except Exception as e:
            logger.error(f"[REP_COACHING] Criterion B: LLM call failed for {comp_label}: {e}")
            question_mapping.append({
                "component": comp_key,
                "component_label": comp_label,
                "question_asked": None,
                "evidence_quote_or_absence_note": (
                    f"LLM call error: {str(e)[:100]}")
            })

    return {
        "question_mapping": question_mapping,
        "note": ("Criterion B evaluates whether the rep asked discovery questions "
                 "mapped to stage_focus_questions, and for Champion, whether they "
                 "attempted to elicit genuine_champion signals.")
    }


def assess_rep_coaching(sb, deal_id: str, as_of: Optional[date] = None) -> Dict[str, Any]:
    """
    Per-deal coaching assessment composing three criteria.

    Args:
        sb: Supabase client
        deal_id: HubSpot deal_id to assess
        as_of: Optional date for point-in-time assessment (defaults to today)

    Returns:
        {"status": "insufficient_data", "reason": str, "note": str}
      or:
        {"status": "ok",
         "criterion_a": {...},  # MEDDICC component advancement
         "criterion_b": {...},  # Discovery question mapping
         "criterion_c": {...},  # Talk-time diagnostic (Apollo only)
         "coverage_note": str,  # Permanent transcript coverage disclosure
         "note": str}
    """
    from sdr_utils import today_in_reporting_tz
    from supabase_client import select_all

    if as_of is None:
        as_of = today_in_reporting_tz()

    # STEP 2: Hard transcript gate - only assess deals with transcript-scored calls
    # Query call_scores for this deal where text_source='transcript', ordered by
    # call_date descending to find the most recent one.
    transcript_calls = select_all(
        sb,
        "call_scores",
        columns="call_id,deal_id,call_date,text_source",
        filters=[
            ("eq", "deal_id", str(deal_id)),
            ("eq", "text_source", "transcript")
        ]
    )

    # STEP 3: Coverage disclosure (permanent, unconditional)
    coverage_note = query_coaching_transcript_coverage(sb)

    if not transcript_calls:
        # Zero transcript-scored calls → insufficient_data, short-circuit immediately
        logger.info(f"[REP_COACHING] deal_id={deal_id} has zero transcript-scored calls, gated")
        return {
            "status": "insufficient_data",
            "reason": "no_transcript_available",
            "note": (
                "This deal has no call_scores rows where text_source='transcript'. "
                "Rep coaching requires at least one transcript-scored call to assess "
                "MEDDICC component advancement, discovery question mapping, and "
                "talk-time diagnostics. This is a data-availability gate, not a "
                "quality judgment."
            ),
            "coverage_note": coverage_note
        }

    # Sort by call_date descending to identify the most recent transcript-scored call
    transcript_calls.sort(key=lambda r: r.get("call_date") or "", reverse=True)
    most_recent_call = transcript_calls[0]
    target_call_id = most_recent_call["call_id"]
    target_call_date = most_recent_call.get("call_date")

    logger.info(f"[REP_COACHING] deal_id={deal_id} has {len(transcript_calls)} "
                f"transcript-scored call(s), targeting most recent: "
                f"call_id={target_call_id}, call_date={target_call_date}")

    # STEP 4: Criterion A - MEDDICC component advancement
    # Step 0 (shared): compute weak-and-concerning components
    try:
        weak_analysis = _compute_weak_components(
            sb, deal_id, target_call_id, target_call_date)
    except Exception as e:
        logger.error(f"[REP_COACHING] Step 0 (weak components) failed: {e}")
        return {
            "status": "insufficient_data",
            "reason": "weak_component_computation_failed",
            "note": f"Failed to compute weak components: {str(e)}",
            "coverage_note": coverage_note
        }

    # Criterion A: component advancement assessment
    try:
        criterion_a = _assess_criterion_a(
            sb, deal_id, target_call_id,
            weak_analysis["weak_components"],
            weak_analysis["pre_call_rollup"],
            weak_analysis["component_bands"]
        )
    except Exception as e:
        logger.error(f"[REP_COACHING] Criterion A failed: {e}")
        return {
            "status": "insufficient_data",
            "reason": "criterion_a_failed",
            "note": f"Failed to assess Criterion A: {str(e)}",
            "coverage_note": coverage_note
        }

    # STEP 5: Criterion B - discovery question mapping
    try:
        criterion_b = _assess_criterion_b(
            sb, deal_id, target_call_id,
            weak_analysis["weak_components"],
            weak_analysis["stage_bucket"]
        )
    except Exception as e:
        logger.error(f"[REP_COACHING] Criterion B failed: {e}")
        return {
            "status": "insufficient_data",
            "reason": "criterion_b_failed",
            "note": f"Failed to assess Criterion B: {str(e)}",
            "coverage_note": coverage_note
        }

    # STEP 6: Criterion C (to be implemented)

    return {
        "status": "insufficient_data",
        "reason": "criterion_c_not_yet_implemented",
        "note": f"Criteria A-B complete, Criterion C pending",
        "target_call_id": target_call_id,
        "target_call_date": target_call_date,
        "transcript_call_count": len(transcript_calls),
        "stage_bucket": weak_analysis["stage_bucket"],
        "weak_components": weak_analysis["weak_components"],
        "criterion_a": criterion_a,
        "criterion_b": criterion_b,
        "coverage_note": coverage_note
    }


if __name__ == "__main__":
    # Basic smoke test
    from supabase_client import create_resilient_supabase_client
    import os

    sb = create_resilient_supabase_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"]
    )

    # Test with a known deal
    result = assess_rep_coaching(sb, "test_deal_id")
    print(f"Result: {result}")
