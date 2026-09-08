#!/usr/bin/env python3
"""
Generalized Backtest Engine — Multi-metric support.

Extends backtest_engine.py to support:
- sum_dollars (pipeline value, deal value aggregates)
- median_days (cycle time)
- percentage (win rate)

Integration point for Phase 2b LLM-generated candidates.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from supabase import create_client, Client
from dotenv import load_dotenv
import yaml

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.field_semantics import is_renewal_base, is_valid_cycle_deal, is_won, is_open


# ============================================================================
# METRIC TYPE HANDLERS
# ============================================================================

def execute_sum_dollars_query(
    sb: Client,
    query_spec: Dict[str, Any],
    population_filter: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute sum aggregation query (e.g., pipeline value, ARR).

    Args:
        sb: Supabase client
        query_spec: Query specification with applied rules
        population_filter: What deals to include (active, won, etc.)

    Returns:
        Execution result with total value, sample size
    """
    print(f"\nExecuting sum_dollars query: {query_spec['description']}")
    print(f"Applied rules: {query_spec['applied_rules'] or 'none'}")

    # Fetch deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,stage,deal_value,pipeline_id,renewal_revenue"
    ).execute()

    print(f"  Total deals in database: {len(all_deals.data)}")

    # Apply population filter
    deal_status = population_filter.get("deal_status", "active")
    if deal_status == "active":
        deals = [d for d in all_deals.data if is_open(d.get("stage"))]
    elif deal_status == "won":
        deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    else:
        deals = all_deals.data

    print(f"  After {deal_status} filter: {len(deals)} deals")

    # Apply hygiene rules
    RENEWAL_PIPELINE_ID = "866608541"

    if query_spec.get('exclude_renewals'):
        deals = [d for d in deals if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]
        print(f"  After exclude_renewals: {len(deals)} deals")

    # Calculate sum
    total_value = sum(d.get("deal_value", 0) or 0 for d in deals)

    print(f"  Total value: ${total_value:,.2f} (n={len(deals)})")

    return {
        "total_dollars": total_value,
        "sample_size": len(deals),
        "deals": [{"deal_id": d["deal_id"], "company_name": d.get("company_name")} for d in deals[:5]]
    }


