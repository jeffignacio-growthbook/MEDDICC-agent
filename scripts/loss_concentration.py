#!/usr/bin/env python3
"""
Loss Concentration Assessor — "where are our losses concentrated, by
rep / segment / stage" (NORTH_STAR.md CRO Priority #5, the buildable
half of the win/loss pattern-reasoning audit, 2026-09-20).

Confirmed before building: query_win_loss already exists and reads
win_loss_narratives, but does zero aggregation in code — pattern
reasoning (why we're losing, concentration by rep/segment/competitor)
is left to whatever the synthesis model does with a raw list. The
audit split that gap in two:
  - competitor-mention / stated-reason pattern reasoning is BLOCKED by
    a hard data ceiling (deals.lost_reason 0% populated fleet-wide,
    win_loss_narratives.competitor_mentioned 1.7% populated) — not
    buildable regardless of primitive design, same class as MEDDICC's
    1.2% coverage or Fireflies' identity dead-end. NOT addressed here.
  - rep/segment/stage-of-loss concentration has NO such ceiling —
    owner_email/segment/highest_stage_order_reached are populated on
    the full closed-deal population, independent of win_loss_narratives
    entirely. THIS primitive is that piece.

Design decisions confirmed before building (Step A):
  1. TIME-WINDOW SCOPED (not all-time) — "this quarter" is the real
     question shape, same as query_win_loss's own _resolve_tw() usage.
     Falls back to insufficient_data if the window's closed-deal count
     doesn't clear MIN_N, same principle as forecast_trust's week-3
     gate — never report a rate off too few deals.
  2. REP/SEGMENT BREAKDOWNS ARE RATE-NORMALIZED, never raw counts alone
     — a busy rep isn't "concentrated" just from volume. Each rate is
     reported against the team-average loss rate for context, never a
     bare ratio (same "gap-to-goal, never bare" discipline as
     pipeline_coverage.py). A rep/segment slice below MIN_N=5 closed
     deals is flagged insufficient_volume instead of reporting a
     misleading 100%/0% rate off 1-2 deals.
  3. STAGE-OF-LOSS USES THE CANONICAL BUCKET MAPPING
     (field_semantics.stage_bucket()), NOT raw
     highest_stage_order_reached. Confirmed live during scoping: order
     8 ('Review'/decisionmakerboughtin) and order 9 ('Disqualified')
     sit numerically AFTER the real terminal stages (Closed Won=6,
     Closed Lost=7) — both are administrative/exclude_from_analysis
     stages bolted on out of the real 0-6 sequence, not a continuation
     of genuine sales-cycle depth. 90.8% of all 1,132 lost deals
     (fleet-wide, at audit time) sat at order 8 or 9 — naive numeric
     clustering would be almost entirely these two administrative
     stages, not real signal. Their share is reported as its own
     explicit, labeled line (administrative_stage_share), NEVER folded
     into the bucket breakdown that's meant to answer "how deep did
     we get before losing."
  4. GHOST-DEAL ($0 deal_value) SHARE reported separately, labeled —
     same precedent as pipeline_coverage.py's HEURISTIC-vs-real-target
     separation: show both the full population and the flagged subset,
     never silently filter one out of the other.
  5. Aggregation is plain, deterministic Python over a single fetched
     row set — code-verified by construction, not model arithmetic.
     No runtime verify_structured_aggregations gate is needed (that
     pattern exists for cases where an LLM-produced count needs
     cross-checking against raw data; there is no such intermediate
     here). Correctness is covered by Steps C/D tests instead,
     targeting the bucket-mapping and rate-normalization logic
     specifically.

Read-only. No writes.
"""
import sys
from pathlib import Path
from collections import Counter
from typing import Optional, Dict, Any, List

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

# The two administrative/parking stages confirmed during scoping: numbered
# (8, 9) out of sequence after the real terminal stages (Closed Won=6,
# Closed Lost=7), both flagged exclude_from_analysis in config/client.yaml.
# Keyed by canonical HubSpot stage id, resolved via field_semantics so an
# alias (e.g. '68509551' for Disqualified) is matched correctly.
ADMINISTRATIVE_STAGE_IDS = {"decisionmakerboughtin", "68509551"}

