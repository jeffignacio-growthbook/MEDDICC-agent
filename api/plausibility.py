#!/usr/bin/env python3
"""
Plausibility checks for analytical outputs.

run_all_checks() runs before synthesis to catch arithmetic errors, invalid
rates, structural impossibilities, and metric drift from verified registry
values. run_answer_checks() runs after it, comparing the answer with the
data it came from (see "Answer-side checks" below).

A plausibility violation either:
1. Surfaces in the answer with a warning flag, OR
2. Blocks the answer entirely (confidence-floor decision)

Never silently passes.
"""
import re
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
        key = str(key)  # tables keyed by stage order / week are int-keyed

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

        # Check by_stage breakdown sums to total_open_count
        if 'by_stage' in obj and 'total_open_count' in obj:
            by_stage = obj['by_stage']
            total_count = obj['total_open_count']

            if isinstance(by_stage, list) and isinstance(total_count, (int, float)):
                stage_sum = sum(s.get('count', 0) for s in by_stage if isinstance(s, dict))

                if stage_sum != total_count:
                    violations.append(PlausibilityViolation(
                        check='sum_consistency',
                        severity='error',  # Structural mismatch, but non-blocking initially
                        message=f"{path}by_stage counts ({stage_sum}) ≠ total_open_count ({total_count})",
                        context={
                            'by_stage_sum': stage_sum,
                            'total_open_count': total_count,
                            'missing_count': total_count - stage_sum,
                            'by_stage_items': len(by_stage)
                        }
                    ))

        # Recurse
        for key, value in obj.items():
            if isinstance(value, dict):
                check_at_level(value, f"{path}{key}.")

    check_at_level(data)
    return violations


_SIGNED_DAY_OFFSET = re.compile(r'(^|_)days_past_')


