#!/usr/bin/env python3
"""
Planted-bug proof for GATE 2 (tests/test_column_reference_validity.py).

Each case writes a small Python file with a bad column hidden in a shape the
first regex-based gate couldn't see, runs the real extractor and audit on it,
and asserts the bad column is reported. The control reproduces what the old
gate saw on the exact forecast_trust.py shape: only the first literal.
"""
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))

import test_column_reference_validity as gate  # noqa: E402

SCHEMA = {"deals": {"deal_id", "company_name", "stage", "create_date", "close_date",
                    "segment", "forecast_category", "deal_status", "arr_usd", "new_arr"}}

FORECAST_TRUST_SHAPE = '''
def f(sb):
    return sb.table("deals").select(
        "deal_id,company_name,stage,create_date,close_date,segment,"
        "forecast_category,deal_status,amount"
    ).eq("deal_status", "active").execute()
'''


def _audit(src):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "planted.py"
        p.write_text(src)
        return gate.audit([p], SCHEMA, root=Path(d))


def _bad(r):
    return sorted((s.table, c) for s, c in r["invalid"])


def test_split_literal_forecast_trust_shape_is_caught():
    r = _audit(FORECAST_TRUST_SHAPE)
    assert _bad(r) == [("deals", "amount")], _bad(r)
    print("✓ adjacent string literals (the forecast_trust.py shape): deals.amount caught")


def test_control_old_regex_saw_only_the_first_literal():
    """What 8d3c1380's gate extracted for this shape: its regex for the
    argument-on-the-next-line case matched only the first literal."""
    lines = FORECAST_TRUST_SHAPE.splitlines()
    i = next(k for k, ln in enumerate(lines) if ".select(" in ln)
    old_arg = re.match(r'\s*["\']([^"\']+)["\']', lines[i + 1]).group(1)
    assert "amount" not in old_arg and old_arg.endswith("segment,")
    (s,) = gate.extract_selects(_write(FORECAST_TRUST_SHAPE), root=Path("/"))
    assert s.arg.endswith("forecast_category,deal_status,amount")
    print(f"✓ control: the old regex saw {old_arg!r}; the AST extractor sees the full joined string")


def _write(src):
    d = Path(tempfile.mkdtemp())
    p = d / "planted.py"
    p.write_text(src)
    return p


def test_other_hiding_shapes_are_caught():
    cases = {
        "backslash chain": 'x = sb.table("deals")\\\n    .select("deal_id, bogus_a")\n',
        "parenthesised chain": 'x = (sb\n  .table("deals")\n  .eq("a", 1)\n  .select("deal_id,"\n          " bogus_b"))\n',
        "keyword after columns": 'x = sb.table("deals").select("deal_id,bogus_c", count="exact")\n',
        "alias and cast": 'x = sb.table("deals").select("v:bogus_d::text, id:deal_id")\n',
        "json path": 'x = sb.table("deals").select("bogus_e->>k")\n',
    }
    for name, src in cases.items():
        r = _audit(src)
        bad = [c for _, c in _bad(r)]
        assert len(bad) == 1 and bad[0].startswith("bogus_"), (name, bad)
    print(f"✓ {len(cases)} more hiding shapes caught: " + ", ".join(cases))


def test_valid_postgrest_syntax_is_not_flagged():
    r = _audit('x = sb.table("deals").select("v:arr_usd::text, deal_id, owner:companies(name), count()")\n')
    assert _bad(r) == [] and r["partly_checked"] == 1, r
    print("✓ alias, cast, embedded resource and aggregate: valid columns pass, "
          "unverifiable items counted as partly checked")


def test_unknown_table_and_dynamic_selects_are_reported_not_passed():
    r = _audit('a = sb.table("deelz").select("deal_id")\n'
               'b = sb.table(name).select("deal_id")\n'
               'c = sb.table("deals").select(cols)\n'
               'd = sb.table("deals").select("*")\n')
    assert [s.table for s in r["unknown_table"]] == ["deelz"]
    assert len(r["unchecked"]["dynamic_table_or_columns"]) == 2
    assert len(r["unchecked"]["wildcard_only"]) == 1
    assert r["fully_checked"] == 0
    print("✓ unknown table fails; dynamic table/columns and wildcards are counted as NOT checked")


def test_real_forecast_trust_select_is_read_in_full():
    (s,) = [x for x in gate.extract_selects(REPO / "scripts" / "forecast_trust.py")
            if x.table == "deals"]
    assert "forecast_category" in s.arg and "deal_status" in s.arg, s.arg
    print(f"✓ scripts/forecast_trust.py:{s.line}: the gate reads the whole column list ({s.arg!r})")


if __name__ == "__main__":
    test_split_literal_forecast_trust_shape_is_caught()
    test_control_old_regex_saw_only_the_first_literal()
    test_other_hiding_shapes_are_caught()
    test_valid_postgrest_syntax_is_not_flagged()
    test_unknown_table_and_dynamic_selects_are_reported_not_passed()
    test_real_forecast_trust_select_is_read_in_full()
    print("\n✅ All tests passed")
