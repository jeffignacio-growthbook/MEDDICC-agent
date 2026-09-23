"""
CI gate: Incremental ARR has ONE definition — api/incremental_arr.py's
incremental_arr(). Any other code that sums new_arr and expansion_arr
itself fails this test.

Why this exists (2026-09-23): the metric-basis-mismatch pattern kept
recurring because the arithmetic lived in ~25 separate inline copies
(`(d.get("new_arr") or 0) + (d.get("expansion_arr") or 0)` and variants)
across api/ and scripts/. A NULL-handling audit found all of them
"individually correct" — which is not the same as governed: any one of
them could drift (drop the `or 0`, add renewal_revenue, read deal_value
instead) with nothing to catch it. They now all call incremental_arr(),
and this gate keeps a new copy from appearing.

How it detects a reimplementation — structurally, via the AST, not by
grepping text:
  - an addition whose two sides reference the two components (one side
    new_arr, the other expansion_arr — as a variable name, a .get("...")
    key, or a ["..."] subscript), in any form: bare names, `or 0`
    coalescing, float(...) wrapping, inside sum(...) generators;
  - sum([...]) / sum((...)) over a literal list/tuple holding both;
  - the same for HubSpot's raw property names (new_revenue +
    expansion_revenue), so the ETL side can't grow its own copy either.

Out of scope, deliberately: scripts/utils.py compute_deal_value() sums
config-listed HubSpot components with an `amount` fallback and a renewal
rule — a different, upstream metric (it produces new_arr/expansion_arr's
source values), and it names no component literally, so it is not
matched. Docstrings, comments and log strings are not code and are never
matched.

Known limitation: a sum split across two statements (`t += new_arr` then
`t += expansion_arr`) is not detected.
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
SCAN_DIRS = [REPO / "api", REPO / "scripts"]
CANONICAL = REPO / "api" / "incremental_arr.py"

COMPONENT_PAIRS = [
    ("new_arr", "expansion_arr"),
    ("new_revenue", "expansion_revenue"),
]


def _referenced_fields(node) -> set:
    """Field names an expression reads: variable names, .get("k") keys,
    ["k"] subscripts, and bare string constants inside it."""
    found = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            found.add(n.id)
        elif isinstance(n, ast.Attribute):
            found.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            found.add(n.value)
    return found


def _pair_in(left: set, right: set):
    for a, b in COMPONENT_PAIRS:
        if (a in left and b in right) or (b in left and a in right):
            return (a, b)
    return None


def find_reimplementations(source: str, filename: str = "<string>") -> list:
    """[(lineno, description)] for every inline component sum in `source`."""
    tree = ast.parse(source, filename=filename)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            pair = _pair_in(_referenced_fields(node.left), _referenced_fields(node.right))
            if pair:
                hits.append((node.lineno, f"{pair[0]} + {pair[1]}"))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "sum" and node.args
              and isinstance(node.args[0], (ast.List, ast.Tuple))):
            elts = [_referenced_fields(e) for e in node.args[0].elts]
            for i, left in enumerate(elts):
                for right in elts[i + 1:]:
                    pair = _pair_in(left, right)
                    if pair:
                        hits.append((node.lineno, f"sum([{pair[0]}, {pair[1]}])"))
    # A nested sum like (a + b) + c reports once per outermost match only.
    return sorted(set(hits))


def _scan_repo() -> dict:
    offenders = {}
    for d in SCAN_DIRS:
        for path in sorted(d.rglob("*.py")):
            if path.resolve() == CANONICAL.resolve() or "__pycache__" in path.parts:
                continue
            try:
                hits = find_reimplementations(path.read_text(), str(path))
            except SyntaxError:
                continue  # not this gate's job; py_compile/other tests own that
            if hits:
                offenders[str(path.relative_to(REPO))] = hits
    return offenders


def test_no_inline_incremental_arr_outside_canonical():
    offenders = _scan_repo()
    assert not offenders, (
        "Incremental ARR re-implemented inline instead of calling the "
        "canonical function. Replace each with "
        "`from api.incremental_arr import incremental_arr` → "
        "`incremental_arr(deal)`:\n" + "\n".join(
            f"  {f}:{ln}  {desc}" for f, hits in offenders.items()
            for ln, desc in hits))
    print("✓ no inline new_arr + expansion_arr outside api/incremental_arr.py")


def test_detector_catches_every_known_shape():
    """Negative control: every shape the ~25 original copies used must be
    flagged, so a passing scan means 'none present', not 'blind'."""
    shapes = [
        'x = (d.get("new_arr") or 0) + (d.get("expansion_arr") or 0)',
        'x = (d.get("expansion_arr") or 0) + (d.get("new_arr") or 0)',
        "x = (deal.get('new_arr', 0) or 0) + (deal.get('expansion_arr', 0) or 0)",
        'new_arr = d.get("new_arr") or 0\nexpansion_arr = d.get("expansion_arr") or 0\n'
        'x = expansion_arr + new_arr',
        'x = float(new_arr or 0) + float(expansion_arr or 0)',
        't = sum((d.get("new_arr") or 0) + (d.get("expansion_arr") or 0) for d in ds)',
        'x = d["new_arr"] + d["expansion_arr"]',
        'x = sum([d["new_arr"], d["expansion_arr"]])',
        'x = row.new_arr + row.expansion_arr',
        'x = p.get("new_revenue") + p.get("expansion_revenue")',
    ]
    for src in shapes:
        assert find_reimplementations(src), f"detector missed: {src!r}"
    clean = [
        'from api.incremental_arr import incremental_arr\nx = incremental_arr(d)',
        'x = (d.get("new_arr") or 0) + (d.get("renewal_revenue") or 0)',
        '"""Incremental ARR = new_arr + expansion_arr"""',
        'logger.info("new_arr + expansion_arr")',
    ]
    for src in clean:
        assert not find_reimplementations(src), f"false positive: {src!r}"
    print(f"✓ detector flags all {len(shapes)} known shapes, "
          f"0 false positives on {len(clean)} clean ones")


def test_canonical_function_still_exists():
    sys.path.insert(0, str(REPO))
    from api.incremental_arr import incremental_arr
    assert incremental_arr({"new_arr": 50000, "expansion_arr": None}) == 50000
    assert incremental_arr({"new_arr": None, "expansion_arr": None}) == 0
    print("✓ api/incremental_arr.py:incremental_arr is importable and NULL-safe")


if __name__ == "__main__":
    test_detector_catches_every_known_shape()
    test_canonical_function_still_exists()
    test_no_inline_incremental_arr_outside_canonical()
    print("\n✅ All tests passed")
