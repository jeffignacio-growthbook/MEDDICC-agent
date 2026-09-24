#!/usr/bin/env python3
"""
scripts/analytics/qualification_call_comparison.py: MEDDICC call scores of
Meeting Set deals that went on to a qualified stage vs deals that stalled,
from calls made before the move only. Exploratory, read-only.

Cutoff (the anti-leakage rule, per deal):
  progressed  calls on or after the first Meeting Set snapshot and on or
              before min(last snapshot before the crossing, Meeting Set + 7
              days). The crossing week is known only to a snapshot, so a call
              in it may be the qualifying call itself: excluded.
  stalled     never seen at a qualified stage, first Meeting Set snapshot at
              least 21 days before the latest snapshot; calls on or after the
              first Meeting Set snapshot and on or before it + 7 days (the same
              observation window as progressed).
  excluded    deals first seen at a qualified stage, and Meeting Set deals
              younger than 21 days that have not crossed.
Second view: stalled limited to deals still open today.

Planted-bug targets: the window bounds (crossing date vs previous snapshot,
the 7-day cap, inclusive ends, the pre-Meeting-Set start), the stalled age
rule, the first-seen-qualified exclusion, the still-open view, and the
within-stratum control.

Real data (tests/fixtures/qualification_call_comparison_2026_09_24.json,
2026-09-24): the 274 deals with a transcript call from 7 days before to 21
days after their first Meeting Set snapshot, their snapshot rows reduced to
the first and last row of each stage run, their deals rows and owners' first
deal dates. Checked independently in SQL: 52 progressed deals (54 calls),
69 stalled (84 calls), 20 of the stalled still open.
"""
import json
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO / "scripts"))

import qualification_call_comparison as qcc  # noqa: E402

MS = "79653122"
DISC = "qualifiedtobuy"
LATEST = date(2026, 9, 21)
FIXTURE = REPO / "tests" / "fixtures" / "qualification_call_comparison_2026_09_24.json"


def _snaps(deal_id, start, stages, step=7):
    return [{"deal_id": deal_id, "snapshot_date": (start + timedelta(days=step * k)).isoformat(),
             "stage_id": st, "pipeline_id": "default"} for k, st in enumerate(stages)]


def _call(deal_id, day, score=5, call_id=None, keys=()):
    c = {"deal_id": deal_id, "call_id": call_id or f"{deal_id}-{day.isoformat()}",
         "call_date": day.isoformat(), "evidence_keys": list(keys)}
    for comp in qcc.COMPONENTS:
        c[comp] = score
    return c


# ---------------------------------------------------------------- milestones

def test_milestones_first_meeting_set_first_qualified_and_previous_snapshot():
    d0 = date(2026, 6, 1)
    snaps = (_snaps("A", d0, [MS, MS, MS, DISC, MS, DISC])          # crossed at week 3
             + _snaps("FQ", d0, [DISC, DISC, MS, DISC])               # first seen qualified
             + _snaps("S", d0, [MS, MS, "closedlost"])                # never qualified
             + [dict(s, pipeline_id="866608541") for s in _snaps("R", d0, [MS, DISC])])
    m = qcc.deal_milestones(snaps)
    assert m["A"] == {"ms_first": d0, "q_first": d0 + timedelta(21),
                      "prev_d": d0 + timedelta(14), "qualified_before_ms": False}, m["A"]
    assert m["FQ"]["qualified_before_ms"] is True
    assert (m["FQ"]["q_first"], m["FQ"]["prev_d"]) == (d0 + timedelta(21), d0 + timedelta(14)), \
        "the crossing is the first qualified row AFTER the first Meeting Set row"
    assert m["S"]["q_first"] is None and m["S"]["prev_d"] is None
    assert "R" not in m, "renewal-pipeline rows must be ignored"
    print("✓ milestones: first Meeting Set, first qualified, the snapshot before it; "
          "first-seen-qualified flagged; other pipelines ignored")


# ------------------------------------------------------------ cutoff windows

def test_progressed_window_ends_at_the_previous_snapshot_capped_at_seven_days():
    d0 = date(2026, 6, 1)
    snaps = (_snaps("FAST", d0, [MS, DISC])            # prev = d0, crossing d0+7
             + _snaps("SLOW", d0, [MS, MS, MS, DISC]))  # prev = d0+14 > cap d0+7
    c = qcc.build_cohorts(qcc.deal_milestones(snaps), LATEST, {})
    assert (c["FAST"]["cohort"], c["FAST"]["start"], c["FAST"]["end"]) == ("progressed", d0, d0), c["FAST"]
    assert (c["SLOW"]["start"], c["SLOW"]["end"]) == (d0, d0 + timedelta(7)), c["SLOW"]
    print("✓ progressed window: [first Meeting Set, min(previous snapshot, +7 days)]")


