#!/usr/bin/env python3
"""
Backtest Engine — Standalone validation loop for metric definitions.

Proves the TEST/COMPARE/REPORT cycle works before wiring to Slack intent system.

Usage:
    python scripts/backtest_engine.py

Test case:
    cycle_time — Known correct answer: 52 days median (non-renewal won deals)
    Starts with deliberately naive candidate (116 days, contaminated)
    Iterates using registry-driven hygiene rules until convergence

Architecture:
    1. Load metric spec and ground truth periods
    2. Load known hygiene rules from config/field_semantics.yaml
    3. Start with naive candidate (no exclusions)
    4. Execute against Supabase → actual result
    5. Compare to ground truth → pass/fail per period
    6. If mismatch: apply next hygiene rule from registry
    7. Iterate until convergence OR exhausted all rules
    8. Output: audit trail with full iteration history

Registry-driven approach:
    Does NOT hardcode "try excluding renewals" as literal candidates.
    Instead reads hygiene rules from field_semantics.yaml and applies
    them systematically. This generalizes to multi-client deployments
    where each client has different hygiene needs.
"""

import os
import sys
import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import field semantics
from api.field_semantics import is_renewal_base, is_valid_cycle_deal, is_won


# ============================================================================
# CONFIGURATION
# ============================================================================

TOLERANCE_DAYS = 3  # Convergence if within ±3 days of ground truth
MAX_ITERATIONS = 10  # Stop after this many attempts


# ============================================================================
# GROUND TRUTH DEFINITION
# ============================================================================

GROUND_TRUTH = {
    "metric_name": "cycle_time",
    "description": "Median days from deal created_at to close_date for won deals",
    "correct_value": 52,  # days
    "unit": "days",
    "validated_by": "Jeff (Q016 investigation, Sep 2026)",

    # Ground truth periods to validate against
    "periods": [
        {
            "name": "All-time",
            "filter": {"deal_status": "won"},  # All won deals
            "expected_median": 52,
            "note": "Non-renewal won deals, all-time window"
        },
        # Can add more periods for multi-period validation:
        # {"name": "FY2027 Q1", "filter": {...}, "expected_median": 48},
        # {"name": "FY2026 Q4", "filter": {...}, "expected_median": 54},
    ],

    "hygiene_requirements": [
        "exclude_renewals",
        "exclude_invalid_cycle_time"
    ],

    "contaminated_result": {
        "value": 116,
        "cause": "Renewal pipeline contamination (30.5% of won deals)",
        "note": "Result before applying hygiene rules"
    }
}


# ============================================================================
# HYGIENE RULES REGISTRY LOADER
# ============================================================================

def load_hygiene_rules() -> List[Dict[str, Any]]:
    """
    Load known hygiene rules from config/field_semantics.yaml.

    Returns:
        List of hygiene rule specs from registry
    """
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


# ============================================================================
# CANDIDATE QUERY GENERATOR
# ============================================================================

def generate_candidate_spec(applied_rules: List[str]) -> Dict[str, Any]:
    """
    Generate query specification based on which hygiene rules are applied.

    Args:
        applied_rules: List of hygiene rule names to apply

    Returns:
        Query spec with filters and description
    """
    descriptions = []

    # Base population: won deals only
    descriptions.append("won deals only")

    # Build filter spec
    exclude_renewals = "exclude_renewals" in applied_rules
    exclude_invalid_cycle = "exclude_invalid_cycle_time" in applied_rules

    if exclude_renewals:
        descriptions.append("exclude renewal pipeline")

    if exclude_invalid_cycle:
        descriptions.append("exclude invalid cycle time")

    return {
        "applied_rules": applied_rules.copy(),
        "exclude_renewals": exclude_renewals,
        "exclude_invalid_cycle": exclude_invalid_cycle,
        "description": " + ".join(descriptions) if descriptions else "naive (no hygiene rules)"
    }


# ============================================================================
# QUERY EXECUTION
# ============================================================================

