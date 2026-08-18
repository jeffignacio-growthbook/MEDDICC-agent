#!/usr/bin/env python3
"""
Eval: SDR utilities data-handling layer.

Tests all data utility functions with focus on edge cases that fail
in production (None, empty, type mismatches, zero division).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime, timezone as _tz


def test_data_utilities():
    """Test all data-handling utility functions."""
    from sdr_utils import (
        safe_get,
        to_float,
        to_int,
        rate_or_gap,
        flatten_buckets,
        parse_iso,
        normalize_disposition,
        connected_from_disposition
    )

    print("=" * 80)
    print("SDR DATA UTILITIES EVAL")
    print("=" * 80)
    print()

    # ── Test 1: safe_get happy path ──
    print("[TEST 1] safe_get - happy path nested access")
    print()

    data = {"a": {"b": {"c": 123}}, "x": [1, 2, 3]}

    result = safe_get(data, "a", "b", "c")
    assert result == 123, f"Expected 123, got {result}"
    print(f"  ✓ safe_get({{'a': {{'b': {{'c': 123}}}}}}, 'a', 'b', 'c') -> 123")

    result = safe_get(data, "x", 1)
    assert result == 2, f"Expected 2, got {result}"
    print(f"  ✓ safe_get({{'x': [1, 2, 3]}}, 'x', 1) -> 2")
    print()

    # ── Test 2: safe_get edge cases ──
    print("[TEST 2] safe_get - edge cases (never raises)")
    print()

    result = safe_get(None, "a")
    assert result is None, f"Expected None, got {result}"
    print(f"  ✓ safe_get(None, 'a') -> None (no raise)")

    result = safe_get(data, "missing")
    assert result is None, f"Expected None, got {result}"
    print(f"  ✓ safe_get(data, 'missing') -> None (missing key)")

    result = safe_get(data, "x", 99)
    assert result is None, f"Expected None, got {result}"
    print(f"  ✓ safe_get(data, 'x', 99) -> None (index out of range)")

    result = safe_get({"a": 1}, "a", "b")
    assert result is None, f"Expected None, got {result}"
    print(f"  ✓ safe_get({{'a': 1}}, 'a', 'b') -> None (int not subscriptable)")

    result = safe_get(data, "a", "b", "c", "d")
    assert result is None, f"Expected None, got {result}"
    print(f"  ✓ safe_get(..., 'a', 'b', 'c', 'd') -> None (path too deep)")
    print()

    # ── Test 3: to_float happy path ──
    print("[TEST 3] to_float - type coercion")
    print()

    assert to_float("0.331") == 0.331
    print(f"  ✓ to_float('0.331') -> 0.331")

    assert to_float(42) == 42.0
    print(f"  ✓ to_float(42) -> 42.0")

    assert to_float(3.7) == 3.7
    print(f"  ✓ to_float(3.7) -> 3.7")
    print()

    # ── Test 4: to_float edge cases ──
    print("[TEST 4] to_float - edge cases (never raises)")
    print()

    assert to_float(None) == 0.0
    print(f"  ✓ to_float(None) -> 0.0 (default)")

    assert to_float("") == 0.0
    print(f"  ✓ to_float('') -> 0.0 (empty string)")

    assert to_float("n/a") == 0.0
    print(f"  ✓ to_float('n/a') -> 0.0 (unparseable)")

    assert to_float("bad", default=99.9) == 99.9
    print(f"  ✓ to_float('bad', default=99.9) -> 99.9 (custom default)")
    print()

    # ── Test 5: to_int happy path ──
    print("[TEST 5] to_int - type coercion")
    print()

    assert to_int("42") == 42
    print(f"  ✓ to_int('42') -> 42")

    assert to_int(3.7) == 3
    print(f"  ✓ to_int(3.7) -> 3 (truncates)")

    assert to_int("3.9") == 3
    print(f"  ✓ to_int('3.9') -> 3 (string float truncates)")
    print()

    # ── Test 6: to_int edge cases ──
    print("[TEST 6] to_int - edge cases (never raises)")
    print()

    assert to_int(None) == 0
    print(f"  ✓ to_int(None) -> 0")

    assert to_int("") == 0
    print(f"  ✓ to_int('') -> 0")

    assert to_int("bad") == 0
    print(f"  ✓ to_int('bad') -> 0")
    print()

    # ── Test 7: rate_or_gap happy path ──
    print("[TEST 7] rate_or_gap - normal cases")
    print()

    result = rate_or_gap(10, 100)
    assert result == {"value": 0.1, "data_gap": False}
    print(f"  ✓ rate_or_gap(10, 100) -> {result}")

    result = rate_or_gap(0, 100)
    assert result == {"value": 0.0, "data_gap": False}
    print(f"  ✓ rate_or_gap(0, 100) -> {result}")
    print()

    # ── Test 8: rate_or_gap edge cases (CRITICAL) ──
    print("[TEST 8] rate_or_gap - edge cases (zero division, None)")
    print()

    result = rate_or_gap(10, 0)
    assert result["value"] is None and result["data_gap"] is True
    print(f"  ✓ rate_or_gap(10, 0) -> {result} (no divide by zero)")

    result = rate_or_gap(10, None)
    assert result["value"] is None and result["data_gap"] is True
    print(f"  ✓ rate_or_gap(10, None) -> {result}")

    result = rate_or_gap(None, 100)
    assert result["value"] is None and result["data_gap"] is True
    print(f"  ✓ rate_or_gap(None, 100) -> {result}")

    result = rate_or_gap(None, None)
    assert result["value"] is None and result["data_gap"] is True
    print(f"  ✓ rate_or_gap(None, None) -> {result}")

    result = rate_or_gap(None, 0)
    assert result["value"] is None and result["data_gap"] is True
    print(f"  ✓ rate_or_gap(None, 0) -> {result}")
    print()

    # ── Test 9: flatten_buckets Apollo shape ──
    print("[TEST 9] flatten_buckets - Apollo analytics response")
    print()

    apollo_response = {
        "table_response": {
            "buckets": [
                {
                    "key": "user_123",
                    "metrics": {
                        "num_phone_calls": {"value": 42},
                        "connect_rate": {"value": 0.23}
                    }
                },
                {
                    "key": "user_456",
                    "metrics": {
                        "num_phone_calls": {"value": 15},
                        "connect_rate": {"value": 0.33}
                    }
                }
            ]
        }
    }

    result = flatten_buckets(apollo_response, "num_phone_calls")
    assert len(result) == 2
    assert result[0]["key"] == "user_123"
    assert result[0]["num_phone_calls"] == 42
    assert result[0]["connect_rate"] == 0.23
    print(f"  ✓ flatten_buckets(apollo_response) -> 2 rows with metrics flattened")
    print()

    # ── Test 10: flatten_buckets edge cases ──
    print("[TEST 10] flatten_buckets - edge cases (never raises)")
    print()

    result = flatten_buckets({}, "metric")
    assert result == []
    print(f"  ✓ flatten_buckets({{}}) -> [] (empty dict)")

    result = flatten_buckets(None, "metric")
    assert result == []
    print(f"  ✓ flatten_buckets(None) -> [] (None input)")

    result = flatten_buckets({"table_response": {}}, "metric")
    assert result == []
    print(f"  ✓ flatten_buckets(no buckets) -> [] (missing buckets)")

    result = flatten_buckets({"table_response": {"buckets": []}}, "metric")
    assert result == []
    print(f"  ✓ flatten_buckets(empty buckets) -> [] (empty array)")
    print()

    # ── Test 11: parse_iso happy path ──
    print("[TEST 11] parse_iso - ISO 8601 parsing")
    print()

    result = parse_iso("2026-03-31T23:00:00Z")
    assert isinstance(result, datetime)
    assert result.tzinfo == _tz.utc
    print(f"  ✓ parse_iso('2026-03-31T23:00:00Z') -> datetime with UTC tzinfo")

    result = parse_iso("2026-03-31T23:00:00+00:00")
    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    print(f"  ✓ parse_iso('2026-03-31T23:00:00+00:00') -> datetime with tzinfo")
    print()

    # ── Test 12: parse_iso edge cases ──
    print("[TEST 12] parse_iso - edge cases (never raises)")
    print()

    result = parse_iso(None)
    assert result is None
    print(f"  ✓ parse_iso(None) -> None")

    result = parse_iso("")
    assert result is None
    print(f"  ✓ parse_iso('') -> None")

    result = parse_iso("not a date")
    assert result is None
    print(f"  ✓ parse_iso('not a date') -> None")

    result = parse_iso("bad", default="fallback")
    assert result == "fallback"
    print(f"  ✓ parse_iso('bad', default='fallback') -> 'fallback'")
    print()

    # ── Test 13: normalize_disposition Apollo ──
    print("[TEST 13] normalize_disposition - Apollo mappings")
    print()

    assert normalize_disposition("Connected", "apollo") == "connected"
    print(f"  ✓ 'Connected' (apollo) -> 'connected'")

    assert normalize_disposition("Demo Scheduled", "apollo") == "meeting_booked"
    print(f"  ✓ 'Demo Scheduled' (apollo) -> 'meeting_booked'")

    assert normalize_disposition("Left Voicemail", "apollo") == "voicemail"
    print(f"  ✓ 'Left Voicemail' (apollo) -> 'voicemail'")

    assert normalize_disposition("No Answer", "apollo") == "no_answer"
    print(f"  ✓ 'No Answer' (apollo) -> 'no_answer'")

    assert normalize_disposition("Wrong Number", "apollo") == "bad_number"
    print(f"  ✓ 'Wrong Number' (apollo) -> 'bad_number'")
    print()

    # ── Test 14: normalize_disposition Salesloft ──
    print("[TEST 14] normalize_disposition - Salesloft mappings")
    print()

    assert normalize_disposition("connected", "salesloft") == "connected"
    print(f"  ✓ 'connected' (salesloft) -> 'connected'")

    assert normalize_disposition("voicemail", "salesloft") == "voicemail"
    print(f"  ✓ 'voicemail' (salesloft) -> 'voicemail'")
    print()

    # ── Test 15: normalize_disposition Aircall ──
    print("[TEST 15] normalize_disposition - Aircall mappings")
    print()

    assert normalize_disposition("answered", "aircall") == "connected"
    print(f"  ✓ 'answered' (aircall) -> 'connected'")

    assert normalize_disposition("missed", "aircall") == "no_answer"
    print(f"  ✓ 'missed' (aircall) -> 'no_answer'")

    assert normalize_disposition("busy", "aircall") == "busy"
    print(f"  ✓ 'busy' (aircall) -> 'busy'")
    print()

    # ── Test 16: normalize_disposition edge cases (CRITICAL) ──
    print("[TEST 16] normalize_disposition - edge cases (never raises)")
    print()

    assert normalize_disposition(None, "apollo") == "unknown"
    print(f"  ✓ normalize_disposition(None, 'apollo') -> 'unknown'")

    assert normalize_disposition("", "apollo") == "unknown"
    print(f"  ✓ normalize_disposition('', 'apollo') -> 'unknown'")

    assert normalize_disposition("unrecognized value", "apollo") == "unknown"
    print(f"  ✓ normalize_disposition('unrecognized value') -> 'unknown'")
    print()

    # ── Test 17: connected_from_disposition ──
    print("[TEST 17] connected_from_disposition")
    print()

    assert connected_from_disposition("connected") is True
    print(f"  ✓ connected_from_disposition('connected') -> True")

    assert connected_from_disposition("meeting_booked") is True
    print(f"  ✓ connected_from_disposition('meeting_booked') -> True")

    assert connected_from_disposition("voicemail") is False
    print(f"  ✓ connected_from_disposition('voicemail') -> False")

    assert connected_from_disposition("no_answer") is False
    print(f"  ✓ connected_from_disposition('no_answer') -> False")

    assert connected_from_disposition("unknown") is False
    print(f"  ✓ connected_from_disposition('unknown') -> False")
    print()

    # ── Final summary ──
    print("=" * 80)
    print("Results: All tests passed!")
    print("=" * 80)
    print()
    print("VERIFIED:")
    print("- safe_get() handles all edge cases (None, missing keys, wrong types)")
    print("- to_float() and to_int() never raise on bad input")
    print("- rate_or_gap() never divides by zero, returns data_gap flag")
    print("- flatten_buckets() handles Apollo response shape and edge cases")
    print("- parse_iso() handles Z suffix, +00:00, and bad input gracefully")
    print("- normalize_disposition() maps all three tools correctly")
    print("- connected_from_disposition() identifies real conversations")
    print("- All functions return sensible defaults instead of raising")


if __name__ == "__main__":
    test_data_utilities()
