#!/usr/bin/env python3
"""
Demonstrate monitoring alert payload adaptation for different trigger types.

Shows how send_monitoring_alert() generalizes cleanly beyond failure_count-like fields.
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional


def send_monitoring_alert(
    monitor_name: str,
    threshold_config: Dict[str, Any],
    evidence: Dict[str, Any],
    message: str,
    alert_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send monitoring alert via Zapier webhook.

    Generalizes cleanly - no forced failure_count field.
    Each trigger type provides its own evidence structure.

    Args:
        monitor_name: Which monitor fired (e.g., 'metric_divergence')
        threshold_config: Snapshot of config that triggered alert
        evidence: Trigger-specific data backing the alert
        message: Human-readable Slack message
        alert_url: Zapier webhook URL (optional for demo)

    Returns:
        Payload dict (for demonstration)
    """
    payload = {
        "type": "monitoring_alert",           # ← Type discriminator (vs "etl_failure")
        "monitor": monitor_name,              # ← Which monitor
        "fired_at": datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),
        "threshold_config": threshold_config, # ← Config snapshot
        "evidence": evidence,                 # ← Trigger-specific data
        "message": message                    # ← Slack text
    }

    # In production, would POST to alert_url
    # For demo, just return payload
    return payload


# ============================================================================
# Example 1: metric_divergence (% divergence with two numeric values)
# ============================================================================

def example_metric_divergence():
    """
    Metric divergence alert: live value differs from verified value.
    Evidence: two numbers + % difference.
    """
    print("="*70)
    print("EXAMPLE 1: METRIC DIVERGENCE")
    print("="*70)
    print()

    payload = send_monitoring_alert(
        monitor_name="metric_divergence",

        threshold_config={
            "metric": "conversion_rate_prospective",
            "tolerance_pct": 5,
            "min_evidence_count": 20
        },

        evidence={
            "metric_name": "conversion_rate_prospective",
            "verified_value": 0.072,
            "verified_date": "2026-09-04",
            "live_value": 0.084,
            "divergence_pct": 16.7,         # ← NOT a failure_count!
            "computation_script": "conversion_by_qualification_week_FINAL_CLEAN.py",
            "denominator": 376,              # ← Context for interpretation
            "live_numerator": 32,
            "verified_numerator": 27
        },

        message=(
            "⚠️ Metric Divergence: conversion_rate_prospective\n\n"
            "Verified (2026-09-04): 7.2% (27/376)\n"
            "Live today: 8.4% (32/376)\n"
            "Divergence: +16.7% (threshold: 5%)\n\n"
            "Check: Has data quality changed since verification? "
            "New deals added to cohort?"
        )
    )

    print("Payload structure:")
    print(json.dumps(payload, indent=2))
    print()
    print("✓ Clean generalization - evidence contains divergence_pct, not failure_count")
    print("✓ Threshold_config shows tolerance_pct = 5 (what triggered alert)")
    print("✓ Evidence gives both values + divergence for context")
    print()


# ============================================================================
# Example 2: snapshot_coverage (row-count ratio)
# ============================================================================

def example_snapshot_coverage():
    """
    Snapshot coverage alert: week's row count below expected.
    Evidence: row counts + ratio.
    """
    print("="*70)
    print("EXAMPLE 2: SNAPSHOT COVERAGE")
    print("="*70)
    print()

    payload = send_monitoring_alert(
        monitor_name="snapshot_coverage",

        threshold_config={
            "min_pct_of_typical": 60,
            "min_expected_rows": 50
        },

        evidence={
            "fiscal_quarter": "FY2027 Q1",
            "week_of_quarter": 11,
            "snapshot_date": "2026-04-13",
            "actual_row_count": 377,          # ← NOT a failure_count!
            "expected_row_count": 685,        # ← Trailing median
            "pct_of_expected": 55.0,          # ← Ratio
            "trailing_weeks_used": [
                {"quarter": "FY2026 Q4", "week": 11, "rows": 509},
                {"quarter": "FY2026 Q3", "week": 11, "rows": 335},
                {"quarter": "FY2026 Q4", "week": 12, "rows": 509},
                {"quarter": "FY2026 Q3", "week": 12, "rows": 355}
            ],
            "pipeline_breakdown": {
                "default": {"expected": 536, "actual": 234, "pct": 43.7},
                "866608541": {"expected": 149, "actual": 143, "pct": 96.0}
            }
        },

        message=(
            "⚠️ Snapshot Coverage Drop: FY2027 Q1 Week 11\n\n"
            "Expected: ~685 rows (based on trailing median)\n"
            "Actual: 377 rows (55% of expected)\n"
            "Threshold: 60%\n\n"
            "Pipeline breakdown:\n"
            "• default: 234 rows (expected 536, 44%)\n"
            "• renewals: 143 rows (expected 149, 96%)\n\n"
            "Check: Did snapshot job change filter? Missing data in source?"
        )
    )

    print("Payload structure:")
    print(json.dumps(payload, indent=2, default=str))
    print()
    print("✓ Clean generalization - evidence contains row counts + ratio")
    print("✓ Pipeline breakdown shows WHERE the drop occurred (default pipeline)")
    print("✓ Trailing_weeks_used provides audit trail for 'expected' calculation")
    print()


# ============================================================================
# Comparison: Original ETL failure payload
# ============================================================================

def show_original_etl_payload():
    """Show original ETL failure payload for comparison."""
    print("="*70)
    print("COMPARISON: ORIGINAL ETL FAILURE PAYLOAD")
    print("="*70)
    print()

    original = {
        "type": "etl_failure",              # ← Different type
        "job": "etl-calls",
        "consecutive_failures": 2,          # ← Specific to ETL failures
        "run_id": "12345",
        "run_url": "https://github.com/...",
        "failed_at": "2026-09-04 12:00 UTC",
        "message": "ETL job 'etl-calls' failed 2 times in a row"
    }

    print("Original structure:")
    print(json.dumps(original, indent=2))
    print()
    print("Key differences:")
    print("  • type: 'etl_failure' vs 'monitoring_alert'")
    print("  • Fields: consecutive_failures (ETL-specific) vs evidence dict (generic)")
    print("  • monitoring_alert includes threshold_config snapshot for audit")
    print()


if __name__ == '__main__':
    print("\n" + "="*70)
    print("MONITORING ALERT PAYLOAD GENERALIZATION DEMO")
    print("="*70)
    print()
    print("Demonstrating how send_monitoring_alert() adapts cleanly for different")
    print("trigger types without forcing every finding into failure_count-like fields.")
    print()

    example_metric_divergence()
    example_snapshot_coverage()
    show_original_etl_payload()

    print("="*70)
    print("CONCLUSION")
    print("="*70)
    print()
    print("✓ Payload shape generalizes cleanly")
    print("✓ Each trigger provides its own evidence structure")
    print("✓ No forced failure_count field - evidence is trigger-specific")
    print("✓ Threshold_config snapshot enables audit (why did this fire?)")
    print("✓ Type discriminator ('monitoring_alert') separates from ETL failures")
    print()
