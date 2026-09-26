#!/usr/bin/env python3
"""
Stage-vs-call-content lag detector (Direction 1) — read-only review list.

Standalone and read-only, like metric_reconciliation.py, rate_mix_decomposition.py
and sensitivity_analysis.py: no handler, no writes, nothing reaches Slack, and
it NEVER changes a deal's stage or forecast_category. Its only output is a
flagged REVIEW list a human looks at.

Direction 1: a deal recorded at a PRE-COMMERCIAL stage (Discovery / Scoping)
whose call evidence says it is commercially further along than the stage
records — a stage that lags the deal's actual progress. The call signal is the
deal's MEDDICC Economic Buyer + Decision Process scores (from the `analyses`
table): both at or above a threshold (default 6/10) means the buyer economics
and the decision process are established, which is late-stage behaviour.

Two gates, in order:
  1. SUBSTANCE — the deal must have a scoreable call: at least one MEDDICC
     analysis carrying real signal (Economic Buyer or Decision Process > 0). A
     deal with no scoreable call is EXCLUDED entirely (counted in
     excluded_no_scoreable_call), never silently treated as "no mismatch". An
     all-zero analysis is the null-input case (e.g. RedCore, EB0/DP0), not a
     real low score.
  2. SIGNAL — Economic Buyer >= eb_threshold AND Decision Process >= dp_threshold
     (BOTH). One high and one low (e.g. shiftkey EB5/DP9, or a deal at EB7/DP5)
     is NOT a flag: a single strong axis is not commercial readiness.

RECENCY LIMITATION (read this before acting on the output): flags are based on
CUMULATIVE call evidence at ANY point in the deal's history (the peak Economic
Buyer / Decision Process across all its analyses), NOT evidence near its
current stage. `analyses.stage_at_analysis` is not populated to support a
near-stage check, so a flag does NOT mean the deal was reviewed recently or
that the commercial signal is current. Treat a flag as "worth a human look",
not "this deal is definitely mis-staged right now".

THIN POOL: on live FY2027-Q3 data this flags ~6 open deals. It is a REVIEW
LIST, not a volume-scale monitoring signal, and must not be represented as one.

    python scripts/analytics/stage_call_lag.py            # live (needs Supabase env)
    python scripts/analytics/stage_call_lag.py --json
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Discovery + Scoping stage ids (config buckets discovery/scoping) — the
# pre-commercial stages. Resolved from config in main(); this default mirrors
# the live default pipeline so the pure functions are usable without config.
PRECOMMERCIAL_STAGES_DEFAULT = ("79653122", "appointmentscheduled", "qualifiedtobuy")

EB_THRESHOLD_DEFAULT = 6
DP_THRESHOLD_DEFAULT = 6

RECENCY_CAVEAT = (
    "Flags are based on cumulative call evidence at any point in the deal's "
    "history (peak Economic Buyer / Decision Process across all analyses), NOT "
    "evidence near its current stage: analyses.stage_at_analysis is not "
    "populated to support that check. A flag does not mean the deal was "
    "reviewed recently — treat it as worth a human look, not a certain "
    "mis-stage."
)
THIN_POOL_NOTE = (
    "This is a review list, not a volume-scale monitoring signal (~6 flagged "
    "on current data). Do not represent it as continuous monitoring."
)


def _score(a: dict, key: str) -> int:
    v = a.get(key)
    return int(v) if v is not None else 0


def classify_deal(analyses_for_deal: List[dict], *,
                  eb_threshold: int = EB_THRESHOLD_DEFAULT,
                  dp_threshold: int = DP_THRESHOLD_DEFAULT) -> Dict[str, Any]:
    """Classify ONE deal from its MEDDICC analyses.

    Returns {"status", "peak_eb", "peak_dp"} where status is:
      "no_scoreable_call" — no analysis with real signal (EB or DP > 0); the
          null-input case, excluded before any threshold test.
      "below_threshold"   — has real signal but not (EB>=t AND DP>=t).
      "flag"              — cumulative peak EB>=t AND peak DP>=t.
    Peak (max across all analyses), never the latest row — see the module's
    RECENCY LIMITATION.
    """
    scoreable = [a for a in analyses_for_deal
                 if _score(a, "economic_buyer_score") > 0
                 or _score(a, "decision_process_score") > 0]
    if not scoreable:
        return {"status": "no_scoreable_call", "peak_eb": None, "peak_dp": None}
    peak_eb = max(_score(a, "economic_buyer_score") for a in scoreable)
    peak_dp = max(_score(a, "decision_process_score") for a in scoreable)
    if peak_eb >= eb_threshold and peak_dp >= dp_threshold:
        status = "flag"
    else:
        status = "below_threshold"
    return {"status": status, "peak_eb": peak_eb, "peak_dp": peak_dp}


def detect_stage_call_lag(deals: List[dict], analyses_by_deal: Dict[str, List[dict]], *,
                          precommercial_stages=PRECOMMERCIAL_STAGES_DEFAULT,
                          eb_threshold: int = EB_THRESHOLD_DEFAULT,
                          dp_threshold: int = DP_THRESHOLD_DEFAULT,
                          open_status: str = "active",
                          stage_labels: Dict[str, str] = None) -> Dict[str, Any]:
    """Flag OPEN, pre-commercial-stage deals whose call evidence says they are
    further along than the stage records. Read-only: returns a review list,
    changes nothing.

    deals: rows with deal_id, company_name, stage, deal_status.
    analyses_by_deal: {str(deal_id): [analysis rows]} (MEDDICC scores).
    """
    stages = set(precommercial_stages)
    labels = stage_labels or {}
    flagged: List[Dict[str, Any]] = []
    considered = excluded_no_call = below = 0

    for d in deals:
        if d.get("deal_status") != open_status:
            continue
        if d.get("stage") not in stages:
            continue
        considered += 1
        cls = classify_deal(analyses_by_deal.get(str(d.get("deal_id")), []),
                            eb_threshold=eb_threshold, dp_threshold=dp_threshold)
        if cls["status"] == "no_scoreable_call":
            excluded_no_call += 1
            continue
        if cls["status"] == "below_threshold":
            below += 1
            continue
        stage = d.get("stage")
        stage_label = labels.get(stage, stage)
        flagged.append({
            "deal_id": d.get("deal_id"),
            "company_name": d.get("company_name"),
            "current_stage": stage,
            "current_stage_label": stage_label,
            "economic_buyer_score": cls["peak_eb"],
            "decision_process_score": cls["peak_dp"],
            "evidence": (
                f"Cumulative call evidence peaks at Economic Buyer {cls['peak_eb']}/10 "
                f"and Decision Process {cls['peak_dp']}/10 (commercial readiness), "
                f"but the deal is recorded at {stage_label}."),
            "suggested_review": (
                "Review whether the recorded stage lags the deal's actual "
                "progress; confirm on the deal before any change — do not "
                "auto-advance the stage or forecast."),
        })

    flagged.sort(key=lambda f: -(f["economic_buyer_score"] + f["decision_process_score"]))
    return {
        "flagged": flagged,
        "flagged_count": len(flagged),
        "considered": considered,
        "excluded_no_scoreable_call": excluded_no_call,
        "below_threshold_count": below,
        "thresholds": {"economic_buyer": eb_threshold, "decision_process": dp_threshold},
        "recency_caveat": RECENCY_CAVEAT,
        "thin_pool_note": THIN_POOL_NOTE,
    }


def report(res: Dict[str, Any]) -> str:
    out = ["Stage-vs-call-content lag — Direction 1 (review list, read-only).", ""]
    t = res["thresholds"]
    out.append(f"Considered {res['considered']} open pre-commercial deals; "
               f"flagged {res['flagged_count']} "
               f"(EB>={t['economic_buyer']} AND DP>={t['decision_process']}); "
               f"{res['below_threshold_count']} below threshold; "
               f"{res['excluded_no_scoreable_call']} excluded (no scoreable call).")
    out.append("")
    for f in res["flagged"]:
        out.append(f"  • {f['company_name']} ({f['deal_id']}) — {f['current_stage_label']}"
                   f"  EB {f['economic_buyer_score']}/10  DP {f['decision_process_score']}/10")
        out.append(f"      {f['suggested_review']}")
    out.append("")
    out.append("NOTE (recency): " + res["recency_caveat"])
    out.append("NOTE (scope): " + res["thin_pool_note"])
    return "\n".join(out)


def _load_precommercial_stages():  # pragma: no cover - config wiring
    """Discovery+Scoping stage ids from config, via the canonical bucket map."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))
    from utils import get_pipeline_config
    from field_semantics import stage_bucket
    cfg = get_pipeline_config()
    stages, labels = [], {}
    for p in cfg.get("pipelines", []):
        if str(p.get("id")) != "default":
            continue
        for s in p.get("stages", []):
            sid = s.get("id")
            if stage_bucket(sid) in ("discovery", "scoping"):
                stages.append(str(sid))
                labels[str(sid)] = s.get("label") or stage_bucket(sid)
    return tuple(stages), labels


