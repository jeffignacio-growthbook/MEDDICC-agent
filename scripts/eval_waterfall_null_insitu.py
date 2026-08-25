#!/usr/bin/env python3
"""
Eval: defect-4 (null deal_value) IN SITU through compute_waterfall_for_dates.

The existing coverage was (a) the null_propagate UTILITY tested directly, and
(b) a source-grep ratchet asserting no `deal_value ... or 0` pattern exists.
Neither drives the actual waterfall: a grep passes whether or not the null
truly reaches the sum, and the utility test says nothing about whether
compute_waterfall CALLS it. This closes that gap by computing a real waterfall
on a fixture with known-null deals and checking the numbers.

Distinguishing a null-propagating implementation from a zero-filling one:
  * a 0-fill and an exclusion produce the SAME dollar sum (0 adds nothing) — so
    the sum alone can't tell them apart. The COUNT can: an excluded deal is
    tallied in null_value_excluded_count; a 0-fill has no such count.
  * above max_null_value_pct the dollar basis is flagged null — a concept a
    0-fill does not have. We force >5% nulls and assert the flag is set.
  * a category add of a None value with the `if value_known` guard removed would
    raise TypeError — so the test COMPUTING AT ALL proves the guard is live.
"""
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch, Mock

REPO = Path(__file__).resolve().parent.parent
for p in ("scripts", "scripts/analytics", "api", "."):
    sys.path.insert(0, str(REPO / p))

if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f

import yaml  # noqa: E402
import supabase_client  # noqa: E402
from analytics import compute_waterfall as cw  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        FAILS.append(name)


PREV = "2026-05-05"
NEW = "2026-05-12"  # same fiscal quarter (FY start month 2 → Q2 = May-Jul)


def _snap_row(did, value, status, order=5, pipeline="default"):
    return {"deal_id": did, "deal_value": value, "deal_status": status,
            "stage_order": order, "pipeline_id": pipeline,
            "company_name": did, "close_date": "2026-07-15",
            "stage_id": "qualifiedtobuy"}


# Beginning (PREV): two known (100, 50), two unknown (None, None) — all active,
# all qualified. Ending (NEW): the two "won" deals leave the active set; kw wins
# with a known 50, uw wins with an unknown value (must NOT add, must be counted).
PREV_SNAP = [
    _snap_row("k1", 100.0, "active"),
    _snap_row("u1", None,  "active"),
    _snap_row("kw", 50.0,  "active"),
    _snap_row("uw", None,  "active"),
]
NEW_SNAP = [
    _snap_row("k1", 100.0, "active"),
    _snap_row("u1", None,  "active"),
    _snap_row("kw", 50.0,  "won"),
    _snap_row("uw", None,  "won"),
]
QUAL_MAP = {d: {"qualified_date": "2026-01-01"} for d in ("k1", "u1", "kw", "uw")}


def _fake_select_all(sb, table, columns="*", filters=None, page_size=1000):
    if table != "deals_snapshot":
        return []
    snap_date = dict((f[1], f[2]) for f in (filters or [])).get("snapshot_date")
    return list(PREV_SNAP if snap_date == PREV else
                NEW_SNAP if snap_date == NEW else [])


class _RecorderSB:
    """Captures the row upserted to waterfall_weekly."""
    def __init__(self):
        self.rows = []

    def table(self, name):
        outer = self

        class _Q:
            def upsert(self, row, **k):
                outer.rows.append(row)
                return self

            def __getattr__(self, _n):
                return lambda *a, **k: self

            def execute(self):
                return types.SimpleNamespace(data=[])
        return _Q()


def run():
    print("=" * 72)
    print("WATERFALL NULL deal_value — IN SITU (defect 4)")
    print("=" * 72)
    config = yaml.safe_load((REPO / "config/client.yaml").read_text())

    sb = _RecorderSB()
    with patch.object(supabase_client, "select_all", _fake_select_all):
        # Computing at all with two None-valued deals proves the `if value_known`
        # guards are live — an unguarded `+= None` would raise TypeError here.
        cw.compute_waterfall_for_dates(
            sb, config, QUAL_MAP, threshold=0,
            prev_date=PREV, new_date=NEW, computed_source="prospective")

    default = [r for r in sb.rows if r.get("pipeline_id") == "default"]
    check("a waterfall row was produced (no crash on None values)", len(default) == 1)
    if not default:
        print("\nFAIL — no row"); return 1
    row = default[0]
    details = json.loads(row["details"])
    summary = next((d for d in details
                    if d.get("change_type") == "null_value_excluded_summary"), None)

    # SUMS exclude the nulls (known values only).
    check("beginning_value = 150 (100+50; two nulls excluded, not 0-filled)",
          row["beginning_value"] == 150.0)
    check("ending_value = 100 (won deals left the active set; u1 null excluded)",
          row["ending_value"] == 100.0)
    check("won_value = 50 (kw known; uw's None NOT summed)",
          row["won_value"] == 50.0)

    # COUNTS — the fact a 0-fill would swallow.
    check("null_value_excluded_summary present in details", summary is not None)
    if summary:
        check("movement null exclusions counted = 2 (u1, uw)",
              summary["movement_null_value_excluded"] == 2)
        check("beginning null exclusions counted = 2",
              summary["beginning_null_value_excluded"] == 2)
        check("ending null exclusions counted = 1 (u1)",
              summary["ending_null_value_excluded"] == 1)
        # >5% nulls → dollar basis flagged null (a concept 0-fill lacks).
        check("beginning dollar basis flagged null (>max_null_value_pct)",
              summary["beginning_dollar_basis_null"] is True)

    # The zero-fill counterfactual, stated: a 0-fill yields the SAME sums but
    # zero exclusions counted and no basis-null flag. The counts above are what
    # separate correct null-propagation from a silent 0.
    if FAILS:
        print(f"\nFAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("\nPASS — nulls excluded from every dollar sum, counted, and basis "
          "flagged; verified on real waterfall arithmetic, not a grep.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
