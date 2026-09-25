#!/usr/bin/env python3
"""
scripts/analytics/commit_cohort_walk.py: the quarter's COMMIT cohort, walked
to its outcome.

Synthetic rows shaped like the live FY2027 Q2 cases:
  - a lost deal whose close_date predates the quarter while stage history
    says it was lost inside it (PhonePe);
  - a won deal that left the snapshots weeks before its close_date
    (Inditex): stage history places it;
  - a won deal with no stage history whose close_date and snapshot exit
    disagree across quarter end: ambiguous, excluded from both rates;
  - a deal missing from `deals`: ambiguous;
  - a won-after-quarter deal, a reopened deal, still-open deals.
Also: the two framings keep their own denominators (still-open never folded
into the eventual win rate), and the report states N on every rate.
"""
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO / "scripts"))

import commit_cohort_walk as cw  # noqa: E402

Q_START, Q_END = date(2026, 5, 1), date(2026, 7, 31)
DATES = [date(2026, 5, 4).fromordinal(date(2026, 5, 4).toordinal() + 7 * i).isoformat() for i in range(13)]
RENEWAL = "866608541"


def _snaps(deal_id, weeks, commit_weeks, value=10000, close="2026-07-15", pipe="default"):
    return [{"deal_id": deal_id, "snapshot_date": DATES[w - 1], "week_of_quarter": w,
             "forecast_category": "COMMIT" if w in commit_weeks else "BEST_CASE",
             "deal_value": value, "close_date": close, "pipeline_id": pipe,
             "stage_id": "x", "deal_status": "active"} for w in weeks]


def _deal(deal_id, stage, close, value=10000, pipe="default"):
    return {"deal_id": deal_id, "company_name": f"Co {deal_id}", "stage": stage,
            "close_date": close, "pipeline_id": pipe, "deal_value": value}


SNAPS = (
    _snaps("LOST_HIST", range(1, 13), range(1, 13), 97600, "2026-07-09", RENEWAL)   # PhonePe
    + _snaps("WON_EARLY_EXIT", range(1, 5), [4], 120000, "2026-07-12", RENEWAL)      # Inditex
    + _snaps("WON_NOHIST", range(1, 8), [5, 6, 7], 30000)                            # clean, close_date only
    + _snaps("AMBIG", range(1, 6), [3, 4, 5], 50000)                                 # left wk6, close after Q
    + _snaps("MISSING", range(1, 14), [2, 3], 5000)
    + _snaps("WON_LATER", range(1, 14), range(3, 14), 70000, "2026-08-20")
    + _snaps("REOPENED", range(1, 14), [3], 20000)
    + _snaps("OPEN", range(1, 14), [3, 4], 80000, "2026-10-31")
    + _snaps("LATE_TAG", [12, 13], [13], 60000, "2026-07-31")
    + _snaps("NEVER", range(1, 14), [], 99999)                                       # not in cohort
)
DEALS = [
    _deal("LOST_HIST", "1297321624", "2026-04-01", 97600, RENEWAL),
    _deal("WON_EARLY_EXIT", "1297321623", "2026-07-11", 115200, RENEWAL),
    _deal("WON_NOHIST", "closedwon", "2026-06-17", 30000),
    _deal("AMBIG", "closedwon", "2026-08-10", 50000),
    _deal("WON_LATER", "closedwon", "2026-08-20", 72000),
    _deal("REOPENED", "closedwon", "2026-09-02", 20000),
    _deal("OPEN", "24682892", "2026-10-31", 80000),
    _deal("LATE_TAG", "closedwon", "2026-07-31", 60000),
    _deal("NEVER", "closedwon", "2026-06-01", 99999),
]
HIST = [
    ["LOST_HIST", "2026-06-22T15:00:00+00:00", "1297321619"],
    ["LOST_HIST", "2026-07-20T16:41:12+00:00", "1297321624"],
    ["WON_EARLY_EXIT", "2026-05-26T12:56:48+00:00", "1297321623"],
    ["WON_LATER", "2026-08-19T10:00:00+00:00", "closedwon"],
    ["REOPENED", "2026-07-10T10:00:00+00:00", "closedwon"],        # won in Q ...
    ["REOPENED", "2026-07-12T10:00:00+00:00", "24682892"],         # ... reopened ...
    ["REOPENED", "2026-09-02T10:00:00+00:00", "closedwon"],        # ... won after Q
]


def _walk(**kw):
    return cw.walk(SNAPS, DATES, DEALS, HIST, [], Q_START, Q_END, [RENEWAL], **kw)


def _by_id(res):
    return {r["deal_id"]: r for r in res["rows"]}


