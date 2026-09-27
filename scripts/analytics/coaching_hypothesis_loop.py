#!/usr/bin/env python3
"""
Autonomous coaching-hypothesis loop.

Reads the latest output of qualification_call_comparison.py, applies the
pre-specified rule, and — if it clears — drafts an experiment proposal and
writes it to the coaching_hypotheses Supabase table with status
'pending_review'. A human must approve (set status → 'approved') before
anything reaches a rep. Nothing in this script reaches a rep directly.

Hard constraints (enforced in code, not just policy):
  1. The gate function evaluate_rule() must pass before any proposal is
     drafted. The rule is fixed and not tuned post-hoc.
  2. All numbers stated in proposals and reports are the real, disclosed
     results of the actual permutation test. No confidence-adjusted or
     belief-updated language is used.
  3. Status 'pending_review' is the maximum autonomy this script reaches.
     The human checkpoint (approve/reject) is never bypassed.

Standalone and write-only to Supabase. No handler, no Slack Q&A surface.
Scheduling via GitHub Actions weekly-analytics.yml.

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=...
        python scripts/analytics/coaching_hypothesis_loop.py [--dry-run]
    python scripts/analytics/coaching_hypothesis_loop.py --input result.json [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Constants from the analysis script — kept in sync, never re-tuned.
TRAIN_P = 0.05
TRAIN_D = 0.3
HOLDOUT_D = 0.2

# Primary view is all_stalled. still_open_stalled is a secondary check.
PRIMARY_VIEW = "all_stalled"

COMPONENTS = (
    "pain", "metrics", "champion", "economic_buyer",
    "decision_criteria", "decision_process", "competition",
)

# One concrete coaching behavior per component. These are descriptions of
# *what reps should do differently*, for use in proposals. They are not
# claims about what drives outcomes — that requires the live experiment.
COACHING_CHANGES = {
    "pain":             "Explicitly name the business problem and quantify its cost before leaving the meeting-set call.",
    "metrics":          "Identify at least one measurable success metric tied to the prospect's stated pain.",
    "champion":         "Ask directly who else cares about this problem and confirm their role before the call ends.",
    "economic_buyer":   "Name the economic buyer explicitly and confirm whether they are on the call or have been briefed.",
    "decision_criteria":"Ask the prospect to describe how they will evaluate solutions before closing the meeting.",
    "decision_process": "Ask who else needs to be involved in the decision and what the typical approval process looks like.",
    "competition":      "Ask whether the prospect is evaluating other solutions and, if so, which ones.",
}


# ------------------------------------------------------------------ gate

def evaluate_rule(train: dict, holdout: dict) -> bool:
    """
    Pre-specified directional rule. Returns True iff ALL four conditions hold:
      1. train stratified permutation p < TRAIN_P (0.05)
      2. |train Cohen's d| >= TRAIN_D (0.3)
      3. |holdout Cohen's d| >= HOLDOUT_D (0.2)
      4. train d and holdout d have the same sign

    This function is the single gate everything else depends on. It is
    extracted here so it can be unit-tested in isolation with planted-bug
    controls. The rule is not tuned: TRAIN_P, TRAIN_D, HOLDOUT_D are fixed.
    """
    train_p = train.get("p")
    train_d = train.get("d")
    holdout_d = holdout.get("d")

    if train_p is None or train_d is None or holdout_d is None:
        return False
    if train_p >= TRAIN_P:
        return False
    if abs(train_d) < TRAIN_D:
        return False
    if abs(holdout_d) < HOLDOUT_D:
        return False
    if (train_d > 0) != (holdout_d > 0):
        return False
    return True


# ------------------------------------------------------------------ ranking

def rank_candidates(view: dict) -> list[dict]:
    """
    Return components that clear the rule, ranked by |train_d| * |holdout_d|
    descending. Each entry is a dict with component, train, holdout, direction,
    score (the ranking key).
    """
    candidates = []
    for comp in COMPONENTS:
        comp_data = view.get("components", {}).get(comp, {})
        train = comp_data.get("train", {})
        holdout = comp_data.get("holdout", {})
        if evaluate_rule(train, holdout):
            train_d = train["d"]
            holdout_d = holdout["d"]
            candidates.append({
                "component": comp,
                "train": train,
                "holdout": holdout,
                "direction": "higher" if train_d > 0 else "lower",
                "score": abs(train_d) * abs(holdout_d),
            })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


# ------------------------------------------------------------------ proposal

def draft_proposal(component: str, train: dict, holdout: dict,
                   direction: str, cohorts: dict, run_date: date) -> dict:
    """
    Draft a full experiment proposal for the given component. The proposal
    describes the coaching change, the observed pattern, the exact numbers,
    and the experiment design (measure crossing rate, disclose vs baseline).

    All numbers come directly from train/holdout. No interpretation beyond
    what the numbers state. No confidence-adjusted language.
    """
    hi_lo = direction  # 'higher' or 'lower'
    behavior = COACHING_CHANGES.get(component, f"Focus on {component} explicitly on meeting-set calls.")

    return {
        "component": component,
        "direction": direction,
        "run_date": run_date.isoformat(),
        "observed_pattern": (
            f"On the training set, progressed deals scored {hi_lo} on '{component}' "
            f"than stalled deals (within-strata mean diff {train.get('strat_diff', 'n/a'):.3f}, "
            f"stratified p={train['p']:.3f}, Cohen's d={train['d']:.3f}, "
            f"n_prog={train['n_prog']}, n_stall={train['n_stall']}). "
            f"The held-out third showed the same direction (d={holdout['d']:.3f})."
        ),
        "caveats": [
            "Stalled deals are mostly closed-lost; the gap may reflect lead fit, not call behavior.",
            "A higher score on a call may mark a deal already moving, not a cause of movement.",
            "This is a hypothesis to test, not a confirmed finding.",
        ],
        "coaching_change": behavior,
        "experiment_design": {
            "what_to_measure": "Weekly qualification crossing rate (Meeting Set → qualified stage) over 8 weeks.",
            "baseline": f"Current crossing rate from qualification_crossing_walk.py.",
            "disclosure": "The disclosed crossing rate each week is the actual count, not adjusted.",
            "no_significance_test": (
                "The experiment reports the raw disclosed number vs baseline each week. "
                "No significance test is run during tracking — the result is reported as-is."
            ),
            "decision_rule": "Human reviews the 8-week crossing rate vs baseline after the run. No automatic conclusion.",
        },
        "numbers": {
            "train_p": train.get("p"),
            "train_d": train.get("d"),
            "train_n_prog": train.get("n_prog"),
            "train_n_stall": train.get("n_stall"),
            "train_n_informative": train.get("n_informative"),
            "holdout_d": holdout.get("d"),
            "holdout_n_prog": holdout.get("n_prog"),
            "holdout_n_stall": holdout.get("n_stall"),
            "cohorts_progressed": cohorts.get("progressed"),
            "cohorts_stalled": cohorts.get("stalled"),
        },
    }


# ------------------------------------------------------------------ Supabase

def _supabase_client():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    from supabase import create_client
    return create_client(url, key)


def _active_components(sb) -> set[str]:
    """Components already in pending_review, approved, or tracking."""
    rows = (sb.table("coaching_hypotheses")
              .select("component")
              .in_("status", ["pending_review", "approved", "tracking"])
              .execute())
    return {r["component"] for r in (rows.data or [])}


def _write_hypothesis(sb, component: str, direction: str, train: dict,
                      holdout: dict, proposal: dict, run_date: date,
                      dry_run: bool) -> None:
    row = {
        "component": component,
        "direction": direction,
        "train_p": train.get("p"),
        "train_d": train.get("d"),
        "holdout_d": holdout.get("d"),
        "run_date": run_date.isoformat(),
        "status": "pending_review",
        "proposal": proposal,
    }
    if dry_run:
        print(f"  [dry-run] would insert: {json.dumps(row, indent=4)}")
    else:
        sb.table("coaching_hypotheses").insert(row).execute()
        print(f"  Inserted coaching_hypotheses row for {component!r} (status=pending_review).")


def _log_no_clear(sb, run_date: date, cohorts: dict, dry_run: bool) -> None:
    row = {
        "component": "none",
        "direction": "none",
        "run_date": run_date.isoformat(),
        "status": "no_clear",
        "notes": (
            f"No component met the pre-specified rule on {run_date.isoformat()}. "
            f"Cohort: {cohorts.get('progressed')} progressed, {cohorts.get('stalled')} stalled. "
            f"This is a normal and expected outcome."
        ),
    }
    if dry_run:
        print(f"  [dry-run] would log no_clear row: {json.dumps(row, indent=4)}")
    else:
        sb.table("coaching_hypotheses").insert(row).execute()
        print("  Logged no_clear row (normal outcome).")


# ------------------------------------------------------------------ main

def process_result(result: dict, run_date: date, sb, dry_run: bool = False) -> dict:
    """
    Core processing function. Given an analyse() result dict, applies the gate,
    drafts proposals for any candidates, writes to Supabase or dry-runs.

    Returns a summary dict for logging/testing.
    """
    cohorts = result.get("cohorts", {})
    view = result.get("views", {}).get(PRIMARY_VIEW, {})

    candidates = rank_candidates(view)

    if not candidates:
        print(f"  No component cleared the rule. Logging no_clear.")
        _log_no_clear(sb, run_date, cohorts, dry_run)
        return {"cleared": [], "skipped": [], "logged": "no_clear"}

    # Check for components already active in Supabase
    try:
        active = _active_components(sb)
    except Exception:
        active = set()

    cleared = []
    skipped = []
    for cand in candidates:
        comp = cand["component"]
        if comp in active:
            print(f"  Skipping {comp!r} — already active in coaching_hypotheses.")
            skipped.append(comp)
            continue
        proposal = draft_proposal(
            component=comp,
            train=cand["train"],
            holdout=cand["holdout"],
            direction=cand["direction"],
            cohorts=cohorts,
            run_date=run_date,
        )
        _write_hypothesis(
            sb=sb, component=comp, direction=cand["direction"],
            train=cand["train"], holdout=cand["holdout"],
            proposal=proposal, run_date=run_date, dry_run=dry_run,
        )
        cleared.append(comp)

    return {"cleared": cleared, "skipped": skipped, "logged": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="Path to analyse() result JSON (offline mode)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written; do not touch Supabase")
    args = parser.parse_args()

    run_date = date.today()

    if args.input:
        result = json.loads(Path(args.input).read_text())
    else:
        # Live mode: run qualification_call_comparison.py against Supabase
        from qualification_call_comparison import _fetch, load_input, analyse
        data = load_input(_fetch())
        result = analyse(data)

    if args.dry_run:
        class _FakeSB:
            def table(self, *a, **kw): return self
            def select(self, *a, **kw): return self
            def in_(self, *a, **kw): return self
            def insert(self, *a, **kw): return self
            def execute(self): return type("R", (), {"data": []})()
        sb = _FakeSB()
    else:
        sb = _supabase_client()

    cohorts = result.get("cohorts", {})
    view = result.get("views", {}).get(PRIMARY_VIEW, {})
    print(f"Coaching hypothesis loop — {run_date}")
    print(f"  Cohort: {cohorts.get('progressed')} progressed, {cohorts.get('stalled')} stalled")
    print(f"  View '{PRIMARY_VIEW}' directional components: {view.get('directional', [])}")

    summary = process_result(result, run_date, sb, dry_run=args.dry_run)
    print(f"  Result: cleared={summary['cleared']}, skipped={summary['skipped']}, "
          f"logged={summary['logged']}")


if __name__ == "__main__":
    main()