def execute_median_days_query(
    sb: Client,
    query_spec: Dict[str, Any],
    population_filter: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute median calculation query (e.g., cycle time).

    Args:
        sb: Supabase client
        query_spec: Query specification with applied rules
        population_filter: What deals to include

    Returns:
        Execution result with median days, sample size
    """
    print(f"\nExecuting median_days query: {query_spec['description']}")
    print(f"Applied rules: {query_spec['applied_rules'] or 'none'}")

    # Fetch deals
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,pipeline_id,renewal_revenue,stage"
    ).execute()

    print(f"  Total deals in database: {len(all_deals.data)}")

    # Apply population filter
    deal_status = population_filter.get("deal_status", "won")
    if deal_status == "won":
        deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    else:
        deals = all_deals.data

    print(f"  After {deal_status} filter: {len(deals)} deals")

    # Apply hygiene rules
    RENEWAL_PIPELINE_ID = "866608541"

    if query_spec.get('exclude_renewals'):
        deals = [d for d in deals if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]
        print(f"  After exclude_renewals: {len(deals)} deals")

    if query_spec.get('exclude_invalid_cycle'):
        deals = [d for d in deals if is_valid_cycle_deal(d)]
        print(f"  After exclude_invalid_cycle: {len(deals)} deals")

    # Calculate cycle times
    cycle_times = []
    for deal in deals:
        try:
            create_date_str = deal.get("create_date")
            close_date_str = deal.get("close_date")

            if not create_date_str or not close_date_str:
                continue

            if isinstance(create_date_str, str):
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
            else:
                create_date = create_date_str

            if isinstance(close_date_str, str):
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
            else:
                close_date = close_date_str

            cycle_days = (close_date - create_date).days

            # NO implicit filtering - include ALL values
            cycle_times.append(cycle_days)

        except (ValueError, AttributeError, TypeError):
            continue

    if not cycle_times:
        return {
            "median_days": None,
            "sample_size": 0,
            "error": "No valid cycle times calculated"
        }

    # Compute median
    sorted_times = sorted(cycle_times)
    n = len(sorted_times)
    median = sorted_times[n // 2] if n % 2 == 1 else (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2

    print(f"  Median cycle time: {median:.1f} days (n={n})")

    return {
        "median_days": round(median, 1),
        "sample_size": n,
        "cycle_times": sorted_times[:10]
    }


# ============================================================================
# GENERIC BACKTEST ENGINE
# ============================================================================

def run_generalized_backtest(
    sb: Client,
    metric_spec: Dict[str, Any],
    ground_truth: Dict[str, Any],
    hygiene_rules: List[Dict[str, Any]],
    tolerance: float,
    max_iterations: int = 10
) -> Dict[str, Any]:
    """
    Run generalized backtest iteration for any metric type.

    Args:
        sb: Supabase client
        metric_spec: Metric specification from LLM or manual definition
        ground_truth: Expected value and configuration
        hygiene_rules: Available hygiene rules from registry
        tolerance: Convergence tolerance (metric-specific)
        max_iterations: Stop after this many iterations

    Returns:
        Complete iteration audit trail
    """
    metric_type = metric_spec.get("metric_type")
    population_filter = metric_spec.get("population_filter", {})

    # Select execution function based on metric type
    if metric_type == "sum_dollars":
        execute_fn = execute_sum_dollars_query
        value_key = "total_dollars"
    elif metric_type == "median_days":
        execute_fn = execute_median_days_query
        value_key = "median_days"
    else:
        raise ValueError(f"Unsupported metric type: {metric_type}")

    iteration_history = []
    converged = False
    iteration = 0

    # Get applicable hygiene rules
    required_rules = ground_truth.get('hygiene_requirements', [])
    applicable_rules = [r for r in hygiene_rules if r['name'] in required_rules]

    print(f"\n{'='*80}")
    print(f"GENERALIZED BACKTEST: {ground_truth.get('metric_name', 'Unknown')}")
    print(f"Metric type: {metric_type}")
    print(f"Ground truth: {ground_truth.get('correct_value')}")
    print(f"Tolerance: ±{tolerance}")
    print(f"Applicable hygiene rules: {[r['name'] for r in applicable_rules]}")
    print(f"{'='*80}")

    # Iteration 0: Naive candidate (no hygiene rules)
    print(f"\n{'─'*80}")
    print(f"ITERATION {iteration}: Naive candidate (no hygiene rules)")
    print(f"{'─'*80}")

    applied_rules = []
    query_spec = {
        "applied_rules": applied_rules,
        "exclude_renewals": False,
        "exclude_invalid_cycle": False,
        "description": "naive (no hygiene rules)"
    }

    result = execute_fn(sb, query_spec, population_filter)
    actual_value = result.get(value_key)
    expected_value = ground_truth.get('correct_value')

    if actual_value is None:
        delta = None
        passed = False
    else:
        delta = abs(actual_value - expected_value)
        passed = delta <= tolerance

    diagnosis = ""
    if passed:
        diagnosis = f"✓ CONVERGED: {actual_value} within tolerance of {expected_value}"
    else:
        diagnosis = f"✗ MISMATCH: {actual_value} vs expected {expected_value} (Δ = {delta})"

    iteration_record = {
        "iteration": iteration,
        "candidate_description": query_spec['description'],
        "applied_rules": applied_rules,
        "result": result,
        "actual_value": actual_value,
        "expected_value": expected_value,
        "delta": delta,
        "converged": passed,
        "diagnosis": diagnosis
    }
    iteration_history.append(iteration_record)

    print(f"\n{diagnosis}")

    if passed:
        converged = True
        print(f"\n✓ Converged on iteration {iteration}")
        return {
            "converged": True,
            "iterations": iteration_history,
            "final_result": result,
            "ground_truth": ground_truth
        }

    # Subsequent iterations: Apply hygiene rules one by one
    for rule_idx, rule in enumerate(applicable_rules, start=1):
        if iteration >= max_iterations:
            print(f"\n⚠️  Reached max iterations ({max_iterations}), stopping")
            break

        iteration += 1
        applied_rules.append(rule['name'])

        print(f"\n{'─'*80}")
        print(f"ITERATION {iteration}: Apply {rule['name']}")
        print(f"  Rule: {rule['description']}")
        print(f"{'─'*80}")

        query_spec = {
            "applied_rules": applied_rules.copy(),
            "exclude_renewals": "exclude_renewals" in applied_rules,
            "exclude_invalid_cycle": "exclude_invalid_cycle_time" in applied_rules,
            "description": f"{' + '.join(applied_rules)}"
        }

        result = execute_fn(sb, query_spec, population_filter)
        actual_value = result.get(value_key)

        if actual_value is None:
            delta = None
            passed = False
        else:
            delta = abs(actual_value - expected_value)
            passed = delta <= tolerance

        diagnosis = ""
        if passed:
            diagnosis = f"✓ CONVERGED: {actual_value} within tolerance of {expected_value}"
        else:
            diagnosis = f"✗ MISMATCH: {actual_value} vs expected {expected_value} (Δ = {delta})"

        iteration_record = {
            "iteration": iteration,
            "candidate_description": query_spec['description'],
            "applied_rules": applied_rules.copy(),
            "new_rule_applied": rule['name'],
            "rule_function": rule['function'],
            "result": result,
            "actual_value": actual_value,
            "expected_value": expected_value,
            "delta": delta,
            "converged": passed,
            "diagnosis": diagnosis
        }
        iteration_history.append(iteration_record)

        print(f"\n{diagnosis}")

        if passed:
            converged = True
            print(f"\n✓ Converged on iteration {iteration}")
            print(f"✓ Successful hygiene rules: {applied_rules}")
            break

    # Final result
    if not converged:
        print(f"\n✗ Did NOT converge after {iteration} iterations")
        print(f"✗ Final delta: {delta} (tolerance: {tolerance})")

    return {
        "converged": converged,
        "iterations": iteration_history,
        "final_result": result if iteration_history else None,
        "ground_truth": ground_truth,
        "total_iterations": iteration,
        "metric_type": metric_type
    }


# ============================================================================
# FORMATTING
# ============================================================================

def format_generalized_audit_trail(backtest_result: Dict[str, Any]) -> str:
    """Format backtest result as human-readable audit trail."""
    lines = []
    lines.append("="*80)
    lines.append("GENERALIZED BACKTEST ENGINE — AUDIT TRAIL")
    lines.append("="*80)
    lines.append("")

    gt = backtest_result['ground_truth']
    lines.append(f"Metric: {gt.get('metric_name', 'Unknown')}")
    lines.append(f"Metric type: {backtest_result.get('metric_type')}")
    lines.append(f"Description: {gt.get('description', 'N/A')}")
    lines.append(f"Ground truth: {gt.get('correct_value')}")
    lines.append("")

    lines.append("─"*80)
    lines.append("ITERATION HISTORY")
    lines.append("─"*80)
    lines.append("")

    for record in backtest_result['iterations']:
        lines.append(f"Iteration {record['iteration']}: {record['candidate_description']}")
        lines.append(f"  Applied rules: {record['applied_rules'] or 'none'}")

        if 'new_rule_applied' in record:
            lines.append(f"  NEW RULE: {record['new_rule_applied']} ({record['rule_function']})")

        lines.append(f"  Result: {record['actual_value']} (n={record['result'].get('sample_size')})")
        lines.append(f"  Expected: {record['expected_value']}")

        if record['delta'] is not None:
            lines.append(f"  Delta: {record['delta']}")

        lines.append(f"  Status: {'✓ CONVERGED' if record['converged'] else '✗ MISMATCH'}")
        lines.append("")

    lines.append("─"*80)
    lines.append("FINAL RESULT")
    lines.append("─"*80)
    lines.append("")

    if backtest_result['converged']:
        lines.append("✓ CONVERGED")
        final_iter = backtest_result['iterations'][-1]
        lines.append(f"  Converged on iteration: {final_iter['iteration']}")
        lines.append(f"  Final value: {final_iter['actual_value']} (n={final_iter['result'].get('sample_size')})")
        lines.append(f"  Applied rules: {final_iter['applied_rules']}")
        lines.append("")
        lines.append("Validated query ready for production use.")
    else:
        lines.append("✗ DID NOT CONVERGE")
        lines.append(f"  Total iterations: {backtest_result['total_iterations']}")
        final_iter = backtest_result['iterations'][-1]
        lines.append(f"  Final delta: {final_iter['delta']}")
        lines.append("")
        lines.append("⚠️  NON-CONVERGENCE DETECTED")
        lines.append("Action required: Human review needed")
        lines.append("")
        lines.append("Possible causes:")
        lines.append("  - Missing hygiene rule (not in registry)")
        lines.append("  - Incorrect ground truth")
        lines.append("  - Data quality issue")
        lines.append("")
        lines.append("DO NOT attempt unsupervised LLM iteration.")
        lines.append("Surface this diagnostic to human for review.")

    lines.append("")
    lines.append("="*80)

    return "\n".join(lines)


# ============================================================================
# HELPER: LOAD HYGIENE RULES
# ============================================================================

def load_hygiene_rules() -> List[Dict[str, Any]]:
    """Load known hygiene rules from config/field_semantics.yaml."""
    config_path = Path(__file__).parent.parent / "config" / "field_semantics.yaml"

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    rules = config.get("known_hygiene_rules", [])

    if not rules:
        print("⚠️  WARNING: No known_hygiene_rules found in field_semantics.yaml")
        return []

    print(f"✓ Loaded {len(rules)} hygiene rules from registry")
    for rule in rules:
        print(f"  - {rule['name']}: {rule['function']}")

    return rules


if __name__ == '__main__':
    print("Generalized backtest engine loaded.")
    print("Use run_generalized_backtest() to test metrics of any type.")
