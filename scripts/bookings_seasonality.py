#!/usr/bin/env python3
"""
Bookings seasonality: how much of a quarter's closed-won ARR is usually in
by this point in the quarter.

Quarter health states pace as the share of the quarter gone against the
share of target won. A straight-line reading of that (61% of the quarter
gone, so 61% of target should be won) assumes bookings arrive evenly. This
measures whether they do, on this business's own history, so pace is never
called ahead or behind on that assumption.

For each of the last N_QUARTERS complete fiscal quarters: closed-won
incremental ARR (new_arr + expansion_arr, incremental_arr()), the share of
it closed by the same fraction of the quarter as today (day
round(f x that quarter's days), f = days elapsed / days in this quarter,
today counted), and the share closed in its last 7 days. Fewer than
MIN_QUARTERS quarters with any bookings: insufficient_data, no median.

On live data (2026-09-25, day 56 of 92) the last 8 quarters had 7.6% to
71.3% (median 39.6%) of their closed-won ARR in by this point and a median
37.4% in the final week: back-loaded and uneven.

Read-only. One query: won deals closed in those quarters.
"""
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "api"))

N_QUARTERS = 8
MIN_QUARTERS = 4
FINAL_WEEK_DAYS = 7


def assess_bookings_seasonality(sb, as_of: Optional[date] = None) -> Dict[str, Any]:
    from incremental_arr import incremental_arr
    from supabase_client import select_all
    from utils import get_fiscal_quarter

    if as_of is None:
        from sdr_utils import today_in_reporting_tz
        as_of = today_in_reporting_tz()
    q_start, q_end, label = get_fiscal_quarter(as_of)
    days_in_quarter = (q_end - q_start).days + 1
    days_elapsed = min(max((as_of - q_start).days + 1, 0), days_in_quarter)
    fraction = days_elapsed / days_in_quarter

    quarters, cursor = [], q_start
    for _ in range(N_QUARTERS):
        s, e, lab = get_fiscal_quarter(cursor - timedelta(days=1))
        quarters.append((s, e, lab))
        cursor = s
    quarters.reverse()

    rows = select_all(sb, "deals", columns="deal_id,close_date,new_arr,expansion_arr",
                      filters=[("eq", "deal_status", "won"),
                               ("gte", "close_date", quarters[0][0].isoformat()),
                               ("lt", "close_date", q_start.isoformat())])

    out = []
    for s, e, lab in quarters:
        n = (e - s).days + 1
        cut = (s + timedelta(days=max(round(fraction * n), 1) - 1)).isoformat()
        fw = (e - timedelta(days=FINAL_WEEK_DAYS - 1)).isoformat()
        inq = [r for r in rows if s.isoformat() <= str(r.get("close_date"))[:10] <= e.isoformat()]
        total = sum(incremental_arr(r) for r in inq)
        if not total:
            continue
        out.append({
            "quarter": lab, "won_deals": len(inq), "won_arr": total,
            "share_by_this_point": sum(incremental_arr(r) for r in inq
                                       if str(r.get("close_date"))[:10] <= cut) / total,
            "share_final_week": sum(incremental_arr(r) for r in inq
                                    if str(r.get("close_date"))[:10] >= fw) / total,
        })

    base = {"fiscal_quarter": label, "days_elapsed": days_elapsed,
            "days_in_quarter": days_in_quarter, "quarters": out,
            "quarters_with_bookings": len(out)}
    if len(out) < MIN_QUARTERS:
        return {"status": "insufficient_data", **base,
                "reason": (f"only {len(out)} of the last {N_QUARTERS} complete quarters have "
                           f"closed-won ARR (need {MIN_QUARTERS}): no seasonality read")}
    by, fw = [q["share_by_this_point"] for q in out], [q["share_final_week"] for q in out]
    return {
        "status": "ok", **base,
        "median_share_by_this_point": statistics.median(by),
        "min_share_by_this_point": min(by), "max_share_by_this_point": max(by),
        "median_share_final_week": statistics.median(fw),
        "min_share_final_week": min(fw), "max_share_final_week": max(fw),
        "note": (f"Share of each of the last {len(out)} complete quarters' closed-won incremental "
                 f"ARR closed by day {days_elapsed} of {days_in_quarter} (scaled to that quarter's "
                 f"length), and in its last {FINAL_WEEK_DAYS} days. This quarter's own deals are "
                 "not part of it."),
    }
