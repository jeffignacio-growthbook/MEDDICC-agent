#!/usr/bin/env python3
"""
Plausibility checks for analytical outputs.

Runs before synthesis to catch arithmetic errors, invalid rates, structural
impossibilities, and metric drift from verified registry values.

A plausibility violation either:
1. Surfaces in the answer with a warning flag, OR
2. Blocks the answer entirely (confidence-floor decision)

Never silently passes.
"""
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import yaml

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))


class PlausibilityViolation:
    """A detected plausibility issue."""

    def __init__(self, check: str, severity: str, message: str, context: Dict = None):
        self.check = check
        self.severity = severity  # 'warning', 'error', 'critical'
        self.message = message
        self.context = context or {}

    def __repr__(self):
        return f"PlausibilityViolation({self.check}, {self.severity}, {self.message})"


def check_rate_bounds(data: Dict, path: str = "") -> List[PlausibilityViolation]:
    """
    Check that all rate/percentage fields are in valid range [0, 1].

    Common violations:
    - Conversion > 1.0 (110% conversion)
    - Negative rates
    - GRR/NRR outside reasonable bounds
    """
    violations = []

    # Fields that should be rates (0-1 range)
    rate_fields = {
        'grr', 'nrr', 'churn', 'conversion', 'win_rate', 'loss_rate',
        'coverage_pct', 'attainment', 'quota_pct'
    }

    def check_value(key: str, value: Any, path: str):
        if not isinstance(value, (int, float)):
            return

        # Check if field name suggests it's a rate
        is_rate_field = any(rf in key.lower() for rf in rate_fields)

        if is_rate_field:
            if value < 0:
                violations.append(PlausibilityViolation(
                    check='rate_bounds',
                    severity='error',
                    message=f"{path}{key} is negative: {value}",
                    context={'field': key, 'value': value}
                ))
            elif value > 1.0 and 'pct' not in key.lower():
                # Allow >1 for percentage fields (like coverage_pct = 95.0)
                # but flag >1 for rate fields (like grr = 1.10)
                violations.append(PlausibilityViolation(
                    check='rate_bounds',
                    severity='error',
                    message=f"{path}{key} exceeds 1.0: {value} ({value*100:.1f}%)",
                    context={'field': key, 'value': value}
                ))

    def traverse(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                check_value(key, value, path)
                traverse(value, f"{path}{key}.")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                traverse(item, f"{path}[{i}].")

    traverse(data)
    return violations


def check_subset_relationships(data: Dict) -> List[PlausibilityViolation]:
    """
    Check that subsets are not larger than their supersets.

    Common violations:
    - qualified > total
    - won > qualified
    - closed > total
    """
    violations = []

    # Common subset relationships
    relationships = [
        ('qualified', 'total', 'Qualified deals cannot exceed total deals'),
        ('won', 'qualified', 'Won deals cannot exceed qualified deals'),
        ('won', 'total', 'Won deals cannot exceed total deals'),
        ('closed', 'total', 'Closed deals cannot exceed total deals'),
        ('lost', 'total', 'Lost deals cannot exceed total deals'),
    ]

    def check_at_level(obj: Dict, path: str = ""):
        for subset_key, superset_key, message in relationships:
            if subset_key in obj and superset_key in obj:
                subset_val = obj[subset_key]
                superset_val = obj[superset_key]

                if isinstance(subset_val, (int, float)) and isinstance(superset_val, (int, float)):
                    if subset_val > superset_val:
                        violations.append(PlausibilityViolation(
                            check='subset_relationship',
                            severity='error',
                            message=f"{path}{message}: {subset_key}={subset_val} > {superset_key}={superset_val}",
                            context={
                                'subset': subset_key,
                                'subset_value': subset_val,
                                'superset': superset_key,
                                'superset_value': superset_val
                            }
                        ))

        # Recurse into nested dicts
        for key, value in obj.items():
            if isinstance(value, dict):
                check_at_level(value, f"{path}{key}.")

    check_at_level(data)
    return violations


def check_sum_consistency(data: Dict) -> List[PlausibilityViolation]:
    """
    Check that parts sum to stated whole.

    Common violations:
    - won + lost + open ≠ total
    - pipeline components don't sum to total
    """
    violations = []

    # Check won + lost + open = total pattern
    def check_at_level(obj: Dict, path: str = ""):
        if all(k in obj for k in ['won', 'lost', 'open', 'total']):
            won = obj['won']
            lost = obj['lost']
            open_val = obj['open']
            total = obj['total']

            if all(isinstance(v, (int, float)) for v in [won, lost, open_val, total]):
                parts_sum = won + lost + open_val
                if abs(parts_sum - total) > 0.01:  # Allow small floating point errors
                    violations.append(PlausibilityViolation(
                        check='sum_consistency',
                        severity='warning',
                        message=f"{path}won + lost + open ({parts_sum}) ≠ total ({total})",
                        context={
                            'won': won,
                            'lost': lost,
                            'open': open_val,
                            'total': total,
                            'difference': parts_sum - total
                        }
                    ))

        # Recurse
        for key, value in obj.items():
            if isinstance(value, dict):
                check_at_level(value, f"{path}{key}.")

    check_at_level(data)
    return violations


def check_negative_counts(data: Dict) -> List[PlausibilityViolation]:
    """
    Check for negative counts or durations.

    Common violations:
    - Negative deal counts
    - Negative durations
    - Negative dollar amounts (in most contexts)
    """
    violations = []

    # Fields that should never be negative
    count_fields = {'count', 'total', 'n', 'deals', 'rows', 'days', 'hours'}

    def check_value(key: str, value: Any, path: str):
        if not isinstance(value, (int, float)):
            return

        # Check if field name suggests it's a count
        is_count_field = any(cf in key.lower() for cf in count_fields)

        if is_count_field and value < 0:
            violations.append(PlausibilityViolation(
                check='negative_count',
                severity='error',
                message=f"{path}{key} is negative: {value}",
                context={'field': key, 'value': value}
            ))

    def traverse(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                check_value(key, value, path)
                traverse(value, f"{path}{key}.")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                traverse(item, f"{path}[{i}].")

    traverse(data)
    return violations


def check_metric_registry_divergence(data: Dict, handler_name: str = None) -> List[PlausibilityViolation]:
    """
    Check if computed metrics diverge from verified registry values.

    This is the highest-value check - catches when a computation drifts from
    a reconciled external reference.
    """
    violations = []

    # Load metrics registry
    metrics_path = REPO_ROOT / 'config' / 'metrics.yaml'
    if not metrics_path.exists():
        return violations

    with open(metrics_path) as f:
        registry = yaml.safe_load(f)

    # Check GRR, NRR, churn
    for metric_id in ['grr', 'nrr', 'churn']:
        if metric_id not in registry:
            continue

        metric_def = registry[metric_id]
        verified = metric_def.get('verified', {})
        tolerance = verified.get('tolerance', 0.005)  # Default ±0.5pp

        # Look for this metric in the data
        metric_value = _extract_metric_value(data, metric_id)
        if metric_value is None:
            continue

        # Check each verified quarter
        for quarter_key, verified_value in verified.items():
            if quarter_key in ['reconciled_against', 'reconciled_on', 'tolerance', 'handler_output',
                              'handler_output_excluding_lion_studios', 'reconciliation_note',
                              'report_exclusions', 'q3_q4_note']:
                continue

            if verified_value is None:
                continue

            # Check if this quarter's data is in the response
            if _contains_quarter(data, quarter_key):
                variance = abs(metric_value - verified_value)

                if variance > tolerance:
                    severity = 'critical' if variance > (tolerance * 3) else 'warning'
                    violations.append(PlausibilityViolation(
                        check='metric_registry_divergence',
                        severity=severity,
                        message=f"{metric_id.upper()} {quarter_key}: {metric_value:.4f} vs verified {verified_value:.4f} (±{tolerance:.3f} tolerance) → {variance:.4f} variance",
                        context={
                            'metric': metric_id,
                            'quarter': quarter_key,
                            'computed': metric_value,
                            'verified': verified_value,
                            'tolerance': tolerance,
                            'variance': variance
                        }
                    ))

    return violations


def _extract_metric_value(data: Dict, metric_id: str) -> Optional[float]:
    """Extract a metric value from nested data structure."""
    # Try direct key
    if metric_id in data:
        val = data[metric_id]
        if isinstance(val, (int, float)):
            return float(val)

    # Try nested in views
    if 'views' in data:
        for view_name, view_data in data['views'].items():
            if isinstance(view_data, dict):
                for quarter, quarter_data in view_data.items():
                    if isinstance(quarter_data, dict) and metric_id in quarter_data:
                        val = quarter_data[metric_id]
                        if isinstance(val, (int, float)):
                            return float(val)

    # Try first-level nesting
    for key, value in data.items():
        if isinstance(value, dict) and metric_id in value:
            val = value[metric_id]
            if isinstance(val, (int, float)):
                return float(val)

    return None


def _contains_quarter(data: Dict, quarter_label: str) -> bool:
    """Check if data contains a specific quarter label."""
    quarter_str = str(quarter_label).lower()
    data_str = str(data).lower()
    return quarter_str in data_str


def run_all_checks(data: Dict, handler_name: str = None) -> Tuple[List[PlausibilityViolation], bool]:
    """
    Run all plausibility checks on data.

    Returns:
        (violations, should_block)

        should_block = True if any critical violations found
    """
    all_violations = []

    all_violations.extend(check_rate_bounds(data))
    all_violations.extend(check_subset_relationships(data))
    all_violations.extend(check_sum_consistency(data))
    all_violations.extend(check_negative_counts(data))
    all_violations.extend(check_metric_registry_divergence(data, handler_name))

    # Determine if we should block
    has_critical = any(v.severity == 'critical' for v in all_violations)
    has_error = any(v.severity == 'error' for v in all_violations)

    # Block on critical violations
    should_block = has_critical

    return all_violations, should_block


def format_violations_for_synthesis(violations: List[PlausibilityViolation]) -> str:
    """
    Format violations for inclusion in synthesis prompt.

    Returns a warning block to prepend to the answer.
    """
    if not violations:
        return ""

    lines = ["⚠️  PLAUSIBILITY CHECKS FLAGGED:"]
    lines.append("")

    for v in violations:
        severity_marker = {
            'warning': '⚠️ ',
            'error': '❌',
            'critical': '🚨'
        }.get(v.severity, '⚠️ ')

        lines.append(f"{severity_marker} {v.message}")

    lines.append("")
    return "\n".join(lines)


# For testing
if __name__ == "__main__":
    # Test with sample data
    test_data = {
        'grr': 1.1182,  # Should flag if Q1 FY2027 in data
        'nrr': 1.1182,
        'total': 100,
        'won': 50,
        'lost': 30,
        'open': 25,  # Sum = 105, exceeds total
        'conversion': 1.10,  # > 1.0, should flag
        'qualified': 60,
        'negative_count': -5
    }

    violations, should_block = run_all_checks(test_data)

    print(f"Found {len(violations)} violations (block={should_block}):")
    print()
    for v in violations:
        print(f"  {v.severity.upper()}: {v.message}")
    print()
    print(format_violations_for_synthesis(violations))
