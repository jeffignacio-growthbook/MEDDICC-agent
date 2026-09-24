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
    # the cohort query (adjacent string literals), then the COMMIT close-date
    # hygiene query added 2026-09-24
    cohort, hygiene = [x for x in gate.extract_selects(REPO / "scripts" / "forecast_trust.py")
                       if x.table == "deals"]
    assert "segment," in cohort.arg and "forecast_category" in cohort.arg and "deal_status" in cohort.arg, cohort.arg
    assert "new_arr,expansion_arr" in cohort.arg, cohort.arg
    assert "forecast_category" in hygiene.arg and "deal_status" in hygiene.arg, hygiene.arg
    print(f"✓ scripts/forecast_trust.py:{cohort.line}: the gate reads the whole column list ({cohort.arg!r}), "
          f"and the hygiene query at line {hygiene.line}")


def test_select_all_and_multi_argument_selects_are_checked():
    """2026-09-24: the 09-23 rewrite checked only .table().select() chains
    and only a select's first argument. select_all(sb, table, columns=...)
    (307 calls) and .select("a", "b") went unchecked."""
    cases = {
        "select_all positional": 'rows = select_all(sb, "deals", "deal_id, bogus_f")\n',
        "select_all keyword": 'rows = select_all(sb, "deals", columns="deal_id,bogus_g", filters=[])\n',
        "attribute select_all": 'rows = supabase_client.select_all(sb, table="deals", columns="bogus_h")\n',
        "multi-argument select": 'x = sb.table("deals").select("deal_id", "new_arr", "bogus_i")\n',
    }
    for name, src in cases.items():
        bad = [c for _, c in _bad(_audit(src))]
        assert len(bad) == 1 and bad[0].startswith("bogus_"), (name, bad)
    r = _audit('a = select_all(sb, name, columns="deal_id")\n'
               'b = select_all(sb, "deals", columns=cols)\n'
               'c = select_all(sb, "deals")\n')
    assert len(r["unchecked"]["dynamic_table_or_columns"]) == 2
    assert len(r["unchecked"]["wildcard_only"]) == 1           # default columns='*'
    print(f"✓ {len(cases)} select_all / multi-argument shapes caught; dynamic and default-'*' "
          "select_all counted as NOT checked")


def test_control_the_previous_extractor_missed_them():
    """What the 09-23 extractor saw: only .select() attributes, first arg."""
    import ast as _ast
    src = ('rows = select_all(sb, "deals", "deal_id, bogus_f")\n'
           'x = sb.table("deals").select("deal_id", "new_arr", "bogus_i")\n')
    seen = []
    for node in _ast.walk(_ast.parse(src)):
        if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                and node.func.attr == "select"):
            seen.append(node.args[0].value)
    assert seen == ["deal_id"], seen
    assert _bad(_audit(src)) == [("deals", "bogus_f"), ("deals", "bogus_i")]
    print("✓ control: the previous extractor saw only 'deal_id' here; the gate now reports both bogus columns")


if __name__ == "__main__":
    test_split_literal_forecast_trust_shape_is_caught()
    test_control_old_regex_saw_only_the_first_literal()
    test_other_hiding_shapes_are_caught()
    test_valid_postgrest_syntax_is_not_flagged()
    test_unknown_table_and_dynamic_selects_are_reported_not_passed()
    test_real_forecast_trust_select_is_read_in_full()
    test_select_all_and_multi_argument_selects_are_checked()
    test_control_the_previous_extractor_missed_them()
    print("\n✅ All tests passed")
