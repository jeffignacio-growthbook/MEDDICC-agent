#!/usr/bin/env python3
"""
scripts/analytics/qualification_crossing_walk.py: Meeting Set -> qualified
crossings on the Sales pipeline, walked to their outcome.

Synthetic rows:
  - CLEAN: Meeting Set for three weeks, then Discovery the next week (pinned), won;
  - GAP: Meeting Set, a 14-day hole, then Scoping (ambiguous, still counted), lost;
  - REVIEW: Meeting Set then Review (decisionmakerboughtin, stage_order 8), lost;
    counted by stage_id even though its order sorts it after the closed stages;
  - OPEN: crossing, deal still active (listed, never in the rate);
  - LOST2: crossing, lost;
  - FIRST_QUAL: first seen at Discovery, later a Meeting Set row, then Scoping:
    not a crossing (first seen already qualified), though it is in the
    "ever at Meeting Set" denominator;
  - NEVER_MS / NULL_FIRST / CLOSED_ONLY: never at Meeting Set, so the crossing
    is not observable: first known stage Discovery; a null-stage row then
    Scoping (first known stage qualified); a lone closedlost row (other);
  - STUCK: Meeting Set, never crosses (in the conversion denominator only);
  - QUAL_BEFORE_MS_ONLY: at Meeting Set only after a qualified row, never after it;
  - RENEWAL: renewal-pipeline rows, Upcoming Renewal -> Renewal Engaged: ignored;
  - EDGE7 / EDGE8: previous snapshot exactly 7 days / 8 days before the crossing.
Also: the rate excludes open deals, the conversion figure's denominator is
deals ever at Meeting Set, and the report states N beside every percentage.
"""
import re
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO / "scripts"))

import qualification_crossing_walk as qc  # noqa: E402

MS = "79653122"
D0 = date(2026, 1, 5)
RENEWAL = "866608541"


def _day(n):
    return (D0 + timedelta(days=n)).isoformat()


def _rows(deal_id, days_stages, pipe="default", src="backfilled", conf="exact"):
    return [{"deal_id": deal_id, "snapshot_date": _day(d), "stage_id": st, "pipeline_id": pipe,
             "snapshot_source": src, "backfill_confidence": conf} for d, st in days_stages]


def _deal(deal_id, status, close=None):
    return {"deal_id": deal_id, "deal_status": status, "close_date": close,
            "company_name": f"Co {deal_id}"}


SNAPS = (
    _rows("CLEAN", [(0, MS), (7, MS), (14, MS), (21, "appointmentscheduled"), (28, "qualifiedtobuy")])
    + _rows("GAP", [(0, MS), (14, "qualifiedtobuy")])
    + _rows("REVIEW", [(0, MS), (7, "decisionmakerboughtin")])
    + _rows("OPEN", [(0, MS), (7, "presentationscheduled")], src="prospective", conf=None)
    + _rows("LOST2", [(0, MS), (7, "24682892")])
    + _rows("FIRST_QUAL", [(0, "appointmentscheduled"), (7, MS), (14, "qualifiedtobuy")])
    + _rows("STUCK", [(0, MS), (7, MS), (14, MS)])
    + _rows("NEVER_MS", [(0, "appointmentscheduled"), (7, "qualifiedtobuy")])
    + _rows("NULL_FIRST", [(0, None), (7, "qualifiedtobuy")], conf="pre_history")
    + _rows("CLOSED_ONLY", [(0, "closedlost")])
    + _rows("RENEWAL", [(0, "1297321618"), (7, "1297321619")], pipe=RENEWAL)
    + _rows("RENEW_MS", [(0, MS), (7, "appointmentscheduled")], pipe=RENEWAL)
    + _rows("EDGE7", [(0, MS), (7, "43449439")])
    + _rows("EDGE8", [(0, MS), (8, "43449439")])
)
DEALS = [
    _deal("CLEAN", "won", _day(61)), _deal("GAP", "lost", _day(44)), _deal("REVIEW", "lost", _day(37)),
    _deal("OPEN", "active"), _deal("LOST2", "lost", _day(20)), _deal("FIRST_QUAL", "won", _day(30)),
    _deal("STUCK", "active"), _deal("NEVER_MS", "won", _day(40)),
    _deal("NULL_FIRST", "lost", _day(40)), _deal("CLOSED_ONLY", "lost", _day(1)), _deal("RENEWAL", "won"), _deal("RENEW_MS", "won"),
    _deal("EDGE7", "won", _day(50)), _deal("EDGE8", "lost", _day(50)),
]


def _run():
    return qc.walk(SNAPS, DEALS)


def test_qualified_set_from_config():
    import yaml
    cfg = yaml.safe_load((REPO / "config" / "client.yaml").read_text())
    got = qc.qualified_stages_from_config(cfg)
    assert got == set(qc.QUALIFIED_STAGES), got
    assert "decisionmakerboughtin" in got and "closedwon" not in got and "68509551" not in got
    print("✓ qualified set from config/client.yaml equals the fixed list (Review in, closed/DQ out)")


