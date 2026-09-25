#!/usr/bin/env python3
"""
Metric reconciliation: explain the change in a sum-over-deals metric between
two point-in-time captures, deal by deal, so the buckets add back to the
observed delta exactly.

Standalone and read-only, like qualification_crossing_walk.py and
commit_cohort_walk.py: no handler, no writes, nothing reaches Slack. Tier A of
the root-cause work — a metric that is a SUM over deals (pipeline value, deal
count, forecast total). Rate/ratio metrics are Tier B and are out of scope
here.

The metric is defined by two things the caller supplies:
  value(row) -> float   the deal's contribution to the metric at a snapshot
                        (e.g. arr_usd; or `lambda _: 1.0` for a deal count).
  scope                 which deals are IN the metric's population at a
                        snapshot, as named components (a dict of
                        name -> predicate(row) -> bool). Membership is the
                        conjunction; the names let a rescope say WHICH
                        condition flipped. A plain in_scope(row) predicate is
                        accepted instead when the reason breakdown isn't
                        wanted.

For every deal present in EITHER capture, its contribution to the change is

    (value(current) if in current scope else 0)
  - (value(prior)   if in prior   scope else 0)

and it lands in exactly one bucket:

  new                          entered scope; NOT in the prior capture universe
                               at all (a deal created between the two points).
  rescoped_in                  entered scope; WAS in the prior universe, out of
                               scope (close date / stage / pipeline moved it
                               into the window). The task's "Rescoped (... moved
                               in ...)".
  value_edited                 in scope on BOTH sides, value changed. The
                               $280K case's Reliance edit.
  exited_won                   left scope; current deal_status is won.
  exited_lost                  left scope; current deal_status is lost.
  exited_still_open_rescoped   left scope; still active (close date moved out,
                               stage now excluded, pipeline reclassified). The
                               task's "Exited still-open-but-rescoped".
  exited_unknown               left scope; no current status available to say
                               how. Reported explicitly — never guessed as a
                               loss. Its dollars still count toward the total.
  unchanged                    in scope on both sides, value identical (a $0
                               contributor; kept for a complete partition).
  unexplained_residual         a non-zero contributor that fits none of the
                               above. A safety net that should stay empty; if
                               it is not, it is reported, never hidden.

Exit outcome is read from the deal's real CURRENT row (its row in the current
capture if it is still in that universe, else `current_state[deal_id]`), the
same rule query_pipeline_movement (_pm_left_reason) and the dynamic-loop diff
path (snapshot_diff.attach_exit_status) use. It is NEVER inferred from a deal's
absence: a deal gone from the current capture is not assumed lost.

The reconciliation closes by construction: summed over the population, the per-
deal contributions equal (current in-scope sum) - (prior in-scope sum). The
result reports observed_delta, reconciled_total and their difference (residual)
as exact numbers. Either the accounting closes or the residual is stated; there
is no "approximately".

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \\
        python scripts/analytics/metric_reconciliation.py --input pair.json
    python scripts/analytics/metric_reconciliation.py --input pair.json --json

--input takes {"prior": [row, ...], "current": [row, ...],
"current_state": {deal_id: row, ...} (optional), "value_field": "arr_usd",
"scope": {"qualifying_stages": [...], "window_start": "...",
"window_end": "...", "active_status": "active"}}.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "api"))

BUCKETS = (
    "new", "rescoped_in", "value_edited",
    "exited_won", "exited_lost", "exited_still_open_rescoped", "exited_unknown",
    "unchanged", "unexplained_residual",
)

# how a deal_status string maps to an exit outcome (same intent as
# snapshot_diff.attach_exit_status: won / lost / still-open, else unknown).
_WON, _LOST, _ACTIVE = "won", "lost", "active"


def _as_value(value) -> Callable[[dict], float]:
    if callable(value):
        return lambda r: float(value(r) or 0.0)
    return lambda r: float(r.get(value) or 0.0)


def in_scope_all(row: dict, components: Dict[str, Callable[[dict], bool]]) -> bool:
    """A row is in scope when every named component predicate holds."""
    return all(pred(row) for pred in components.values())


def _flipped(prior_row: Optional[dict], current_row: Optional[dict],
             components: Optional[Dict[str, Callable[[dict], bool]]]) -> Optional[str]:
    """A human reason: which scope components differ between the two rows, with
    the values that changed. None when components weren't supplied or nothing
    identifiable flipped."""
    if not components or prior_row is None or current_row is None:
        return None
    parts = []
    for name, pred in components.items():
        try:
            p_ok, c_ok = bool(pred(prior_row)), bool(pred(current_row))
        except Exception:
            continue
        if p_ok != c_ok:
            # name the underlying field change where the component keys off one
            field = _FIELD_FOR_COMPONENT.get(name)
            if field and prior_row.get(field) != current_row.get(field):
                parts.append(f"{name} ({prior_row.get(field)} -> {current_row.get(field)})")
            else:
                parts.append(name)
    return "; ".join(parts) or None


# best-effort field a component name reads, for a readable reason string
_FIELD_FOR_COMPONENT = {
    "active": "deal_status",
    "qualifying_stage": "stage",
    "close_in_window": "close_date",
    "pipeline": "pipeline_id",
}


def _status_of(row: Optional[dict], status_field: str) -> Optional[str]:
    if not row:
        return None
    return str(row.get(status_field) or "").lower() or None


def reconcile(prior_rows: List[dict], current_rows: List[dict], *,
              value,
              scope_components: Optional[Dict[str, Callable[[dict], bool]]] = None,
              in_scope: Optional[Callable[[dict], bool]] = None,
              current_state: Optional[Dict[str, dict]] = None,
              key: str = "deal_id", status: str = "deal_status",
              label: str = "company_name", eps: float = 0.005) -> Dict[str, Any]:
    """Decompose the change in a sum-over-deals metric into one bucket per deal.

    See the module docstring for the buckets and the closing guarantee. Either
    `scope_components` (named predicates; membership is their conjunction, and
    rescope reasons name the flipped component) or `in_scope` (a bare
    membership predicate) must be given.
    """
    if scope_components is None and in_scope is None:
        raise ValueError("provide scope_components or in_scope")
    val = _as_value(value)
    if in_scope is None:
        def in_scope(r):  # noqa: E306 — conjunction of the named components
            return in_scope_all(r, scope_components)

    current_state = {str(k): v for k, v in (current_state or {}).items()}
    prior = {str(r.get(key)): r for r in prior_rows if r.get(key) is not None}
    current = {str(r.get(key)): r for r in current_rows if r.get(key) is not None}

    def _blank():
        return {"count": 0, "value": 0.0, "deals": []}
    buckets = {b: _blank() for b in BUCKETS}

    prior_in_value = sum(val(r) for r in prior.values() if in_scope(r))
    prior_in_count = sum(1 for r in prior.values() if in_scope(r))
    cur_in_value = sum(val(r) for r in current.values() if in_scope(r))
    cur_in_count = sum(1 for r in current.values() if in_scope(r))
    observed_delta = cur_in_value - prior_in_value

    reconciled_total = 0.0
    for did in sorted(set(prior) | set(current)):
        p = prior.get(did)
        c = current.get(did)
        p_in = bool(p is not None and in_scope(p))
        c_in = bool(c is not None and in_scope(c))
        if not p_in and not c_in:
            continue  # not in the population at either point — contributes nothing
        vp = val(p) if p_in else 0.0
        vc = val(c) if c_in else 0.0
        contribution = vc - vp

        reason = None
        if p_in and c_in:
            bucket = "value_edited" if abs(contribution) > eps else "unchanged"
        elif c_in and not p_in:
            # entered scope: new deal vs a deal that existed out of scope
            if p is None:
                bucket = "new"
            else:
                bucket = "rescoped_in"
                reason = _flipped(p, c, scope_components)
        elif p_in and not c_in:
            # left scope: classify by the deal's real current row, not absence
            current_row = c if c is not None else current_state.get(did)
            st = _status_of(current_row, status)
            if st == _WON:
                bucket = "exited_won"
            elif st == _LOST:
                bucket = "exited_lost"
            elif st == _ACTIVE:
                bucket = "exited_still_open_rescoped"
                reason = _flipped(p, current_row, scope_components)
            else:
                bucket = "exited_unknown"
        else:  # unreachable given the guards above; caught, never hidden
            bucket = "unexplained_residual"

        reconciled_total += contribution
        b = buckets[bucket]
        b["count"] += 1
        b["value"] += contribution
        if bucket != "unchanged":  # keep the zero-contributors as a count only
            b["deals"].append({
                "deal_id": did,
                "company_name": (c or p).get(label),
                "contribution": contribution,
                "reason": reason,
            })

    for b in buckets.values():
        b["value"] = round(b["value"], 2)
        b["deals"].sort(key=lambda d: -abs(d["contribution"]))

    residual = observed_delta - reconciled_total
    return {
        "observed_delta": round(observed_delta, 2),
        "reconciled_total": round(reconciled_total, 2),
        "residual": round(residual, 2),
        "closes": abs(residual) <= eps,
        "prior_in_scope": {"count": prior_in_count, "value": round(prior_in_value, 2)},
        "current_in_scope": {"count": cur_in_count, "value": round(cur_in_value, 2)},
        "buckets": buckets,
        "unexplained_residual": {
            "count": buckets["unexplained_residual"]["count"],
            "value": buckets["unexplained_residual"]["value"],
            "deals": buckets["unexplained_residual"]["deals"],
        },
    }


# --- scope helper for the qualified-pipeline case (the waterfall metric) ------

def qualified_pipeline_scope(qualifying_stages, window_start, window_end,
                             active_status="active"):
    """The named scope components for the qualified-pipeline Incremental ARR
    metric: active, at a qualifying stage, closing inside the window."""
    qs = {str(s) for s in qualifying_stages}
    return {
        "active": lambda r: r.get("deal_status") == active_status,
        "qualifying_stage": lambda r: str(r.get("stage")) in qs,
        "close_in_window": lambda r: r.get("close_date") is not None
        and window_start <= str(r["close_date"])[:10] <= window_end,
    }


def report(result: Dict[str, Any]) -> str:
    out = []
    d = result
    out.append(f"Observed delta:      {d['observed_delta']:+,.2f}")
    out.append(f"Reconciled total:    {d['reconciled_total']:+,.2f}")
    out.append(f"Residual:            {d['residual']:+,.2f}   "
               f"({'closes' if d['closes'] else 'DOES NOT CLOSE'})")
    out.append(f"Prior in scope:      {d['prior_in_scope']['count']:>4}  "
               f"${d['prior_in_scope']['value']:,.2f}")
    out.append(f"Current in scope:    {d['current_in_scope']['count']:>4}  "
               f"${d['current_in_scope']['value']:,.2f}")
    out.append("")
    for name in BUCKETS:
        b = d["buckets"][name]
        if b["count"] == 0:
            continue
        out.append(f"{name:<28} n={b['count']:>3}  {b['value']:+,.2f}")
        for deal in b["deals"]:
            reason = f"  [{deal['reason']}]" if deal.get("reason") else ""
            out.append(f"    {deal['deal_id']:<12} {str(deal['company_name'])[:26]:<26} "
                       f"{deal['contribution']:+,.2f}{reason}")
    return "\n".join(out)


def _fetch(_args):  # pragma: no cover - exercised only against a live DB
    raise SystemExit(
        "Live fetch is not built in: this Tier-A tool reconciles two captures you "
        "supply with --input (prior/current deal lists + scope). Capture the two "
        "point-in-time deal lists read-only and pass them in.")


def main():  # pragma: no cover - CLI wrapper
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True,
                    help="JSON: {prior, current, current_state?, value_field, scope}")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON too")
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text())
    scope = data["scope"]
    components = qualified_pipeline_scope(
        scope["qualifying_stages"], scope["window_start"], scope["window_end"],
        scope.get("active_status", "active"))
    result = reconcile(
        data["prior"], data["current"],
        value=data.get("value_field", "arr_usd"),
        scope_components=components,
        current_state=data.get("current_state"))
    print("Metric reconciliation (sum over deals, two captures), read-only.\n")
    print(report(result))
    if args.json:
        print("\nJSON " + json.dumps(result, default=str))


if __name__ == "__main__":
    main()