def test_calls_in_the_crossing_week_or_before_meeting_set_are_excluded():
    d0 = date(2026, 6, 1)
    snaps = _snaps("P", d0, [MS, MS, DISC])            # prev d0+7, crossing d0+14
    calls = [_call("P", d0 - timedelta(1)),            # before Meeting Set: out
             _call("P", d0),                           # start, inclusive: in
             _call("P", d0 + timedelta(7)),            # previous snapshot, inclusive: in
             _call("P", d0 + timedelta(8)),            # crossing week: out
             _call("P", d0 + timedelta(14))]           # crossing day: out
    cohorts = qcc.build_cohorts(qcc.deal_milestones(snaps), LATEST, {})
    got = [c["call_date"] for c in qcc.window_calls(calls, cohorts)["P"]]
    assert got == [d0.isoformat(), (d0 + timedelta(7)).isoformat()], got
    print("✓ only calls from Meeting Set entry to the pre-crossing snapshot count; "
          "crossing-week and pre-Meeting-Set calls do not")


def test_stalled_needs_21_days_at_meeting_set_and_gets_the_same_seven_day_window():
    old, edge, young = LATEST - timedelta(28), LATEST - timedelta(21), LATEST - timedelta(20)
    snaps = (_snaps("OLD", old, [MS, MS, MS, MS, MS]) + _snaps("EDGE", edge, [MS, MS, MS, MS])
             + [{"deal_id": "YOUNG", "snapshot_date": young.isoformat(), "stage_id": MS,
                 "pipeline_id": "default"}])
    c = qcc.build_cohorts(qcc.deal_milestones(snaps), LATEST, {})
    assert "YOUNG" not in c, "a deal 20 days into Meeting Set has not had time to stall"
    assert c["EDGE"]["cohort"] == "stalled", "exactly 21 days counts as stalled"
    assert (c["OLD"]["start"], c["OLD"]["end"]) == (old, old + timedelta(7)), c["OLD"]
    calls = [_call("OLD", old + timedelta(7)), _call("OLD", old + timedelta(8))]
    assert [x["call_date"] for x in qcc.window_calls(calls, c)["OLD"]] == [(old + timedelta(7)).isoformat()]
    print("✓ stalled: never qualified, >= 21 days since first Meeting Set; window "
          "[first Meeting Set, +7 days] inclusive")


def test_first_seen_qualified_is_in_neither_cohort():
    d0 = date(2026, 3, 2)
    snaps = _snaps("FQ", d0, [DISC, MS, MS, DISC]) + _snaps("FQ2", d0, [DISC, MS, MS, MS])
    c = qcc.build_cohorts(qcc.deal_milestones(snaps), LATEST, {})
    assert "FQ" not in c and "FQ2" not in c, c
    print("✓ a deal first seen at a qualified stage is neither progressed nor stalled")


def test_still_open_view_keeps_only_active_stalled_deals():
    d0 = date(2026, 3, 2)
    snaps = (_snaps("P1", d0, [MS, DISC]) + _snaps("S_LOST", d0, [MS, MS])
             + _snaps("S_OPEN", d0, [MS, MS]) + _snaps("S_WON", d0, [MS, "closedwon"]))
    st = {"P1": "lost", "S_LOST": "lost", "S_OPEN": "active", "S_WON": "won"}
    c = qcc.build_cohorts(qcc.deal_milestones(snaps), LATEST, st)
    assert {k for k, v in c.items() if v["still_open"]} == {"S_OPEN"}, c
    assert c["P1"]["still_open"] is False, "progressed deals are never filtered by status"
    print("✓ still-open view: stalled deals whose deal_status is active; progressed unchanged")


# ------------------------------------------------------ snapshot compression

def test_compression_keeps_every_milestone():
    rnd = random.Random(7)
    d0 = date(2025, 8, 4)
    snaps = []
    for i in range(300):
        seq = [rnd.choice([MS, MS, MS, DISC, "presentationscheduled", "closedlost", None])
               for _ in range(rnd.randint(1, 30))]
        snaps += _snaps(f"D{i}", d0 + timedelta(rnd.randint(0, 60)), seq)
    kept = qcc.compress_snapshots(snaps)
    assert len(kept) < len(snaps)
    assert qcc.deal_milestones(kept) == qcc.deal_milestones(snaps)
    fx = qcc.load_input(json.loads(FIXTURE.read_text()))
    assert qcc.compress_snapshots(fx["snapshots"]) == fx["snapshots"], "fixture is already compressed"
    print("✓ keeping the first and last row of each stage run preserves every milestone; "
          "the committed fixture is a fixed point")


