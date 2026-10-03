#!/usr/bin/env python3
"""
One-off audit: compare the OLD actual_incremental_closed_won() filter
(pipeline_id-based renewal exclusion + is_won(current stage) outcome)
against the proposed NEW filter (is_incremental_pipeline() dollar-based
exclusion + deal_status=="won" outcome — matching query_path_to_target's
inline computation and assess_loss_concentration.won_incremental_arr) —
over REAL data, for:
  1. The current fiscal quarter (the new current-quarter QTD use this
     filter change is being made for).
  2. Every prior-year window query_coverage_proxy_target_by_week()
     actually uses (the existing use of this function, computing the
     proxy-target curve's historical base).

Also reports query_rep_attainment's own won-ARR total for the current
quarter as a fourth, independently-computed reference point (it has yet
a different renewal-exclusion rule: deal_status=="won" + pipeline_id-based
exclusion — a hybrid of the OLD and NEW definitions below).

Report only. No primitive is changed here. Safe to delete once this
one-time comparison is read.
"""
import sys
from pathlib import Path
from datetime import date

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "analytics"))
sys.path.insert(0, str(REPO_ROOT / "api"))
sys.path.insert(0, str(REPO_ROOT))


def _old_definition(sb, q_start_iso, q_end_iso):
    """pipeline_id-based renewal exclusion + is_won(current stage)."""
    from field_semantics import _RENEWAL_PIPELINE_ID, is_won
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr
    deals = select_all(sb, 'deals',
        columns='deal_id,stage,close_date,pipeline_id,new_arr,expansion_arr,deal_status')
    total, n = 0.0, 0
    for d in deals:
        stage, close_date, pipeline_id = d.get('stage'), d.get('close_date'), d.get('pipeline_id')
        if not stage or not close_date:
            continue
        if str(pipeline_id) == _RENEWAL_PIPELINE_ID:
            continue
        try:
            if not is_won(str(stage)):
                continue
        except Exception:
            continue
        if not (q_start_iso <= str(close_date)[:10] <= q_end_iso):
            continue
        total += incremental_arr(d)
        n += 1
    return total, n


def _new_definition(sb, q_start_iso, q_end_iso):
    """is_incremental_pipeline() dollar-based exclusion + deal_status=='won'."""
    from field_semantics import is_incremental_pipeline
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr
    deals = select_all(sb, 'deals',
        columns='deal_id,close_date,pipeline_id,new_arr,expansion_arr,deal_status',
        filters=[('eq', 'deal_status', 'won'),
                 ('gte', 'close_date', q_start_iso),
                 ('lte', 'close_date', q_end_iso)])
    total, n = 0.0, 0
    for d in deals:
        if is_incremental_pipeline(d):
            total += incremental_arr(d)
            n += 1
    return total, n


def _rep_attainment_definition(sb, q_start_iso, q_end_iso):
    """query_rep_attainment's own rule: deal_status=='won' + pipeline_id-
    based exclusion (a hybrid of old and new, reported for reference)."""
    from field_semantics import _RENEWAL_PIPELINE_ID
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr
    deals = select_all(sb, 'deals',
        columns='owner_email,new_arr,expansion_arr,pipeline_id,deal_status,close_date',
        filters=[('eq', 'deal_status', 'won'),
                 ('gte', 'close_date', q_start_iso),
                 ('lte', 'close_date', q_end_iso)])
    total, n = 0.0, 0
    for d in deals:
        if str(d.get('pipeline_id') or '') == _RENEWAL_PIPELINE_ID:
            continue
        total += incremental_arr(d)
        n += 1
    return total, n


