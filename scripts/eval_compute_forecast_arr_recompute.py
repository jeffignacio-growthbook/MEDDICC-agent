#!/usr/bin/env python3
"""
Regression coverage for compute_forecast.py's Incremental-ARR recompute
(migration 064 / PENDING_WORK.md Low Priority #11).

Before this, compute_forecast.py had ZERO automated test coverage anywhere
in this repo — confirmed via grep across tests/, scripts/eval_*.py, and
scripts/test_*.py. eval_forecast_correctness.py and test_forecast_analyses.py
test a DIFFERENT module (scripts/analytics/forecast_analyses.py), not this
one, despite similar-sounding names. The two Sites fixed tonight
(compute_forecast.py:132 and :234) were verified only by direct logic
simulation and eval_reconstruction.py's null-coalescing ratchet (which only
confirms the forbidden `or 0` string pattern is gone, not that the new logic
is correct end-to-end). This file closes that gap for the specific behavior
that changed: recomputing Incremental ARR from new_arr/expansion_arr instead
of trusting deal_value, and falling back honestly when those components
aren't available.

Offline: stubs supabase at module load (compute_forecast.py imports it
locally inside main()), and patches the two data-access seams
(supabase.create_client, supabase_client.select_all) plus the Supabase
client's .table(...).upsert(...).execute() write, so main() runs against
fixture data with no real network/DB access.
"""
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parent.parent
for p in ("scripts", "scripts/analytics", "."):
    sys.path.insert(0, str(REPO / p))

if "supabase" not in sys.modules:
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: None
    _fake.Client = type("Client", (), {})
    sys.modules["supabase"] = _fake

import compute_forecast  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        FAILS.append(name)


class _FakeUpsertQuery:
    def __init__(self, sink, table_name):
        self.sink = sink
        self.table_name = table_name
        self._rows = None

    def upsert(self, rows, on_conflict=None):
        self._rows = rows
        return self

    def execute(self):
        # main() upserts one row dict at a time, not a list of rows.
        self.sink.setdefault(self.table_name, []).append(self._rows)
        return MagicMock()


class _FakeSB:
    """Captures every forecast_weekly row main() writes, instead of hitting
    a real Supabase project."""
    def __init__(self):
        self.written = {}

    def table(self, name):
        return _FakeUpsertQuery(self.written, name)


def _run_main(deals_rows, week3_rows_by_filter=None):
    """Runs compute_forecast.main() against fixture deals/week3 rows and
    returns the captured forecast_weekly rows, keyed by
    (pipeline_id, fiscal_quarter)."""
    sb = _FakeSB()

    def fake_select_all(_sb, table, columns=None, filters=None, page_size=1000):
        if table == "deals":
            return list(deals_rows)
        if table == "deals_snapshot":
            # week3_rows_by_filter maps fiscal_quarter -> rows; every test
            # here uses a single quarter, so filters aren't inspected.
            if week3_rows_by_filter is None:
                return []
            return next(iter(week3_rows_by_filter.values()), [])
        return []

    with patch.object(sys.modules["supabase"], "create_client", return_value=sb), \
         patch("supabase_client.select_all", side_effect=fake_select_all), \
         patch.dict("os.environ", {"SUPABASE_URL": "https://x.test",
                                    "SUPABASE_SERVICE_KEY": "fake-key"}):
        compute_forecast.main()

    rows = sb.written.get("forecast_weekly", [])
    return {(r["pipeline_id"], r["fiscal_quarter"]): r for r in rows}


def _deal(deal_id, stage, close_date, deal_value=None, new_arr=None,
          expansion_arr=None, pipeline_id="default", deal_status="active",
          forecast_category=None, region=None, segment=None):
    return {
        "deal_id": deal_id, "pipeline_id": pipeline_id, "stage": stage,
        "deal_value": deal_value, "new_arr": new_arr,
        "expansion_arr": expansion_arr, "close_date": close_date,
        "deal_status": deal_status, "forecast_category": forecast_category,
        "region": region, "segment": segment,
    }


# A real, qualified default-pipeline open stage (order >= qualified_stage_order)
QUALIFIED_STAGE = "appointmentscheduled"


def test_site1_recomputes_from_components_not_deal_value():
    """The open-deals loop must sum new_arr+expansion_arr directly — not
    trust deal_value, which can be affected by HubSpot's own NULL-out
    hazard. A deliberately-wrong deal_value proves the recompute path is
    actually being used, not silently falling back to the old behavior."""
    deals = [
        _deal("d1", QUALIFIED_STAGE, "2099-01-01",
              deal_value=999999.0,  # deliberately wrong — must be ignored
              new_arr=100.0, expansion_arr=None),
        _deal("d2", QUALIFIED_STAGE, "2099-01-01",
              deal_value=999999.0,
              new_arr=None, expansion_arr=50.0),
    ]
    rows = _run_main(deals)
    row = next(iter(rows.values()))
    check("open_pipeline_value is 150 (100+50), not 1,999,998 (2x deal_value)",
          abs(row["open_pipeline_value"] - 150.0) < 0.01)