# -------------------------------------------------------------- holdout/stats

def test_holdout_is_a_deterministic_third_independent_of_cohort():
    ids = [str(40000000000 + i * 7919) for i in range(3000)]
    h = [i for i in ids if qcc.holdout(i)]
    assert 900 < len(h) < 1100, len(h)
    assert h == [i for i in reversed(ids) if qcc.holdout(i)][::-1]
    print(f"✓ holdout: hash of deal_id, {len(h)} of 3000 held out, order-independent")


def test_mann_whitney_and_cohens_d_match_hand_values():
    a, b = [1, 2, 3, 4, 5], [6, 7, 8, 9, 10]
    u, p = qcc.mann_whitney(a, b)
    assert u == 0 and 0.005 < p < 0.02, (u, p)        # normal approx: p ~ 0.012
    assert abs(qcc.cohens_d(b, a) - 3.162) < 0.01, qcc.cohens_d(b, a)
    u, p = qcc.mann_whitney([3, 3, 3], [3, 3, 3])
    assert p == 1.0
    print("✓ Mann-Whitney (tie-corrected normal approx) and Cohen's d match hand values")


def test_stratified_permutation_controls_for_the_strata():
    # Progressed deals are all Enterprise with high scores, stalled all SMB with
    # low: pooled, a big gap; within strata, nothing to compare.
    vals = [8] * 20 + [2] * 20
    labels = [1] * 20 + [0] * 20
    strata = ["Ent"] * 20 + ["SMB"] * 20
    stat, p, n_inf = qcc.stratified_permutation(vals, labels, strata, n_perm=500, seed=1)
    assert n_inf == 0 and p == 1.0 and stat == 0.0, (stat, p, n_inf)
    # Same gap inside each stratum: detected.
    vals = [8] * 10 + [2] * 10 + [8] * 10 + [2] * 10
    labels = ([1] * 10 + [0] * 10) * 2
    strata = ["Ent"] * 20 + ["SMB"] * 20
    stat, p, n_inf = qcc.stratified_permutation(vals, labels, strata, n_perm=500, seed=1)
    assert n_inf == 40 and stat == 6.0 and p < 0.01, (stat, p, n_inf)
    print("✓ stratified permutation: a gap that is only between strata counts for nothing; "
          "a within-stratum gap is detected")


# ------------------------------------------------------------ end to end