def test_crossings_classified():
    r = _run()
    cross = {c["deal_id"]: c for c in r["crossings"]}
    assert set(cross) == {"CLEAN", "GAP", "REVIEW", "OPEN", "LOST2", "EDGE7", "EDGE8"}, set(cross)
    assert cross["CLEAN"]["crossing_date"] == _day(21) and cross["CLEAN"]["prev_date"] == _day(14)
    assert cross["CLEAN"]["crossing_stage"] == "appointmentscheduled"
    assert cross["REVIEW"]["crossing_stage"] == "decisionmakerboughtin"
    assert "FIRST_QUAL" not in cross and "STUCK" not in cross
    assert not {"NEVER_MS", "NULL_FIRST", "CLOSED_ONLY"} & set(cross)
    assert "RENEWAL" not in cross and "RENEW_MS" not in cross
    print("✓ crossings: clean, gap, Review-by-stage_id, open, lost, edges; "
          "first-seen-qualified, stuck and renewal excluded")


def test_pin_threshold():
    cross = {c["deal_id"]: c for c in _run()["crossings"]}
    assert cross["EDGE7"]["pinned"] is True and cross["EDGE7"]["gap_days"] == 7
    assert cross["EDGE8"]["pinned"] is False and cross["EDGE8"]["gap_days"] == 8
    assert cross["GAP"]["pinned"] is False and cross["CLEAN"]["pinned"] is True
    s = _run()["summary"]
    assert (s["pinned"], s["ambiguous"]) == (5, 2), s
    print("✓ pin threshold: 7 days pinned, 8 days ambiguous; 5 pinned / 2 ambiguous")


def test_population_counts():
    s = _run()["summary"]
    # ever at Meeting Set on the Sales pipeline: all but RENEWAL/RENEW_MS; FIRST_QUAL has a MS row
    assert s["ever_meeting_set"] == 9, s
    assert s["deals_seen"] == 12, s                          # renewal rows ignored
    assert s["never_meeting_set"] == 3, s                    # NEVER_MS, NULL_FIRST, CLOSED_ONLY
    assert s["never_ms_first_known"] == {"qualified": 2, "other": 1, "no_stage": 0}, s
    assert s["ever_meeting_set"] + s["never_meeting_set"] == s["deals_seen"]
    assert s["first_seen_qualified_later_ms"] == 1, s        # FIRST_QUAL
    assert s["crossers"] == 7
    print("✓ populations: 9 ever at Meeting Set, 3 never (crossing not observable; 2 first known "
          "qualified, 1 other), 1 first-seen-qualified with a later MS row, 7 crossers, renewal ignored")


def test_rate_excludes_open():
    s = _run()["summary"]
    assert (s["won"], s["lost"], s["resolved"], s["open"]) == (2, 4, 6, 1), s
    assert [d["deal_id"] for d in s["open_deals"]] == ["OPEN"]
    assert s["won"] + s["lost"] == s["resolved"] and s["resolved"] + s["open"] == s["crossers"]
    print("✓ win rate: 2 won of 6 resolved; the 1 open crosser listed separately, not folded in")


def test_conversion_denominator():
    s = _run()["summary"]
    assert (s["conversion"]["crossers"], s["conversion"]["of"]) == (7, 9), s["conversion"]
    print("✓ conversion: 7 crossers of 9 deals ever at Meeting Set")


def test_sources_around_crossing():
    s = _run()["summary"]
    assert s["sources"] == {"backfilled/exact -> backfilled/exact": 6,
                            "prospective/null -> prospective/null": 1}, s["sources"]
    print("✓ snapshot source/confidence tallied for the two snapshots around each crossing")


def test_report_states_n():
    r = _run()
    text = qc.report(r) + "\n" + qc.detail(r)
    for m in re.finditer(r"\d+%", text):
        window = text[max(0, m.start() - 60):m.start()]
        assert re.search(r"\d+ (\w+ )?of \d+", window), f"bare percentage: ...{window}{m.group()}"
    assert "2 won of 6 resolved" in text, text
    assert "7 of 9 deals ever seen at Meeting Set" in text, text
    assert "1 still open" in text and "not in the rate" in text, text
    assert "ever crossed so far" in text
    assert "2 ambiguous" in text and "5 pinned" in text
    assert "Never seen at Meeting Set: 3 of 12 deals" in text, text
    assert "1 deal(s) first seen at a qualified stage later show a Meeting Set row" in text, text
    assert "Co OPEN" in text
    # no quarter split: "quarter" appears only in the hygiene note's PhonePe example
    assert "quarter" not in text.lower().split("note on crm hygiene")[0], text
    print("✓ report: N beside every percentage; open listed; ambiguous counted; no quarter split")


if __name__ == "__main__":
    test_qualified_set_from_config()
    test_crossings_classified()
    test_pin_threshold()
    test_population_counts()
    test_rate_excludes_open()
    test_conversion_denominator()
    test_sources_around_crossing()
    test_report_states_n()
    print("\n✅ All tests passed")
