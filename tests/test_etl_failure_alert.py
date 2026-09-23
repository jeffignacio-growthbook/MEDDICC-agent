"""
Regression test: a failing ETL workflow actually alerts someone.

Why this exists (2026-09-23): #36 made the deals ETL exit non-zero on
failure, but a red run only helps if it notifies someone. The existing alert
(scripts/alert_etl_failure.py, used by the Daily Deal and Daily Calls ETLs)
could never fire:
  - its failure counter reads/writes Supabase etl_failures, but neither
    workflow's alert step passed SUPABASE_URL / SUPABASE_SERVICE_KEY;
  - on that error record_failure() returned 1 ("first failure"), below the
    default threshold of 2, so no alert was ever sent. etl_failures had 0
    rows, ever.
The Daily Analytics ETL — since #37 the only writer of Supabase deals, every
4 hours — had no alert step at all.

Pins:
  1. An unknown failure count alerts (fail open); a counted first failure
     does not; a second does. Planted control: the old `return 1`.
  2. All three ETL workflows have an `if: failure()` alert step with the
     Zapier URL and the Supabase credentials its counter needs, running
     after the ETL step with nothing (continue-on-error, `|| true`) that
     would keep a failing ETL from reaching it. Planted control: the
     pre-fix Daily Deal ETL alert step (no Supabase env) is rejected.
"""
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "api"))

import alert_etl_failure as A  # noqa: E402

ETL_WORKFLOWS = {
    "daily-deal-etl.yml": "etl_deals.py",
    "daily-calls-etl.yml": "etl_calls.py",
    "daily-analytics-etl.yml": "etl_deals.py --mode analytics",
    "hourly-deal-sync.yml": "etl_deals.py --mode incremental",
}
REQUIRED_ALERT_ENV = {"ZAPIER_ALERT_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"}


def _run_main(record_result, threshold=None):
    sent = []
    saved = (A.record_failure, A.send_zapier_alert, sys.argv)
    A.record_failure = lambda job, run_id: record_result
    A.send_zapier_alert = lambda job, run_id, n: sent.append((job, n)) or True
    sys.argv = ["alert_etl_failure.py", "--job", "etl-x", "--run-id", "42"] + (
        ["--threshold", str(threshold)] if threshold else [])
    try:
        code = A.main()
    finally:
        A.record_failure, A.send_zapier_alert, sys.argv = saved
    return code, sent


def test_unknown_count_alerts_counted_first_does_not_second_does():
    assert _run_main(None) == (0, [("etl-x", 0)])
    assert _run_main(1) == (0, [])
    assert _run_main(2) == (0, [("etl-x", 2)])
    print("✓ count unknown → alert; 1st counted failure → no alert; 2nd → alert; always exit 0")


def test_record_failure_returns_none_when_supabase_unreachable():
    import os
    saved = os.environ.pop("SUPABASE_URL", None)
    try:
        assert A.record_failure("etl-x", "42") is None
    finally:
        if saved is not None:
            os.environ["SUPABASE_URL"] = saved
    print("✓ record_failure() with no Supabase config returns None (not the old silent 1)")


def test_alert_logic_check_catches_the_old_fallback():
    """Planted bug: the pre-fix `return 1` when the count can't be recorded."""
    code, sent = _run_main(1)  # what the old fallback returned on any DB error
    assert sent == [], "the old fallback value must stay below threshold (proves the gap)"
    print("✓ planted old fallback (return 1) sends nothing — the gap the fix closes")


def _alert_step_problems(workflow_text, etl_command):
    """Reasons a workflow would let a failing ETL go un-alerted ([] if none)."""
    wf = yaml.safe_load(workflow_text)
    problems = []
    for job_id, job in wf["jobs"].items():
        steps = job.get("steps", [])
        etl = [i for i, s in enumerate(steps) if etl_command in (s.get("run") or "")]
        alert = [i for i, s in enumerate(steps) if "alert_etl_failure.py" in (s.get("run") or "")]
        if not etl:
            continue
        if not alert:
            problems.append(f"{job_id}: no alert_etl_failure.py step")
            continue
        a = steps[alert[0]]
        if a.get("if") != "failure()":
            problems.append(f"{job_id}: alert step if={a.get('if')!r}, not failure()")
        if alert[0] < etl[0]:
            problems.append(f"{job_id}: alert step runs before the ETL step")
        missing = REQUIRED_ALERT_ENV - set(a.get("env") or {})
        if missing:
            problems.append(f"{job_id}: alert step env missing {sorted(missing)}")
        e = steps[etl[0]]
        if e.get("continue-on-error"):
            problems.append(f"{job_id}: ETL step has continue-on-error")
        if "|| true" in (e.get("run") or ""):
            problems.append(f"{job_id}: ETL step swallows its exit code (|| true)")
    return problems


def test_every_etl_workflow_alerts_on_failure():
    for name, cmd in ETL_WORKFLOWS.items():
        text = (REPO / ".github" / "workflows" / name).read_text()
        assert cmd in text, f"{name} no longer runs {cmd!r}; update this test"
        problems = _alert_step_problems(text, cmd)
        assert not problems, f"{name}: {problems}"
    print(f"✓ all {len(ETL_WORKFLOWS)} ETL workflows: if: failure() alert step after the ETL, "
          f"with {sorted(REQUIRED_ALERT_ENV)}, and nothing swallowing the ETL's exit code")


def test_workflow_check_catches_the_pre_fix_alert_steps():
    """Planted bugs: the pre-fix deal-ETL alert env, a missing alert step,
    and an ETL step that swallows its exit code."""
    text = (REPO / ".github" / "workflows" / "daily-deal-etl.yml").read_text()
    wf = yaml.safe_load(text)
    steps = wf["jobs"]["etl-deals"]["steps"]
    alert = next(s for s in steps if "alert_etl_failure.py" in (s.get("run") or ""))
    etl = next(s for s in steps if "etl_deals.py" in (s.get("run") or ""))

    saved_env = dict(alert["env"])
    alert["env"] = {"ZAPIER_ALERT_URL": saved_env["ZAPIER_ALERT_URL"]}  # pre-fix
    assert any("missing" in p for p in _alert_step_problems(yaml.safe_dump(wf), "etl_deals.py"))
    alert["env"] = saved_env

    steps.remove(alert)
    assert any("no alert" in p for p in _alert_step_problems(yaml.safe_dump(wf), "etl_deals.py"))
    steps.append(alert)

    etl["run"] = etl["run"].rstrip() + " || true"
    assert any("|| true" in p for p in _alert_step_problems(yaml.safe_dump(wf), "etl_deals.py"))
    print("✓ planted pre-fix alert env, missing alert step, and `|| true` are each rejected")


if __name__ == "__main__":
    test_unknown_count_alerts_counted_first_does_not_second_does()
    test_record_failure_returns_none_when_supabase_unreachable()
    test_alert_logic_check_catches_the_old_fallback()
    test_every_etl_workflow_alerts_on_failure()
    test_workflow_check_catches_the_pre_fix_alert_steps()
    print("\n✅ All tests passed")
