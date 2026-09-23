"""
Realistic return shapes for the canary regression test — one per
unified-routing handler plus the dynamic_query primitive fallback.

Key sets and list sizes mirror each handler's real success return in
api/handlers.py (see the line refs). Sizes are chosen to match what the
handler really produces on a normal quarter, NOT minimal toy payloads:
a canary that only survives a 2-row fixture proves nothing about the
narrowing points (row sampling, character truncation) that only trigger
on real-sized results.
"""

STAGES = ["Discovery", "Scoping", "Technical Evaluation", "Proposal",
          "Negotiation", "Closed Won"]
OWNERS = ["dan@growthbook.io", "jake@growthbook.io", "scott.keller@growthbook.io",
          "james.shannon@growthbook.io", "christian@growthbook.io", "marcel@growthbook.io"]


def _deal(i, **extra):
    row = {
        "deal_id": str(40000 + i),
        "company_name": f"Company{i}",
        "stage": STAGES[i % len(STAGES)],
        "owner_email": OWNERS[i % len(OWNERS)],
        "close_date": f"2026-{8 + i % 3:02d}-{1 + i % 28:02d}",
    }
    row.update(extra)
    return row


# api/handlers.py:2812 — deals is top 20; by_stage/by_owner are dicts.
QUERY_PIPELINE = {
    "total_deals": 64,
    "total_pipeline": 2_410_000,
    "q3_scoped_pipeline": 1_180_000,
    "q3_scoped_deals": 31,
    "quarterly_target": 1_550_000,
    "coverage_ratio": 0.76,
    "current_quarter": "FY2027 Q3",
    "zero_arr_deals": {"count": 4, "total_value": 0, "note": "4 deals have no ARR"},
    "uncategorized_deals": {"count": 1, "total_value": 12000, "note": "1 deal has no stage"},
    "by_stage": {s: {"count": 10 + i, "value": 300_000 + i * 50_000} for i, s in enumerate(STAGES)},
    "by_owner": {o: {"count": 8 + i, "value": 200_000 + i * 40_000} for i, o in enumerate(OWNERS)},
    "deals": [_deal(i, incremental_arr=90_000 - i * 3000, expansion_arr=40_000,
                    new_arr=50_000 - i * 3000, deal_value=90_000 - i * 3000)
              for i in range(20)],
    "filters_applied": {"pipeline": "all", "owner": None},
    "_synthesis_note": "Pipeline = expansion_arr + new_arr.",
    "business_definition_note": "Renewal base excluded.",
}

# api/handlers.py:5631 — view="movement": top-level "rows" (up to 200) plus
# by_stage with unbounded id lists, totals and summary.
QUERY_PIPELINE_MOVEMENT = {
    "view": "movement",
    "fiscal_quarter": "FY2027 Q3",
    "scope": "all pipelines",
    "scope_statement": "All open new-business and expansion deals.",
    "basis": "deals_snapshot weekly",
    "query_stats": {"snapshots_read": 8, "rows_read": 480},
    "snapshot_dates": ["2026-08-04", "2026-09-22"],
    "by_stage": [
        {"stage": s, "count": 12, "entered": 3, "exited": 2,
         "deal_ids": [str(40000 + j) for j in range(i * 12, i * 12 + 12)],
         "entered_from_other_stage_ids": [str(40000 + j) for j in range(i * 3, i * 3 + 3)],
         "new_to_pipeline_ids": [str(41000 + j) for j in range(i * 2, i * 2 + 2)],
         "exited_ids": [str(42000 + j) for j in range(i * 2, i * 2 + 2)]}
        for i, s in enumerate(STAGES)
    ],
    "totals": {"start_count": 58, "end_count": 64},
    "summary": {"new_to_pipeline": 12, "left_pipeline": 6, "moved_between_stages": 18,
                "added_arr_total": 610_000, "exited_arr_total": 190_000,
                "net_arr_change": 420_000},
    "confidence": "high",
    "current_position": {"as_of": "2026-09-22"},
    "rows": [_deal(i, week_of_quarter=1 + i % 13, backfill_confidence="high")
             for i in range(64)],
    "data_gaps": [],
}

# api/handlers.py:3593 — stale_deals is unbounded.
QUERY_STALE_DEALS = {
    "stale_deals": [_deal(i, deal_value=60_000 - i * 1000, days_since_activity=21 + i,
                          is_past_close_date=i % 4 == 0, overall_score=30 + i % 20)
                    for i in range(25)],
    "past_close_date_count": 7,
    "stale_count": 25,
    "total_stale_pipeline": 1_200_000,
    "stale_threshold_days": 21,
}

