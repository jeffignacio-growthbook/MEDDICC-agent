#!/usr/bin/env python3
"""
Bookings seasonality: how much of a quarter's closed-won ARR is usually in
by this point, so a pace read (share of target won vs share of the quarter
gone) isn't called ahead or behind on a straight-line assumption.

For each of the last 8 complete fiscal quarters: closed-won incremental ARR
(new + expansion) in the quarter, the share of it closed by the same
fraction of the quarter as today (day round(f x quarter days), f = days
elapsed / days in this quarter, today counted), and the share closed in its
last 7 days.

Live history (won deals 2024-08-01..2026-10-31, captured read-only
2026-09-25), as of 2026-09-25 (day 56 of 92):

  quarter      won ARR       by this point  final week
  FY2025 Q3      243,712          69.8%        0.0%
  FY2025 Q4      330,635          28.3%       56.9%
  FY2026 Q1      122,715          62.7%       37.3%
  FY2026 Q2      648,969          31.5%       29.1%
  FY2026 Q3      711,017           7.6%       37.5%
  FY2026 Q4    1,694,721          71.3%        7.8%
  FY2027 Q1      981,455          47.7%       41.0%
  FY2027 Q2    1,935,321          21.0%       48.9%
  median 39.6% (range 7.6%-71.3%); final-week median 37.4%

Back-loaded on the median (40% in by 61% of the way through), and far too
uneven to call a quarter ahead or behind from pace alone.
"""
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "api"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from strict_supabase import StrictSupabase  # noqa: E402

FX = json.loads((REPO / "tests" / "fixtures" / "coverage_and_pace_2026_09_25.json").read_text())
AS_OF = date(2026, 9, 25)
EXPECT = [("FY2025 Q3", 243712.47, 0.6982, 0.0), ("FY2025 Q4", 330634.97, 0.2832, 0.5686),
          ("FY2026 Q1", 122715.24, 0.6272, 0.3728), ("FY2026 Q2", 648968.81, 0.3147, 0.2910),
          ("FY2026 Q3", 711016.88, 0.0762, 0.3748), ("FY2026 Q4", 1694721.07, 0.7127, 0.0784),
          ("FY2027 Q1", 981454.76, 0.4773, 0.4097), ("FY2027 Q2", 1935320.58, 0.2102, 0.4890)]


def run(rows=None, as_of=AS_OF):
    from bookings_seasonality import assess_bookings_seasonality
    sb = StrictSupabase({"deals": rows if rows is not None else FX["won_history"]})
    return assess_bookings_seasonality(sb, as_of=as_of), sb


def test_live_history():
    r, sb = run()
    assert r["status"] == "ok" and (r["days_elapsed"], r["days_in_quarter"]) == (56, 92), r
    got = [(q["quarter"], round(q["won_arr"], 2), round(q["share_by_this_point"], 4),
            round(q["share_final_week"], 4)) for q in r["quarters"]]
    assert got == EXPECT, got
    assert (round(r["median_share_by_this_point"], 4), round(r["min_share_by_this_point"], 4),
            round(r["max_share_by_this_point"], 4)) == (0.3960, 0.0762, 0.7127), r
    assert round(r["median_share_final_week"], 4) == 0.3738
    f = [x for q in sb.queries if q["table"] == "deals" for x in q["filters"]]
    assert any(x[0] == "eq" and x[1] == "deal_status" for x in f) and \
        any(x[0] == "lt" and x[1] == "close_date" and x[2] == "2026-08-01" for x in f), f
    print("✓ last 8 complete quarters: by this point 7.6%-71.3% (median 39.6%) of the quarter's "
          "closed-won ARR was in; final week median 37.4%; this quarter's own deals not read")


def test_too_few_quarters_is_stated():
    rows = [w for w in FX["won_history"] if w["close_date"] >= "2026-02-01"]
    r, _ = run(rows)
    assert r["status"] == "insufficient_data" and r["quarters_with_bookings"] == 2 and r["reason"], r
    print("✓ fewer than 4 quarters with bookings: insufficient_data with the reason, no median")


if __name__ == "__main__":
    test_live_history()
    test_too_few_quarters_is_stated()
    print("\n✅ All tests passed")
