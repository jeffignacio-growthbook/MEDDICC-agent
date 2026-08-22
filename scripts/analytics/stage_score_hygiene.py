#!/usr/bin/env python3
"""
Stage-vs-score hygiene (FIX_MEDDICC_SCORING_PIPELINE, Part 5).

Only meaningful now that Part 3 removed stage from the scoring prompt — score
and stage are independent, so comparing them is not circular.

For each active deal, compare its MEDDICC qualification against its recorded
CRM stage:

  | score | stage | reading                                             |
  |-------|-------|-----------------------------------------------------|
  | high  | early | deal is further along than the CRM says — STAGE NOT |
  |       |       | UPDATED                                             |
  | low   | late  | stage advanced without the qualification to support |
  |       |       | it                                                  |
  | aligned      | stage is trustworthy                                 |

THRESHOLDS ARE NOT TUNED. The bar is the stage_progression gates already in
config/client.yaml — the minimum component scores the sales process itself
requires to advance between stages (same 0-10 space as rubric.py's bands; the
final gate, all components >= 8, sits in rubric's green band). A deal's
"qualified stage" is the furthest stage whose entry gates its scores clear.
The only knob is stage_score_hygiene.stage_gap_margin (config), the number of
stages of divergence to flag. We report what falls out.

Scores come from the latest PASSED analysis per deal only (the reliable score,
same rule query_pre_call_brief uses); deals with no passed analysis are
reported as unscored, not classified.

__main__ reads Supabase (CI). The classification functions are pure and
import-safe for the offline eval.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
for p in ("scripts", "api"):
    sp = str(REPO / p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

try:
    from stage_requirements import get_requirements_for_stage, _get_stage_by_id, _load_config
except ImportError:
    from api.stage_requirements import get_requirements_for_stage, _get_stage_by_id, _load_config

_COMPONENTS = ["metrics", "economic_buyer", "decision_criteria",
               "decision_process", "pain", "champion", "competition"]
# analyses table column -> component key
_SCORE_COLS = {
    "metrics_score": "metrics", "economic_buyer_score": "economic_buyer",
    "decision_criteria_score": "decision_criteria",
    "decision_process_score": "decision_process", "pain_score": "pain",
    "champion_score": "champion", "competition_score": "competition",
}


def _ladder():
    """Analyzable, non-terminal stages in ascending order: [(order, id, name)].

    These are the rungs a deal can legitimately sit on. Excluded / won / lost
    stages are not rungs."""
    cfg = _load_config()
    rungs = []
    for pipeline in cfg.get("pipeline", {}).get("pipelines", []):
        if pipeline.get("analyze") is False:
            continue
        for st in pipeline.get("stages", []):
            if st.get("exclude_from_analysis") or st.get("is_won") or st.get("is_lost"):
                continue
            rungs.append((st["order"], st["id"], st["name"]))
    rungs.sort(key=lambda x: x[0])
    return rungs


def _meets(gate: dict, scores: dict) -> bool:
    """Does the deal clear every component threshold in this gate?"""
    return all((scores.get(comp) or 0) >= thr for comp, thr in gate.items())


def qualified_order(scores: dict, ladder=None):
    """The furthest rung the deal's scores support sitting on.

    Walk the rungs upward; advance past a rung only if the scores clear that
    rung's gate (the requirement to LEAVE it). Stop at the first gate the
    scores fail, or a rung with no defined gate."""
    ladder = ladder or _ladder()
    if not ladder:
        return None
    q = ladder[0][0]
    for i, (order, stage_id, _name) in enumerate(ladder):
        gate = get_requirements_for_stage(stage_id)
        if gate and _meets(gate, scores):
            # cleared this rung's gate → qualified for the next rung
            q = ladder[i + 1][0] if i + 1 < len(ladder) else order + 1
        else:
            break
    return q


def stage_gap_margin() -> int:
    cfg = _load_config()
    try:
        return int(cfg.get("stage_score_hygiene", {}).get("stage_gap_margin", 1))
    except (TypeError, ValueError):
        return 1


def classify(actual_order, scores, ladder=None, margin=None):
    """Return (reading, qualified_order, gap).

    reading ∈ {score_ahead_of_stage, stage_ahead_of_score, aligned}."""
    margin = stage_gap_margin() if margin is None else margin
    q = qualified_order(scores, ladder)
    if actual_order is None or q is None:
        return ("aligned", q, None)
    gap = q - actual_order
    if gap >= margin:
        return ("score_ahead_of_stage", q, gap)   # stage not updated
    if gap <= -margin:
        return ("stage_ahead_of_score", q, gap)   # advanced without qualification
    return ("aligned", q, gap)


# ── live report (CI) ───────────────────────────────────────────────────────

def _latest_passed(analyses_rows):
    """{deal_id: latest passed analysis row}."""
    latest = {}
    for a in analyses_rows:
        if not a.get("passed"):
            continue
        did = a.get("deal_id")
        if did not in latest or str(a.get("analyzed_at") or "") > str(latest[did].get("analyzed_at") or ""):
            latest[did] = a
    return latest


def main():
    from api.db import get_supabase
    from supabase_client import select_all
    sb = get_supabase()
    ladder = _ladder()
    margin = stage_gap_margin()
    order_to_name = {o: n for o, _id, n in ladder}

    print("=" * 76)
    print("STAGE-vs-SCORE HYGIENE — active deals, latest PASSED analysis")
    print(f"gates from config.stage_progression; stage_gap_margin={margin} (not tuned)")
    print("ladder: " + " → ".join(f"{n}({o})" for o, _id, n in ladder))
    print("=" * 76)

    deals = select_all(sb, "deals",
        columns="deal_id,company_name,stage,deal_value",
        filters=[("eq", "deal_status", "active")])
    analyses = select_all(sb, "analyses",
        columns="deal_id," + ",".join(_SCORE_COLS) + ",overall_score,analyzed_at,passed")
    latest = _latest_passed(analyses)

    ladder_orders = {o for o, _id, _n in ladder}
    buckets = {"score_ahead_of_stage": [], "stage_ahead_of_score": [],
               "aligned": [], "unscored": [], "off_ladder": []}
    for d in deals:
        did = d.get("deal_id")
        st = _get_stage_by_id(d.get("stage") or "")
        actual_order = st["order"] if st else None
        # Only deals sitting on an analyzable rung can be compared. A deal on
        # Meeting Set (order 0, excluded), a renewal-pipeline stage, or a
        # terminal stage has no rung to compare against — classifying it would
        # floor `qualified` at the lowest rung and manufacture a false gap.
        if actual_order not in ladder_orders:
            buckets["off_ladder"].append(d.get("company_name") or did)
            continue
        a = latest.get(did)
        if not a:
            buckets["unscored"].append((d.get("company_name") or did, did))
            continue
        scores = {comp: a.get(col) for col, comp in _SCORE_COLS.items()}
        reading, q, gap = classify(actual_order, scores, ladder, margin)
        buckets[reading].append({
            "company": d.get("company_name"), "deal_id": did,
            "stage": (st or {}).get("name"), "actual_order": actual_order,
            "qualified_order": q, "qualified_stage": order_to_name.get(q, f"order {q}"),
            "gap": gap, "overall": a.get("overall_score"),
            "scores": {c: scores.get(c) for c in _COMPONENTS},
        })

    def _fmt(row):
        return (f"  {str(row['company'])[:28]:28} stage={str(row['stage'])[:16]:16} "
                f"qualifies={str(row['qualified_stage'])[:16]:16} gap={row['gap']:+d} "
                f"overall={row['overall']}/70")

    total_classified = sum(len(buckets[k]) for k in
                           ("score_ahead_of_stage", "stage_ahead_of_score", "aligned"))
    print(f"\nactive deals: {len(deals)}  |  on-ladder scored (passed): {total_classified}  |  "
          f"on-ladder unscored: {len(buckets['unscored'])}  |  "
          f"off-ladder (Meeting Set / renewal / terminal, not classified): "
          f"{len(buckets['off_ladder'])}\n")

    print(f"[SCORE AHEAD OF STAGE — CRM stale, deal further along] "
          f"({len(buckets['score_ahead_of_stage'])})")
    for r in sorted(buckets["score_ahead_of_stage"], key=lambda x: -(x["gap"] or 0)):
        print(_fmt(r))
    print(f"\n[STAGE AHEAD OF SCORE — advanced without qualification] "
          f"({len(buckets['stage_ahead_of_score'])})")
    for r in sorted(buckets["stage_ahead_of_score"], key=lambda x: (x["gap"] or 0)):
        print(_fmt(r))
    print(f"\n[ALIGNED] ({len(buckets['aligned'])})  "
          f"[UNSCORED — no passed analysis] ({len(buckets['unscored'])})  "
          f"[OFF-LADDER — not classified] ({len(buckets['off_ladder'])})")

    # COVERAGE: why are on-ladder deals unscored? The hygiene check only sees
    # deals with a PASSED analysis, so a large unscored count means the check
    # runs on a small sample. Split the cause so it's actionable, not just a
    # number: evaluator gating (has analyses, none passed) vs. never analysed
    # with calls present (nightly not reaching them) vs. no calls to score.
    analyzed_ids = {a.get("deal_id") for a in analyses}
    passed_ids = set(latest.keys())
    try:
        call_rows = select_all(sb, "calls", columns="deal_id")
        call_ids = {c.get("deal_id") for c in call_rows}
    except Exception:
        call_ids = set()
    cause = {"has_analyses_none_passed": 0, "never_analysed_has_calls": 0,
             "never_analysed_no_calls": 0}
    for _company, did in buckets["unscored"]:
        if did in analyzed_ids and did not in passed_ids:
            cause["has_analyses_none_passed"] += 1   # evaluator gating
        elif did in call_ids:
            cause["never_analysed_has_calls"] += 1    # nightly not reaching / guard
        else:
            cause["never_analysed_no_calls"] += 1     # nothing to score
    print("\n[COVERAGE — why on-ladder deals are unscored]")
    print(f"  evaluator gated (analysed, none passed): {cause['has_analyses_none_passed']}")
    print(f"  never analysed but has calls (nightly gap): {cause['never_analysed_has_calls']}")
    print(f"  never analysed, no calls (nothing to score): {cause['never_analysed_no_calls']}")
    print("  NOTE: the hygiene classification above runs only on the "
          f"{total_classified} on-ladder deals with a passed analysis — a "
          "sample of the book, not the whole book.")

    # LiveSport worked example
    print("\n" + "-" * 76)
    for r in (buckets["score_ahead_of_stage"] + buckets["stage_ahead_of_score"]
              + buckets["aligned"]):
        if "livesport" in str(r["company"] or "").lower():
            print(f"LIVESPORT worked example: stage={r['stage']} "
                  f"(order {r['actual_order']}), qualifies for {r['qualified_stage']} "
                  f"(order {r['qualified_order']}), gap={r['gap']:+d} → "
                  f"{[k for k in buckets if r in buckets[k]][0]}")
            print(f"  components: {r['scores']}  overall={r['overall']}/70")
            break
    print("=" * 76)


if __name__ == "__main__":
    main()
