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
  - stated-reason (deals.lost_reason) pattern reasoning IS buildable
    (fixed 2026-09-25). It was long recorded here as BLOCKED by a "hard
    data ceiling (deals.lost_reason 0% populated)", but that was an ETL
    FETCH GAP, not a CRM ceiling: HubSpot's closed_lost_reason is
    populated (100% of the recent quarter's closed-lost, ~44% fleet-wide
    over all history — older deals predate the field), the ETL just never
    requested it. Now fetched (DEAL_SYNC_PROPERTIES) and backfilled, and
    win_loss_narratives.stated_reason tracks it. Bucketing losses by
    stated reason (competitor / budget / fit / unresponsive) is a real,
    buildable primitive — NOT built here; logged in PENDING_WORK.
  - competitor-mention pattern reasoning IS still ceilinged
    (win_loss_narratives.competitor_mentioned 1.7% populated) — genuinely
    thin data, same class as MEDDICC's 1.2% coverage. NOT addressed here.
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

Qualified loss rate (2026-09-25). The headline is no longer lost / all
closed. On live FY2027 Q3 data that read 92.4% (109 of 118) because it
counted 52 deals closed as Disqualified (inbound leads that never
qualified), 17 that closed without reaching Discovery and the renewals.
The lead figure is now the QUALIFIED loss rate: Sales-pipeline deals seen
in deals_snapshot at Discovery or later (Discovery, Scoping, Technical
Evaluation, Negotiating, Awaiting Signature; derived from config:
order >= qualified_stage_order, not won/lost, not exclude_from_analysis)
on or before their close_date, and not closed as Disqualified. Review is
not "Discovery or later": config calls it a parking lot for stalled/dead
deals, and live snapshots show deals going Meeting Set -> Review without
ever reaching Discovery. deals.highest_stage_order_reached cannot answer
the question (Closed Lost is order 7, Disqualified 9, so every loss reads
7+). A Sales deal with no snapshot history is counted as
no_stage_history, never guessed in or out; the headline gives the rate if
all of them had qualified. The all-closed rate is always reported beside
it, with where the difference comes from (loss_rate_headline, built here
so the wording is code's, not the model's).

by_rep and by_segment are over the qualified population, and an owner
whose user_personas role is 'sdr' is kept out of the rep table (listed in
by_rep_excluded; their deals still count in the team rate): otherwise a
BDR's disqualified inbound leads read as a "100% loss rate".

won_incremental_arr: closed-won incremental ARR (new + expansion) summed
over the same fetched won rows won_count counts, for quarter health's
QTD-vs-target line (no second query).

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

SALES_PIPELINE = "default"
NON_CLOSING_ROLES = {"sdr"}  # user_personas.role values kept out of by_rep
_ID_CHUNK = 100


def _sales_stages(pipeline_config: dict = None) -> tuple:
    if pipeline_config is None:
        from utils import get_pipeline_config
        pipeline_config = get_pipeline_config()
    for p in pipeline_config.get("pipelines", []):
        if str(p.get("id")) == SALES_PIPELINE:
            return p.get("stages", []), p.get("qualified_stage_order", 1)
    return [], 1


def discovery_or_later_stages(pipeline_config: dict = None) -> tuple:
    """Sales stages a deal has to have been seen at to count as qualified:
    order >= qualified_stage_order, not won/lost, not exclude_from_analysis
    (which leaves out Meeting Set, Review and Disqualified)."""
    stages, qso = _sales_stages(pipeline_config)
    return tuple(str(s["id"]) for s in sorted(stages, key=lambda s: s.get("order", 0))
                 if s.get("order") is not None and s["order"] >= qso
                 and not s.get("is_won") and not s.get("is_lost")
                 and not s.get("exclude_from_analysis"))


