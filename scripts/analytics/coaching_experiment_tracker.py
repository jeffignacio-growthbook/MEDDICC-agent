#!/usr/bin/env python3
"""
Coaching experiment tracker.

For each hypothesis in status='approved', records the current week's
qualification crossing rate (Meeting Set → qualified stage) and updates
the experiment field in coaching_hypotheses. After 8 weeks it marks the
hypothesis 'completed' and prints a final report.

The reported crossing rate is the actual disclosed count for the week
— no adjustment, no significance test, no interpretation. The output
states numbers only; a human decides what they mean.

Hard constraints (same as coaching_hypothesis_loop.py):
  1. Nothing reaches a rep. This script only updates Supabase.
  2. All numbers are the real, disclosed results of the actual count.
  3. No significance test is run during tracking.
  4. No confidence-adjusted or belief-updated language is emitted.

Standalone and write-only to Supabase. Scheduling via weekly-analytics.yml.

Usage:
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=...
        python scripts/analytics/coaching_experiment_tracker.py [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

EXPERIMENT_WEEKS = 8


def _supabase_client():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    from supabase import create_client
    return create_client(url, key)


def _fetch_crossing_rate(sb, week_start: date, week_end: date) -> dict:
    """
    Count deals that crossed from Meeting Set into a qualified stage during
    [week_start, week_end]. Returns {total_crossing, window_start, window_end}.

    Reads from deals_snapshot via consecutive snapshot pairs. This is the same
    cohort definition as qualification_crossing_walk.py: pipeline 'default',
    MEETING_SET='79653122', QUALIFIED_STAGES as defined there.
    """
    from qualification_crossing_walk import MEETING_SET, PIPELINE, QUALIFIED_STAGES
    qualified_set = set(QUALIFIED_STAGES)

    # Fetch snapshots in the window plus the one just before (to detect crossings)
    look_back = week_start - timedelta(days=8)
    resp = sb.table("deals_snapshot").select(
        "deal_id,snapshot_date,stage_id,pipeline_id"
    ).gte("snapshot_date", look_back.isoformat()).lte(
        "snapshot_date", week_end.isoformat()
    ).eq("pipeline_id", PIPELINE).execute()

    rows = resp.data or []
    by_deal: dict[str, list[dict]] = {}
    for r in rows:
        by_deal.setdefault(str(r["deal_id"]), []).append(r)

    crossings = 0
    for deal_id, snaps in by_deal.items():
        snaps.sort(key=lambda s: str(s["snapshot_date"]))
        stages = [str(s.get("stage_id") or "") for s in snaps]
        dates = [str(s["snapshot_date"])[:10] for s in snaps]
        for i in range(1, len(snaps)):
            if (stages[i - 1] == MEETING_SET and stages[i] in qualified_set
                    and dates[i] >= week_start.isoformat()):
                crossings += 1
                break

    return {
        "total_crossing": crossings,
        "window_start": week_start.isoformat(),
        "window_end": week_end.isoformat(),
    }


def track_approved(sb, dry_run: bool = False) -> list[dict]:
    """
    Process all hypotheses in status='approved'.
    For each, fetch this week's crossing rate, append to experiment.weeks,
    and update Supabase. After EXPERIMENT_WEEKS weeks, mark 'completed'.

    Returns a list of summary dicts for logging.
    """
    resp = sb.table("coaching_hypotheses").select("*").eq("status", "approved").execute()
    hypotheses = resp.data or []

    if not hypotheses:
        print("  No hypotheses in status='approved'. Nothing to track.")
        return []

    today = date.today()
    week_end = today
    week_start = today - timedelta(days=6)

    summaries = []
    for hyp in hypotheses:
        hyp_id = hyp["id"]
        component = hyp["component"]
        experiment = hyp.get("experiment") or {"weeks": [], "baseline": None}
        if isinstance(experiment, str):
            experiment = json.loads(experiment)

        # Fetch this week's crossing rate
        try:
            crossing = _fetch_crossing_rate(sb, week_start, week_end)
        except Exception as e:
            print(f"  ERROR fetching crossing rate for hypothesis {hyp_id}: {e}")
            summaries.append({"id": hyp_id, "component": component, "error": str(e)})
            continue

        # Store baseline on first week
        if not experiment.get("baseline"):
            experiment["baseline"] = crossing["total_crossing"]
            print(f"  Hypothesis {hyp_id} ({component}): baseline set to {crossing['total_crossing']} crossings.")

        week_record = {
            "week": len(experiment["weeks"]) + 1,
            "window_start": crossing["window_start"],
            "window_end": crossing["window_end"],
            "crossing_count": crossing["total_crossing"],
            "vs_baseline": crossing["total_crossing"] - experiment["baseline"],
        }
        experiment["weeks"].append(week_record)

        n_weeks = len(experiment["weeks"])
        new_status = "completed" if n_weeks >= EXPERIMENT_WEEKS else "approved"

        print(f"  Hypothesis {hyp_id} ({component}): week {n_weeks}/{EXPERIMENT_WEEKS}, "
              f"crossings={crossing['total_crossing']} "
              f"(vs baseline {experiment['baseline']}: {week_record['vs_baseline']:+d}). "
              f"Status → {new_status}.")

        if new_status == "completed":
            _print_final_report(hyp, experiment)

        if dry_run:
            print(f"  [dry-run] would update hypothesis {hyp_id}: status={new_status}")
        else:
            sb.table("coaching_hypotheses").update({
                "status": new_status,
                "experiment": experiment,
                "updated_at": "now()",
            }).eq("id", hyp_id).execute()

        summaries.append({
            "id": hyp_id, "component": component, "week": n_weeks,
            "crossing_count": crossing["total_crossing"],
            "vs_baseline": week_record["vs_baseline"],
            "new_status": new_status,
        })

    return summaries


def _print_final_report(hyp: dict, experiment: dict) -> None:
    """
    Print an 8-week report. All numbers are the actual disclosed crossing
    counts. No interpretation, no significance test, no recommendation.
    """
    comp = hyp["component"]
    baseline = experiment.get("baseline", "n/a")
    weeks = experiment.get("weeks", [])
    print(f"\n  === Final experiment report: {comp} ===")
    print(f"  Baseline crossing count (week 1): {baseline}")
    print(f"  {'Week':<6} {'Window':<24} {'Crossings':<12} {'vs baseline':<12}")
    for w in weeks:
        sign = "+" if w["vs_baseline"] >= 0 else ""
        print(f"  {w['week']:<6} {w['window_start']} to {w['window_end']:<10} "
              f"{w['crossing_count']:<12} {sign}{w['vs_baseline']}")
    print(f"  The above are the actual crossing counts for each week.")
    print(f"  No significance test was run. A human reviews these numbers.")
    print(f"  === End report ===\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written; do not touch Supabase")
    args = parser.parse_args()

    if args.dry_run:
        class _FakeSB:
            def table(self, *a, **kw): return self
            def select(self, *a, **kw): return self
            def eq(self, *a, **kw): return self
            def gte(self, *a, **kw): return self
            def lte(self, *a, **kw): return self
            def update(self, *a, **kw): return self
            def execute(self): return type("R", (), {"data": []})()
        sb = _FakeSB()
    else:
        sb = _supabase_client()

    print(f"Coaching experiment tracker — {date.today()}")
    summaries = track_approved(sb, dry_run=args.dry_run)
    print(f"  Processed {len(summaries)} hypothesis/hypotheses.")


if __name__ == "__main__":
    main()