def execute_candidate_query(sb: Client, query_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute candidate query against Supabase and compute median cycle time.

    Args:
        sb: Supabase client
        query_spec: Query specification from generate_candidate_spec

    Returns:
        Execution result with median, sample size, and raw data
    """
    print(f"\nExecuting candidate: {query_spec['description']}")
    print(f"Applied rules: {query_spec['applied_rules'] or 'none'}")

    # Fetch all deals (following pattern from api/handlers.py query_cycle_time)
    # CRITICAL: We need create_date, close_date, pipeline_id, renewal_revenue for hygiene checks
    all_deals = sb.table("deals").select(
        "deal_id,company_name,create_date,close_date,pipeline_id,renewal_revenue,stage"
    ).execute()

    print(f"  Total deals in database: {len(all_deals.data)}")

    # Filter: won deals only (using is_won from field_semantics)
    deals = [d for d in all_deals.data if is_won(d.get("stage"))]
    print(f"  After won filter: {len(deals)} deals")

    # Apply hygiene rules
    RENEWAL_PIPELINE_ID = "866608541"

    if query_spec['exclude_renewals']:
        # Exclude renewal pipeline deals
        deals = [d for d in deals if d.get("pipeline_id") != RENEWAL_PIPELINE_ID]
        print(f"  After exclude_renewals: {len(deals)} deals")

    if query_spec['exclude_invalid_cycle']:
        # Exclude deals with invalid cycle time (negative or missing dates)
        deals = [d for d in deals if is_valid_cycle_deal(d)]
        print(f"  After exclude_invalid_cycle: {len(deals)} deals")

    # Calculate median cycle time
    if not deals:
        return {
            "median_days": None,
            "sample_size": 0,
            "error": "No deals matched filters",
            "deals": []
        }

    cycle_times = []
    for deal in deals:
        try:
            create_date_str = deal.get("create_date")
            close_date_str = deal.get("close_date")

            if not create_date_str or not close_date_str:
                continue

            # Parse dates (handle ISO strings)
            if isinstance(create_date_str, str):
                create_date = datetime.fromisoformat(create_date_str.replace("Z", "+00:00"))
            else:
                create_date = create_date_str

            if isinstance(close_date_str, str):
                close_date = datetime.fromisoformat(close_date_str.replace("Z", "+00:00"))
            else:
                close_date = close_date_str

            # Calculate cycle time in days
            cycle_days = (close_date - create_date).days

            # CRITICAL BUG FIX: Do NOT filter negative cycle times here unless
            # exclude_invalid_cycle_time is in applied_rules. Otherwise we're
            # applying hygiene rules implicitly, masking the need for explicit rules.
            #
            # The original code had: if cycle_days >= 0: cycle_times.append(cycle_days)
            # This silently filtered negative cycle times even when exclude_invalid_cycle_time
            # was NOT in applied_rules, causing false convergence.
            #
            # Correct behavior: Include ALL cycle times (even negative) unless the
            # explicit hygiene rule was applied during the filtering step above.
            # This ensures the engine only converges when the right rules are applied.
            cycle_times.append(cycle_days)

        except (ValueError, AttributeError, TypeError):
            # Skip deals with unparseable dates
            continue

    if not cycle_times:
        return {
            "median_days": None,
            "sample_size": 0,
            "error": "No valid cycle times calculated",
            "deals": deals[:5]
        }

    # Compute median
    sorted_times = sorted(cycle_times)
    n = len(sorted_times)
    median = sorted_times[n // 2] if n % 2 == 1 else (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2

    print(f"  Median cycle time: {median:.1f} days (n={n})")

    return {
        "median_days": round(median, 1),
        "sample_size": n,
        "raw_sample_size": len(deals),
        "deals": [{"deal_id": d["deal_id"], "company_name": d.get("company_name")} for d in deals[:5]],  # Store first 5 for audit trail
        "cycle_times": sorted_times[:10]  # Store first 10 for inspection
    }


# ============================================================================
# COMPARISON AND CONVERGENCE CHECK
# ============================================================================

def compare_to_ground_truth(result: Dict[str, Any], ground_truth: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare candidate result to ground truth.

    Args:
        result: Execution result from execute_candidate_query
        ground_truth: Expected values from GROUND_TRUTH

    Returns:
        Comparison result with pass/fail and diagnosis
    """
    expected = ground_truth['correct_value']
    actual = result.get('median_days')

    if actual is None:
        return {
            "passed": False,
            "expected": expected,
            "actual": None,
            "delta": None,
            "diagnosis": result.get('error', 'Query returned no valid results'),
            "converged": False
        }

    delta = abs(actual - expected)
    passed = delta <= TOLERANCE_DAYS

    diagnosis = ""
    if passed:
        diagnosis = f"✓ CONVERGED: {actual} days within {TOLERANCE_DAYS}-day tolerance of {expected} days"
    else:
        diagnosis = f"✗ MISMATCH: {actual} days vs expected {expected} days (Δ = {delta:.1f} days)"

        # Add diagnostic hints
        if actual > expected:
            diagnosis += f"\n  Likely contamination: result {delta:.1f} days too high"
            diagnosis += f"\n  Suggests additional filtering needed"
        else:
            diagnosis += f"\n  Result {delta:.1f} days too low"
            diagnosis += f"\n  May be over-filtering or incorrect ground truth"

    return {
        "passed": passed,
        "expected": expected,
        "actual": actual,
        "delta": delta,
        "diagnosis": diagnosis,
        "converged": passed
    }


# ============================================================================
# ITERATION ENGINE
# ============================================================================

def run_backtest_iteration(
    sb: Client,
    hygiene_rules: List[Dict[str, Any]],
    ground_truth: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Run full backtest iteration cycle.

    Starts with naive candidate (no rules), applies hygiene rules one by one
    until convergence or exhaustion.

    Args:
        sb: Supabase client
        hygiene_rules: Loaded hygiene rules from registry
        ground_truth: Ground truth specification

    Returns:
        Complete iteration audit trail
    """
    iteration_history = []
    converged = False
    iteration = 0

    # Get metric-specific hygiene rules
    required_rules = ground_truth.get('hygiene_requirements', [])
    applicable_rules = [r for r in hygiene_rules if r['name'] in required_rules]

    print(f"\n{'='*80}")
    print(f"BACKTEST: {ground_truth['metric_name']}")
    print(f"Ground truth: {ground_truth['correct_value']} {ground_truth['unit']}")
    print(f"Applicable hygiene rules: {[r['name'] for r in applicable_rules]}")
    print(f"{'='*80}")

    # Iteration 0: Naive candidate (no hygiene rules)
    print(f"\n{'─'*80}")
    print(f"ITERATION {iteration}: Naive candidate (no hygiene rules)")
    print(f"{'─'*80}")

    applied_rules = []
    query_spec = generate_candidate_spec(applied_rules)
    result = execute_candidate_query(sb, query_spec)
    comparison = compare_to_ground_truth(result, ground_truth)

    iteration_record = {
        "iteration": iteration,
        "candidate_description": query_spec['description'],
        "applied_rules": applied_rules,
        "result": result,
        "comparison": comparison,
        "converged": comparison['converged']
    }
    iteration_history.append(iteration_record)

    print(f"\n{comparison['diagnosis']}")

    if comparison['converged']:
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
        if iteration >= MAX_ITERATIONS:
            print(f"\n⚠️  Reached max iterations ({MAX_ITERATIONS}), stopping")
            break

        iteration += 1
        applied_rules.append(rule['name'])

        print(f"\n{'─'*80}")
        print(f"ITERATION {iteration}: Apply {rule['name']}")
        print(f"  Rule: {rule['description']}")
        print(f"{'─'*80}")

        query_spec = generate_candidate_spec(applied_rules)
        result = execute_candidate_query(sb, query_spec)
        comparison = compare_to_ground_truth(result, ground_truth)

        iteration_record = {
            "iteration": iteration,
            "candidate_description": query_spec['description'],
            "applied_rules": applied_rules.copy(),
            "new_rule_applied": rule['name'],
            "rule_function": rule['function'],
            "result": result,
            "comparison": comparison,
            "converged": comparison['converged']
        }
        iteration_history.append(iteration_record)

        print(f"\n{comparison['diagnosis']}")

        if comparison['converged']:
            converged = True
            print(f"\n✓ Converged on iteration {iteration}")
            print(f"✓ Successful hygiene rules: {applied_rules}")
            break

    # Final result
    if not converged:
        print(f"\n✗ Did NOT converge after {iteration} iterations")
        print(f"✗ Final delta: {comparison['delta']:.1f} days (tolerance: {TOLERANCE_DAYS} days)")

    return {
        "converged": converged,
        "iterations": iteration_history,
        "final_result": result if iteration_history else None,
        "ground_truth": ground_truth,
        "total_iterations": iteration
    }


# ============================================================================
# OUTPUT FORMATTING
# ============================================================================

def format_audit_trail(backtest_result: Dict[str, Any]) -> str:
    """
    Format backtest result as human-readable audit trail.

    Args:
        backtest_result: Complete iteration history from run_backtest_iteration

    Returns:
        Formatted audit trail string
    """
    lines = []
    lines.append("="*80)
    lines.append("BACKTEST ENGINE — AUDIT TRAIL")
    lines.append("="*80)
    lines.append("")

    gt = backtest_result['ground_truth']
    lines.append(f"Metric: {gt['metric_name']}")
    lines.append(f"Description: {gt['description']}")
    lines.append(f"Ground truth: {gt['correct_value']} {gt['unit']}")
    lines.append(f"Validated by: {gt['validated_by']}")
    lines.append(f"Tolerance: ±{TOLERANCE_DAYS} {gt['unit']}")
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

        res = record['result']
        lines.append(f"  Result: {res.get('median_days')} days (n={res.get('sample_size')})")

        comp = record['comparison']
        lines.append(f"  Expected: {comp['expected']} days")
        lines.append(f"  Delta: {comp['delta']:.1f} days" if comp['delta'] is not None else "  Delta: N/A")
        lines.append(f"  Status: {'✓ CONVERGED' if comp['converged'] else '✗ MISMATCH'}")
        lines.append("")

    lines.append("─"*80)
    lines.append("FINAL RESULT")
    lines.append("─"*80)
    lines.append("")

    if backtest_result['converged']:
        lines.append("✓ CONVERGED")
        final = backtest_result['final_result']
        final_iter = backtest_result['iterations'][-1]
        lines.append(f"  Converged on iteration: {final_iter['iteration']}")
        lines.append(f"  Final value: {final['median_days']} days (n={final['sample_size']})")
        lines.append(f"  Applied rules: {final_iter['applied_rules']}")
        lines.append("")
        lines.append("Validated query ready for production use.")
    else:
        lines.append("✗ DID NOT CONVERGE")
        lines.append(f"  Total iterations: {backtest_result['total_iterations']}")
        final_iter = backtest_result['iterations'][-1]
        lines.append(f"  Final delta: {final_iter['comparison']['delta']:.1f} days")
        lines.append(f"  Tolerance: {TOLERANCE_DAYS} days")
        lines.append("")
        lines.append("Additional hygiene rules needed OR incorrect ground truth.")

    lines.append("")
    lines.append("="*80)

    return "\n".join(lines)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Run backtest engine on cycle_time test case."""

    print("BACKTEST ENGINE v1.0")
    print("Standalone metric validation loop")
    print("")

    # Load configuration
    print("Loading configuration...")
    hygiene_rules = load_hygiene_rules()
    print("")

    # Initialize Supabase client
    print("Connecting to Supabase...")
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_SERVICE_KEY')

    if not supabase_url or not supabase_key:
        print("✗ ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    sb = create_client(supabase_url, supabase_key)
    print("✓ Connected")

    # Run backtest
    print("")
    result = run_backtest_iteration(sb, hygiene_rules, GROUND_TRUTH)

    # Output audit trail
    print("")
    print("")
    audit_trail = format_audit_trail(result)
    print(audit_trail)

    # Save audit trail to file
    output_path = Path(__file__).parent.parent / "BACKTEST_AUDIT_TRAIL.md"
    with open(output_path, 'w') as f:
        f.write(audit_trail)

    print("")
    print(f"✓ Audit trail saved to: {output_path}")

    # Exit with appropriate code
    sys.exit(0 if result['converged'] else 1)


if __name__ == '__main__':
    main()
