#!/usr/bin/env python3
"""
Eval: daily incremental scoring plan (PROGRESSIVE_SCORING_SPEC Phase 5b).

Pure/offline. Drives score_new_calls.plan_deal() — the decision that governs
cost AND correctness of nightly scoring — and locks:

  - all-new deal (no prior scores) → full fold of every call;
  - fully-scored deal → skip (no model calls);
  - prior + new-after-prior → incremental: score ONLY the new calls, seeded with
    the reconstructed prior rolled state (old calls not re-scored);
  - a back-dated new call (arrives BEFORE an already-scored call) → full refold,
    because the cumulative fold order changed;
  - prior scored but its stored rows are missing (can't rebuild state) → full
    refold, never a wrong incremental.

If this logic were wrong we'd either silently re-score the whole book nightly
(cost) or thread a stale/zero prior state into a new call's cumulative score
(wrong numbers). Neither is observable without this lock.
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def _stub_if_missing(name, **attrs):
    try:
        __import__(name)
    except Exception:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m


_stub_if_missing("anthropic", Anthropic=type("Anthropic", (), {}),
                 APIError=type("APIError", (Exception,), {}))
_stub_if_missing("supabase", create_client=lambda *a, **k: None,
                 Client=type("Client", (), {}))

import score_new_calls as snc  # noqa: E402
import call_scorer as cs  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        FAILS.append(name)


def _call(cid, date):
    return ({"call_id": cid, "call_date": date}, f"text for {cid}", "summary")


def _stored(cid, date, **scores):
    row = {"call_id": cid, "call_date": date, "deal_id": "d1",
           "evidence": None, "scorer_version": cs.SCORER_VERSION}
    for col in ("metrics_score", "economic_buyer_score", "decision_criteria_score",
                "decision_process_score", "pain_score", "champion_score",
                "competition_score"):
        row[col] = None
    for k, v in scores.items():
        row[k + "_score"] = v
    return row


def run():
    print("=" * 72)
    print("DAILY INCREMENTAL SCORING — plan_deal() (offline)")
    print("=" * 72)

    c1 = _call("c1", "2026-08-01")
    c2 = _call("c2", "2026-08-10")
    c3 = _call("c3", "2026-08-20")
    scoreable = [c1, c2, c3]

    # A. nothing scored yet → full fold of all three
    mode, prior, to_score = snc.plan_deal(scoreable, set(), {})
    check("all-new → full", mode == "full")
    check("all-new scores every call", len(to_score) == 3)

    # B. everything already scored → skip
    mode, prior, to_score = snc.plan_deal(scoreable, {"c1", "c2", "c3"}, {})
    check("fully-scored → skip", mode == "skip")
    check("skip scores nothing", to_score == [])

    # C. c1,c2 scored; c3 is new and AFTER → incremental, only c3
    stored = {"c1": _stored("c1", "2026-08-01", metrics=7),
              "c2": _stored("c2", "2026-08-10", pain=8)}
    mode, prior, to_score = snc.plan_deal(scoreable, {"c1", "c2"}, stored)
    check("prior + new-after → incremental", mode == "incremental")
    check("incremental scores only the new call", [c[0]["call_id"] for c in to_score] == ["c3"])
    check("incremental seeds prior fold rows", len(prior) == 2)
    rolled = cs.roll_up(prior)
    check("reconstructed prior state carries metrics=7", rolled["metrics"]["score"] == 7)
    check("reconstructed prior state carries pain=8", rolled["pain"]["score"] == 8)

    # D. c1,c3 scored; c2 is new and lands BETWEEN them → out of order → full
    stored_ac = {"c1": _stored("c1", "2026-08-01", metrics=7),
                 "c3": _stored("c3", "2026-08-20", champion=5)}
    mode, prior, to_score = snc.plan_deal(scoreable, {"c1", "c3"}, stored_ac)
    check("back-dated new call → full refold", mode == "full")
    check("full refold re-scores every call", len(to_score) == 3)

    # E. prior scored but stored rows missing → can't rebuild → full
    mode, prior, to_score = snc.plan_deal(scoreable, {"c1", "c2"}, {})  # no stored rows
    check("prior rows missing → full refold", mode == "full")

    if FAILS:
        print(f"\nFAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("\nPASS — incremental/full/skip decision + prior-state reconstruction locked.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
