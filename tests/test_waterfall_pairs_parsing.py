#!/usr/bin/env python3
"""
compute_waterfall_segmented.parse_pairs: explicit-pairs spec parsing.

--pairs recomputes exactly the historical week grid (each new == an existing
week_ending) for the qualified_date $0 repair, instead of --recompute-from's
pair-every-consecutive-snapshot behaviour, which fabricates sub-weekly rows
when backfilled and prospective snapshots interleave (e.g. Aug 2026:
backfilled 8/17,8/24,8/28 alongside prospective 8/19,8/20,8/23,8/30,8/31).

This is offline and pure: it asserts the parse contract and that a malformed
or empty spec fails loudly (so a bad ops invocation can't silently recompute
nothing). Planted-bug controls at the bottom confirm the assertions actually
bind.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

from compute_waterfall_segmented import parse_pairs, value_basis_for  # noqa: E402


def test_source_defaults_to_prospective():
    assert parse_pairs("2026-09-14:2026-09-21") == [
        ("2026-09-14", "2026-09-21", "prospective")
    ]


def test_explicit_source_kept():
    assert parse_pairs("2026-08-10:2026-08-17:backfill") == [
        ("2026-08-10", "2026-08-17", "backfill")
    ]


def test_multiple_pairs_and_whitespace():
    spec = " 2026-08-10:2026-08-17:backfill , 2026-09-14:2026-09-21 "
    assert parse_pairs(spec) == [
        ("2026-08-10", "2026-08-17", "backfill"),
        ("2026-09-14", "2026-09-21", "prospective"),
    ]


def test_the_seven_repair_pairs():
    """The exact grid the qualified_date fix recomputes — each 'new' is a real
    stored week_ending; the value_basis per pair must match what is stored
    (deal_value through 09-08, incremental_arr from the 09-11 boundary)."""
    spec = ("2026-08-10:2026-08-17:backfill,"
            "2026-08-17:2026-08-24:backfill,"
            "2026-08-24:2026-08-28:backfill,"
            "2026-08-31:2026-09-07:prospective,"
            "2026-09-07:2026-09-08:prospective,"
            "2026-09-11:2026-09-14:prospective,"
            "2026-09-14:2026-09-21:prospective")
    pairs = parse_pairs(spec)
    assert len(pairs) == 7
    week_endings = [new for _, new, _ in pairs]
    assert week_endings == ["2026-08-17", "2026-08-24", "2026-08-28",
                            "2026-09-07", "2026-09-08", "2026-09-14",
                            "2026-09-21"]
    expected_basis = {
        "2026-08-17": "deal_value", "2026-08-24": "deal_value",
        "2026-08-28": "deal_value", "2026-09-07": "deal_value",
        "2026-09-08": "deal_value", "2026-09-14": "incremental_arr",
        "2026-09-21": "incremental_arr",
    }
    for prev, new, _src in pairs:
        assert value_basis_for(prev) == expected_basis[new], (
            f"{new}: basis {value_basis_for(prev)} != {expected_basis[new]}")


def _raises(spec):
    try:
        parse_pairs(spec)
        return False
    except ValueError:
        return True


def test_malformed_specs_fail_loudly():
    assert _raises("")                       # empty
    assert _raises("   ")                     # only whitespace
    assert _raises(",")                       # no tokens
    assert _raises("2026-08-10")              # single field, no ':'
    assert _raises(":2026-08-17")             # empty prev
    assert _raises("2026-08-10:")             # empty new
    assert _raises("a:b:c:d")                 # too many fields


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")

    # Planted-bug controls: swap the name the test functions actually call
    # (this module's global `parse_pairs`) for a broken impl and confirm a
    # test catches it.
    print("\n--- planted-bug controls ---")
    real = parse_pairs

    def bad_default_source(spec):
        # regression: default source flips to 'backfill' instead of prospective
        return [(p, n, ("backfill" if s == "prospective" else s))
                for (p, n, s) in real(spec)]

    parse_pairs = bad_default_source  # noqa: F811 - deliberate for the control
    try:
        try:
            test_source_defaults_to_prospective()
            print("MISS default-source planted bug NOT caught"); sys.exit(1)
        except AssertionError:
            print("CAUGHT default-source planted bug")
    finally:
        parse_pairs = real

    def never_raises(spec):
        # regression: malformed specs silently yield a dummy pair
        try:
            return real(spec)
        except ValueError:
            return [("x", "y", "prospective")]

    parse_pairs = never_raises  # noqa: F811 - deliberate for the control
    try:
        try:
            test_malformed_specs_fail_loudly()
            print("MISS malformed-spec planted bug NOT caught"); sys.exit(1)
        except AssertionError:
            print("CAUGHT malformed-spec planted bug")
    finally:
        parse_pairs = real

    print("\nAll parse_pairs tests + planted-bug controls passed.")
