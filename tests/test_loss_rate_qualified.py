#!/usr/bin/env python3
"""
query_loss_concentration leads with the QUALIFIED loss rate.

The live FY2027 Q3 answer (2026-09-25) said "92.4% loss rate": 109 of 118
closed deals. That counts every closed deal, including 52 closed as
Disqualified (inbound leads that never qualified) and deals that never got
past Meeting Set. It is not a loss rate anyone manages to.

Qualified population (the same stage boundary as
scripts/analytics/qualification_crossing_walk.py, with Review left out):
  - Sales pipeline ('default') only;
  - seen in deals_snapshot, on or before its close_date, at a stage the
    config marks qualified and in progression: order >= the pipeline's
    qualified_stage_order, not won/lost, not exclude_from_analysis. That is
    Discovery, Scoping, Technical Evaluation, Negotiating, Awaiting
    Signature. Review is out: config calls it a parking lot for
    stalled/dead deals, not progression, and the live snapshots show 5
    deals that went Meeting Set -> Review without ever reaching Discovery;
  - not closed as Disqualified (stage 68509551 at close), whatever it
    reached first.
A Sales deal with no snapshot history can't be placed: it is counted as
no_stage_history, never guessed into or out of the rate, and the headline
gives the rate if all of them had qualified.

Both rates, always: the qualified rate first, the all-closed rate beside
it with where the difference comes from.

by_rep / by_segment use the qualified population too (a BDR's
disqualified inbound leads read as a "100% loss rate" otherwise), and an
owner whose user_personas role is 'sdr' is kept out of the rep table and
listed in by_rep_excluded (their deals still count in the team rate).

Real numbers: tests/fixtures/loss_concentration_fy2027_q3_2026_09_25.json,
captured read-only from live Supabase on 2026-09-25 (md5 of the capture
582ee52f67ddae5923b9c6297f5af668).
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "api"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import loss_concentration as lc  # noqa: E402
from strict_supabase import StrictSupabase  # noqa: E402

FIXTURE = json.loads((REPO / "tests" / "fixtures" /
                      "loss_concentration_fy2027_q3_2026_09_25.json").read_text())
TW = {"start": "2026-08-01", "end": "2026-10-31", "label": "FY2027 Q3"}
SDR = "jake.stangl@growthbook.io"

REAL_HEADLINE = (
    "Qualified loss rate: 77.8% (28 of 36 closed Sales deals that reached Discovery or later "
    "before closing; deals closed as Disqualified are not counted). All closed deals: 92.4% "
    "(109 of 118); the difference is 52 closed as Disqualified, 17 that closed without reaching "
    "Discovery, 3 with no stage history and 10 renewals. If all 3 deals with no stage history "
    "had qualified, the qualified rate would be 79.5% (31 of 39)."
)


def fixture_tables():
    cols = FIXTURE["deals_snapshot_columns"]
    return {"deals": FIXTURE["deals"],
            "deals_snapshot": [dict(zip(cols, r)) for r in FIXTURE["deals_snapshot"]],
            "user_personas": FIXTURE["user_personas"]}


def real_result():
    return lc.assess_loss_concentration(StrictSupabase(fixture_tables()), time_window=TW)


def test_stage_boundary_comes_from_config():
    assert lc.discovery_or_later_stages() == (
        "appointmentscheduled", "qualifiedtobuy", "presentationscheduled", "24682892", "43449439")
    assert lc.disqualified_stage_ids() == {"68509551"}
    print("✓ Discovery-or-later = Discovery..Awaiting Signature from config (Review, Meeting Set, "
          "closed stages out); Disqualified = 68509551")


def test_real_quarter_both_rates():
    r = real_result()
    assert r["status"] == "ok"
    assert (r["closed_deal_count"], r["won_count"], r["lost_count"]) == (118, 9, 109)
    assert r["all_closed_loss_rate"] == 0.9237
    assert r["qualified"] == {"closed": 36, "won": 8, "lost": 28}, r["qualified"]
    assert r["qualified_loss_rate"] == 0.7778 and r["team_loss_rate"] == 0.7778
    assert r["excluded_from_qualified"] == {"renewal_pipeline": 10, "disqualified_at_close": 52,
                                            "never_reached_discovery": 17, "no_stage_history": 3}, \
        r["excluded_from_qualified"]
    assert r["loss_rate_headline"] == REAL_HEADLINE, r["loss_rate_headline"]
    assert "qualified" in r["loss_rate_note"] and "Review does not count" in r["loss_rate_note"]
    print("✓ FY2027 Q3 (live capture): qualified 77.8% (28/36), all closed 92.4% (109/118); "
          "52 Disqualified, 17 never reached Discovery, 3 no history, 10 renewals")


def test_real_rep_table_is_qualified_and_has_no_sdr():
    r = real_result()
    reps = {row["owner_email"]: row for row in r["by_rep"]}
    assert set(reps) == {"cary@growthbook.io", "christian@growthbook.io", "dan@growthbook.io",
                         "jake@growthbook.io", "james.shannon@growthbook.io",
                         "marcel@growthbook.io", "scott.keller@growthbook.io"}, set(reps)
    assert SDR not in reps
    assert sum(row["closed"] for row in r["by_rep"]) == 36
    c = reps["christian@growthbook.io"]
    assert (c["won"], c["lost"], c["loss_rate"], c["role"]) == (0, 14, 1.0, "ae"), c
    assert abs(c["vs_team_avg_pts"] - (1.0 - 0.7778)) < 1e-9
    d = reps["dan@growthbook.io"]
    assert (d["won"], d["lost"], d["loss_rate"]) == (2, 4, 0.6667), d
    assert reps["cary@growthbook.io"]["insufficient_volume"] is True
    ex = {e["owner_email"]: e for e in r["by_rep_excluded"]}
    assert ex[SDR]["role"] == "sdr" and ex[SDR]["closed_all"] == 21 and ex[SDR]["qualified_closed"] == 0
    assert sum(row["closed"] for row in r["by_segment"]) == 36
    print("✓ rep table: 7 AEs over the 36 qualified deals (Christian 14/14, Dan 4/6); the SDR's "
          "21 Disqualified inbound leads are out of it and listed as excluded")


def test_real_won_arr_comes_from_the_same_rows():
    r = real_result()
    assert r["won_incremental_arr"] == 373400.0, r["won_incremental_arr"]
    assert "incremental ARR" in r["won_arr_note"] and "1 won renewal" in r["won_arr_note"]
    print("✓ closed-won incremental ARR $373,400 from the same 9 won rows (1 renewal at $0)")


# ------------------------------------------------------------- boundaries

def _d(i, status, stage, owner="ae@x.io", pipeline="default", close="2026-09-15", **kw):
    row = {"deal_id": i, "deal_status": status, "deal_value": 1000, "new_arr": 1000,
           "expansion_arr": None, "close_date": close, "owner_email": owner, "segment": "SMB",
           "highest_stage_order_reached": 7, "pipeline_id": pipeline, "stage": stage}
    row.update(kw)
    return row


def _run(deals, snaps, personas=()):
    sb = StrictSupabase({"deals": deals,
                         "deals_snapshot": [{"deal_id": a, "snapshot_date": b, "stage_id": c}
                                            for a, b, c in snaps],
                         "user_personas": list(personas)})
    return lc.assess_loss_concentration(sb, time_window=TW)


# Five qualified closes so the qualified slice clears MIN_N.
BASE = [_d(f"q{i}", "lost" if i < 3 else "won", "closedlost" if i < 3 else "closedwon")
        for i in range(5)]
BASE_SNAPS = [(f"q{i}", "2026-08-10", "presentationscheduled") for i in range(5)]


def test_review_is_not_reaching_discovery():
    r = _run(BASE + [_d("rv", "lost", "closedlost")],
             BASE_SNAPS + [("rv", "2026-08-01", "79653122"), ("rv", "2026-08-20", "decisionmakerboughtin")])
    assert r["qualified"]["closed"] == 5 and r["excluded_from_qualified"]["never_reached_discovery"] == 1
    print("✓ Meeting Set -> Review -> Closed Lost is not a qualified loss")


def test_discovery_seen_only_after_close_does_not_count():
    r = _run(BASE + [_d("late", "lost", "closedlost", close="2026-09-01")],
             BASE_SNAPS + [("late", "2026-08-15", "79653122"), ("late", "2026-09-05", "appointmentscheduled")])
    assert r["excluded_from_qualified"]["never_reached_discovery"] == 1 and r["qualified"]["closed"] == 5
    print("✓ a Discovery snapshot dated after close_date does not qualify the deal")


def test_disqualified_after_negotiating_is_excluded():
    r = _run(BASE + [_d("dq", "lost", "68509551")], BASE_SNAPS + [("dq", "2026-08-12", "24682892")])
    assert r["excluded_from_qualified"]["disqualified_at_close"] == 1 and r["qualified"]["lost"] == 3
    print("✓ closed as Disqualified is excluded even after reaching Negotiating")


def test_no_history_counted_not_guessed_and_renewals_out():
    r = _run(BASE + [_d("nh", "lost", "closedlost"), _d("rn", "lost", "1297321624", pipeline="866608541")],
             BASE_SNAPS)
    ex = r["excluded_from_qualified"]
    assert (ex["no_stage_history"], ex["renewal_pipeline"]) == (1, 1) and r["qualified"]["closed"] == 5
    assert "If the 1 deal with no stage history had qualified, the qualified rate would be 66.7% (4 of 6)." \
        in r["loss_rate_headline"], r["loss_rate_headline"]
    print("✓ no stage history: counted separately with the if-qualified rate; renewals out")


def test_sdr_owned_qualified_deal_counts_for_team_not_rep_table():
    deals = BASE + [_d(f"s{i}", "lost", "closedlost", owner="bdr@x.io") for i in range(5)]
    snaps = BASE_SNAPS + [(f"s{i}", "2026-08-10", "appointmentscheduled") for i in range(5)]
    r = _run(deals, snaps, personas=[{"email": "bdr@x.io", "role": "sdr"},
                                     {"email": "ae@x.io", "role": "ae"}])
    assert r["qualified"] == {"closed": 10, "won": 2, "lost": 8}
    assert "bdr@x.io" not in {x["owner_email"] for x in r["by_rep"]}
    assert r["by_rep_excluded"][0]["owner_email"] == "bdr@x.io" and r["by_rep_excluded"][0]["qualified_closed"] == 5
    print("✓ an SDR-owned qualified loss counts in the team rate, not in the rep table")


def test_too_few_qualified_states_it_instead_of_a_rate():
    r = _run(BASE[:2] + [_d(f"dq{i}", "lost", "68509551") for i in range(5)], BASE_SNAPS[:2])
    assert r["status"] == "ok" and r["qualified_loss_rate"] is None and r["team_loss_rate"] is None
    assert r["loss_rate_headline"].startswith(
        "Qualified loss rate: not reported, only 2 closed Sales deals reached Discovery or later "
        f"(fewer than {lc.MIN_N})."), r["loss_rate_headline"]
    print("✓ fewer than MIN_N qualified closes: no qualified rate, said so; the raw rate still given")


if __name__ == "__main__":
    test_stage_boundary_comes_from_config()
    test_real_quarter_both_rates()
    test_real_rep_table_is_qualified_and_has_no_sdr()
    test_real_won_arr_comes_from_the_same_rows()
    test_review_is_not_reaching_discovery()
    test_discovery_seen_only_after_close_does_not_count()
    test_disqualified_after_negotiating_is_excluded()
    test_no_history_counted_not_guessed_and_renewals_out()
    test_sdr_owned_qualified_deal_counts_for_team_not_rep_table()
    test_too_few_qualified_states_it_instead_of_a_rate()
    print("\n✅ All tests passed")
