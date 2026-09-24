#!/usr/bin/env python3
"""
COMMIT tag vs close date: flag active deals tagged COMMIT whose close_date
is missing or outside the current quarter.

A COMMIT tag says the deal closes this quarter; the close date says when
it closes. When they disagree, one of the two is wrong. FY2027 Q2's commit
cohort walk (scripts/analytics/commit_cohort_walk.py) found the biggest
dollar miss was exactly this: a $960,000 renewal tagged COMMIT for 8 weeks
against its own 2026-12-12 close date. It is a hygiene flag, not a risk
signal: of the 5 Q2 deals the rule catches, 2 closed won inside the quarter
(their close dates were simply wrong).

Pure check: api/commit_close_date.commit_close_date_mismatches(). Shown in
query_pipeline's answer (like zero_arr_deals) and in assess_forecast_trust's,
whose own COMMIT query filters on close_date and so never saw these deals.

Fixtures are real:
  - tests/fixtures/commit_close_date_fy2027_q2_snapshots.json: every
    FY2027 Q2 deals_snapshot row tagged COMMIT (162 rows, 30 deals), run
    week by week: exactly the 5 deals the cohort walk found;
  - tests/fixtures/commit_close_date_live_2026_09_24.json: today's 9 active
    COMMIT deals, all closing in FY2027 Q3: flags none.
"""
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

try:
    from api.commit_close_date import commit_close_date_mismatches  # noqa: E402
except ImportError:            # pre-fix: the tests fail, not the import
    commit_close_date_mismatches = None

FIX = REPO / "tests" / "fixtures"
Q2 = json.loads((FIX / "commit_close_date_fy2027_q2_snapshots.json").read_text())
LIVE = json.loads((FIX / "commit_close_date_live_2026_09_24.json").read_text())


def test_fy2027_q2_flags_exactly_the_five_deals_week_by_week():
    q = Q2["quarter"]
    by_week = defaultdict(list)
    for r in Q2["rows"]:
        by_week[r["week_of_quarter"]].append(r)
    flagged = defaultdict(list)
    checked = 0
    for week in sorted(by_week):
        res = commit_close_date_mismatches(by_week[week], q["start"], q["end"], q["label"])
        checked += res["checked"]
        for d in res["deals"]:
            flagged[d["company_name"]].append(week)
        assert res["count"] == len(res["deals"]) <= 10
    assert checked == 162, checked
    assert dict(flagged) == {
        "StarHub": [7, 8, 9, 10, 11],
        "Anthropic": [5, 6, 7, 8, 9, 10, 11, 12],
        "Extra Space Storage": [11, 12],
        "Taxfix": [13],
        "Trade Me": [13],
    }, dict(flagged)
    wk7 = commit_close_date_mismatches(by_week[7], q["start"], q["end"], q["label"])
    assert [d["company_name"] for d in wk7["deals"]] == ["Anthropic", "StarHub"], "largest first"
    assert wk7["deals"][0]["reason"] == "after_quarter" and wk7["total_value"] == 860000 + 40000
    print("✓ real FY2027 Q2 COMMIT snapshots (162 rows, week by week): flags exactly Anthropic "
          "(weeks 5-12), StarHub (7-11), Extra Space Storage (11-12), Taxfix and Trade Me (13); "
          "largest first")


def test_todays_live_commit_set_flags_nothing():
    q = LIVE["quarter"]
    res = commit_close_date_mismatches(LIVE["deals"], q["start"], q["end"], q["label"])
    assert (res["checked"], res["count"], res["deals"]) == (9, 0, []), res
    print("✓ today's 9 live active COMMIT deals, all closing in FY2027 Q3: 0 flagged")


def test_reasons_boundaries_and_scope():
    def d(i, close, fc="COMMIT", status="active", value=1000):
        return {"deal_id": i, "company_name": i, "close_date": close, "forecast_category": fc,
                "deal_status": status, "deal_value": value, "pipeline_id": "default"}
    deals = [
        d("start", "2026-08-01"), d("end", "2026-10-31"),               # boundaries are inside
        d("before", "2026-07-31", value=3000), d("after", "2026-11-01", value=2000),
        d("none", None, value=500), d("lower", "2027-01-15", fc="commit", value=100),
        d("ml", "2027-01-15", fc="MOST_LIKELY"), d("won", "2027-01-15", status="won"),
    ]
    res = commit_close_date_mismatches(deals, date(2026, 8, 1), date(2026, 10, 31), "FY2027 Q3")
    assert res["checked"] == 6, res                       # active COMMIT only, any case
    assert [(x["deal_id"], x["reason"]) for x in res["deals"]] == [
        ("before", "before_quarter"), ("after", "after_quarter"),
        ("none", "no_close_date"), ("lower", "after_quarter")], res["deals"]
    assert res["by_reason"] == {"before_quarter": 1, "after_quarter": 2, "no_close_date": 1}
    assert "FY2027 Q3 (2026-08-01 to 2026-10-31)" in res["note"]
    assert "not a risk signal" in res["note"]
    print("✓ quarter boundaries count as inside; before / after / missing close dates flagged; "
          "only active COMMIT deals (any case) checked; ISO strings or dates accepted")