def _reopened_deal_diagnostic(sb, q_start_iso, q_end_iso):
    """Deals where the outcome source (deal_status) and the materialized
    `stage` column disagree on whether the deal is won, within the given
    close_date window. Two directions, independently real:
      (a) stage says won, deal_status says not won — e.g. reopened after
          being marked Closed Won, stage not yet re-synced (or lagging).
      (b) deal_status says won, stage says not won (a stage-lag/correction
          scenario in the other direction).
    Needed to size how much the 2026-10-03 filter generalization (reading
    deal_status instead of stage) actually moves real numbers, beyond the
    synthetic fixture in tests/test_coverage_qtd_reconciliation.py.
    Report only — no write, no primitive touched."""
    from field_semantics import is_won
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr
    deals = select_all(sb, 'deals',
        columns='deal_id,stage,deal_status,close_date,new_arr,expansion_arr',
        filters=[('gte', 'close_date', q_start_iso),
                 ('lte', 'close_date', q_end_iso)])
    stage_won_status_not = []
    status_won_stage_not = []
    for d in deals:
        stage = d.get('stage')
        status = (d.get('deal_status') or '').lower()
        try:
            stage_says_won = bool(stage) and is_won(str(stage))
        except Exception:
            stage_says_won = False
        status_says_won = status == 'won'
        if stage_says_won and not status_says_won:
            stage_won_status_not.append(d)
        elif status_says_won and not stage_says_won:
            status_won_stage_not.append(d)
    return stage_won_status_not, status_won_stage_not


def _owner_email_audit(sb, q_start_iso, q_end_iso):
    """Current-quarter won deals (deal_status=='won', renewal pipeline
    excluded via is_incremental_pipeline — the NEW/current definition)
    with a missing or unmapped owner_email.

    'Unmapped' = owner_email is set but does not appear in either
    config/targets.yaml (quota reps + non_quota_roles) or the
    user_personas table — i.e. query_rep_attainment's roster would never
    attribute this deal's ARR to a named rep, so it is silently absent
    from team_summary.closed_won_qtd's per-rep breakdown even though it
    may still land in a team-level sum depending on which definition is
    used upstream."""
    import yaml
    from field_semantics import is_incremental_pipeline
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr

    targets_path = REPO_ROOT / "config" / "targets.yaml"
    known_emails = set()
    try:
        tcfg = yaml.safe_load(open(targets_path))
        for qdata in (tcfg or {}).get("targets", {}).values():
            known_emails.update((qdata.get("reps") or {}).keys())
            known_emails.update(qdata.get("non_quota_roles") or [])
    except Exception as e:
        print(f"  (could not load config/targets.yaml roster: {e})")

    try:
        persona_rows = select_all(sb, "user_personas", columns="email")
        known_emails.update(p.get("email") for p in persona_rows if p.get("email"))
    except Exception as e:
        print(f"  (could not load user_personas roster: {e})")

    deals = select_all(sb, "deals",
        columns="deal_id,owner_email,new_arr,expansion_arr,pipeline_id,deal_status,close_date",
        filters=[("eq", "deal_status", "won"),
                 ("gte", "close_date", q_start_iso),
                 ("lte", "close_date", q_end_iso)])

    missing, unmapped = [], []
    for d in deals:
        if not is_incremental_pipeline(d):
            continue
        email = d.get("owner_email")
        if not email:
            missing.append(d)
        elif email not in known_emails:
            unmapped.append(d)

    missing_total = sum(incremental_arr(d) for d in missing)
    unmapped_total = sum(incremental_arr(d) for d in unmapped)
    print(f"Missing owner_email: {len(missing)} deals, ${missing_total:,.0f} — "
          f"{[d['deal_id'] for d in missing] if missing else '(none)'}")
    print(f"Unmapped owner_email (set but not in config/targets.yaml or "
          f"user_personas): {len(unmapped)} deals, ${unmapped_total:,.0f} — "
          f"{[(d['deal_id'], d.get('owner_email')) for d in unmapped] if unmapped else '(none)'}")
    return missing, unmapped


