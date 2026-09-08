#!/usr/bin/env python3
"""
LLM Candidate Generator — Phase 2b

Translates plain-language metric descriptions into candidate queries,
then feeds them into Phase 2a's proven backtest engine.

CRITICAL: This module ONLY generates candidates. All filtering, iteration,
and convergence logic stays in the proven backtest_engine.py.

NO IMPLICIT FILTERING in this module - all hygiene rules must be explicit
and traceable to registry selections made by the backtest engine.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Any
from dotenv import load_dotenv
import anthropic

# Load environment
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# SCHEMA DOCUMENTATION FOR LLM
# ============================================================================

SCHEMA_CONTEXT = """
# Supabase Database Schema (GrowthBook CRM)

## Primary Table: deals

Key columns:
- deal_id: Unique identifier (text)
- company_name: Customer/prospect name (text)
- stage: Current deal stage (text) - use field_semantics.is_won(stage) to check if won
- deal_status: 'active', 'won', 'lost' (text)
- pipeline_id: Pipeline identifier (text) - '866608541' is renewal pipeline
- create_date: Deal creation date (timestamp)
- close_date: Deal close date (timestamp)
- deal_value: Incremental ARR (new + expansion) (numeric)
- arr_usd: Total ARR (numeric)
- new_arr: New business ARR component (numeric)
- expansion_arr: Expansion ARR component (numeric)
- renewal_revenue: Renewal base ARR (numeric)

## Important Business Rules

**DO NOT hardcode these in your query** - the backtest engine will apply them:
- Renewals should be excluded from new-business metrics (pipeline_id != '866608541')
- Invalid cycle time deals should be excluded (create_date <= close_date)
- Test/bulk cleanup deals should be excluded (various criteria)

Your job: Generate the NAIVE query based on plain language. Let the backtest
engine's hygiene rules handle the filtering.

## Helper Functions Available

From api/field_semantics.py:
- is_won(stage: str) -> bool: True if deal is won
- is_lost(stage: str) -> bool: True if deal is lost
- is_open(stage: str) -> bool: True if deal is still open
- is_renewal_base(deal: dict) -> bool: True if renewal deal
- is_valid_cycle_deal(deal: dict) -> bool: True if valid cycle time data

CRITICAL: Do NOT call these functions in your SQL generation. Your query should
be written in terms of raw SQL filters. The backtest engine will apply Python-side
filtering based on registry rules.
"""


# ============================================================================
# LLM CANDIDATE GENERATOR
# ============================================================================

def generate_candidate_query(
    metric_description: str,
    anthropic_client: anthropic.Anthropic
) -> Dict[str, Any]:
    """
    Generate a candidate query from plain-language metric description.

    This is EXPECTED to produce a naive interpretation on first try.
    The backtest engine will handle iteration and hygiene rules.

    Args:
        metric_description: Plain language description (e.g., "what percentage of deals do we win")
        anthropic_client: Anthropic client for LLM calls

    Returns:
        Candidate specification with:
        - metric_type: 'percentage', 'median_days', 'sum_dollars', etc.
        - population_filter: Dict describing which deals to include
        - computation: Dict describing how to calculate the metric
        - reasoning: LLM's explanation of its interpretation
    """

    prompt = f"""You are generating a SQL query specification to answer a business question about sales deals.

METRIC QUESTION:
{metric_description}

DATABASE SCHEMA:
{SCHEMA_CONTEXT}

TASK:
Generate a query specification (NOT actual SQL code) that describes:
1. Which deals to include (population filter)
2. How to calculate the metric (computation)

CRITICAL INSTRUCTIONS:
- Provide a NAIVE, straightforward interpretation of the question
- Do NOT try to anticipate or apply business hygiene rules (like excluding renewals)
- Do NOT filter out edge cases or outliers
- The backtest engine will handle all filtering based on a registry of hygiene rules

OUTPUT FORMAT (JSON):
{{
    "metric_type": "percentage|median_days|sum_dollars|count",
    "population_filter": {{
        "deal_status": "won|lost|active|all",
        "pipeline_filter": "all|new_business_only|renewals_only",
        "date_range": "all_time|specific_period",
        "additional_filters": []
    }},
    "computation": {{
        "numerator": "description of what to count/sum in numerator",
        "denominator": "description of what to count/sum in denominator (if percentage)",
        "aggregation": "median|mean|sum|count"
    }},
    "reasoning": "Brief explanation of your interpretation"
}}

