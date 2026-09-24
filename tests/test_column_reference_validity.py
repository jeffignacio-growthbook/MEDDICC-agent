#!/usr/bin/env python3
"""
GATE 2: every column named in a Supabase .select() exists in the real schema.

The bug this exists for (2026-09-21, "Bug #1"): scripts/forecast_trust.py
selects deals.amount, a column that has never existed. Mocked tests passed;
in production every call failed ("column deals.amount does not exist" in the
Postgres logs, 7 times 2026-09-21 23:55 to 2026-09-23 00:23 UTC).

2026-09-24: the 2026-09-23 rewrite still missed two shapes: select_all(sb,
table, columns=...) (scripts/supabase_client.py's paginated select, 307
calls) and multi-argument .select("a", "b"). Both are covered now; the
first real finding was scripts/analytics/investigate_missing_deals.py
selecting deals.stage_id (deals has `stage`).

The first version of this gate (8d3c1380) never caught it. It found selects
with regexes and read only the FIRST string literal of the argument, and
forecast_trust.py writes its column list as two adjacent literals:

    .select(
        "deal_id,company_name,stage,create_date,close_date,segment,"
        "forecast_category,deal_status,amount"
    )

Python joins those into one string; the regex saw six valid columns and
passed. 15 of the 144 selects it reported as validated were truncated that
way (re-audit 2026-09-23). It also checked against data_dictionary, a
registry, not the schema, and it ran only on manual dispatch.

This version:
  - parses each file with ast, so adjacent literals are joined, and
    backslash, parenthesised and multi-line chains resolve, exactly as
    Python does;
  - checks against tests/fixtures/db_schema_columns.json, a snapshot of
    information_schema.columns (tables and views). It runs offline on every
    push (pr-offline-tests.yml). scripts/snapshot_db_schema.py --check
    compares the snapshot to the live schema;
  - fails on a column missing from its table, and on a table the snapshot
    doesn't know (a typo, or a new table: regenerate the snapshot);
  - reports every select it could NOT check, by reason, so the coverage
    number means what it says.

PostgREST select syntax handled: "a, b", "alias:col", "col::type",
"col->>key" (base column checked), "*" (unchecked), and embedded resources
or aggregates like "companies(name)" or "count()" (that item unchecked, the
rest of the select still checked).
"""
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set

REPO_ROOT = Path(__file__).parent.parent
SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "db_schema_columns.json"
SCAN_DIRS = [REPO_ROOT / "scripts", REPO_ROOT / "api"]

# One-off analysis scripts that reference historical columns (unchanged
# from the first version of this gate).
SKIP_PATTERNS = [
    "analyze_signal",
    "check_signal",
    "compare_signal",
    "derive_signal",
    "investigate_signal",
    "recompute_with_",
    "sample_newly_",
    "test_meddicc_timing",
    "check_enterprise_discovery_fallback",
    "check_meddicc_scores_for_validation",
]


# Selects that deliberately probe whether a table exists (inside
# try/except, printing the result), not code that depends on it. Reported
# as unchecked, by (file, table), never silently skipped.
EXISTENCE_PROBES = {
    ("scripts/verify_activity_baseline.py", "engagements"),
    ("scripts/verify_activity_baseline.py", "notes"),
    ("scripts/verify_zero_arr_age_activity.py", "engagements"),
}


class Select(NamedTuple):
    """One Supabase select: a .table(...).select(...) chain or a
    select_all(sb, table, columns) call."""
    file: str
    line: int
    table: Optional[str]      # None: no .table() in the chain; DYNAMIC: not a literal
    arg: Optional[str]        # the full, Python-joined string; None if not a literal


def load_schema(path: Path = SNAPSHOT) -> Dict[str, Set[str]]:
    data = json.loads(path.read_text())
    return {t: {c.lower() for c in cols} for t, cols in data["tables"].items()}


DYNAMIC = "<dynamic>"


def _chain_table(node: ast.AST) -> Optional[str]:
    """The table of the nearest .table(...) / .from_(...) in a call chain:
    its name, DYNAMIC if it isn't a string literal, None if there is none."""
    while isinstance(node, (ast.Call, ast.Attribute, ast.Subscript)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("table", "from_") and node.args):
            a = node.args[0]
            return a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else DYNAMIC
        node = node.func if isinstance(node, ast.Call) else node.value
    return None


