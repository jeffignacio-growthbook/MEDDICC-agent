#!/usr/bin/env python3
"""
Gate: every third-party import in shipped code is declared in requirements.txt.

Declared-deps drift from imported-deps and the gap only surfaces on a genuinely
clean install — exactly how `yaml` bit the template repo and `python-dotenv` was
one clean checkout from biting this one (imported unguarded in 27 scripts,
surviving on a transitive install). This turns that one-time discovery into a
guard, next to the null-coalescing ratchet: the class fails a normal PR instead
of a clean-env run someone happens to do later.

Design (fail-closed, explicit, informational-reverse):
  1. Unknown imports FAIL, never skip. A third-party import that is neither in
     the alias map nor resolvable to a declared package fails with a clear
     "add to alias map or declare in requirements.txt". A silent skip on an
     unrecognized name is how the guard stops guarding.
  2. The scanned set is an explicit named constant (SHIPPED_PATHS), not a
     directory convention — a new top-level dir falling outside the scan is a
     visible decision, not an accident.
  3. A requirements entry that nothing imports is reported as a WARNING (dead
     weight / leftover), never a failure.
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Only these trees are "shipped" and scanned for imports. Anything outside is a
# deliberate exclusion — change this constant, not the convention, to add one.
SHIPPED_PATHS = ["scripts/", "api/"]

# import-name -> pip package, ONLY where they differ. A direct match (import
# name == package name: requests, anthropic, fastapi, …) resolves without an
# entry here. THIS MAP is the human-eyes part: a new dependency whose import
# name differs from its PyPI package name needs one line added.
ALIAS = {
    "yaml":     "PyYAML",
    "dotenv":   "python-dotenv",
    "dateutil": "python-dateutil",
    "psycopg2": "psycopg2-binary",
    # NB: PyGithub and python-multipart are declared but NOT imported by shipped
    # code (they surface in the reverse-check warning below), so their
    # import→package aliases (github→PyGithub, multipart→python-multipart) are
    # intentionally absent — the map holds only what the current tree imports.
    # Add the line back the day shipped code imports one of them.
}


def _requirements_packages():
    """Base package names declared in requirements.txt (lowercased, extras and
    version specifiers stripped): 'uvicorn[standard]>=0.24' -> 'uvicorn'."""
    out = set()
    for line in (REPO / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        base = line
        for sep in ("[", ">", "<", "=", "!", "~", " ", ";"):
            base = base.split(sep)[0]
        if base:
            out.add(base.strip().lower())
    return out


def _local_module_names():
    """Names importable as local modules/packages — so they're never mistaken
    for third-party. Built comprehensively from the whole repo (every .py stem
    and every package dir), because a missed local name would be a false
    failure under the fail-closed rule."""
    local = set()
    for p in REPO.rglob("*.py"):
        s = str(p)
        if "__pycache__" in s or "/.git/" in s:
            continue
        local.add(p.stem)
    for p in REPO.rglob("*"):
        if p.is_dir() and (p / "__init__.py").exists():
            local.add(p.name)
    # Top-level dirs on the PYTHONPATH the tests run under are import roots too.
    for d in ("scripts", "api", "scripts/analytics", "scripts/adapters",
              "scripts/enrichment"):
        dd = REPO / d
        if dd.is_dir():
            local.add(dd.name)
    return local


def _scan_imports():
    """{top_level_import_name: {files}} over SHIPPED_PATHS. Relative imports
    (level>0) are local by definition and skipped."""
    found = {}
    for base in SHIPPED_PATHS:
        for p in (REPO / base).rglob("*.py"):
            if "__pycache__" in str(p):
                continue
            try:
                tree = ast.parse(p.read_text())
            except Exception:
                continue
            for n in ast.walk(tree):
                names = []
                if isinstance(n, ast.Import):
                    names = [a.name.split(".")[0] for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    names = [n.module.split(".")[0]]
                for m in names:
                    found.setdefault(m, set()).add(str(p.relative_to(REPO)))
    return found


def run():
    print("=" * 74)
    print("REQUIREMENTS COMPLETENESS — every shipped import is declared")
    print(f"  scanned: {SHIPPED_PATHS}")
    print("=" * 74)

    stdlib = set(sys.stdlib_module_names)
    local = _local_module_names()
    declared = _requirements_packages()
    imports = _scan_imports()

    def resolve(name):
        """The pip package a third-party import resolves to, or None."""
        pkg = ALIAS.get(name, name)
        return pkg if pkg.lower() in declared else None

    unresolved = []          # third-party import → no declared package (FAIL)
    used_packages = set()    # declared packages that something imports
    third_party = {}
    for name, files in sorted(imports.items()):
        if name in stdlib or name in local or name.startswith("_"):
            continue
        third_party[name] = files
        pkg = resolve(name)
        if pkg is None:
            unresolved.append((name, sorted(files)[:3]))
        else:
            used_packages.add(pkg.lower())

    print(f"\nthird-party imports in shipped code: {len(third_party)}")
    for name in sorted(third_party):
        pkg = resolve(name)
        via = f" (alias→{ALIAS[name]})" if name in ALIAS else ""
        print(f"  {'OK ' if pkg else 'MISSING'}  {name:16} -> "
              f"{pkg or '???':18}{via}  [{len(third_party[name])} files]")

    # 3. Reverse check — declared but never imported. WARNING, not failure.
    unused = sorted(declared - used_packages)
    if unused:
        print(f"\n  ⚠️  declared in requirements.txt but not imported by shipped "
              f"code ({len(unused)}): {', '.join(unused)}")
        print("      (informational — dead weight, a runtime-only dep, or a "
              "leftover; not a failure)")

    # 1. Fail-closed on anything that didn't resolve.
    if unresolved:
        print("\n" + "=" * 74)
        print("FAIL — unresolved third-party import(s):")
        for name, files in unresolved:
            print(f"  {name}  (e.g. {', '.join(files)})")
            print(f"      unknown import '{name}' — add it to the ALIAS map "
                  f"(import-name → pip package) or declare it in requirements.txt")
        print("=" * 74)
        return 1

    print("\n" + "=" * 74)
    print(f"PASS — all {len(third_party)} third-party imports resolve to a "
          f"declared package.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(run())
