#!/usr/bin/env python3
"""
compute_waterfall_segmented.py: weeks move onto incremental_arr() from
INCREMENTAL_BASIS_FROM (2026-09-11, the first deals_snapshot carrying
new_arr / expansion_arr); earlier weeks stay on deal_value; every row
records its value_basis.

Runs the real compute_waterfall_for_dates() against a fake Supabase: one
qualified deal enters the pipeline in each week. Its snapshot has
deal_value 90,000 (HubSpot amount fallback included) and incremental ARR
80,000 (new 80,000, expansion NULL), so the week's new_pipeline_value shows
which basis was used.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))
sys.path.insert(0, str(REPO))

import compute_waterfall_segmented as cws  # noqa: E402


sys.path.insert(0, str(REPO / "tests"))
from strict_supabase import StrictSupabase  # noqa: E402


class DB(StrictSupabase):
    """Strict fake (tests/strict_supabase.py): reads answer like Postgres
    (the REAL select_all, only selected columns, every filter), and every
    upsert is checked against the real schema before it is recorded. Until
    2026-09-24 a select_all lambda ignored the table and filter operator, and
    a catch-all chain accepted any call."""
    @property
    def upserts(self):
        return [row for w in self.writes if w["kind"] == "upsert"
                for row in (w["payload"] if isinstance(w["payload"], list) else [w["payload"]])]


def _snap(deal_id, date, **over):
    row = {"deal_id": deal_id, "snapshot_date": date, "stage_id": "presentationscheduled",
           "stage_order": 3, "pipeline_id": "default", "region": "EMEA", "segment": "Enterprise",
           "deal_value": 90000.0, "new_arr": 80000.0, "expansion_arr": None,
           "close_date": "2026-10-30", "deal_status": "active", "forecast_category": "COMMIT"}
    row.update(over)
    return row


def _run(prev_date, new_date):
    # the new snapshot holds D1; a decoy row on another date must not be read
    db = DB({"deals_snapshot": [_snap("D1", new_date), _snap("DECOY", "2026-01-05")],
             "waterfall_weekly": [], "property_history": []})
    from utils import load_client_config
    cws.compute_waterfall_for_dates(
        db, load_client_config(),
        qual_map={"D1": {"qualified_date": "2026-01-01"}},
        enrichment_map={"D1": {"company_name": "Delta Co"}},
        deal_status_map={"D1": {"close_date": "2026-10-30", "stage": "presentationscheduled"}},
        is_test_deal_fn=lambda d: False, threshold=1,
        prev_date=prev_date, new_date=new_date, computed_source="prospective")
    rows = [r for r in db.upserts if r.get("region") == "EMEA"]
    assert len(rows) == 1, db.upserts
    return rows[0]


def test_basis_boundary():
    assert cws.INCREMENTAL_BASIS_FROM == "2026-09-11"
    assert cws.value_basis_for("2026-09-08") == "deal_value"
    assert cws.value_basis_for("2026-09-11") == "incremental_arr"
    assert cws.value_basis_for("2026-09-14") == "incremental_arr"
    print("✓ basis boundary: a week whose earlier snapshot is >= 2026-09-11 uses incremental_arr")


def test_week_before_the_switch_stays_on_deal_value():
    row = _run("2026-09-07", "2026-09-08")
    assert row["value_basis"] == "deal_value", row
    assert row["new_pipeline_value"] == 90000.0, row["new_pipeline_value"]
    print("✓ week 09-07 -> 09-08: new_pipeline_value 90,000 on deal_value, value_basis=deal_value")


def test_week_after_the_switch_uses_incremental_arr():
    row = _run("2026-09-14", "2026-09-21")
    assert row["value_basis"] == "incremental_arr", row
    assert row["new_pipeline_value"] == 80000.0, row["new_pipeline_value"]
    print("✓ week 09-14 -> 09-21: new_pipeline_value 80,000 on incremental_arr(), "
          "value_basis=incremental_arr")


if __name__ == "__main__":
    test_basis_boundary()
    test_week_before_the_switch_stays_on_deal_value()
    test_week_after_the_switch_uses_incremental_arr()
    print("\n✅ All tests passed")
