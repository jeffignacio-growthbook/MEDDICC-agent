#!/usr/bin/env python3
"""
Audit-only script: CRO Priority #5 (win/loss pattern reasoning) scoping.

READ-ONLY. No writes, no primitive design or build here.

Background: query_win_loss (api/handlers.py) already exists and reads
win_loss_narratives (confirmed real/populated, unlike the dead
deal_risks/pipeline_signals/competitive_signals tables). Reading its
source directly (this session, prior to this audit) shows it returns
RAW lists — narratives, wins, losses, win_count, loss_count, analyses —
with zero aggregation/pattern computation in code. Any "why are we
losing" / "which competitor do we lose to most" reasoning is left
entirely to the synthesis model eyeballing whatever raw rows came back.
This script checks the three things that determine whether building a
real pattern-computation primitive is worth it:

  1. DATA QUALITY: is win_loss_narratives' pattern-relevant data
     (competitor_mentioned, key_factors, stated_reason) populated
     widely enough to reason over, or is it hit by the same kind of
     hard ceiling as MEDDICC's 1.2% coverage / Fireflies' identity
     dead-end? Specifically checks deals.lost_reason blank rate
     FLEET-WIDE (not the one 19/19 EMEA sample), win_loss_narratives'
     OWN coverage of closed deals (it's generated in capped batches,
     not automatically for every close), and whether competitor_
     mentioned/key_factors are populated independently of stated_reason
     (they're LLM-derived from call transcripts + MEDDICC score
     history, per scripts/analytics/generate_win_loss.py's prompt —
     stated_reason is only ONE input, not the sole source, so a blank
     CRM lost_reason does not necessarily mean a blank narrative).
  2. WHAT'S ALREADY COMPUTABLE: actually computes competitor-mention
     frequency, key_factors frequency, and loss concentration by rep/
     segment from win_loss_narratives + deals, to prove (or disprove)
     that the raw material for pattern reasoning already exists and
     just isn't being aggregated in code today. Also checks the raw
     TYPE of key_factors as returned by the client (a real JSON array,
     or a double-encoded JSON string) — generate_win_loss.py writes it
     via json.dumps() into a jsonb column, which is a known way to
     accidentally store a STRING that looks like an array instead of a
     real one.
  3. REAL HISTORICAL DEMAND: searches query_cost_log, fallback_log,
     learning_log, and unanswered_queries for real past questions whose
     text suggests win/loss PATTERN reasoning (why/losing/competitor/
     compete/win rate/pattern), not just "show me lost deals" — same
     evidence standard as every other primitive audited tonight.

Needs SUPABASE_URL + SUPABASE_SERVICE_KEY.
"""
import json
import re
import sys
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

from db import get_supabase
from supabase_client import select_all

PATTERN_KEYWORDS = [
    "why are we losing", "why did we lose", "why we lost", "why we're losing",
    "causing our losses", "causing us to lose", "losing deals", "lose to",
    "lose most", "compete against", "competitor", "win rate", "win/loss",
    "win loss", "loss pattern", "losing pattern", "concentration",
]


def _try_parse_jsonish(value):
    """key_factors may be a real list (correctly stored jsonb array) or a
    string that IS json text (double-encoded via json.dumps() before
    insert) — try to normalize either into a Python list for counting,
    without assuming which shape it actually is."""
    if isinstance(value, list):
        return value, "list"
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed, "json-encoded-string"
        except Exception:
            pass
        return [value], "plain-string"
    return [], "empty"