MIN_N = 5  # both the primitive-level gate and the per-rep/segment row floor


def _order_to_stage_id(pipeline_config: dict) -> Dict[int, str]:
    """highest_stage_order_reached (int) -> HubSpot stage id, from
    config/client.yaml's pipeline stages list. No existing reverse
    lookup for this direction (get_stage_order() only goes id->order),
    so this is a small, single-purpose helper built fresh — everything
    it feeds into (stage_bucket()/stage_label()) is the existing
    canonical source, not reinvented."""
    mapping = {}
    for pipeline in pipeline_config.get("pipelines", []):
        for stage in pipeline.get("stages", []):
            order = stage.get("order")
            if order is not None:
                mapping.setdefault(order, stage["id"])
    return mapping


def _rate_row(key_value: str, key_name: str, won: int, lost: int,
              team_loss_rate: float) -> Dict[str, Any]:
    """One rep/segment row. Never a bare ratio — always phrased with
    team-average context. Below MIN_N, no rate is computed at all
    (insufficient_volume=True) rather than reporting a misleading
    100%/0% off a couple of deals."""
    closed = won + lost
    row = {key_name: key_value, "won": won, "lost": lost, "closed": closed}
    if closed < MIN_N:
        row["loss_rate"] = None
        row["insufficient_volume"] = True
        row["text"] = (f"{key_value}: {lost}/{closed} closed lost — fewer "
                        f"than {MIN_N} closed deals, too thin to report a "
                        f"reliable rate")
        return row
    loss_rate = lost / closed
    vs_team = loss_rate - team_loss_rate
    row["loss_rate"] = round(loss_rate, 4)
    row["vs_team_avg_pts"] = round(vs_team, 4)
    direction = "above" if vs_team > 0 else ("below" if vs_team < 0 else "equal to")
    row["text"] = (f"{key_value}: {lost}/{closed} closed lost "
                    f"({loss_rate:.1%} loss rate), "
                    f"{abs(vs_team):.1%} {direction} the team average "
                    f"of {team_loss_rate:.1%}")
    return row


def _rate_breakdown(deals: List[dict], key: str,
                     team_loss_rate: float) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, int]] = {}
    for d in deals:
        k = d.get(key) or "Unknown"
        bucket = by_key.setdefault(k, {"won": 0, "lost": 0})
        bucket["won" if d.get("deal_status") == "won" else "lost"] += 1

    rows = [_rate_row(k, key, c["won"], c["lost"], team_loss_rate)
            for k, c in by_key.items()]
    # Sort by loss_rate descending (worst first); insufficient-volume rows
    # (loss_rate=None) sort last, never masquerading as "0% loss".
    rows.sort(key=lambda r: (r["loss_rate"] is None, -(r["loss_rate"] or 0)))
    return rows