def test_query_pipeline_answer_carries_the_flag():
    import test_query_pipeline_note_and_entities as qp
    import test_zero_arr_deal_counting as za
    base = dict(za.DEALS[0])
    deals = [dict(base, deal_id="OK", forecast_category="COMMIT", close_date="2026-09-30"),
             dict(base, deal_id="BAD", company_name="Mis-dated", forecast_category="COMMIT",
                  close_date="2026-12-12", deal_value=960000),
             dict(base, deal_id="ML", forecast_category="MOST_LIKELY", close_date="2026-12-12")]
    # the strict fake (tests/strict_supabase.py) returns only the selected
    # columns, like Postgres: a query that forgets forecast_category or
    # deal_status flags nothing
    r = qp._run({}, deals)
    flag = r.get("commit_close_date_mismatch")
    assert flag and flag["count"] == 1 and flag["deals"][0]["deal_id"] == "BAD", flag
    assert flag["checked"] == 2
    note = r["_synthesis_note"]
    assert "COMMIT CLOSE DATES" in note and "commit_close_date_mismatch" in note, note[-600:]
    print("✓ query_pipeline: an active COMMIT deal closing 2026-12-12 is flagged in "
          "commit_close_date_mismatch, and the synthesis note says how to report it")


def test_forecast_trust_answer_carries_the_flag():
    import forecast_trust
    from strict_supabase import StrictSupabase

    def deal(i, cat, close, inc):
        return {"deal_id": i, "company_name": i, "forecast_category": cat, "deal_status": "active",
                "close_date": close, "deal_value": inc, "pipeline_id": "default", "stage": "24682892",
                "create_date": "2026-05-01", "segment": "SMB", "new_arr": inc, "expansion_arr": None}
    rows = [deal("BAD", "COMMIT", "2026-12-12", 960000),     # COMMIT, closes after Q3
            deal("OK", "COMMIT", "2026-09-30", 40000),       # COMMIT, closes in Q3
            deal("ML", "MOST_LIKELY", "2026-12-12", 10000)]  # not COMMIT: never flagged

    def run(sb, as_of=date(2026, 9, 24)):                    # week 8 of FY2027 Q3
        with patch("deal_risk_assessor.assess_deal_risk",
                   return_value={"assessed_deals": [], "summary": {"total_assessed": 0}}), \
             patch("forecast_analyses.query_commit_ml_calibration_by_week",
                   return_value={"by_week": {}}):
            return forecast_trust.assess_forecast_trust(sb, as_of=as_of)

    # strict fake (tests/strict_supabase.py): the real filters apply, so the
    # cohort query itself shows what the flag exists for
    sb = StrictSupabase({"deals": rows})
    r = run(sb)
    assert r["pipeline"]["deal_count"] == 1, r["pipeline"]        # the cohort sees OK only
    flag = r.get("commit_close_date_mismatch")
    assert flag and flag["count"] == 1 and flag["deals"][0]["deal_id"] == "BAD", flag
    assert flag["deals"][0]["reason"] == "after_quarter" and flag["checked"] == 2, flag
    deals_q = [q for q in sb.queries if q["table"] == "deals"]
    cats = [f[2] for f in deals_q[0]["filters"] if f[:2] == ("in", "forecast_category")]
    assert cats == [forecast_trust.CATEGORIES], deals_q[0]            # cohort first, COMMIT + ML
    assert not any(f[1] == "close_date" for f in deals_q[1]["filters"]), deals_q[1]

    # the hygiene query failing leaves the trust result intact, flag None
    class Flaky(StrictSupabase):
        n = 0
        def table(self, name):
            Flaky.n += 1
            if Flaky.n == 2:
                raise RuntimeError("network")
            return super().table(name)
    f = run(Flaky({"deals": rows}))
    assert f["status"] == "ok" and f["commit_close_date_mismatch"] is None, f

    # below week 3 the gate is a hard stop: no queries, so no flag
    class NoQuery:
        def table(self, name):
            raise AssertionError("gate must not query")
    g = forecast_trust.assess_forecast_trust(NoQuery(), as_of=date(2026, 8, 5))
    assert g["status"] == "insufficient_data" and "commit_close_date_mismatch" not in g, g
    print("✓ assess_forecast_trust (week 3+), on the strict fake: its close-date-filtered cohort "
          "sees only the in-quarter COMMIT deal; the mis-dated one is surfaced in "
          "commit_close_date_mismatch (MOST_LIKELY never flagged); a failed hygiene query is "
          "contained; below week 3 the gate still makes no queries")


if __name__ == "__main__":
    test_fy2027_q2_flags_exactly_the_five_deals_week_by_week()
    test_todays_live_commit_set_flags_nothing()
    test_reasons_boundaries_and_scope()
    test_query_pipeline_answer_carries_the_flag()
    test_forecast_trust_answer_carries_the_flag()
    print("\n✅ All tests passed")
