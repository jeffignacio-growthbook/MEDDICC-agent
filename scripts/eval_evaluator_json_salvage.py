#!/usr/bin/env python3
"""
Eval: evaluator JSON salvage. Offline.

The evaluator's verbose critiques break json.loads (unescaped double quotes
inside required_changes). The old code replaced the real critique with a
generic "Evaluator parse error" string, so the regeneration loop ran on
meaningless feedback — a swallowed signal. _salvage_evaluation must recover the
`pass` boolean AND the actual critique text from malformed JSON.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def run():
    from meddicc_agent import _salvage_evaluation
    print("=" * 72)
    print("EVALUATOR JSON SALVAGE — recover pass + real critique from bad JSON")
    print("=" * 72)
    passed = failed = 0

    def check(label, cond):
        nonlocal passed, failed
        if cond:
            passed += 1; print(f"  ✓ {label}")
        else:
            failed += 1; print(f"  ❌ {label}")

    # 1) The real failure mode: unescaped double quotes inside required_changes.
    broken = ('{\n  "pass": false,\n  "required_changes": "CRITERION 4 FAILURE — '
              'Champion next step uses "make the case" which is vague seller '
              'language; reframe as a specific question about internal advocacy."\n}')
    r = _salvage_evaluation(broken, "Expecting ',' delimiter")
    print("\n[unescaped quotes inside required_changes]")
    check("pass recovered as False", r["pass"] is False)
    check("required_changes recovered (not a parse-error placeholder)",
          "CRITERION 4 FAILURE" in r["required_changes"]
          and "parse error" not in r["required_changes"].lower())
    check("the embedded critique detail survives",
          "make the case" in r["required_changes"])
    check("marked salvaged", r.get("salvaged") is True)
    check("failed eval carries a failure marker",
          bool(r["iteration_failures"]))

    # 2) A broken-JSON PASS must recover pass=True (so we don't force a needless
    #    regeneration on a deal the evaluator actually passed).
    broken_pass = ('{ "pass": true, "required_changes": "Minor: tighten the '
                   '"Metrics" evidence quote." }')
    r2 = _salvage_evaluation(broken_pass, "err")
    print("\n[broken JSON but pass=true]")
    check("pass recovered as True", r2["pass"] is True)
    check("no failure marker when passed", not r2["iteration_failures"])

    # 3) Truly unrecoverable required_changes → non-empty guidance, never blank
    #    (the loop must always get actionable feedback on a fail).
    r3 = _salvage_evaluation('{ "pass": false }', "err")
    print("\n[no required_changes present]")
    check("required_changes non-empty fallback", bool(r3["required_changes"].strip()))
    check("fallback is not the old 'parse error' string",
          "parse error" not in r3["required_changes"].lower())

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