def disqualified_stage_ids(pipeline_config: dict = None) -> set:
    """Config rule: Disqualified stages carry BOTH is_lost and
    exclude_from_analysis."""
    stages, _ = _sales_stages(pipeline_config)
    return {str(s["id"]) for s in stages if s.get("is_lost") and s.get("exclude_from_analysis")}


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
              team_loss_rate: Optional[float]) -> Dict[str, Any]:
    """One rep/segment row. Never a bare ratio — always phrased with
    team-average context. Below MIN_N, no rate is computed at all
    (insufficient_volume=True) rather than reporting a misleading
    100%/0% off a couple of deals."""
    closed = won + lost
    row = {key_name: key_value, "won": won, "lost": lost, "closed": closed}
    if closed < MIN_N:
        row["loss_rate"] = None
        row["insufficient_volume"] = True
        row["text"] = (f"{key_value}: {lost}/{closed} closed lost, fewer than "
                       f"{MIN_N}: too thin for a rate")
        return row
    loss_rate = lost / closed
    vs_team = loss_rate - team_loss_rate
    row["loss_rate"] = round(loss_rate, 4)
    row["vs_team_avg_pts"] = round(vs_team, 4)
    pts = round(abs(vs_team) * 100, 1)
    rel = (f"{pts} pts {'above' if vs_team > 0 else 'below'} the team's {team_loss_rate:.1%}"
           if pts else f"equal to the team's {team_loss_rate:.1%}")
    row["text"] = (f"{key_value}: {lost}/{closed} qualified closed lost "
                   f"({loss_rate:.1%} loss rate), {rel}")
    return row


