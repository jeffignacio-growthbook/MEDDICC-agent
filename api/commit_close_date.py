"""
COMMIT tag vs close date: active deals tagged COMMIT whose close_date is
missing or outside the current quarter.

A COMMIT tag says the deal closes this quarter; the close date says when it
closes. When they disagree, one of the two is wrong, and the deal drops out of
every close-date-scoped figure for the quarter (assess_forecast_trust's COMMIT
cohort, query_pipeline's this-quarter total) while still being called a commit.

Found by the FY2027 Q2 commit cohort walk (scripts/analytics/commit_cohort_walk.py):
the biggest dollar miss was a $960,000 renewal tagged COMMIT for 8 weeks
against its own 2026-12-12 close date. It is a hygiene flag, not a risk
signal: 2 of the 5 Q2 deals this rule catches closed won inside the quarter,
their close dates were just wrong.
"""
from datetime import date

REASONS = ("before_quarter", "after_quarter", "no_close_date")


def _iso(v):
    return v.isoformat() if isinstance(v, date) else str(v)[:10]


def commit_close_date_mismatches(deals, q_start, q_end, quarter_label=None, limit=10):
    """Check active COMMIT deals against the quarter [q_start, q_end] (inclusive).

    deals: dicts with deal_id, company_name, forecast_category, deal_status,
    close_date, deal_value, pipeline_id. Other deals are ignored.
    q_start / q_end: dates or ISO strings.

    Returns {"checked", "count", "total_value", "by_reason", "deals" (largest
    deal_value first, at most `limit`), "note"}.
    """
    start, end = _iso(q_start), _iso(q_end)
    commits = [d for d in deals
               if str(d.get("forecast_category") or "").upper() == "COMMIT"
               and str(d.get("deal_status") or "").lower() == "active"]
    flagged = []
    for d in commits:
        close = str(d["close_date"])[:10] if d.get("close_date") else None
        if close is None:
            reason = "no_close_date"
        elif close < start:
            reason = "before_quarter"
        elif close > end:
            reason = "after_quarter"
        else:
            continue
        flagged.append({"deal_id": d.get("deal_id"), "company_name": d.get("company_name"),
                        "close_date": close, "reason": reason,
                        "deal_value": d.get("deal_value") or 0,
                        "pipeline_id": d.get("pipeline_id")})
    flagged.sort(key=lambda x: -(x["deal_value"] or 0))
    label = f"{quarter_label} ({start} to {end})" if quarter_label else f"{start} to {end}"
    return {
        "checked": len(commits),
        "count": len(flagged),
        "total_value": sum(x["deal_value"] or 0 for x in flagged),
        "by_reason": {r: n for r in REASONS if (n := sum(x["reason"] == r for x in flagged))},
        "deals": flagged[:limit],
        "note": (f"Active deals tagged COMMIT whose close_date is missing or outside {label}. "
                 "The tag says this quarter, the close date says otherwise, so one of the two "
                 "is wrong and the deal is left out of this quarter's close-date-scoped figures. "
                 "Hygiene flag, not a risk signal: report it as 'N COMMIT deal(s) have a close "
                 "date outside this quarter', naming each deal and its close date; say nothing "
                 "when the count is 0. total_value is HubSpot deal_value."),
    }