def test_buckets_and_outcome_dates():
    r = _by_id(_walk())
    assert "NEVER" not in r, "a deal never tagged COMMIT is not in the cohort"
    got = {k: v["bucket"] for k, v in r.items()}
    assert got == {"LOST_HIST": "LOST", "WON_EARLY_EXIT": "WON_IN_QUARTER",
                   "WON_NOHIST": "WON_IN_QUARTER", "AMBIG": None, "MISSING": None,
                   "WON_LATER": "WON_LATER", "REOPENED": "WON_LATER",
                   "OPEN": "STILL_OPEN", "LATE_TAG": "WON_IN_QUARTER"}, got
    assert (r["LOST_HIST"]["outcome_date"], r["LOST_HIST"]["lost_timing"]) == ("2026-07-20", "in_quarter")
    assert r["WON_EARLY_EXIT"]["outcome_date"] == "2026-05-26"
    assert r["WON_EARLY_EXIT"]["outcome_date_source"] == "stage_history"
    assert r["REOPENED"]["outcome_date"] == "2026-09-02", "the last entry into won counts, not the first"
    assert r["WON_NOHIST"]["outcome_date_source"] == "close_date"
    print("✓ four buckets: lost-in-quarter by stage history despite a pre-quarter close_date; "
          "won with an early snapshot exit placed by history; won later; reopened then won later; "
          "still open; never-COMMIT deals excluded")


def test_ambiguity_is_detected_and_explained():
    r = _by_id(_walk())
    assert r["MISSING"]["ambiguous"] == "not in deals", r["MISSING"]
    assert "different sides of quarter end" in r["AMBIG"]["ambiguous"], r["AMBIG"]
    assert r["WON_NOHIST"]["ambiguous"] is None, "close_date and snapshot exit agree: not ambiguous"
    assert any("can't confirm" in f for f in r["LATE_TAG"]["flags"]), r["LATE_TAG"]["flags"]
    assert r["LATE_TAG"]["ambiguous"] is None
    lost_flags = " ".join(r["LOST_HIST"]["flags"])
    assert "2026-04-01 (before the quarter) disagrees with stage history (lost 2026-07-20, in it)" in lost_flags
    assert not any(f.startswith("lost ") for f in r["LOST_HIST"]["flags"]), "the outcome itself is in-quarter"
    print("✓ ambiguous: missing from deals; no history with close_date and snapshot exit across "
          "quarter end. Flagged only: close_date vs history disagreement, close_date-only "
          "outcome still open in the last snapshot")


def test_two_framings_keep_their_own_denominators():
    s = _walk()["summary"]["all"]
    assert s["n"] == 9 and s["ambiguous"] == 2
    h, e = s["in_quarter_hit"], s["eventual_win"]
    assert (h["won"], h["of"]) == (3, 9), h
    assert (e["won"], e["of_resolved"], e["still_open"]) == (5, 6, 1), e
    assert h["committed_value_won"] == 120000 + 30000 + 60000, h
    assert h["won_value"] == 115200 + 30000 + 60000, h
    assert e["committed_value_open"] == 80000 and e["committed_value_resolved"] == 97600 + 120000 + 30000 + 70000 + 20000 + 60000
    ren = _walk()["summary"]["renewal"]
    assert ren["n"] == 2 and ren["buckets"]["LOST"]["n"] == 1
    print("✓ in-quarter hit rate = 3 of N=9 (ambiguous stay in N); eventual win = 5 of 6 resolved, "
          "1 still open reported beside it; committed and won dollars per framing; renewal split")


def test_anchor_week_cohort():
    ids = sorted(_by_id(_walk(anchor_week=3)))
    assert ids == ["AMBIG", "LOST_HIST", "MISSING", "OPEN", "REOPENED", "WON_LATER"], ids
    print("✓ COMMIT-at-week-3 cohort: only deals tagged COMMIT in week 3's snapshot")


def test_report_states_n_on_every_rate():
    text = cw.report("Ever COMMIT", _walk()["summary"]["all"])
    assert "N = 9 deals" in text
    for line in text.splitlines():
        for m in re.finditer(r"\((\d+)%\)", line):
            before = line[:m.start()]
            assert re.search(r"\d+ of \d+", before) or re.search(r"\$[\d,]+ of \$[\d,]+", before), line
    assert "Small sample: N = 9" in text
    print("✓ report: every percentage sits next to its 'x of N' count; small-sample warning states N")