def main():
    sb = get_supabase()

    print("=" * 100)
    print("STEP 1: population overview — closed deals vs win_loss_narratives coverage")
    print("=" * 100)
    closed_deals = select_all(sb, "deals",
        columns="deal_id,company_name,deal_status,deal_value,close_date,"
                "lost_reason,owner_email,segment,region,"
                "highest_stage_order_reached",
        filters=[("in_", "deal_status", ["won", "lost"])])
    lost_deals = [d for d in closed_deals if d.get("deal_status") == "lost"]
    won_deals = [d for d in closed_deals if d.get("deal_status") == "won"]
    print(f"Total closed deals (won+lost, all time): {len(closed_deals)}")
    print(f"  Won:  {len(won_deals)}")
    print(f"  Lost: {len(lost_deals)}")

    narratives = select_all(sb, "win_loss_narratives",
        columns="deal_id,company_name,outcome,stated_reason,narrative,"
                "key_factors,competitor_mentioned,generated_at")
    print(f"\nTotal win_loss_narratives rows: {len(narratives)}")
    closed_ids = {d["deal_id"] for d in closed_deals}
    narrative_ids = {n["deal_id"] for n in narratives}
    covered = closed_ids & narrative_ids
    print(f"Closed deals WITH a narrative: {len(covered)}/{len(closed_deals)} "
          f"({len(covered) / max(len(closed_deals), 1) * 100:.1f}%)"
          " — generate_win_loss.py runs in capped batches (default limit 25/run, "
          "cutoff at qualification_seeded_at unless --include-historical), so "
          "this is NOT automatic for every close.")

    print("\n" + "=" * 100)
    print("STEP 2: data quality — deals.lost_reason blank rate FLEET-WIDE")
    print("=" * 100)
    lost_with_reason = [d for d in lost_deals if (d.get("lost_reason") or "").strip()]
    blank_rate = (1 - len(lost_with_reason) / max(len(lost_deals), 1)) * 100
    print(f"Lost deals with a non-blank lost_reason: {len(lost_with_reason)}/{len(lost_deals)} "
          f"({100 - blank_rate:.1f}% populated, {blank_rate:.1f}% blank)")
    print("(Compare against the 19/19 blank finding from tonight's earlier EMEA-thread "
          "sample — this is the FULL fleet-wide denominator, not one thread's subset.)")

    print("\n" + "=" * 100)
    print("STEP 2b: win_loss_narratives' OWN pattern fields — populated independently "
          "of stated_reason?")
    print("=" * 100)
    lost_narratives = [n for n in narratives if n.get("outcome") == "lost"]
    n_total = len(lost_narratives) or 1
    n_stated = sum(1 for n in lost_narratives if (n.get("stated_reason") or "").strip())
    n_competitor = sum(1 for n in lost_narratives if (n.get("competitor_mentioned") or "").strip())
    n_narrative_text = sum(1 for n in lost_narratives if (n.get("narrative") or "").strip())

    key_factor_counts = []
    key_factor_shapes = Counter()
    for n in lost_narratives:
        parsed, shape = _try_parse_jsonish(n.get("key_factors"))
        key_factor_shapes[shape] += 1
        key_factor_counts.append(len(parsed))
    n_with_factors = sum(1 for c in key_factor_counts if c > 0)

    print(f"Lost-outcome narratives: {len(lost_narratives)}")
    print(f"  stated_reason populated:      {n_stated}/{len(lost_narratives)} "
          f"({n_stated / n_total * 100:.1f}%)  <- should mirror deals.lost_reason "
          f"(copied verbatim at generation time)")
    print(f"  competitor_mentioned populated: {n_competitor}/{len(lost_narratives)} "
          f"({n_competitor / n_total * 100:.1f}%)  <- LLM-derived from call transcripts "
          f"+ MEDDICC history, NOT solely from stated_reason")
    print(f"  narrative text populated:      {n_narrative_text}/{len(lost_narratives)} "
          f"({n_narrative_text / n_total * 100:.1f}%)")
    print(f"  key_factors non-empty:         {n_with_factors}/{len(lost_narratives)} "
          f"({n_with_factors / n_total * 100:.1f}%)")
    print(f"  key_factors raw shape as returned by the client: {dict(key_factor_shapes)}")
    if key_factor_shapes.get("json-encoded-string"):
        print("  >>> key_factors is being stored/returned as a JSON-encoded STRING, "
              "not a native array — generate_win_loss.py's json.dumps() before "
              ".upsert() into a jsonb column double-encodes it. Any code treating "
              "it as a list directly (without json.loads() first) will misbehave.")

    print("\n" + "=" * 100)
    print("STEP 3: proving pattern computation IS possible today (or isn't)")
    print("=" * 100)
    deal_by_id = {d["deal_id"]: d for d in closed_deals}

    competitor_counts = Counter(
        n["competitor_mentioned"].strip() for n in lost_narratives
        if (n.get("competitor_mentioned") or "").strip())
    print(f"\nCompetitor-mention frequency (from {n_competitor} populated rows):")
    for comp, ct in competitor_counts.most_common(10):
        print(f"  {comp:30s} {ct}")
    if not competitor_counts:
        print("  (none — competitor_mentioned is empty across all sampled lost narratives)")

    factor_counter = Counter()
    for n in lost_narratives:
        parsed, _ = _try_parse_jsonish(n.get("key_factors"))
        for f in parsed:
            if isinstance(f, str) and f.strip():
                factor_counter[f.strip()] += 1
    print(f"\nTop raw key_factors strings (not yet normalized/clustered, "
          f"{sum(factor_counter.values())} total mentions):")
    for factor, ct in factor_counter.most_common(10):
        print(f"  ({ct}x) {factor}")

    rep_loss_counts = Counter()
    segment_loss_counts = Counter()
    for n in lost_narratives:
        d = deal_by_id.get(n["deal_id"])
        if not d:
            continue
        if d.get("owner_email"):
            rep_loss_counts[d["owner_email"]] += 1
        if d.get("segment"):
            segment_loss_counts[d["segment"]] += 1
    print(f"\nLoss concentration by rep (join win_loss_narratives.deal_id -> deals.owner_email):")
    for rep, ct in rep_loss_counts.most_common(10):
        print(f"  {rep:35s} {ct}")
    print(f"\nLoss concentration by segment:")
    for seg, ct in segment_loss_counts.most_common(10):
        print(f"  {seg:20s} {ct}")

    stage_loss_counts = Counter()
    for d in lost_deals:
        stage_loss_counts[d.get("highest_stage_order_reached")] += 1
    print(f"\nStage-of-loss clustering (deals.highest_stage_order_reached, ALL lost deals, "
          f"n={len(lost_deals)}):")
    for stage, ct in sorted(stage_loss_counts.items(), key=lambda x: (x[0] is None, x[0])):
        print(f"  stage_order={stage!r:6}  {ct} deals")

    print("\n" + "=" * 100)
    print("STEP 4: real historical demand — searching cost/fallback/learning/unanswered logs")
    print("=" * 100)
    for table, cols in [
        ("query_cost_log", "question,outcome,reason_tag,answered,created_at"),
        ("fallback_log", "question,trigger,fast_path_attempted,answered,created_at"),
        ("learning_log", "question,handler_used,issue_type,logged_at"),
        ("unanswered_queries", "question,reason,asked_at"),
    ]:
        try:
            rows = select_all(sb, table, columns=cols)
        except Exception as e:
            print(f"\n[{table}] could not read ({type(e).__name__}: {e}) — "
                  f"table may not exist or migration not applied")
            continue
        matches = [r for r in rows
                   if any(kw in (r.get("question") or "").lower() for kw in PATTERN_KEYWORDS)]
        print(f"\n[{table}] {len(rows)} total rows, {len(matches)} match win/loss "
              f"pattern-style keywords")
        for m in matches[:15]:
            extra = {k: v for k, v in m.items() if k != "question"}
            print(f"    Q: {m.get('question')!r}")
            print(f"       {extra}")

    print("\nDONE")


if __name__ == "__main__":
    main()
