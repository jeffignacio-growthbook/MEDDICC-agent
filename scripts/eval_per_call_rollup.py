#!/usr/bin/env python3
"""
Eval: per-call scorer parse + roll-up contract (PROGRESSIVE_SCORING_SPEC, Phase 1).

Locks the deterministic logic that does NOT need the model:
  - JSON parse tolerates fences/trailing prose; missing/malformed → null.
  - 0 and negative are coerced to null (0-means-not-discussed is forbidden).
  - Evidence is dropped when its score is null.
  - roll_up takes the most-recent-non-null per component (regression allowed;
    no max() floor); an all-null component rolls up to null.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

import call_scorer as cs  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {name}")
    if not ok:
        print(f"      got:  {got!r}")
        print(f"      want: {want!r}")
        FAILS.append(name)


def test_parse():
    print("parse_call_scores")

    # Clean JSON with a null component and a scored one.
    txt = ('{"metrics": {"score": 8, "evidence": "50k FTDs = EUR1M/yr"},'
           ' "economic_buyer": {"score": null, "evidence": null},'
           ' "decision_criteria": {"score": 7, "evidence": "unified SDK required"},'
           ' "decision_process": {"score": null, "evidence": null},'
           ' "pain": {"score": 9, "evidence": "30-day release delay"},'
           ' "champion": {"score": null, "evidence": null},'
           ' "competition": {"score": 8, "evidence": "Optimizely incumbent"}}')
    p = cs.parse_call_scores(txt)
    check("metrics scored", p["metrics"], {"score": 8, "evidence": "50k FTDs = EUR1M/yr"})
    check("economic_buyer null", p["economic_buyer"], {"score": None, "evidence": None})
    check("champion null", p["champion"], {"score": None, "evidence": None})

    # Code-fenced + trailing prose.
    fenced = "```json\n" + txt + "\n```\nThat is my assessment."
    check("fenced+prose parses", cs.parse_call_scores(fenced)["pain"], {"score": 9, "evidence": "30-day release delay"})

    # 0 is coerced to null (0-means-not-discussed is forbidden), evidence dropped.
    z = '{"metrics": {"score": 0, "evidence": "not discussed"}}'
    check("zero -> null", cs.parse_call_scores(z)["metrics"], {"score": None, "evidence": None})

    # Score as string; evidence kept.
    s = '{"champion": {"score": "3", "evidence": "owns CPO intro"}}'
    check("string score coerced", cs.parse_call_scores(s)["champion"], {"score": 3, "evidence": "owns CPO intro"})

    # Out-of-range -> null.
    oor = '{"pain": {"score": 42, "evidence": "x"}}'
    check("out-of-range -> null", cs.parse_call_scores(oor)["pain"], {"score": None, "evidence": None})

    # Non-null score but missing evidence stays scored with null evidence.
    ne = '{"metrics": {"score": 6}}'
    check("score w/o evidence", cs.parse_call_scores(ne)["metrics"], {"score": 6, "evidence": None})

    # Garbage / empty -> all null, never raises.
    check("garbage -> all null", cs.parse_call_scores("not json at all")["metrics"], {"score": None, "evidence": None})
    check("empty -> all null", cs.parse_call_scores("")["competition"], {"score": None, "evidence": None})

    # Every call returns all seven keys.
    check("all seven keys present", sorted(cs.parse_call_scores("{}").keys()), sorted(cs.COMPONENT_KEYS))


def _comps(**kw):
    """Build a components dict; unspecified keys are null."""
    c = {k: {"score": None, "evidence": None} for k in cs.COMPONENT_KEYS}
    for k, (s, e) in kw.items():
        c[k] = {"score": s, "evidence": e}
    return c


def test_rollup():
    print("roll_up")

    # Out-of-order input; most-recent-non-null wins.
    calls = [
        {"call_id": "c2", "call_date": "2026-07-30", "components": _comps(
            economic_buyer=(5, "CPO review referenced"), champion=(5, "coordinating"))},
        {"call_id": "c1", "call_date": "2026-07-15", "components": _comps(
            pain=(8, "cost pain"), champion=(3, "engaged, no action"))},
        {"call_id": "c3", "call_date": "2026-08-05", "components": _comps(
            economic_buyer=(6, "budget owner named"))},
    ]
    r = cs.roll_up(calls)
    check("champion from latest non-null (c2=5)", (r["champion"]["score"], r["champion"]["call_id"]), (5, "c2"))
    check("economic_buyer from newest (c3=6)", (r["economic_buyer"]["score"], r["economic_buyer"]["call_id"]), (6, "c3"))
    check("pain carried from only call that had it", (r["pain"]["score"], r["pain"]["call_id"]), (8, "c1"))
    check("metrics never scored -> null", r["metrics"], {"score": None, "evidence": None, "call_id": None, "call_date": None})

    # Regression: a later call LOWERS a component (champion leaves). No max floor.
    reg = [
        {"call_id": "a", "call_date": "2026-01-01", "components": _comps(champion=(8, "building business case"))},
        {"call_id": "b", "call_date": "2026-02-01", "components": _comps(champion=(2, "champion left the company"))},
    ]
    rr = cs.roll_up(reg)
    check("regression allowed (8 -> 2)", (rr["champion"]["score"], rr["champion"]["call_id"]), (2, "b"))

    # A later null does NOT overwrite an earlier score (silence maintains).
    sil = [
        {"call_id": "a", "call_date": "2026-01-01", "components": _comps(metrics=(7, "quantified"))},
        {"call_id": "b", "call_date": "2026-02-01", "components": _comps()},  # silent on everything
    ]
    rs = cs.roll_up(sil)
    check("later null does not clear earlier score", (rs["metrics"]["score"], rs["metrics"]["call_id"]), (7, "a"))

    # Total is the sum of non-null rolled scores.
    check("rollup_total sums non-null", cs.rollup_total(r), 5 + 6 + 8)
    check("empty rollup total 0", cs.rollup_total(cs.roll_up([])), 0)


def test_to_score_row():
    print("to_score_row")
    result = {"components": _comps(metrics=(8, "quant"), champion=(None, None), pain=(9, "urgent")),
              "model": "claude-sonnet-4-6", "input_tokens": 1, "output_tokens": 2}
    row = cs.to_score_row("call1", "deal1", "2026-07-30", result, "summary")
    check("metrics_score column", row["metrics_score"], 8)
    check("champion_score null column", row["champion_score"], None)
    check("text_source recorded", row["text_source"], "summary")
    check("scorer_version stamped", row["scorer_version"], cs.SCORER_VERSION)
    # evidence JSON holds only non-null-scored components with evidence.
    import json as _j
    ev = _j.loads(row["evidence"])
    check("evidence only for scored comps", sorted(ev.keys()), ["metrics", "pain"])
    # deal_id None stays None (unlinked call), never the string "None".
    row2 = cs.to_score_row("call2", None, "2026-07-30", result, "transcript")
    check("null deal_id preserved", row2["deal_id"], None)


def run():
    test_parse()
    test_rollup()
    test_to_score_row()
    if FAILS:
        print(f"\nFAIL — {len(FAILS)} check(s): {', '.join(FAILS)}")
        return 1
    print("\nPASS — parse, null semantics, most-recent-non-null roll-up (regression allowed), row build.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