def test_site1_excludes_both_blank_deals_not_zero_fills():
    """A deal with both new_arr and expansion_arr genuinely blank must be
    excluded from open_count/open_value entirely — never counted as a $0
    contribution."""
    deals = [
        _deal("d1", QUALIFIED_STAGE, "2099-01-01", new_arr=100.0, expansion_arr=0.0),
        _deal("d2", QUALIFIED_STAGE, "2099-01-01", new_arr=None, expansion_arr=None),
    ]
    rows = _run_main(deals)
    row = next(iter(rows.values()))
    check("only the known deal counts (open_value=100)",
          abs(row["open_pipeline_value"] - 100.0) < 0.01)
    check("only the known deal is counted (open_deal_count=1, not 2)",
          row["open_deal_count"] == 1)


def test_site2_recomputes_week3_from_components_when_present():
    """The week-3 average-deal-size fallback must recompute from
    new_arr/expansion_arr on deals_snapshot (migration 064) rather than
    trusting deal_value, mirroring Site 1."""
    # No won deals -> won_deal_avg is None -> forces the Site 2 fallback path.
    deals = [
        _deal("o1", QUALIFIED_STAGE, "2099-01-01", new_arr=10.0, expansion_arr=10.0),
    ]
    week3_rows = [
        {"deal_id": "w1", "stage_id": QUALIFIED_STAGE, "pipeline_id": "default",
         "deal_value": 999999.0, "new_arr": 200.0, "expansion_arr": None},
        {"deal_id": "w2", "stage_id": QUALIFIED_STAGE, "pipeline_id": "default",
         "deal_value": 999999.0, "new_arr": None, "expansion_arr": 100.0},
    ]
    rows = _run_main(deals, week3_rows_by_filter={"any": week3_rows})
    row = next(iter(rows.values()))
    # avg_deal_size = (200+100)/2 = 150; week3_count=2 -> mid = 2 * 0.099 * 150 = 29.7
    expected_mid = 2 * 0.099 * 150.0
    check("historical_conversion_mid uses the recomputed avg (150), not deal_value (999,999)",
          abs(row["historical_conversion_mid"] - expected_mid) < 0.01)


def test_site2_falls_back_to_deal_value_for_legacy_rows():
    """A week-3 row predating migration 064 (new_arr/expansion_arr both
    NULL because the columns didn't exist yet) must fall back to that
    deal's own deal_value — not be treated as unknown when a real number
    is available."""
    deals = [
        _deal("o1", QUALIFIED_STAGE, "2099-01-01", new_arr=10.0, expansion_arr=10.0),
    ]
    week3_rows = [
        {"deal_id": "legacy1", "stage_id": QUALIFIED_STAGE, "pipeline_id": "default",
         "deal_value": 80.0, "new_arr": None, "expansion_arr": None},
    ]
    rows = _run_main(deals, week3_rows_by_filter={"any": week3_rows})
    row = next(iter(rows.values()))
    expected_mid = 1 * 0.099 * 80.0
    check("legacy row (both components NULL) falls back to its own deal_value (80)",
          abs(row["historical_conversion_mid"] - expected_mid) < 0.01)


def test_site2_excludes_genuinely_unknown_deals_not_zero_fills():
    """A week-3 row with both components AND deal_value NULL is genuinely
    unknown — excluded from the average, never coalesced to 0."""
    deals = [
        _deal("o1", QUALIFIED_STAGE, "2099-01-01", new_arr=10.0, expansion_arr=10.0),
    ]
    week3_rows = [
        {"deal_id": "known1", "stage_id": QUALIFIED_STAGE, "pipeline_id": "default",
         "deal_value": None, "new_arr": 60.0, "expansion_arr": 0.0},
        {"deal_id": "unknown1", "stage_id": QUALIFIED_STAGE, "pipeline_id": "default",
         "deal_value": None, "new_arr": None, "expansion_arr": None},
    ]
    rows = _run_main(deals, week3_rows_by_filter={"any": week3_rows})
    row = next(iter(rows.values()))
    # avg must be 60 (only the known deal), not 30 (60 averaged over both,
    # which would be the zero-filling bug this whole investigation started
    # from) and not a crash.
    expected_mid = 2 * 0.099 * 60.0  # week3_count is still 2 (both qualified)
    check("unknown deal excluded from the average (avg=60, not 30)",
          abs(row["historical_conversion_mid"] - expected_mid) < 0.01)


def run():
    print("=" * 72)
    print("COMPUTE_FORECAST — Incremental ARR recompute (migration 064)")
    print("=" * 72)
    for title, fn in (
        ("Site 1: recompute from components, not deal_value",
         test_site1_recomputes_from_components_not_deal_value),
        ("Site 1: both-blank deals excluded, not zero-filled",
         test_site1_excludes_both_blank_deals_not_zero_fills),
        ("Site 2: recompute from new_arr/expansion_arr when present",
         test_site2_recomputes_week3_from_components_when_present),
        ("Site 2: legacy (pre-migration) rows fall back to deal_value",
         test_site2_falls_back_to_deal_value_for_legacy_rows),
        ("Site 2: genuinely-unknown deals excluded, not zero-filled",
         test_site2_excludes_genuinely_unknown_deals_not_zero_fills),
    ):
        print(f"\n[{title}]")
        fn()

    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("PASS — Incremental ARR recompute verified end-to-end through main().")
    return 0


if __name__ == "__main__":
    sys.exit(run())