def assess_loss_concentration(sb, time_window: Optional[dict] = None) -> Dict[str, Any]:
    """
    Rep/segment/stage-of-loss concentration for closed (won+lost) deals
    in a time window — code-verified aggregation, never model arithmetic.

    Args:
        sb: Supabase client
        time_window: already-resolved {"start","end","label"} dict (the
            router always injects this; falls back to the current
            quarter if not given, same convention as resolve_time_window).

    Returns (gated):
        {"status": "insufficient_data", "reason": "too_few_closed_deals",
         "period": str, "closed_deal_count": int, "min_required": int,
         "note": str}
      or:
        {"status": "ok", "period": str,
         "closed_deal_count": int, "won_count": int, "lost_count": int,
         "team_loss_rate": float,
         "by_rep": [...rate rows, worst first...],
         "by_segment": [...rate rows, worst first...],
         "stage_of_loss": {
             "by_bucket": {bucket: {"count", "pct"}, ...},
             "administrative_stage_share": {"count", "pct", "note"},
         },
         "ghost_deal_share": {"count", "pct", "note"},
         "min_n_floor": int,
         "note": str}
    """
    from field_semantics import stage_bucket
    from supabase_client import select_all
    from time_resolver import resolve_time_window
    from utils import get_pipeline_config

    if not time_window or "start" not in time_window or "end" not in time_window:
        time_window = resolve_time_window(time_window or {})
    tw_start, tw_end = time_window["start"], time_window["end"]
    tw_label = time_window.get("label", "")

    deals = select_all(sb, "deals",
        columns="deal_id,deal_status,deal_value,close_date,"
                "owner_email,segment,highest_stage_order_reached",
        filters=[("in_", "deal_status", ["won", "lost"]),
                 ("gte", "close_date", tw_start),
                 ("lte", "close_date", tw_end)])

    total_closed = len(deals)
    if total_closed < MIN_N:
        return {
            "status": "insufficient_data",
            "reason": "too_few_closed_deals",
            "period": tw_label,
            "closed_deal_count": total_closed,
            "min_required": MIN_N,
            "note": (f"Only {total_closed} closed deal(s) in {tw_label} — "
                     f"need at least {MIN_N} for a meaningful concentration "
                     f"breakdown."),
        }

    wins = [d for d in deals if d.get("deal_status") == "won"]
    losses = [d for d in deals if d.get("deal_status") == "lost"]
    # Verified by construction: wins/losses are a partition of the same
    # fetched row set (deal_status is in ("won","lost") by the filter
    # above, so every row lands in exactly one bucket) — no separate
    # "structured output" exists here to drift from the underlying data.
    won_count, lost_count = len(wins), len(losses)
    team_loss_rate = lost_count / total_closed

    by_rep = _rate_breakdown(deals, "owner_email", team_loss_rate)
    by_segment = _rate_breakdown(deals, "segment", team_loss_rate)

    # Stage-of-loss: canonical BUCKET mapping, not raw numeric order —
    # see module docstring decision #3.
    pipeline_config = get_pipeline_config()
    order_to_stage_id = _order_to_stage_id(pipeline_config)

    bucket_counts = Counter()
    admin_stage_count = 0
    for d in losses:
        order = d.get("highest_stage_order_reached")
        stage_id = order_to_stage_id.get(order) if order is not None else None
        bucket_counts[stage_bucket(stage_id) if stage_id else "unknown"] += 1
        if stage_id in ADMINISTRATIVE_STAGE_IDS:
            admin_stage_count += 1

    by_bucket = {
        b: {"count": c, "pct": round(c / lost_count, 4)}
        for b, c in bucket_counts.most_common()
    } if lost_count else {}

    stage_of_loss = {
        "by_bucket": by_bucket,
        "administrative_stage_share": {
            "count": admin_stage_count,
            "pct": round(admin_stage_count / lost_count, 4) if lost_count else None,
            "note": ("Deals whose deepest recorded stage was 'Review' or "
                     "'Disqualified' — both flagged exclude_from_analysis "
                     "in config/client.yaml, numbered (8, 9) OUT OF "
                     "SEQUENCE after the real terminal stages (Closed "
                     "Won=6, Closed Lost=7). NOT a signal of real sales-"
                     "cycle depth — reported separately so it's never "
                     "folded into by_bucket above."),
        },
    }

    ghost_losses = [d for d in losses if not d.get("deal_value")]
    ghost_deal_share = {
        "count": len(ghost_losses),
        "pct": round(len(ghost_losses) / lost_count, 4) if lost_count else None,
        "note": ("Lost deals with $0/null deal_value — likely never "
                 "properly qualified or entered, not a genuine competitive "
                 "loss. Reported separately; NOT excluded from by_rep/"
                 "by_segment/stage_of_loss above, which cover the full "
                 "population."),
    }

    return {
        "status": "ok",
        "period": tw_label,
        "closed_deal_count": total_closed,
        "won_count": won_count,
        "lost_count": lost_count,
        "team_loss_rate": round(team_loss_rate, 4),
        "by_rep": by_rep,
        "by_segment": by_segment,
        "stage_of_loss": stage_of_loss,
        "ghost_deal_share": ghost_deal_share,
        "min_n_floor": MIN_N,
        "note": ("Rep/segment rates are never bare — always reported "
                 "against the team-average loss rate. Rows below "
                 f"{MIN_N} closed deals are flagged insufficient_volume, "
                 "not reported with a misleading rate. Stage-of-loss uses "
                 "the canonical bucket mapping, not raw "
                 "highest_stage_order_reached, to avoid the two "
                 "administrative stages (order 8, 9) masquerading as "
                 "sales-cycle depth."),
    }