Generate the specification now:"""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": prompt
        }]
    )

    # Parse response
    response_text = response.content[0].text

    # Extract JSON from response (may be wrapped in markdown)
    import re
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        spec = json.loads(json_match.group(0))
    else:
        raise ValueError(f"Could not parse JSON from LLM response: {response_text}")

    return spec


def translate_spec_to_python_function(spec: Dict[str, Any]) -> str:
    """
    Translate LLM's specification into executable Python function.

    This generates code that will be executed by the backtest engine.
    CRITICAL: No implicit filtering - only what spec explicitly requests.

    Args:
        spec: LLM-generated specification

    Returns:
        Python code as string
    """

    metric_type = spec['metric_type']
    population = spec['population_filter']
    computation = spec['computation']

    code_lines = [
        "def calculate_metric(deals):",
        "    \"\"\"LLM-generated metric calculation.\"\"\"",
        "    from datetime import datetime",
        "    from api.field_semantics import is_won, is_lost, is_open",
        "",
        "    # Population filter (naive interpretation)",
    ]

    # Generate population filter
    if population.get('deal_status') == 'won':
        code_lines.append("    deals = [d for d in deals if is_won(d.get('stage'))]")
    elif population.get('deal_status') == 'lost':
        code_lines.append("    deals = [d for d in deals if is_lost(d.get('stage'))]")
    elif population.get('deal_status') == 'active':
        code_lines.append("    deals = [d for d in deals if is_open(d.get('stage'))]")

    # Pipeline filter (if specified)
    if population.get('pipeline_filter') == 'new_business_only':
        code_lines.append("    # NOTE: This is NAIVE - not filtering renewals yet")
        code_lines.append("    # Backtest engine will apply exclude_renewals rule")

    code_lines.append("")
    code_lines.append("    # Computation")

    # Generate computation based on metric type
    if metric_type == 'percentage':
        code_lines.extend([
            "    # Calculate percentage",
            f"    numerator = len([d for d in deals if <numerator_condition>])",
            f"    denominator = len(deals)",
            "    if denominator == 0:",
            "        return None, 0",
            "    percentage = (numerator / denominator) * 100",
            "    return round(percentage, 1), denominator"
        ])
    elif metric_type == 'median_days':
        code_lines.extend([
            "    # Calculate median cycle time",
            "    cycle_times = []",
            "    for deal in deals:",
            "        try:",
            "            create_date = datetime.fromisoformat(deal['create_date'].replace('Z', '+00:00'))",
            "            close_date = datetime.fromisoformat(deal['close_date'].replace('Z', '+00:00'))",
            "            cycle_days = (close_date - create_date).days",
            "            # NO IMPLICIT FILTERING - include ALL cycle times",
            "            cycle_times.append(cycle_days)",
            "        except:",
            "            continue",
            "    ",
            "    if not cycle_times:",
            "        return None, 0",
            "    ",
            "    sorted_times = sorted(cycle_times)",
            "    n = len(sorted_times)",
            "    median = sorted_times[n // 2] if n % 2 == 1 else (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2",
            "    return round(median, 1), n"
        ])
    elif metric_type == 'sum_dollars':
        code_lines.extend([
            "    # Calculate sum of deal values",
            "    total = sum(d.get('deal_value', 0) or 0 for d in deals)",
            "    return round(total, 2), len(deals)"
        ])

    return "\n".join(code_lines)


# ============================================================================
# INTEGRATION WITH PHASE 2A ENGINE
# ============================================================================

def run_llm_backtest(
    metric_description: str,
    ground_truth: Dict[str, Any],
    anthropic_client: anthropic.Anthropic,
    sb_client  # Supabase client
) -> Dict[str, Any]:
    """
    Full Phase 2b flow: LLM generation → Phase 2a backtest.

    Args:
        metric_description: Plain language metric description
        ground_truth: Known correct value and metadata
        anthropic_client: Anthropic client
        sb_client: Supabase client

    Returns:
        Complete audit trail from generation through convergence (or non-convergence)
    """

    print("="*80)
    print("PHASE 2B: LLM-DRIVEN METRIC GENERATION + BACKTEST")
    print("="*80)
    print()
    print(f"Metric Description: {metric_description}")
    print(f"Ground Truth: {ground_truth['correct_value']} {ground_truth['unit']}")
    print()

    # Step 1: LLM generates candidate specification
    print("-"*80)
    print("STEP 1: LLM Candidate Generation")
    print("-"*80)
    print()

    spec = generate_candidate_query(metric_description, anthropic_client)

    print("LLM-Generated Specification:")
    print(json.dumps(spec, indent=2))
    print()
    print(f"Reasoning: {spec.get('reasoning')}")
    print()

    # Step 2: Translate spec to executable function
    # (For this proof-of-concept, we'll use a hardcoded implementation
    # that matches the expected metrics - win_rate or pipeline_value)

    print("-"*80)
    print("STEP 2: Execute Naive Candidate")
    print("-"*80)
    print()

    # For proof-of-concept: Execute the naive query and get baseline result
    # This would normally use the generated function, but for this demo
    # we'll implement win_rate and pipeline_value directly

    metric_type = ground_truth.get('metric_name')

    if metric_type == 'win_rate':
        naive_result = calculate_naive_win_rate(sb_client)
    elif metric_type == 'pipeline_value':
        naive_result = calculate_naive_pipeline_value(sb_client)
    else:
        raise ValueError(f"Unknown metric type: {metric_type}")

    print(f"Naive result: {naive_result['value']} {ground_truth['unit']} (n={naive_result['sample_size']})")
    print()

    # Step 3: Compare to ground truth
    print("-"*80)
    print("STEP 3: Compare to Ground Truth")
    print("-"*80)
    print()

    expected = ground_truth['correct_value']
    actual = naive_result['value']
    tolerance = ground_truth.get('tolerance', 3)

    if actual is None:
        delta = None
        converged = False
    else:
        delta = abs(actual - expected)
        converged = delta <= tolerance

    print(f"Expected: {expected} {ground_truth['unit']}")
    print(f"Actual: {actual} {ground_truth['unit']}")
    delta_str = f"{delta:.1f}" if delta is not None else "N/A"
    print(f"Delta: {delta_str} {ground_truth['unit']}")
    print(f"Tolerance: ±{tolerance} {ground_truth['unit']}")
    print()

    if converged:
        print("✓ CONVERGED: Naive interpretation happened to be correct")
        print()
        print("This is unexpected - usually naive interpretation is contaminated.")
        print("Verify ground truth and contamination assumptions.")
        return {
            "converged": True,
            "iterations": 0,
            "llm_spec": spec,
            "naive_result": naive_result,
            "ground_truth": ground_truth
        }

    print("✗ MISMATCH: Naive interpretation contaminated (expected)")
    print()
    print("This is the CORRECT baseline - naive LLM interpretation should be wrong.")
    print("Now feeding to Phase 2a backtest engine for registry-driven iteration...")
    print()

    # Step 4: Feed to Phase 2a engine (would call backtest_engine.py here)
    # For this proof-of-concept, document what would happen

    print("-"*80)
    print("STEP 4: Phase 2a Iteration (Integration Point)")
    print("-"*80)
    print()
    print("At this point, the naive candidate would be fed to:")
    print("  scripts/backtest_engine.py (unchanged from Phase 2a)")
    print()
    print("Expected behavior:")
    print("  1. Load hygiene rules from config/field_semantics.yaml")
    print("  2. Detect mismatch (naive result != ground truth)")
    print("  3. Apply first hygiene rule from registry")
    print("  4. Re-execute and compare")
    print("  5. Iterate until convergence or rules exhausted")
    print()
    print("NON-CONVERGENCE HANDLING:")
    print("  If all rules exhausted and still no convergence:")
    print("  - STOP (do not let LLM generate new candidates)")
    print("  - Surface full diagnostic to human for review")
    print("  - Preserves 'propose, human confirms' discipline")
    print()

    return {
        "converged": False,
        "requires_iteration": True,
        "llm_spec": spec,
        "naive_result": naive_result,
        "ground_truth": ground_truth,
        "next_step": "Feed to Phase 2a backtest engine"
    }


# ============================================================================
# NAIVE METRIC IMPLEMENTATIONS (For Proof-of-Concept)
# ============================================================================

def calculate_naive_win_rate(sb) -> Dict[str, Any]:
    """
    Calculate win rate the NAIVE way (includes all deals, no filtering).

    This is the contaminated baseline the LLM would naturally produce.
    Expected: ~3.7% (wrong - includes bulk cleanup, pre-2023 legacy)
    Clean: ~15.2% (correct - excludes contamination)
    """
    from api.field_semantics import is_won, is_lost

    # Fetch ALL deals (no filtering)
    all_deals = sb.table("deals").select("deal_id,stage").execute()

    won = [d for d in all_deals.data if is_won(d.get("stage"))]
    lost = [d for d in all_deals.data if is_lost(d.get("stage"))]

    total_closed = len(won) + len(lost)

    if total_closed == 0:
        return {"value": None, "sample_size": 0, "error": "No closed deals"}

    win_rate = (len(won) / total_closed) * 100

    return {
        "value": round(win_rate, 1),
        "sample_size": total_closed,
        "won_count": len(won),
        "lost_count": len(lost),
        "interpretation": "Naive - includes all deals without hygiene filtering"
    }


def calculate_naive_pipeline_value(sb) -> Dict[str, Any]:
    """
    Calculate pipeline value the NAIVE way (includes renewals, all active deals).

    This is the contaminated baseline the LLM would naturally produce.
    Expected: Includes renewal base ARR (wrong)
    Clean: Incremental ARR only (correct)
    """
    from api.field_semantics import is_open

    # Fetch ALL active deals (no filtering)
    all_deals = sb.table("deals").select(
        "deal_id,stage,deal_value,new_arr,expansion_arr,renewal_revenue,pipeline_id"
    ).execute()

    active = [d for d in all_deals.data if is_open(d.get("stage"))]

    # Naive interpretation: sum ALL deal_value
    total = sum(d.get("deal_value", 0) or 0 for d in active)

    return {
        "value": round(total, 2),
        "sample_size": len(active),
        "interpretation": "Naive - includes all active deals, possibly including renewal base"
    }


# ============================================================================
# MAIN (Demo)
# ============================================================================

def main():
    """Demonstrate Phase 2b with win_rate test case."""

    print("PHASE 2B — LLM-Driven Metric Generation")
    print("Proof-of-concept demonstration")
    print()

    # Initialize clients
    anthropic_client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    from supabase import create_client
    sb = create_client(
        os.environ['SUPABASE_URL'],
        os.environ['SUPABASE_SERVICE_KEY']
    )

    # Test case: pipeline_value (naive interpretation includes renewals - known wrong)
    metric_description = "What is the total value of our open pipeline?"

    # Clean pipeline (incremental ARR only, excluding renewals)
    # Naive will include renewal base ARR which should be excluded
    ground_truth = {
        "metric_name": "pipeline_value",
        "correct_value": 7_160_865,  # Clean: $7.2M (excludes renewal pipeline)
        "unit": "dollars",
        "tolerance": 100_000,  # $100K tolerance
        "validated_by": "Session analysis + calculate_pipeline_ground_truth.py (2026-09-07)",
        "contamination_expected": "Naive includes renewal base ARR ~$14.2M (should only count incremental: new + expansion ~$7.2M)",
        "expected_naive": 14_221_230,  # Naive includes renewals
        "contamination_amount": 7_060_365,  # $7M contamination (49.6%)
    }

    # Run LLM → backtest flow
    result = run_llm_backtest(
        metric_description,
        ground_truth,
        anthropic_client,
        sb
    )

    # Output summary
    print("="*80)
    print("PHASE 2B RESULT")
    print("="*80)
    print()

    if result['converged']:
        print("✓ Converged on first try (unexpected)")
    else:
        print("✗ Naive candidate contaminated (expected)")
        print()
        print("Next step: Feed to Phase 2a backtest engine for iteration")

    print()
    print("Full result:")
    print(json.dumps({k: v for k, v in result.items() if k != 'llm_spec'}, indent=2, default=str))


if __name__ == '__main__':
    main()