def _rep_targets_report(sb, period):
    """All rep_targets rows for `period`, regardless of level/role/metric
    (query_rep_attainment itself only ever reads level='rep', role='ae') —
    broken out here so any other level/role/metric combination actually
    stored is visible, and so the rep-level sum can be checked against the
    team-level row and against the known $1.55M team quota."""
    from supabase_client import select_all

    rows = select_all(sb, "rep_targets",
        columns="period,level,role,entity_name,entity_email,metric,target_value",
        filters=[("eq", "period", period)])

    print(f"rep_targets rows for period={period!r}: {len(rows)} total")
    by_key = {}
    for r in rows:
        key = (r.get("level"), r.get("role"), r.get("metric"))
        by_key.setdefault(key, []).append(r)

    for key in sorted(by_key, key=lambda k: (str(k[0]), str(k[1]), str(k[2]))):
        level, role, metric = key
        group = by_key[key]
        subtotal = sum((r.get("target_value") or 0) for r in group)
        print(f"  level={level!r} role={role!r} metric={metric!r}: "
              f"{len(group)} rows, sum=${subtotal:,.0f}")
        for r in group:
            print(f"    {r.get('entity_name')!r} ({r.get('entity_email')}): "
                  f"${(r.get('target_value') or 0):,.0f}")

    rep_ae_rows = by_key.get(("rep", "ae", "incremental_arr"), [])
    rep_sum = sum((r.get("target_value") or 0) for r in rep_ae_rows)
    team_rows = [r for r in rows if r.get("level") == "team"]
    team_value = sum((r.get("target_value") or 0) for r in team_rows)

    print(f"  Sum of level='rep' role='ae' metric='incremental_arr' targets: ${rep_sum:,.0f}")
    print(f"  Sum of level='team' row(s): ${team_value:,.0f}")
    print(f"  Known committed team quota (config/targets.yaml team_total): $1,550,000")
    gap_vs_known = rep_sum - 1_550_000
    gap_vs_team_row = rep_sum - team_value if team_rows else None
    if gap_vs_known != 0:
        print(f"  MISMATCH: rep-level sum differs from $1.55M team quota by ${gap_vs_known:,.0f}")
    else:
        print("  OK: rep-level sum matches the $1.55M team quota exactly.")
    if team_rows and gap_vs_team_row != 0:
        print(f"  MISMATCH: rep-level sum differs from stored level='team' row by ${gap_vs_team_row:,.0f}")
    return rows


def _explain_rep_attainment_vs_new_diff(sb, q_start_iso, q_end_iso):
    """Per-deal explanation of DIFF (rep_attainment - new): walks every
    won deal in the window and flags it wherever
    is_incremental_pipeline(d) (the NEW/actual_incremental_closed_won
    test) disagrees with "pipeline_id != renewal_id" (query_rep_
    attainment's own test), i.e. exactly the deals each definition
    includes that the other excludes."""
    from field_semantics import is_incremental_pipeline, _RENEWAL_PIPELINE_ID
    from supabase_client import select_all
    from api.incremental_arr import incremental_arr

    deals = select_all(sb, "deals",
        columns="deal_id,owner_email,new_arr,expansion_arr,pipeline_id,deal_status,close_date",
        filters=[("eq", "deal_status", "won"),
                 ("gte", "close_date", q_start_iso),
                 ("lte", "close_date", q_end_iso)])

    new_only, ra_only = [], []
    for d in deals:
        in_new = is_incremental_pipeline(d)
        in_ra = str(d.get("pipeline_id") or "") != _RENEWAL_PIPELINE_ID
        if in_new and not in_ra:
            new_only.append(d)   # NEW includes it (real $ arr), rep_attainment excludes (renewal pipeline_id)
        elif in_ra and not in_new:
            ra_only.append(d)    # rep_attainment includes it (not renewal pipeline_id), NEW excludes (zero $ arr)

    new_only_total = sum(incremental_arr(d) for d in new_only)
    ra_only_total = sum(incremental_arr(d) for d in ra_only)
    print(f"Deals NEW includes that rep_attainment excludes (renewal pipeline_id, "
          f"real expansion/new ARR): {len(new_only)} deals, ${new_only_total:,.0f} — "
          f"{[d['deal_id'] for d in new_only] if new_only else '(none)'}")
    print(f"Deals rep_attainment includes that NEW excludes (non-renewal pipeline_id, "
          f"but zero new_arr/expansion_arr): {len(ra_only)} deals, ${ra_only_total:,.0f} — "
          f"{[d['deal_id'] for d in ra_only] if ra_only else '(none)'}")
    print(f"Net (new_only_total - ra_only_total) should equal DIFF(new - rep_attainment) above: "
          f"${new_only_total - ra_only_total:,.0f}")
    return new_only, ra_only


def _print_reopened_deal_diagnostic(label, q_start_iso, q_end_iso, a, b):
    from api.incremental_arr import incremental_arr
    a_total = sum(incremental_arr(d) for d in a)
    b_total = sum(incremental_arr(d) for d in b)
    print(f"{label} [{q_start_iso}..{q_end_iso}] reopened/stage-lag diagnostic:")
    print(f"  (a) stage=won, deal_status!=won: {len(a)} deals, ${a_total:,.0f} — "
          f"{[d['deal_id'] for d in a] if a else '(none)'}")
    print(f"  (b) deal_status=won, stage!=won: {len(b)} deals, ${b_total:,.0f} — "
          f"{[d['deal_id'] for d in b] if b else '(none)'}")


