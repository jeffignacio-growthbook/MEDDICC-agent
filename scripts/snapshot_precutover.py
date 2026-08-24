#!/usr/bin/env python3
"""
Pre-cutover snapshot (PROGRESSIVE_SCORING_SPEC, Phase 5b).

Captures the CURRENT scoring state of the book BEFORE the first progressive
roll-up nightly, so Phase 5c can prove the numbers moved in the predicted
direction rather than just "look different".

Three things are captured, all keyed by deal so a post-cutover re-run diffs
cleanly:

  1. Per-deal MEDDICC scores — the score of record. Read from the analyses
     table (latest PASSED analysis per deal, the same rule the hygiene report
     and query_pre_call_brief use), and, when HUBSPOT_API_KEY is set, the live
     `meddicc_*_score` deal properties too. The two agree when the last nightly
     wrote both; capturing both makes the snapshot self-checking.

  2. Stage-vs-score hygiene buckets — score_ahead_of_stage / stage_ahead_of_score
     / aligned counts, computed with analytics.stage_score_hygiene.classify (NOT
     re-implemented here — the gate-tested classifier is the single source).
     PREDICTED MOVEMENT after cutover: progressive scores higher, so the
     score_ahead_of_stage bucket GROWS and stage_ahead_of_score SHRINKS. This
     snapshot is the baseline that prediction is checked against.

  3. Pipeline value by stage — active-deal deal_value summed per stage, a cheap
     "current shape" reference (not the temporal waterfall, which needs history).

The snapshot is written to memory/snapshots/precutover_<ts>.json plus a short
markdown summary next to it, and printed. summarize() is pure and import-safe so
the offline eval can drive it on synthetic rows.

This does NOT change any scores. It only reads.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

REPO = Path(__file__).resolve().parent.parent
# "" is the repo root — required so `api.db` resolves as a package (the batch
# scripts include it; the offline eval added it itself, which hid its absence).
for p in ("", "scripts", "api", "scripts/analytics"):
    sp = str(REPO / p) if p else str(REPO)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Config/gate logic only — no network at import time.
from analytics.stage_score_hygiene import (  # noqa: E402
    classify, _ladder, stage_gap_margin, _latest_passed,
    _SCORE_COLS, _COMPONENTS,
)
try:
    from stage_requirements import _get_stage_by_id
except ImportError:  # pragma: no cover
    from api.stage_requirements import _get_stage_by_id

READINGS = ("score_ahead_of_stage", "stage_ahead_of_score", "aligned")


def summarize(deals, analyses, ladder=None, margin=None):
    """Pure: build the snapshot payload from deals + analyses rows.

    deals:    [{deal_id, company_name, stage, deal_value, pipeline?}]
    analyses: [{deal_id, *_score, overall_score, analyzed_at, passed}]

    Returns a dict with per-deal rows, bucket counts, and pipeline-by-stage —
    the exact shape re-run post-cutover diffs against.
    """
    ladder = ladder if ladder is not None else _ladder()
    margin = stage_gap_margin() if margin is None else margin
    ladder_orders = {o for o, _id, _n in ladder}
    order_to_name = {o: n for o, _id, n in ladder}

    latest = _latest_passed(analyses)

    rows = []
    counts = {k: 0 for k in READINGS}
    counts.update(unscored=0, off_ladder=0)
    pipeline_by_stage = defaultdict(lambda: {"count": 0, "value": 0.0})

    for d in deals:
        did = d.get("deal_id")
        stage_id = d.get("stage") or ""
        st = _get_stage_by_id(stage_id)
        stage_name = (st or {}).get("name") or stage_id
        actual_order = st["order"] if st else None

        # Pipeline-by-stage over active deals (deal_value may be None → skip value)
        pv = pipeline_by_stage[stage_name]
        pv["count"] += 1
        dv = d.get("deal_value")
        if isinstance(dv, (int, float)):
            pv["value"] += float(dv)

        if actual_order not in ladder_orders:
            counts["off_ladder"] += 1
            continue
        a = latest.get(did)
        if not a:
            counts["unscored"] += 1
            continue

        scores = {comp: a.get(col) for col, comp in _SCORE_COLS.items()}
        reading, q, gap = classify(actual_order, scores, ladder, margin)
        counts[reading] += 1
        rows.append({
            "deal_id": did,
            "company": d.get("company_name"),
            "stage": stage_name,
            "actual_order": actual_order,
            "qualified_order": q,
            "qualified_stage": order_to_name.get(q, f"order {q}"),
            "gap": gap,
            "reading": reading,
            "overall": a.get("overall_score"),
            "scores": {c: scores.get(c) for c in _COMPONENTS},
        })

    return {
        "counts": counts,
        "deals": sorted(rows, key=lambda r: -(r["gap"] or 0)),
        "pipeline_by_stage": {k: dict(v) for k, v in pipeline_by_stage.items()},
        "margin": margin,
        "ladder": [{"order": o, "id": i, "name": n} for o, i, n in ladder],
    }


def _read_hubspot_scores(active_deal_ids):
    """Live meddicc_*_score deal properties, keyed by deal_id. Best-effort:
    returns {} if HubSpot is unreachable or the key is unset."""
    if not os.getenv("HUBSPOT_API_KEY"):
        return {}
    try:
        from hubspot_deals import get_hubspot_deals_client
        hs = get_hubspot_deals_client()
    except Exception as e:  # pragma: no cover
        print(f"  (HubSpot read skipped: {e})")
        return {}

    score_props = ["meddicc_score", "meddicc_status"] + [
        f"meddicc_{c}_score" for c in _COMPONENTS
    ]
    out = {}
    try:
        deals = hs.get_active_deals()
    except Exception as e:  # pragma: no cover
        print(f"  (HubSpot get_active_deals failed: {e})")
        return {}
    # get_active_deals doesn't request the score props; re-read each deal's
    # score properties directly. One GET per deal, guarded.
    want = set(active_deal_ids)
    for d in deals:
        did = str(d.get("id") or "")
        if want and did not in want:
            continue
        try:
            resp = hs._get(
                f"/crm/v3/objects/deals/{did}",
                params={"properties": ",".join(score_props)},
            )
            props = resp.get("properties", {}) or {}
            out[did] = {k: props.get(k) for k in score_props}
        except Exception:
            continue
    return out


def _render_summary_md(snap, now_iso):
    c = snap["counts"]
    lines = [
        "# Pre-cutover snapshot",
        "",
        f"Captured: {now_iso}",
        f"Stage-gap margin: {snap['margin']} (not tuned)",
        "",
        "## Stage-vs-score hygiene (baseline)",
        "",
        f"- **score_ahead_of_stage** (CRM stale): {c['score_ahead_of_stage']}",
        f"- **stage_ahead_of_score** (advanced w/o qualification): {c['stage_ahead_of_score']}",
        f"- aligned: {c['aligned']}",
        f"- unscored (no passed analysis): {c['unscored']}",
        f"- off-ladder (not classified): {c['off_ladder']}",
        "",
        "> Predicted movement after progressive cutover: scores rise, so",
        "> **score_ahead_of_stage grows** and **stage_ahead_of_score shrinks**.",
        "",
        "## Pipeline value by stage (active deals)",
        "",
    ]
    for stage, v in sorted(snap["pipeline_by_stage"].items(),
                           key=lambda kv: -kv[1]["value"]):
        lines.append(f"- {stage}: {v['count']} deals, ${v['value']:,.0f}")
    return "\n".join(lines) + "\n"


def main():
    from api.db import get_supabase
    from supabase_client import select_all

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    ts = now.strftime("%Y%m%dT%H%M%SZ")

    print("=" * 76)
    print("PRE-CUTOVER SNAPSHOT — baseline before first progressive nightly")
    print(f"captured: {now_iso}")
    print("=" * 76)

    sb = get_supabase()
    deals = select_all(sb, "deals",
                       columns="deal_id,company_name,stage,deal_value,pipeline",
                       filters=[("eq", "deal_status", "active")])
    analyses = select_all(sb, "analyses",
                         columns="deal_id," + ",".join(_SCORE_COLS)
                                 + ",overall_score,analyzed_at,passed")

    snap = summarize(deals, analyses)
    snap["hubspot_scores"] = _read_hubspot_scores(
        [r["deal_id"] for r in snap["deals"]])
    snap["captured_at"] = now_iso
    snap["source"] = "analyses(latest passed) + deals(active)"

    c = snap["counts"]
    print(f"\nactive deals: {len(deals)}")
    print(f"  score_ahead_of_stage : {c['score_ahead_of_stage']}")
    print(f"  stage_ahead_of_score : {c['stage_ahead_of_score']}")
    print(f"  aligned              : {c['aligned']}")
    print(f"  unscored             : {c['unscored']}")
    print(f"  off_ladder           : {c['off_ladder']}")
    print(f"  hubspot scores read  : {len(snap['hubspot_scores'])}")

    out_dir = REPO / "memory" / "snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"precutover_{ts}.json"
    md_path = out_dir / f"precutover_{ts}.md"
    json_path.write_text(json.dumps(snap, indent=2, default=str))
    md_path.write_text(_render_summary_md(snap, now_iso))

    # Stable "latest" pointer so 5c doesn't have to guess the timestamp.
    (out_dir / "precutover_latest.json").write_text(
        json.dumps(snap, indent=2, default=str))

    print(f"\nsnapshot written:\n  {json_path}\n  {md_path}\n  "
          f"{out_dir / 'precutover_latest.json'}")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    sys.exit(main())
