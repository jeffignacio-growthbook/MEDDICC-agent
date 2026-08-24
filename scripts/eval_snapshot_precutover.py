#!/usr/bin/env python3
"""
Eval: pre-cutover snapshot summarize() (PROGRESSIVE_SCORING_SPEC Phase 5b).

Pure/offline. Drives snapshot_precutover.summarize() on synthetic deals +
analyses built against the REAL config ladder, and locks the invariants the
Phase 5c before/after diff depends on:

  - every deal lands in exactly one bucket (classified + unscored + off_ladder
    == active deals) — a miscount would silently corrupt the direction check;
  - a strong-scored deal on the earliest rung reads score_ahead_of_stage, a
    weak-scored deal on the latest rung reads stage_ahead_of_score (same
    classifier the hygiene report is gate-tested on, wired through summarize);
  - a deal with no passed analysis is unscored, not classified;
  - pipeline_by_stage sums value + count and tolerates null deal_value;
  - the markdown summary renders without error.
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api", "scripts/analytics"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def _stub_if_missing(name, **attrs):
    try:
        __import__(name)
    except Exception:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m


_stub_if_missing("pytz", timezone=lambda *a, **k: None, utc=None)
_stub_if_missing("anthropic", Anthropic=type("Anthropic", (), {}),
                 APIError=type("APIError", (Exception,), {}))
_stub_if_missing("supabase", create_client=lambda *a, **k: None,
                 Client=type("Client", (), {}))

import snapshot_precutover as snap  # noqa: E402
from analytics.stage_score_hygiene import _ladder, _SCORE_COLS  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        FAILS.append(name)


def _analysis(deal_id, val, passed=True, analyzed_at="2026-08-20T00:00:00Z"):
    row = {"deal_id": deal_id, "passed": passed, "analyzed_at": analyzed_at,
           "overall_score": val * 7}
    for col in _SCORE_COLS:
        row[col] = val
    return row


def run():
    print("=" * 72)
    print("PRE-CUTOVER SNAPSHOT — summarize() (offline, real config ladder)")
    print("=" * 72)

    ladder = _ladder()
    lo_order, lo_id, _lo_name = ladder[0]
    hi_order, hi_id, _hi_name = ladder[-1]

    deals = [
        # strong scores on the earliest rung → score_ahead_of_stage
        {"deal_id": "d_strong_early", "company_name": "StrongEarly",
         "stage": lo_id, "deal_value": 100000.0},
        # weak scores on the latest rung → stage_ahead_of_score
        {"deal_id": "d_weak_late", "company_name": "WeakLate",
         "stage": hi_id, "deal_value": 50000.0},
        # on-ladder but no passed analysis → unscored
        {"deal_id": "d_unscored", "company_name": "Unscored",
         "stage": lo_id, "deal_value": None},
        # off-ladder stage → off_ladder, still counted in pipeline_by_stage
        {"deal_id": "d_offladder", "company_name": "OffLadder",
         "stage": "not_a_real_stage_id", "deal_value": 25000.0},
    ]
    analyses = [
        _analysis("d_strong_early", 9),
        _analysis("d_weak_late", 2),
        # only a NON-passed analysis for d_unscored → must be treated as unscored
        _analysis("d_unscored", 8, passed=False),
    ]

    s = snap.summarize(deals, analyses, ladder=ladder)
    c = s["counts"]

    print(f"counts: {c}")
    classified = sum(c[k] for k in snap.READINGS)
    check("every active deal in exactly one bucket",
          classified + c["unscored"] + c["off_ladder"] == len(deals))
    check("strong@earliest → score_ahead_of_stage", c["score_ahead_of_stage"] >= 1)
    check("weak@latest → stage_ahead_of_score", c["stage_ahead_of_score"] >= 1)
    check("non-passed analysis → unscored (not classified)", c["unscored"] == 1)
    check("off-ladder stage → off_ladder", c["off_ladder"] == 1)

    by_stage = s["pipeline_by_stage"]
    total_deals_counted = sum(v["count"] for v in by_stage.values())
    check("pipeline_by_stage counts every active deal",
          total_deals_counted == len(deals))
    total_val = sum(v["value"] for v in by_stage.values())
    check("pipeline value sums non-null deal_value (null tolerated)",
          total_val == 100000.0 + 50000.0 + 25000.0)

    rows = s["deals"]
    check("classified rows carry deal_id + reading + scores",
          all(r.get("deal_id") and r.get("reading") and "scores" in r
              for r in rows))
    check("rows exclude unscored/off-ladder deals", len(rows) == classified)

    # markdown render must not raise
    md = snap._render_summary_md(s, "2026-08-24T00:00:00Z")
    check("markdown summary renders", "Pre-cutover snapshot" in md
          and "score_ahead_of_stage" in md)

    if FAILS:
        print(f"\nFAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("\nPASS — snapshot summarize() buckets, pipeline agg, and render locked.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