def main():
    from db import get_supabase
    from utils import get_fiscal_quarter
    from forecast_analyses import _get_complete_quarters, _quarter_window_iso, _prior_year_window

    sb = get_supabase()

    print("=" * 70)
    print("CURRENT QUARTER (the new use this filter change is being made for)")
    print("=" * 70)
    q_start, q_end, label = get_fiscal_quarter(date.today())
    q_start_iso, q_end_iso = q_start.isoformat(), q_end.isoformat()
    old_total, old_n = _old_definition(sb, q_start_iso, q_end_iso)
    new_total, new_n = _new_definition(sb, q_start_iso, q_end_iso)
    ra_total, ra_n = _rep_attainment_definition(sb, q_start_iso, q_end_iso)
    print(f"{label} [{q_start_iso}..{q_end_iso}]")
    print(f"  OLD (pipeline_id excl + is_won(stage)): ${old_total:,.0f} (n={old_n})")
    print(f"  NEW (is_incremental_pipeline + deal_status==won): ${new_total:,.0f} (n={new_n})")
    print(f"  DIFF (new - old): ${new_total - old_total:,.0f}")
    print(f"  query_rep_attainment's own rule (4th definition): ${ra_total:,.0f} (n={ra_n})")
    print(f"  DIFF (rep_attainment - new): ${ra_total - new_total:,.0f}")
    a, b = _reopened_deal_diagnostic(sb, q_start_iso, q_end_iso)
    _print_reopened_deal_diagnostic(label, q_start_iso, q_end_iso, a, b)

    print()
    print("=" * 70)
    print("ATTAINMENT AUDIT A.1: owner_email coverage on current-quarter won deals")
    print("=" * 70)
    _owner_email_audit(sb, q_start_iso, q_end_iso)

    print()
    print("=" * 70)
    print("ATTAINMENT AUDIT A.2/A.3: rep_targets rows for the current period")
    print("=" * 70)
    period = label.replace(" ", "_")
    _rep_targets_report(sb, period)

    print()
    print("=" * 70)
    print("ATTAINMENT AUDIT A.4: which deals explain (rep_attainment - new)")
    print("=" * 70)
    _explain_rep_attainment_vs_new_diff(sb, q_start_iso, q_end_iso)

    print()
    print("=" * 70)
    print("PRIOR-YEAR WINDOWS (query_coverage_proxy_target_by_week's existing use)")
    print("=" * 70)
    complete_quarters = _get_complete_quarters(sb)
    if not complete_quarters:
        print("No complete quarters found — nothing to compare.")
        return 0

    total_abs_diff = 0.0
    for quarter in complete_quarters:
        q_start_iso, q_end_iso = _quarter_window_iso(sb, quarter)
        if not q_start_iso:
            print(f"{quarter}: no snapshot date found, skipping")
            continue
        prior_start_iso, prior_end_iso, prior_label = _prior_year_window(q_start_iso)
        old_total, old_n = _old_definition(sb, prior_start_iso, prior_end_iso)
        new_total, new_n = _new_definition(sb, prior_start_iso, prior_end_iso)
        diff = new_total - old_total
        total_abs_diff += abs(diff)
        print(f"{quarter}'s prior-year base ({prior_label}) [{prior_start_iso}..{prior_end_iso}]")
        print(f"  OLD: ${old_total:,.0f} (n={old_n})   NEW: ${new_total:,.0f} (n={new_n})   "
              f"DIFF: ${diff:,.0f}")
        if diff != 0:
            print(f"  -> This changes query_coverage_proxy_target_by_week's proxy_targets['{quarter}']"
                  f"['value'] (2x this base) by ${2 * diff:,.0f}")
        a, b = _reopened_deal_diagnostic(sb, prior_start_iso, prior_end_iso)
        _print_reopened_deal_diagnostic(prior_label, prior_start_iso, prior_end_iso, a, b)

    print()
    print(f"Sum of |diff| across all prior-year windows: ${total_abs_diff:,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