def _rate_breakdown(deals: List[dict], key: str, team_loss_rate: Optional[float],
                    roles: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, int]] = {}
    for d in deals:
        k = d.get(key) or "Unknown"
        bucket = by_key.setdefault(k, {"won": 0, "lost": 0})
        bucket["won" if d.get("deal_status") == "won" else "lost"] += 1

    rows = [_rate_row(k, key, c["won"], c["lost"], team_loss_rate)
            for k, c in by_key.items()]
    if roles is not None:
        for r in rows:
            r["role"] = roles.get(str(r[key]).lower(), "unknown")
    # Sort by loss_rate descending (worst first); insufficient-volume rows
    # (loss_rate=None) sort last, never masquerading as "0% loss".
    rows.sort(key=lambda r: (r["loss_rate"] is None, -(r["loss_rate"] or 0)))
    return rows


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _join(parts: List[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def loss_rate_headline(qualified: Dict[str, int], closed: int, lost: int,
                       excluded: Dict[str, int], no_history_lost: int) -> str:
    """The two-figure loss-rate line, in code: the qualified rate first, the
    all-closed rate beside it with where the difference comes from, and the
    rate if every deal with no stage history had qualified."""
    qc, ql = qualified["closed"], qualified["lost"]
    if qc >= MIN_N:
        out = (f"Qualified loss rate: {ql / qc:.1%} ({ql} of {qc} closed Sales deals that reached "
               "Discovery or later before closing; deals closed as Disqualified are not counted).")
    else:
        out = (f"Qualified loss rate: not reported, only {qc} closed Sales deal"
               f"{'' if qc == 1 else 's'} reached Discovery or later (fewer than {MIN_N}).")
    parts = [p for n, p in (
        (excluded["disqualified_at_close"], f"{excluded['disqualified_at_close']} closed as Disqualified"),
        (excluded["never_reached_discovery"],
         f"{excluded['never_reached_discovery']} that closed without reaching Discovery"),
        (excluded["no_stage_history"], f"{excluded['no_stage_history']} with no stage history"),
        (excluded["renewal_pipeline"], _plural(excluded["renewal_pipeline"], "renewal", "renewals")),
    ) if n]
    out += f" All closed deals: {lost / closed:.1%} ({lost} of {closed})"
    out += ("; the difference is " + _join(parts) + ".") if parts else ", the same deals."
    nh = excluded["no_stage_history"]
    if nh and qc + nh >= MIN_N:
        who = ("If the 1 deal with no stage history had qualified" if nh == 1 else
               f"If all {nh} deals with no stage history had qualified")
        out += (f" {who}, the qualified rate would be {(ql + no_history_lost) / (qc + nh):.1%} "
                f"({ql + no_history_lost} of {qc + nh}).")
    return out


def _classify(deals: List[dict], snaps: Dict[str, List[tuple]], qualifying: set,
              disqualified: set) -> Dict[str, str]:
    """deal_id -> one of qualified / renewal_pipeline / disqualified_at_close /
    no_stage_history / never_reached_discovery. Only snapshots dated on or
    before the deal's close_date count ("before closing")."""
    out = {}
    for d in deals:
        did = str(d.get("deal_id"))
        if str(d.get("pipeline_id")) != SALES_PIPELINE:
            out[did] = "renewal_pipeline"
            continue
        if str(d.get("stage")) in disqualified:
            out[did] = "disqualified_at_close"
            continue
        close = str(d.get("close_date") or "")[:10]
        seen = [stage for day, stage in snaps.get(did, []) if str(day)[:10] <= close]
        if not seen:
            out[did] = "no_stage_history"
        elif any(stage in qualifying for stage in seen):
            out[did] = "qualified"
        else:
            out[did] = "never_reached_discovery"
    return out


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
         "won_incremental_arr": float, "won_arr_note": str, "note": str}
      or:
        {"status": "ok", "period": str,
         "closed_deal_count": int, "won_count": int, "lost_count": int,
         "qualified": {"closed", "won", "lost"},
         "qualified_loss_rate": float | None,   (the lead figure)
         "all_closed_loss_rate": float,
         "team_loss_rate": float | None,        (= qualified_loss_rate; rep
                                                 and segment rows compare to it)
         "excluded_from_qualified": {"renewal_pipeline",
             "disqualified_at_close", "never_reached_discovery",
             "no_stage_history"},
         "loss_rate_headline": str, "loss_rate_note": str,
         "by_rep": [...qualified rate rows, worst first, SDRs out...],
         "by_rep_excluded": [{"owner_email", "role", "closed_all",
                              "qualified_closed", "reason"}],
         "by_segment": [...qualified rate rows, worst first...],
         "stage_of_loss": {
             "by_bucket": {bucket: {"count", "pct"}, ...},
             "administrative_stage_share": {"count", "pct", "note"},
         },
         "ghost_deal_share": {"count", "pct", "note"},
         "won_incremental_arr": float, "won_arr_note": str,
         "min_n_floor": int,
         "note": str}
    """
    from field_semantics import stage_bucket
    from supabase_client import select_all
    from time_resolver import resolve_time_window
    from utils import get_pipeline_config
    from incremental_arr import incremental_arr

    if not time_window or "start" not in time_window or "end" not in time_window:
        time_window = resolve_time_window(time_window or {})
    tw_start, tw_end = time_window["start"], time_window["end"]
    tw_label = time_window.get("label", "")

    deals = select_all(sb, "deals",
        columns="deal_id,deal_status,deal_value,new_arr,expansion_arr,close_date,"
                "owner_email,segment,highest_stage_order_reached,pipeline_id,stage",
        filters=[("in_", "deal_status", ["won", "lost"]),
                 ("gte", "close_date", tw_start),
                 ("lte", "close_date", tw_end)])

    total_closed = len(deals)
    wins = [d for d in deals if d.get("deal_status") == "won"]
    losses = [d for d in deals if d.get("deal_status") == "lost"]
    # Verified by construction: wins/losses are a partition of the same
    # fetched row set (deal_status is in ("won","lost") by the filter
    # above, so every row lands in exactly one bucket) — no separate
    # "structured output" exists here to drift from the underlying data.
    won_count, lost_count = len(wins), len(losses)
    won_arr = sum(incremental_arr(d) for d in wins)
    won_renewals = sum(1 for d in wins if str(d.get("pipeline_id")) != SALES_PIPELINE)
    won_arr_note = (f"Closed-won incremental ARR (new_arr + expansion_arr) over the {won_count} won "
                    f"deal{'' if won_count == 1 else 's'} closed in {tw_label}, the same rows won_count "
                    "counts." + (f" Renewal revenue is not incremental ARR, so the "
                                 f"{_plural(won_renewals, 'won renewal counts', 'won renewals count')} "
                                 "only expansion ARR." if won_renewals else ""))

    if total_closed < MIN_N:
        return {
            "status": "insufficient_data",
            "reason": "too_few_closed_deals",
            "period": tw_label,
            "closed_deal_count": total_closed,
            "min_required": MIN_N,
            "won_count": won_count,
            "won_incremental_arr": won_arr,
            "won_arr_note": won_arr_note,
            "note": (f"Only {total_closed} closed deal(s) in {tw_label} — "
                     f"need at least {MIN_N} for a meaningful concentration "
                     f"breakdown."),
        }

    pipeline_config = get_pipeline_config()
    qualifying = set(discovery_or_later_stages(pipeline_config))
    disqualified = disqualified_stage_ids(pipeline_config)

    need = sorted({str(d["deal_id"]) for d in deals
                   if str(d.get("pipeline_id")) == SALES_PIPELINE
                   and str(d.get("stage")) not in disqualified})
    snaps: Dict[str, List[tuple]] = {}
    for i in range(0, len(need), _ID_CHUNK):
        for r in select_all(sb, "deals_snapshot", columns="deal_id,snapshot_date,stage_id",
                            filters=[("in_", "deal_id", need[i:i + _ID_CHUNK])]):
            snaps.setdefault(str(r["deal_id"]), []).append((r.get("snapshot_date"), str(r.get("stage_id"))))

    cls = _classify(deals, snaps, qualifying, disqualified)
    qual = [d for d in deals if cls[str(d["deal_id"])] == "qualified"]
    q_won = sum(1 for d in qual if d.get("deal_status") == "won")
    qualified = {"closed": len(qual), "won": q_won, "lost": len(qual) - q_won}
    excluded = {k: sum(1 for v in cls.values() if v == k)
                for k in ("renewal_pipeline", "disqualified_at_close",
                          "never_reached_discovery", "no_stage_history")}
    no_history_lost = sum(1 for d in losses if cls[str(d["deal_id"])] == "no_stage_history")
    q_rate = (qualified["lost"] / qualified["closed"]) if qualified["closed"] >= MIN_N else None
    all_rate = lost_count / total_closed

    personas = select_all(sb, "user_personas", columns="email,role")
    roles = {str(p.get("email") or "").lower(): (p.get("role") or "unknown") for p in personas}

    def _role(d):
        return roles.get(str(d.get("owner_email") or "").lower(), "unknown")

    rep_deals = [d for d in qual if _role(d) not in NON_CLOSING_ROLES]
    by_rep = _rate_breakdown(rep_deals, "owner_email", q_rate, roles)
    by_rep_excluded = []
    for owner in sorted({d.get("owner_email") for d in deals
                         if _role(d) in NON_CLOSING_ROLES and d.get("owner_email")}):
        by_rep_excluded.append({
            "owner_email": owner, "role": roles.get(owner.lower()),
            "closed_all": sum(1 for d in deals if d.get("owner_email") == owner),
            "qualified_closed": sum(1 for d in qual if d.get("owner_email") == owner),
            "reason": "SDR role; their qualified deals still count in the team rate",
        })
    by_segment = _rate_breakdown(qual, "segment", q_rate)

    # Stage-of-loss: canonical BUCKET mapping, not raw numeric order —
    # see module docstring decision #3.
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
                 "loss. Reported separately over every loss, like "
                 "stage_of_loss; by_rep/by_segment cover the qualified "
                 "population only."),
    }

    return {
        "status": "ok",
        "period": tw_label,
        "closed_deal_count": total_closed,
        "won_count": won_count,
        "lost_count": lost_count,
        "qualified": qualified,
        "qualified_loss_rate": round(q_rate, 4) if q_rate is not None else None,
        "all_closed_loss_rate": round(all_rate, 4),
        "team_loss_rate": round(q_rate, 4) if q_rate is not None else None,
        "excluded_from_qualified": excluded,
        "loss_rate_headline": loss_rate_headline(qualified, total_closed, lost_count,
                                                 excluded, no_history_lost),
        "loss_rate_note": (
            "Lead with the qualified loss rate; give the all-closed rate beside it, never alone. "
            "Qualified = Sales deals seen at Discovery through Awaiting Signature on or before "
            "close, not closed as Disqualified. Review does not count (config: a parking lot for "
            "stalled deals). Renewals are outside it. team_loss_rate is the qualified rate."),
        "by_rep": by_rep,
        "by_rep_excluded": by_rep_excluded,
        "by_segment": by_segment,
        "stage_of_loss": stage_of_loss,
        "ghost_deal_share": ghost_deal_share,
        "won_incremental_arr": won_arr,
        "won_arr_note": won_arr_note,
        "min_n_floor": MIN_N,
        "note": (f"by_rep/by_segment: qualified deals only, each rate against the team's "
                 f"qualified rate; SDR owners are in by_rep_excluded; rows under {MIN_N} closed "
                 "deals get no rate. stage_of_loss uses the canonical bucket mapping, not raw "
                 "highest_stage_order_reached (Review and Disqualified sit at order 8 and 9)."),
    }