def extract_selects(path: Path, root: Path = REPO_ROOT) -> List[Select]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "select":
            table = _chain_table(node.func.value)
            # supabase-py joins .select("a", "b") into "a,b": check every
            # argument, not just the first.
            arg = (",".join(a.value for a in node.args) if node.args and all(
                isinstance(a, ast.Constant) and isinstance(a.value, str) for a in node.args)
                else None)
            if table is None and arg is None:
                continue      # not a Supabase select we can say anything about
            out.append(Select(rel, node.lineno, table, arg))
        elif _is_select_all(node):
            # select_all(sb, table, columns='*', filters=None) in
            # scripts/supabase_client.py: the paginated select most code uses.
            t = _arg(node, 1, "table")
            cols = _arg(node, 2, "columns")
            table = (t.value if isinstance(t, ast.Constant) and isinstance(t.value, str)
                     else DYNAMIC)
            if cols is None:
                arg = "*"
            elif isinstance(cols, ast.Constant) and isinstance(cols.value, str):
                arg = cols.value
            else:
                arg = None
            out.append(Select(rel, node.lineno, table, arg))
    return sorted(out, key=lambda x: x.line)


def _is_select_all(node: ast.Call) -> bool:
    f = node.func
    return (isinstance(f, ast.Name) and f.id == "select_all") or (
        isinstance(f, ast.Attribute) and f.attr == "select_all")


def _arg(node: ast.Call, pos: int, name: str):
    for k in node.keywords:
        if k.arg == name:
            return k.value
    return node.args[pos] if len(node.args) > pos else None


def _split_top_level(s: str) -> List[str]:
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def parse_columns(arg: str):
    """(checkable column names, number of items that can't be checked)."""
    cols, unchecked = [], 0
    for item in _split_top_level(arg):
        item = item.strip()
        if not item:
            continue
        if "(" in item or item == "*" or item.endswith(".*"):
            unchecked += 1           # embedded resource, aggregate, wildcard
            continue
        item = item.split("::")[0]                 # cast
        if ":" in item:
            item = item.split(":", 1)[1]           # alias:column
        item = item.split("->")[0].strip()         # JSON path
        if item.replace("_", "").isalnum() and not item[0].isdigit():
            cols.append(item.lower())
        else:
            unchecked += 1
    return cols, unchecked


def audit(files, schema: Dict[str, Set[str]], root: Path = REPO_ROOT) -> dict:
    r = {"total": 0, "fully_checked": 0, "partly_checked": 0,
         "unchecked": {"dynamic_table_or_columns": [], "no_table_in_chain": [], "wildcard_only": [],
                       "existence_probe": []},
         "invalid": [], "unknown_table": []}
    for path in files:
        for s in extract_selects(path, root):
            r["total"] += 1
            if s.arg is None or s.table == DYNAMIC:
                r["unchecked"]["dynamic_table_or_columns"].append(s)
                continue
            if s.table is None:
                r["unchecked"]["no_table_in_chain"].append(s)
                continue
            cols, unchecked = parse_columns(s.arg)
            if not cols:
                r["unchecked"]["wildcard_only"].append(s)
                continue
            if s.table not in schema:
                key = "existence_probe" if (s.file, s.table) in EXISTENCE_PROBES else None
                (r["unchecked"][key] if key else r["unknown_table"]).append(s)
                continue
            r["partly_checked" if unchecked else "fully_checked"] += 1
            for c in cols:
                if c not in schema[s.table]:
                    r["invalid"].append((s, c))
    return r


def scanned_files():
    for d in SCAN_DIRS:
        for f in sorted(d.rglob("*.py")):
            if not any(p in f.name for p in SKIP_PATTERNS):
                yield f


def report(r: dict) -> str:
    unchecked = sum(len(v) for v in r["unchecked"].values())
    checked = r["fully_checked"] + r["partly_checked"]
    lines = [f"Supabase .select() calls found: {r['total']}",
             f"  checked against the schema: {checked} "
             f"({r['fully_checked']} fully, {r['partly_checked']} with embedded/aggregate items skipped)",
             f"  NOT checked: {unchecked} — "
             + ", ".join(f"{k.replace('_', ' ')} {len(v)}" for k, v in r["unchecked"].items())]
    if r["unknown_table"]:
        lines.append(f"  on tables missing from the snapshot: {len(r['unknown_table'])}")
    return "\n".join(lines)


def test_column_reference_validity():
    print("\n" + "=" * 80 + "\nGATE 2: column reference validity (AST, real schema)\n" + "=" * 80)
    r = audit(scanned_files(), load_schema())
    print(report(r))
    problems = []
    for s, c in r["invalid"]:
        problems.append(f"{s.file}:{s.line}: {s.table}.{c} does not exist")
    for s in r["unknown_table"]:
        problems.append(f"{s.file}:{s.line}: table {s.table!r} is not in {SNAPSHOT.name} "
                        f"(typo, or regenerate: python scripts/snapshot_db_schema.py)")
    if problems:
        print("\n❌ " + "\n❌ ".join(problems))
        raise AssertionError(f"{len(problems)} invalid Supabase select reference(s)")
    print("\n✅ every checkable column reference exists in the schema")


if __name__ == "__main__":
    test_column_reference_validity()