def main():  # pragma: no cover - live wiring
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eb-threshold", type=int, default=EB_THRESHOLD_DEFAULT)
    ap.add_argument("--dp-threshold", type=int, default=DP_THRESHOLD_DEFAULT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from supabase_client import SupabaseWriter, select_all

    stages, labels = _load_precommercial_stages()
    sb = SupabaseWriter().client
    deals = select_all(sb, "deals",
        columns="deal_id,company_name,stage,deal_status,pipeline_id",
        filters=[("eq", "deal_status", "active"), ("eq", "pipeline_id", "default"),
                 ("in_", "stage", list(stages))])
    ids = [str(d["deal_id"]) for d in deals]
    analyses_by_deal: Dict[str, List[dict]] = {}
    for i in range(0, len(ids), 100):
        for a in select_all(sb, "analyses",
                columns="deal_id,economic_buyer_score,decision_process_score",
                filters=[("in_", "deal_id", ids[i:i + 100])]):
            analyses_by_deal.setdefault(str(a["deal_id"]), []).append(a)

    res = detect_stage_call_lag(deals, analyses_by_deal, precommercial_stages=stages,
                                eb_threshold=args.eb_threshold, dp_threshold=args.dp_threshold,
                                stage_labels=labels)
    print(report(res))
    if args.json:
        print("\nJSON " + json.dumps(res, default=str))


if __name__ == "__main__":
    main()