# api/handlers.py:802 — waterfall rows are weekly; cache_payload holds all deals.
QUERY_WATERFALL = {
    "pipeline_summary": {
        "total_open_arr": 2_410_000,
        "total_open_count": 64,
        "population_statement": "64 open deals across all pipelines.",
        "by_stage": [{"stage_name": s, "count": 10, "arr": 400_000} for s in STAGES],
        "needs_attention": {"no_arr_count": 4, "no_arr_deals": [f"Company{i}" for i in range(4)],
                            "at_risk_count": 5,
                            "at_risk_deals": [{"company": f"Company{i}", "risk": "stale"} for i in range(5)]},
    },
    "waterfall": [{"week_ending": f"2026-{8 + w // 5:02d}-{1 + (w * 7) % 28:02d}",
                   "pipeline_id": "default", "new_pipeline_value": 120_000,
                   "won_value": 30_000, "lost_value": 10_000, "net_change": 80_000,
                   "pulled_in_value": 5_000, "pushed_out_value": 15_000,
                   "deals_qualified_count": 4}
                  for w in range(8)],
    "period": {"label": "FY2027 Q3", "start": "2026-08-01", "end": "2026-10-31"},
    "report_shape": "weekly",
    "cache_payload": {"deals": [_deal(i, deal_value=40_000, arr_usd=40_000,
                                      segment="Enterprise", deal_status="open")
                                for i in range(64)]},
}

# api/handlers.py:2999 — deals holds ALL of a rep's active deals.
QUERY_REP_PIPELINE = {
    "owner_email": "cary@growthbook.io",
    "owner_name": "Cary",
    "resolution_note": "Resolved 'Cary' to cary@growthbook.io",
    "period": {"label": "current"},
    "deals": [_deal(i, deal_value=50_000 + i * 1000, overall_score=40 + i % 25,
                    champion_score=5, forecast_category="pipeline",
                    owner_email="cary@growthbook.io")
              for i in range(30)],
    "summary": {"total_deals": 30, "total_pipeline": 1_935_000,
                "avg_deal_value": 64_500, "no_value_count": 0},
    "data_gap": False,
}

# api/handlers.py:1178 — wins/losses/narratives unbounded, analyses ≤ 20.
QUERY_WIN_LOSS = {
    "narratives": [{"company_name": f"Company{i}", "outcome": "won" if i % 2 else "lost",
                    "stated_reason": "pricing", "competitor_mentioned": "Statsig",
                    "key_factors": ["champion", "timeline"],
                    "narrative": "Champion drove the evaluation through security review.",
                    "generated_at": "2026-09-01"} for i in range(12)],
    "wins": [_deal(i, deal_value=70_000, deal_status="won", lost_reason=None,
                   segment="Enterprise") for i in range(15)],
    "losses": [_deal(100 + i, deal_value=55_000, deal_status="lost",
                     lost_reason="went with competitor", segment="Mid-Market")
               for i in range(15)],
    "win_count": 15,
    "loss_count": 15,
    "analyses": [{"deal_id": str(40000 + i), "overall_score": 50} for i in range(20)],
    "period": {"label": "FY2027 Q2"},
    "has_narratives": True,
    "data_quality_note": "12 of 30 closed deals have generated narratives.",
}

# api/handlers.py:894 — top 10.
QUERY_DEALS_AT_RISK = {
    "deals_at_risk": [_deal(i, overall_score=20 + i, risk_level="high",
                            risk_factors=["no champion", "stale 30d"])
                      for i in range(10)],
    "total_at_risk": 14,
}


def filter_table_result(n_rows: int) -> dict:
    """filter_table's real shape is {"rows", "table"}; the canary stands in
    for any extra computed key a primitive (or a future wrapper) adds."""
    return {
        "rows": [_deal(i, new_arr=30_000, expansion_arr=10_000, region="EMEA",
                       segment="Enterprise") for i in range(n_rows)],
        "table": "deals",
    }


# (label, question, tool_name, tool_params, fixture)
CASES = [
    ("query_pipeline", "what does our current pipeline look like by stage?",
     "query_pipeline", {}, QUERY_PIPELINE),
    ("query_pipeline_movement", "how has pipeline moved between stages since the start of the quarter?",
     "query_pipeline_movement", {"view": "movement", "fiscal_quarter": "FY2027 Q3"},
     QUERY_PIPELINE_MOVEMENT),
    ("query_stale_deals", "which deals have gone stale?",
     "query_stale_deals", {}, QUERY_STALE_DEALS),
    ("query_waterfall", "show me the pipeline waterfall",
     "query_waterfall", {}, QUERY_WATERFALL),
    ("query_rep_pipeline", "what's in Cary's pipeline?",
     "query_rep_pipeline", {"owner_email": "cary@growthbook.io"}, QUERY_REP_PIPELINE),
    ("query_win_loss", "why did we win and lose deals last quarter?",
     "query_win_loss", {}, QUERY_WIN_LOSS),
    ("query_deals_at_risk", "which deals are at risk?",
     "query_deals_at_risk", {}, QUERY_DEALS_AT_RISK),
    ("dynamic_query:filter_table(10 rows)", "list the deals in EMEA",
     "filter_table", {"table": "deals", "columns": ["deal_id", "company_name"],
                      "filters": [["eq", "region", "EMEA"]]},
     filter_table_result(10)),
    ("dynamic_query:filter_table(60 rows)", "list the deals in EMEA",
     "filter_table", {"table": "deals", "columns": ["deal_id", "company_name"],
                      "filters": [["eq", "region", "EMEA"]]},
     filter_table_result(60)),
]