def _synthetic(effect):
    """80 progressed / 80 stalled deals, same segment/size/tenure mix. effect
    adds to every progressed score on 'champion' only."""
    rnd = random.Random(11)
    d0 = date(2026, 1, 5)
    snaps, calls, deals = [], [], []
    for i in range(160):
        did = str(50000000000 + i)
        prog = i % 2 == 0
        snaps += _snaps(did, d0, [MS, MS, DISC] if prog else [MS, MS, MS, MS])
        c = _call(did, d0 + timedelta(3), keys=("champion",) if prog else ())
        for comp in qcc.COMPONENTS:
            c[comp] = min(9, max(1, rnd.randint(3, 6) + (effect if prog and comp == "champion" else 0)))
        calls.append(c)
        deals.append({"deal_id": did, "deal_status": "active" if i % 3 else "lost",
                      "segment": ["SMB", "Enterprise"][(i // 2) % 2], "new_arr": 20000,
                      "expansion_arr": 0, "deal_value": 20000, "owner_email": "a@x",
                      "create_date": "2025-12-01"})
    return {"latest_snapshot": LATEST.isoformat(), "snapshots": snaps, "calls": calls,
            "deals": deals, "owners_first_deal": {"a@x": "2024-01-01"}}


CAUSAL = re.compile(r"\b(caus\w*|drive[sn]?|driving|leads? to|lead to|results? in|because of|"
                    r"predict\w*|makes? deals|increases? the chance|boost\w*)\b", re.I)


def _assert_framing(text):
    assert "exploratory" in text.lower() and "hypothesis" in text.lower(), text[:300]
    assert "Caveat 1" in text and "lost" in text and "lead fit" in text.lower(), "caveat 1 missing"
    assert "Caveat 2" in text and "already moving" in text, "caveat 2 missing"
    assert "coaching change" in text and "crossing rate" in text, "live-test next step missing"
    bad = CAUSAL.findall(text)
    assert not bad, f"causal language in report: {bad}"


def test_null_result_says_no_reliable_signal_and_keeps_the_framing():
    r = qcc.analyse(qcc.load_input(_synthetic(effect=0)))
    assert not r["views"]["all_stalled"]["directional"], r["views"]["all_stalled"]["directional"]
    text = qcc.report(r)
    assert text.count("No reliable signal found") == 2, "both views must say so"
    _assert_framing(text)
    print("✓ null data: 'No reliable signal found' in both views, caveats and next step stated, "
          "no causal wording")


def test_directional_result_names_the_component_without_causal_language():
    r = qcc.analyse(qcc.load_input(_synthetic(effect=3)))
    v = r["views"]["all_stalled"]
    assert v["directional"] == ["champion"], v["directional"]
    ch = v["components"]["champion"]
    assert ch["train"]["d"] > 0.3 and ch["holdout"]["d"] > 0.2 and ch["train"]["p"] < 0.05, ch
    text = qcc.report(r)
    assert "champion" in text and "No reliable signal found in this view" not in text.split("View 2")[0]
    _assert_framing(text)
    print("✓ a planted champion gap is flagged directional on train and holdout; the report "
          "names it as a coaching-test candidate, still without causal wording")


# ------------------------------------------------------------ real fixture

def test_real_fixture_cohorts_match_the_sql_counts():
    data = qcc.load_input(json.loads(FIXTURE.read_text()))
    r = qcc.analyse(data)
    co = r["cohorts"]
    assert (co["progressed"], co["progressed_calls"]) == (52, 54), co
    assert (co["stalled"], co["stalled_calls"]) == (69, 84), co
    assert co["stalled_still_open"] == 20, co
    assert r["views"]["all_stalled"]["n_stalled"] == 69
    assert r["views"]["still_open_stalled"]["n_stalled"] == 20
    assert r["views"]["still_open_stalled"]["n_progressed"] == 52
    text = qcc.report(r)
    _assert_framing(text)
    assert "52 progressed" in text and "69 stalled" in text and "20 still open" in text, text[:800]
    print("✓ real 2026-09-24 data: 52 progressed (54 calls), 69 stalled (84 calls), 20 still "
          "open; report framed and caveated")


def test_live_fetch_against_the_strict_fake_gives_the_same_cohorts():
    """_fetch() is the only code that touches the database. Run it on the
    real rows through the strict fake (real schema, real select_all): every
    selected/filtered column must exist, renewal-pipeline snapshots and
    non-transcript calls must be filtered out, and evidence (a JSON-encoded
    string in call_scores) must parse into per-component text."""
    import os
    import types
    from strict_supabase import StrictSupabase
    fx = qcc.load_input(json.loads(FIXTURE.read_text()))
    snaps = [dict(s) for s in fx["snapshots"]]
    snaps.append({"deal_id": fx["deals"][0]["deal_id"], "snapshot_date": "2025-08-04",
                  "stage_id": "qualifiedtobuy", "pipeline_id": "866608541"})
    call_rows = []
    for c in fx["calls"]:
        row = {"deal_id": c["deal_id"], "call_id": c["call_id"], "call_date": c["call_date"],
               "text_source": "transcript",
               "evidence": json.dumps({k: f"quote {k}" for k in c["evidence_keys"]}) if c["evidence_keys"] else None}
        row.update({f"{k}_score": c[k] for k in qcc.COMPONENTS})
        call_rows.append(row)
        call_rows.append(dict(row, call_id=c["call_id"] + "-summary", text_source="summary",
                              pain_score=9, metrics_score=9))
    sb = StrictSupabase({"deals_snapshot": snaps, "call_scores": call_rows, "deals": fx["deals"]})
    stub = types.ModuleType("supabase")
    stub.create_client = lambda url, key: sb
    saved = sys.modules.get("supabase")
    sys.modules["supabase"] = stub
    os.environ.setdefault("SUPABASE_URL", "http://fake")
    os.environ.setdefault("SUPABASE_SERVICE_KEY", "fake")
    try:
        raw = qcc._fetch()
    finally:
        if saved is not None:
            sys.modules["supabase"] = saved
        else:
            del sys.modules["supabase"]
    assert all(c["call_id"].endswith("-summary") is False for c in raw["calls"]), "summary calls leaked"
    r = qcc.analyse(qcc.load_input(raw))
    co = r["cohorts"]
    assert (co["progressed"], co["stalled"], co["stalled_still_open"]) == (52, 69, 20), co
    with_ev = next(c for c in raw["calls"] if c["evidence_keys"])
    assert with_ev["evidence"][with_ev["evidence_keys"][0]].startswith("quote "), with_ev
    print("✓ _fetch() on the strict fake: real columns, renewal rows and summary calls filtered, "
          "evidence parsed; same 52 / 69 / 20")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\n✅ All tests passed")
