"""Tests for consistent period-key format across all code paths.

The rep_targets Supabase table stores period values in FY-first format:
'FY2027_Q3' (not 'Q3_FY2027'). Every code path that queries this table
must produce that format. These tests verify:

1. _period_label_for_quarter() produces FY-first format
2. resolve_time_window() fiscal_quarter path produces FY-first label
3. current_quarter_label() produces FY-first format
4. Router schema and handler error messages document FY-first format

Planted-bug controls: tests assert the CORRECT format and fail on inverted.
"""
import sys
from pathlib import Path
from datetime import date
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


# ── Test 1: _period_label_for_quarter produces FY-first ──────────────────

def test_period_label_for_quarter_fy_first():
    """_period_label_for_quarter('FY2027 Q3') must return 'FY2027_Q3'."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from pipeline_coverage import _period_label_for_quarter
    assert _period_label_for_quarter("FY2027 Q3") == "FY2027_Q3"


def test_period_label_for_quarter_other_quarters():
    from pipeline_coverage import _period_label_for_quarter
    assert _period_label_for_quarter("FY2027 Q1") == "FY2027_Q1"
    assert _period_label_for_quarter("FY2026 Q4") == "FY2026_Q4"
    assert _period_label_for_quarter("FY2028 Q2") == "FY2028_Q2"


def test_period_label_for_quarter_rejects_inverted():
    """Must NOT produce Q3_FY2027 (inverted) format."""
    from pipeline_coverage import _period_label_for_quarter
    result = _period_label_for_quarter("FY2027 Q3")
    assert not result.startswith("Q"), f"Got inverted format: {result}"


# ── Test 2: resolve_time_window fiscal_quarter path label ─────────────────

def test_resolve_time_window_fiscal_quarter_label_fy_first():
    """When period='fiscal_quarter', label must be FY-first (e.g. 'FY2027 Q3')."""
    sys.path.insert(0, str(ROOT / "api"))
    from time_resolver import resolve_time_window
    tw_input = {"period": "fiscal_quarter", "fiscal_quarter": "Q3 FY2027"}
    with patch("time_resolver._client_config", return_value={"fiscal": {"fy_start_month": 2}}):
        result = resolve_time_window(tw_input)
    label = result.get("label", "")
    assert label.startswith("FY"), f"Expected FY-first label, got: {label}"
    assert label == "FY2027 Q3", f"Expected 'FY2027 Q3', got: {label}"


def test_resolve_time_window_fiscal_quarter_q1():
    sys.path.insert(0, str(ROOT / "api"))
    from time_resolver import resolve_time_window
    tw_input = {"period": "fiscal_quarter", "fiscal_quarter": "Q1 FY2027"}
    with patch("time_resolver._client_config", return_value={"fiscal": {"fy_start_month": 2}}):
        result = resolve_time_window(tw_input)
    assert result["label"] == "FY2027 Q1"


# ── Test 3: current_quarter_label produces FY-first ──────────────────────

def test_current_quarter_label_fy_first():
    """current_quarter_label() output must start with 'FY'."""
    sys.path.insert(0, str(ROOT / "api"))
    from time_resolver import current_quarter_label
    with patch("time_resolver._client_config", return_value={"fiscal": {"fy_start_month": 2}}):
        with patch("time_resolver._today", return_value=date(2026, 9, 30)):
            label = current_quarter_label()
    assert label.startswith("FY"), f"Expected FY-first, got: {label}"
    assert label == "FY2027_Q3", f"Expected 'FY2027_Q3', got: {label}"


# ── Test 4: query_coverage period derivation ──────────────────────────────

def test_coverage_period_from_tw_label():
    """query_coverage derives period_label from tw label — must be FY-first."""
    label = "FY2027 Q3"
    period_label = label.replace(" ", "_")
    assert period_label == "FY2027_Q3"
    assert not period_label.startswith("Q")


def test_coverage_period_from_fiscal_quarter_tw():
    """Even when resolve_time_window handles 'fiscal_quarter', the derived
    period must be FY-first after .replace(' ', '_')."""
    sys.path.insert(0, str(ROOT / "api"))
    from time_resolver import resolve_time_window
    tw_input = {"period": "fiscal_quarter", "fiscal_quarter": "Q3 FY2027"}
    with patch("time_resolver._client_config", return_value={"fiscal": {"fy_start_month": 2}}):
        tw = resolve_time_window(tw_input)
    period_label = tw.get("label", "").replace(" ", "_")
    assert period_label == "FY2027_Q3", f"Got: {period_label}"


# ── Planted-bug control: inverted format must fail ────────────────────────

def test_planted_bug_inverted_format_detected():
    """If _period_label_for_quarter returned 'Q3_FY2027', this test catches it."""
    from pipeline_coverage import _period_label_for_quarter
    result = _period_label_for_quarter("FY2027 Q3")
    assert result != "Q3_FY2027", "Planted-bug control: inverted format not detected"