def test_headlines_lead_with_the_three_findings():
    rows = _walk()["rows"]
    h = cw.headlines(rows, last_week=13)
    assert (h["lost"], h["n"]) == (1, 9), h
    # OPEN's committed close_date (2026-10-31) sits outside the quarter in both COMMIT weeks;
    # WON_LATER's (2026-08-20) in all eleven; LATE_TAG's 2026-07-31 is inside
    got = [(c["deal_id"], c["weeks"]) for c in h["close_outside"]]
    assert got == [("OPEN", [3, 4]), ("WON_LATER", list(range(3, 14)))], got
    assert (h["late_wins"], h["wins"], h["late_from_week"]) == (1, 3, 11), h
    text = cw.headline_text(h)
    assert text.startswith("1. Lost outright: 1 of 9") and "\n2. COMMIT against a close date outside" in text
    assert "Largest: Co OPEN ($80,000), 2 COMMIT week(s) [3, 4], now STILL_OPEN" in text, text
    assert "3. Late tags: 1 of 3 in-quarter wins" in text
    # boundary: a win first tagged in week 11 is late, week 10 is not; a late-tagged
    # deal that did not win is not a late WIN
    def row(fw, bucket):
        return {"first_commit_week": fw, "bucket": bucket, "committed_value": 1.0,
                "commit_weeks_close_outside": [], "deal_id": str(fw), "company_name": "x"}
    edge = cw.headlines([row(10, "WON_IN_QUARTER"), row(11, "WON_IN_QUARTER"),
                         row(12, "STILL_OPEN"), row(13, "LOST")], last_week=13)
    assert (edge["late_wins"], edge["wins"]) == (1, 2), edge
    print("✓ headlines: lost outright 1 of 9; COMMIT against an out-of-quarter close date "
          "(largest first, weeks listed); late-tagged wins 1 of 3 in weeks 11-13")


def test_unknown_deal_value_is_excluded_and_counted_never_zero_filled():
    """eval_reconstruction (Pre-Merge Gate Tests) flagged two `deal_value or
    0` sites here: a snapshot row with no value history reconstructs to
    None (Phase 2b), and 0-filling it re-fabricates the number inside a
    dollar total. An unknown committed value (last COMMIT snapshot) or won
    value (deals row) now stays None: out of every dollar figure,
    numerator and denominator alike, and counted; deal counts unchanged."""
    snaps = SNAPS + _snaps("NULLV", range(1, 14), [3], None) + _snaps("NULLWON", range(1, 8), [4], 40000)
    deals = DEALS + [_deal("NULLV", "closedlost", "2026-06-01", None),
                     _deal("NULLWON", "closedwon", "2026-06-10", None)]
    res = cw.walk(snaps, DATES, deals, HIST, [], Q_START, Q_END, [RENEWAL])
    r = _by_id(res)
    assert r["NULLV"]["committed_value"] is None and r["NULLV"]["bucket"] == "LOST", r["NULLV"]
    assert r["NULLWON"]["won_value"] is None and r["NULLWON"]["committed_value"] == 40000, r["NULLWON"]
    s, base = res["summary"]["all"], _walk()["summary"]["all"]
    assert s["n"] == 11 and s["committed_value"] == base["committed_value"] + 40000, s
    assert s["value_unknown"] == {"committed": 1, "won": 1}, s.get("value_unknown")
    h = s["in_quarter_hit"]
    assert (h["won"], h["of"]) == (4, 11), h                        # counts include both
    assert h["committed_value_won"] == base["in_quarter_hit"]["committed_value_won"] + 40000
    assert h["won_value"] == base["in_quarter_hit"]["won_value"], "an unknown won value adds nothing"
    assert s["buckets"]["LOST"]["committed_value"] == base["buckets"]["LOST"]["committed_value"]
    text = cw.report("Ever COMMIT", s)
    assert "1 committed value and 1 won value unknown" in text, text
    assert "unknown" in cw.detail(res["rows"])
    hl = cw.headlines(res["rows"], last_week=13)
    assert hl["lost_value"] == base["buckets"]["LOST"]["committed_value"] and hl["lost_value_unknown"] == 1
    assert "1 with no value" in cw.headline_text(hl)
    print("✓ unknown deal_value: None, excluded from every dollar total and counted "
          "(1 committed, 1 won); deal counts and the known dollars unchanged")


if __name__ == "__main__":
    test_unknown_deal_value_is_excluded_and_counted_never_zero_filled()
    test_buckets_and_outcome_dates()
    test_ambiguity_is_detected_and_explained()
    test_two_framings_keep_their_own_denominators()
    test_anchor_week_cohort()
    test_report_states_n_on_every_rate()
    test_headlines_lead_with_the_three_findings()
    print("\n✅ All tests passed")