def check_benchmark_offsets(data: Dict) -> List[PlausibilityViolation]:
    """
    days_past_benchmark (scripts/deal_risk_assessor.py) is days_open minus the
    segment's cycle benchmark, so it's negative for every deal still inside
    its benchmark. What IS implausible, per record that carries it:
    - no valid benchmark next to it (cycle_benchmark_days missing, None, <= 0);
    - it isn't days_open - cycle_benchmark_days (e.g. a flipped sign).

    2026-09-23: before this, check_negative_counts() flagged every negative
    days_past_benchmark, 11 in the first live forecast_trust answer after the
    deals.amount fix, which put a "worth verifying" banner on a correct answer.
    """
    violations = []

    def check_record(rec: Dict, path: str):
        if rec.get('days_past_benchmark') is None:
            return
        offset = rec['days_past_benchmark']
        bench = rec.get('cycle_benchmark_days')
        if not isinstance(bench, (int, float)) or bench <= 0:
            violations.append(PlausibilityViolation(
                check='benchmark_offset',
                severity='error',
                message=(f"{path}days_past_benchmark ({offset}) without a valid "
                         f"cycle_benchmark_days ({bench!r})"),
                context={'days_past_benchmark': offset, 'cycle_benchmark_days': bench}
            ))
            return
        days_open = rec.get('days_open')
        if isinstance(days_open, (int, float)) and days_open - bench != offset:
            violations.append(PlausibilityViolation(
                check='benchmark_offset',
                severity='error',
                message=(f"{path}days_past_benchmark is {offset}, but days_open - "
                         f"cycle_benchmark_days = {days_open} - {bench} = {days_open - bench}"),
                context={'days_past_benchmark': offset, 'days_open': days_open,
                         'cycle_benchmark_days': bench}
            ))

    def traverse(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            if 'days_past_benchmark' in obj:
                check_record(obj, path)
            for key, value in obj.items():
                traverse(value, f"{path}{key}.")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                traverse(item, f"{path}[{i}].")

    traverse(data)
    return violations


def check_negative_counts(data: Dict) -> List[PlausibilityViolation]:
    """
    Check for negative counts or durations.

    Targets actual counts and durations that can't be below zero.
    Excludes signed fields (net change, delta, variance) which are negative by definition.

    Common violations:
    - Negative deal counts
    - Negative durations
    """
    violations = []

    # Fields that should never be negative (counts, durations)
    count_fields = {'count', 'total', 'deals', 'rows', 'days', 'hours', 'minutes'}

    # Signed fields that CAN be negative (changes, differences)
    signed_fields = {'net', 'delta', 'change', 'diff', 'variance', 'movement', 'shift', 'swing'}

    def check_value(key: str, value: Any, path: str):
        if not isinstance(value, (int, float)):
            return
        key = str(key)  # tables keyed by stage order / week are int-keyed

        key_lower = key.lower()

        # Skip signed fields (net, delta, change, etc.)
        if any(sf in key_lower for sf in signed_fields):
            return
        # Skip signed day offsets: days_past_benchmark, days_past_close, ...
        # are "days beyond a reference", negative while the reference hasn't
        # been reached (a deal still inside its cycle benchmark is low_risk,
        # not implausible). check_benchmark_offsets() checks those for real.
        if _SIGNED_DAY_OFFSET.search(key_lower):
            return

        # Check if field name suggests it's a count
        is_count_field = any(cf in key_lower for cf in count_fields)

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

        # Check each verified quarter
        for quarter_key, verified_value in verified.items():
            if quarter_key in ['reconciled_against', 'reconciled_on', 'tolerance', 'handler_output',
                              'handler_output_excluding_lion_studios', 'reconciliation_note',
                              'report_exclusions', 'q3_q4_note']:
                continue

            if verified_value is None:
                continue

            # Check if this quarter's data is in the response
            if not _contains_quarter(data, quarter_key):
                continue

            # Extract metric value for this specific quarter
            metric_value = _extract_metric_value(data, metric_id, quarter_key)
            if metric_value is None:
                continue

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

    # Check conversion rate (week3_conversion)
    if 'week3_conversion' in registry:
        metric_def = registry['week3_conversion']
        verified = metric_def.get('verified', {})
        verified_rate = verified.get('pooled')  # Use pooled rate (better estimator)

        if verified_rate is not None:
            # Conversion rate has no tolerance in registry, use 0.02 (±2pp)
            # 6.5% vs 9.9% = 3.4pp variance, should trigger
            tolerance = 0.02

            # Look for conversion rate in data (various field names possible)
            conversion_fields = ['conversion', 'conversion_rate', 'week3_conversion',
                                'close_rate', 'win_rate_qualified']

            for field in conversion_fields:
                computed_rate = _extract_metric_value(data, field)

                if computed_rate is not None:
                    variance = abs(computed_rate - verified_rate)

                    if variance > tolerance:
                        severity = 'critical' if variance > (tolerance * 2) else 'warning'
                        violations.append(PlausibilityViolation(
                            check='metric_registry_divergence',
                            severity=severity,
                            message=f"CONVERSION RATE: {computed_rate:.1%} vs verified {verified_rate:.1%} (±{tolerance:.1%} tolerance) → {variance:.1%} variance. DO NOT derive conversion from coverage - use verified rate from registry.",
                            context={
                                'metric': 'week3_conversion',
                                'field': field,
                                'computed': computed_rate,
                                'verified': verified_rate,
                                'tolerance': tolerance,
                                'variance': variance
                            }
                        ))

    return violations


def _extract_metric_value(data: Dict, metric_id: str, quarter_key: str = None) -> Optional[float]:
    """
    Extract a metric value from nested data structure.

    Args:
        data: The data dictionary to search
        metric_id: The metric to find (e.g., 'grr', 'nrr')
        quarter_key: Optional quarter to match (e.g., 'q1_fy2027_closed_only')
    """
    import re

    # Try direct key
    if metric_id in data:
        val = data[metric_id]
        if isinstance(val, (int, float)):
            return float(val)

    # If quarter_key provided, extract quarter and FY from it
    target_quarter = None
    target_fy = None
    target_view = None

    if quarter_key:
        match = re.search(r'q(\d+).*fy(\d+)', quarter_key.lower())
        if match:
            target_quarter = match.group(1)
            target_fy = match.group(2)
        if 'closed_only' in quarter_key.lower():
            target_view = 'closed_only'
        elif 'assume' in quarter_key.lower() or 'open' in quarter_key.lower():
            target_view = 'assume_open_wins'

    # Try nested in views
    if 'views' in data:
        for view_name, view_data in data['views'].items():
            # If we have a target view, only check that one
            if target_view and view_name != target_view:
                continue

            if isinstance(view_data, dict):
                for quarter, quarter_data in view_data.items():
                    # Check if this quarter matches our target
                    if target_quarter and target_fy:
                        quarter_lower = quarter.lower()
                        if f"q{target_quarter}" in quarter_lower and target_fy in quarter_lower:
                            if isinstance(quarter_data, dict) and metric_id in quarter_data:
                                val = quarter_data[metric_id]
                                if isinstance(val, (int, float)):
                                    return float(val)
                    # No target, return first match
                    elif isinstance(quarter_data, dict) and metric_id in quarter_data:
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
    """
    Check if data contains a specific quarter label.

    Handles mapping between registry keys (q1_fy2027) and data keys (FY2027 Q1).
    """
    quarter_str = str(quarter_label).lower()

    # Extract quarter number and fiscal year from registry key
    # e.g., "q1_fy2027_closed_only" -> "q1", "2027"
    import re
    match = re.search(r'q(\d+).*fy(\d+)', quarter_str)
    if match:
        q_num = match.group(1)
        fy_year = match.group(2)
        # Look for "FY2027 Q1" format in data
        alt_format = f"fy{fy_year} q{q_num}"
        data_str = str(data).lower()
        if alt_format in data_str:
            return True

    # Fallback to simple string match
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
    all_violations.extend(check_benchmark_offsets(data))
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

    Returns a warning block to prepend to the answer in plain language.
    """
    if not violations:
        return ""

    lines = ["⚠️  Data quality notes:"]
    lines.append("")

    for v in violations:
        # Convert technical message to plain language
        if v.check == 'metric_registry_divergence':
            ctx = v.context
            metric = ctx.get('metric', 'metric').upper()
            computed = ctx.get('computed', 0)
            verified = ctx.get('verified', 0)

            # Plain language note
            lines.append(
                f"• {metric} came back {computed*100:.1f}% but we've verified it at "
                f"{verified*100:.0f}%. Numbers are close but worth noting."
            )
        elif v.check == 'rate_bounds':
            field = v.context.get('field', 'rate')
            value = v.context.get('value', 0)
            lines.append(f"• {field} result ({value*100:.0f}%) looks unusual.")
        elif v.check == 'subset_relationship':
            subset = v.context.get('subset', 'subset')
            superset = v.context.get('superset', 'superset')
            lines.append(f"• {subset} count higher than {superset} — worth double-checking.")
        else:
            # Generic warning in plain language
            lines.append(f"• Data check flagged: worth verifying this result.")

    lines.append("")
    return "\n".join(lines)


def format_block_message(violations: List[PlausibilityViolation]) -> str:
    """
    Format critical violations for blocked answer in plain language.

    Returns honest, actionable explanation of what failed and where to look.
    """
    if not violations:
        return "Cannot provide answer due to data quality issues."

    critical = [v for v in violations if v.severity == 'critical']

    if not critical:
        # Shouldn't happen (block triggered without critical), but handle it
        return "Cannot provide answer due to data quality issues."

    lines = []

    for v in critical:
        if v.check == 'metric_registry_divergence':
            # Make registry divergence human-readable
            ctx = v.context
            metric = ctx.get('metric', 'metric').upper()
            quarter = ctx.get('quarter', 'quarter')
            computed = ctx.get('computed', 0)
            verified = ctx.get('verified', 0)

            # Parse quarter for display
            # e.g., "q1_fy2027_closed_only" -> "Q1 FY2027 (closed deals)"
            import re
            match = re.search(r'q(\d+).*fy(\d+)', quarter.lower())
            if match:
                q_num = match.group(1)
                fy_year = match.group(2)
                quarter_display = f"Q{q_num} FY{fy_year}"
                if 'closed' in quarter.lower():
                    quarter_display += " (closed deals)"
                elif 'assume' in quarter.lower() or 'open' in quarter.lower():
                    quarter_display += " (assume open wins)"
            else:
                quarter_display = quarter.replace('_', ' ').upper()

            lines.append(
                f"I'm not showing {metric} for {quarter_display} — the number I calculated "
                f"doesn't match what we've verified, so I don't trust it. Flagged for Jeff to check."
            )
        elif v.check == 'rate_bounds':
            # Rate exceeded bounds
            field = v.context.get('field', 'rate')
            value = v.context.get('value', 0)
            lines.append(
                f"I'm not showing {field} — the result I got ({value*100:.0f}%) doesn't make sense. "
                f"Flagged for Jeff to check."
            )
        elif v.check == 'subset_relationship':
            # Subset larger than superset
            subset = v.context.get('subset', 'subset')
            superset = v.context.get('superset', 'superset')
            lines.append(
                f"I'm not showing these numbers — {subset} count came back higher than {superset}, "
                f"which shouldn't be possible. Flagged for Jeff to check."
            )
        else:
            # Generic critical violation
            lines.append(
                f"I'm not showing this number — something doesn't add up. "
                f"Flagged for Jeff to check."
            )

    if not lines:
        return "I'm not showing this number — something doesn't add up. Flagged for Jeff to check."

    return "\n\n".join(lines)


# For testing
# ══════════════════════════════════════════════════════════════════════
# Answer-side checks (2026-09-24)
# ══════════════════════════════════════════════════════════════════════
# run_all_checks() above looks at handler data before synthesis, and only
# on route_question's classifier path; dynamic_query returns before it
# runs. These compare the synthesized ANSWER with the data it came from
# and run on both paths: dynamic_query_loop()'s wrapper (every exit of the
# loop) and route_question after synthesis. A violation appends a caveat
# to the shipped answer (answer_caveat()); in the dynamic loop it also
# sets its own query_cost_log outcome (see router.FAILURE_MODE_PRIMITIVES).

_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]

# Answer wording -> value_basis. Matched case-insensitively per line.
_BASIS_WORDS = {
    # "Incremental ARR", and table abbreviations "Incr. ARR" / "Incr ARR" (2026-09-24 live)
    "incremental_arr": re.compile(r"\bincr(?:emental|\.)?\s*arr\b", re.I),
    "deal_value": re.compile(r"deal[\s_]value", re.I),
    "mixed": re.compile(r"mixed\s+basis", re.I),
}


def _iter_dicts(data):
    """Every dict nested anywhere in data (lists and dicts walked)."""
    stack = [data]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            yield x
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)


def _waterfall_week_dicts(data) -> Dict[str, Dict]:
    """week_ending -> the waterfall week row itself, for every week row in data."""
    weeks = {}
    for d in _iter_dicts(data):
        if d.get("week_ending") and d.get("value_basis") and "by_slice" in d:
            weeks[str(d["week_ending"])[:10]] = d
    return weeks


def _waterfall_week_rows(data) -> Dict[str, str]:
    """week_ending -> value_basis for every waterfall week row in data."""
    return {w: d["value_basis"] for w, d in _waterfall_week_dicts(data).items()}


_TOTAL_FIELDS = ("new_pipeline_value", "won_value", "lost_value", "net_change",
                 "pulled_in_value", "pushed_out_value")


def _mixed_basis_totals(week_rows: Dict[str, Dict]) -> List[Tuple[str, float]]:
    """(field, total) for every quarter-level total whose contributing
    (non-zero) weeks are on more than one basis."""
    out = []
    for f in _TOTAL_FIELDS:
        contrib = [(float(r.get(f) or 0), r["value_basis"]) for r in week_rows.values()
                   if float(r.get(f) or 0)]
        if len({b for _, b in contrib}) > 1:
            out.append((f, sum(v for v, _ in contrib)))
    return out


def _week_date_pattern(week_ending: str):
    """Ways an answer writes a week date: 2026-09-14, Sep 14, Sept. 14,
    September 14, 9/14, 09/14."""
    y, m, d = week_ending.split("-")
    mi, di = int(m), int(d)
    full = _MONTHS[mi - 1]
    names = {full, full[:3]} | ({"Sept"} if mi == 9 else set())
    alts = [re.escape(week_ending),
            r"\b(?:%s)\.?\s+0?%d(?:st|nd|rd|th)?\b" % ("|".join(sorted(names)), di),
            r"(?<![\d/])0?%d/0?%d(?![\d/])" % (mi, di)]
    return re.compile("|".join(alts), re.I)


def _bases_named(text: str) -> set:
    return {b for b, rx in _BASIS_WORDS.items() if rx.search(text)}


def check_answer_week_basis(answer: str, data: Dict) -> List[PlausibilityViolation]:
    """Each waterfall week the answer mentions must carry its own row's
    basis. waterfall_weekly weeks before 2026-09-11 are valued on deal_value
    and later ones on incremental_arr, so a multi-week table can mix them.

    For each answer line naming a week:
      - the line names a basis: it must be that week's value_basis;
      - the line names none: the answer's other lines (a header or footnote)
        count as a table-wide statement. One table-wide basis that isn't
        this week's is a mismatch. No basis anywhere while the mentioned
        weeks differ is flagged too: the reader can't tell which is which.
    """
    weeks = _waterfall_week_rows(data)
    if not answer or not weeks:
        return []
    lines = answer.splitlines()
    mentions = []                                   # (week, line_no, bases on line)
    for week, basis in weeks.items():
        rx = _week_date_pattern(week)
        for i, line in enumerate(lines):
            if rx.search(line):
                mentions.append((week, i, _bases_named(line)))
    week_lines = {i for _, i, _ in mentions}
    table_wide = _bases_named("\n".join(l for i, l in enumerate(lines) if i not in week_lines))

    # A week is judged on the lines that name it:
    #   - a line naming bases that don't include the week's own: wrong;
    #   - a line naming none: the answer's other lines count as a table-wide
    #     statement only if they name exactly ONE basis (the "one note
    #     applied to the whole table" failure). Several table-wide bases
    #     don't say which week is which: not stated, never "wrong";
    #   - once any line labels the week correctly, other mentions of it
    #     (prose like "especially Sep 21: $1.76M pushed out") can't make it
    #     unlabeled.
    # 2026-09-24: the first live run flagged a correct table because its
    # rows said "Incr. ARR" (unrecognised) and the old fallback treated
    # several table-wide bases as a wrong one.
    wrong, unlabeled, labeled_ok, seen_wrong = [], [], set(), set()
    for week, i, named in mentions:
        actual = weeks[week]
        if named:
            if actual in named:
                labeled_ok.add(week)
            elif (week, i) not in seen_wrong:
                seen_wrong.add((week, i))
                wrong.append({"week_ending": week, "stated": sorted(named), "actual": actual,
                              "line": lines[i].strip()[:160]})
        elif len(table_wide) == 1:
            if actual in table_wide:
                labeled_ok.add(week)
            elif (week, i) not in seen_wrong:
                seen_wrong.add((week, i))
                wrong.append({"week_ending": week, "stated": sorted(table_wide), "actual": actual,
                              "line": lines[i].strip()[:160]})
        elif not table_wide:
            unlabeled.append(week)
    unlabeled = [w for w in unlabeled if w not in labeled_ok]
    mentioned_bases = {weeks[w] for w, _, _ in mentions}
    out = []

    # Quarter-level totals (2026-09-24): a line quoting a total across weeks
    # whose contributing weeks are on different bases must say so ("mixed
    # basis", or both bases named). Week lines are left to the rules above.
    unlabeled_totals = []
    for f, total in _mixed_basis_totals(_waterfall_week_dicts(data)):
        for i, line in enumerate(lines):
            if i in week_lines:
                continue
            if not any(_matches(v, u, total) for _, v, u, _ in _stated_dollar_figures(line)):
                continue
            named = _bases_named(line)
            if "mixed" in named or {"deal_value", "incremental_arr"} <= named:
                continue
            unlabeled_totals.append({"field": f, "total": total, "line": line.strip()[:160]})
    if unlabeled_totals:
        out.append(PlausibilityViolation(
            "answer_week_basis", "error",
            "answer states quarter-level total(s) mixing bases without saying so: "
            + "; ".join(f"{t['field']} ${t['total']:,.0f}" for t in unlabeled_totals),
            {"unlabeled_totals": unlabeled_totals}))
    if wrong:
        out.append(PlausibilityViolation(
            "answer_week_basis", "error",
            f"answer states the wrong basis for {len(wrong)} week(s): "
            + "; ".join(f"{w['week_ending']} stated {w['stated']} but stored as {w['actual']}"
                        for w in wrong),
            {"wrong": wrong}))
    if unlabeled and len(mentioned_bases) > 1:
        out.append(PlausibilityViolation(
            "answer_week_basis", "error",
            f"answer gives no basis for week(s) {sorted(set(unlabeled))} while the weeks it "
            f"shows are on different bases ({sorted(mentioned_bases)})",
            {"unlabeled": sorted(set(unlabeled)), "bases": sorted(mentioned_bases)}))
    return out


# A stated dollar figure: $4,577,066 / $4577 / $374K / $4.6M / $1.2 billion
_DOLLAR_FIGURE = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(k|m|mm|b|bn|thousand|million|billion)?\b", re.I)
_SUFFIX = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6,
           "b": 1e9, "bn": 1e9, "billion": 1e9}
# Keys whose numbers are dollars, and keys that look like it but aren't.
_MONEY_KEY = re.compile(r"arr|value|amount|revenue|pipeline|bookings|won|lost|net_change|"
                        r"_usd|quota|target|acv|deal_size|pulled_in|pushed_out|total", re.I)
_NOT_MONEY_KEY = re.compile(r"count|days|pct|percent|rate|ratio|_id$|^id$|order|week|quarter|"
                            r"score|rank|prob|age|_deals$|^deals$|num_|_num|year", re.I)
_SLIP_FACTORS = (1e3, 1e6)
_SLIP_MIN_SOURCE = 10_000   # a slip is against a real deal-sized figure
_SLIP_MIN_SIG_DIGITS = 3    # "$30" or "$25.0M" x1000 hits round deal values by chance


def _stated_dollar_figures(answer: str):
    """(text, value, display_unit, significant_digits) for each $ figure in
    the answer. The unit is the precision it was written to ($4.6M ->
    100,000; $374K -> 1,000)."""
    out = []
    for m in _DOLLAR_FIGURE.finditer(answer or ""):
        whole, frac, suffix = m.group(1), m.group(2) or "", (m.group(3) or "").lower()
        mult = _SUFFIX.get(suffix, 1.0)
        value = float(whole.replace(",", "") + ("." + frac if frac else "")) * mult
        sig = len((whole.replace(",", "") + frac).lstrip("0").rstrip("0"))
        out.append((m.group(0).strip(), value, mult / (10 ** len(frac)), sig))
    return out


def _source_money_values(data) -> List[Tuple[str, float, bool]]:
    """(key, value, in_row) for every dollar-valued number anywhere in data.
    in_row: the dict sits inside a list (a deal or week row), as opposed to
    a summary scalar such as pipeline_summary.total_incremental_arr."""
    out = []
    stack = [(data, False)]
    while stack:
        x, in_row = stack.pop()
        if isinstance(x, list):
            stack.extend((i, True) for i in x)
        elif isinstance(x, dict):
            for k, v in x.items():
                if (isinstance(v, (int, float)) and not isinstance(v, bool) and v
                        and _MONEY_KEY.search(str(k)) and not _NOT_MONEY_KEY.search(str(k))):
                    out.append((str(k), abs(float(v)), in_row))
                elif isinstance(v, (dict, list)):
                    stack.append((v, in_row))
    return out


def _matches(stated: float, unit: float, source: float) -> bool:
    """stated agrees with source at the precision stated was written to
    (half a display unit, or 1% for rounded prose)."""
    return abs(stated - source) <= max(unit / 2, 0.01 * source)


def _exact_at_precision(stated: float, unit: float, source: float) -> bool:
    """Stricter, for slip candidates: within half a display unit, no 1% slack."""
    return abs(stated - source) <= unit / 2


def check_answer_unit_slips(answer: str, data: Dict) -> List[PlausibilityViolation]:
    """A dollar figure that matches no source value, but matches one after
    multiplying or dividing by 1,000 or 1,000,000, is a suspected unit slip:
    "$4,577" for $4,577,066, "$374M" for $374,000.

    Figures matching a source value directly are never flagged, and neither
    are ones that match nothing (derived totals, sums the model computed):
    this only fires when the only explanation found is a factor of 1,000.

    Tuned on 2,053 figures in 159 production answers (answers_given,
    2026-09-24) replayed against every money value in deals (352): a loose
    version flagged 26 figures, all false. The limits that brought it to 0:
      - a slip match must be exact at the figure's written precision, and
        the figure needs 3+ significant digits ("$30" x1000 or "$25.0M"
        /1000 hits a round deal value by chance);
      - "stated too LARGE" (source x1000) is only checked against summary
        scalars, never row values: a multi-million aggregate /1000 equals
        some $10-40K deal ("$23.8M" vs a $23,800 deal) too often.
    """
    stated = _stated_dollar_figures(answer)
    if not stated:
        return []
    sources = _source_money_values(data)
    if not sources:
        return []
    slips = []
    for text, value, unit, sig in stated:
        if value <= 0 or sig < _SLIP_MIN_SIG_DIGITS or any(
                _matches(value, unit, v) for _, v, _ in sources):
            continue
        for factor in _SLIP_FACTORS:
            hit = next(((k, v) for k, v, in_row in sources if v >= _SLIP_MIN_SOURCE and (
                _exact_at_precision(value * factor, unit * factor, v)
                or (not in_row and _exact_at_precision(value / factor, unit / factor, v)))), None)
            if hit:
                slips.append({"stated": text, "stated_value": value, "source_key": hit[0],
                              "source_value": hit[1], "factor": factor})
                break
    if not slips:
        return []
    return [PlausibilityViolation(
        "answer_unit_slip", "error",
        f"{len(slips)} stated figure(s) off from a source value by a factor of 1,000 or more: "
        + "; ".join(f"{s['stated']} vs {s['source_key']}={s['source_value']:,.0f} "
                    f"(x{s['factor']:,.0f})" for s in slips),
        {"slips": slips})]


def run_answer_checks(answer: str, data: Dict) -> List[PlausibilityViolation]:
    """Every answer-side check. Never raises: a checker bug must not cost
    the user their answer (it is logged by the caller and returns [])."""
    out = []
    for check in (check_answer_week_basis, check_answer_unit_slips):
        try:
            out.extend(check(answer, data))
        except Exception as e:  # pragma: no cover - defensive
            import logging
            logging.getLogger(__name__).warning(f"[PLAUSIBILITY] {check.__name__} raised: {e}")
    return out


_ANSWER_CAVEATS = {
    "answer_week_basis": (
        "⚠️ Note: weekly figures before Sep 11, 2026 are valued on deal value and later weeks "
        "on Incremental ARR. The basis shown for one or more weeks above doesn't match how "
        "that week was computed."),
}


def answer_caveat(violations: List[PlausibilityViolation]) -> str:
    """The plain-language note appended to an answer for these violations
    (one line per kind of check), or '' when there are none."""
    seen = []
    for v in violations:
        if v.check == "answer_week_basis" and v.context.get("unlabeled_totals"):
            text = ("⚠️ Note: a quarter total above adds weeks valued on deal value (before "
                    "Sep 11, 2026) to weeks valued on Incremental ARR, so it mixes two bases.")
            if text not in seen:
                seen.append(text)
            continue
        if v.check == "answer_unit_slip":
            for sl in v.context.get("slips", []):
                seen.append(f"⚠️ Note: {sl['stated']} above may be off by a factor of "
                            f"{sl['factor']:,.0f}: the underlying figure is "
                            f"${sl['source_value']:,.0f}. Please double-check before relying on it.")
            continue
        text = _ANSWER_CAVEATS.get(v.check)
        if text and text not in seen:
            seen.append(text)
    return "\n".join(seen)


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
