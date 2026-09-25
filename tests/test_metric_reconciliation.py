#!/usr/bin/env python3
"""
Metric reconciliation (scripts/analytics/metric_reconciliation.py): decompose
the change in a sum-over-deals metric between two point-in-time captures into
one bucket per deal, so a headline move is explained deal by deal and the
buckets add back to the observed delta exactly.

Real, already-solved case: the two FY2027 Q3 waterfall captures from
2026-09-24 (02:43 UTC and 14:37 UTC) whose qualified-pipeline Incremental ARR
headline moved +$280,000. That move was three real CRM edits:

  Cursor              +$400,000   rescoped in  (Meeting Set -> Scoping)
  Virgin Media O2     -$100,000   exited, still open (close date moved to 2027)
  Reliance Industries  -$20,000   value edited (ARR 60,000 -> 40,000)

The fixture is both full capture universes (221 / 220 deals) plus the
authoritative CURRENT row for the one exited deal absent from the current
capture, so its outcome is read from real status, never inferred from absence.
This test does NOT tell the reconciler the answer: it hands it the two
universes and the scope, and checks it finds those three deals and nothing
else, and that the accounting closes to the cent.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import metric_reconciliation as mr  # noqa: E402

FX = json.loads((REPO / "tests" / "fixtures"
                 / "metric_reconciliation_waterfall_2026_09_24.json").read_text())
SCOPE = FX["_meta"]["scope"]
CURSOR, VIRGIN, RELIANCE = "65168412257", "63327879453", "58956770692"


def _value(row):
    v = row.get("arr_usd")
    return float(v) if v is not None else 0.0


def _components():
    """The qualified-pipeline scope, as named components so the reconciler can
    say WHICH condition flipped when a deal enters or leaves."""
    qs = set(SCOPE["qualifying_stages"])
    w0, w1 = SCOPE["window_start"], SCOPE["window_end"]
    return {
        "active": lambda r: r.get("deal_status") == SCOPE["active_status"],
        "qualifying_stage": lambda r: str(r.get("stage")) in qs,
        "close_in_window": lambda r: r.get("close_date") is not None
        and w0 <= str(r["close_date"])[:10] <= w1,
    }


def _reconcile_fixture():
    return mr.reconcile(
        FX["prior"], FX["current"],
        value=_value,
        scope_components=_components(),
        current_state=FX["current_state"],
    )


def _by_deal(result):
    out = {}
    for name, b in result["buckets"].items():
        for d in b.get("deals", []):
            out[str(d["deal_id"])] = (name, round(d["contribution"], 2), d.get("reason"))
    return out


def test_the_280k_case_is_reproduced_deal_by_deal():
    r = _reconcile_fixture()
    assert round(r["observed_delta"], 2) == 280000.00, r["observed_delta"]
    assert round(r["reconciled_total"], 2) == 280000.00, r["reconciled_total"]
    assert round(r["residual"], 2) == 0.00 and r["closes"] is True, r["residual"]
    assert (r["prior_in_scope"]["count"], round(r["prior_in_scope"]["value"], 2)) == (46, 4587065.68)
    assert (r["current_in_scope"]["count"], round(r["current_in_scope"]["value"], 2)) == (46, 4867065.68)

    by = _by_deal(r)
    # exactly the three real changes, each in the right bucket with the right sign
    assert by[CURSOR][:2] == ("rescoped_in", 400000.00), by.get(CURSOR)
    assert by[VIRGIN][:2] == ("exited_still_open_rescoped", -100000.00), by.get(VIRGIN)
    assert by[RELIANCE][:2] == ("value_edited", -20000.00), by.get(RELIANCE)
    assert set(by) == {CURSOR, VIRGIN, RELIANCE}, set(by)  # nothing else moved
    print("✓ +$280,000 explained by exactly Cursor (+400K rescoped in), Virgin (-100K exited still "
          "open), Reliance (-20K value edited); reconciled total == observed delta, residual $0.00")


def test_the_reasons_name_the_real_crm_edit():
    by = _by_deal(_reconcile_fixture())
    assert "qualifying_stage" in (by[CURSOR][2] or ""), by[CURSOR]      # stage moved into scope
    assert "close_in_window" in (by[VIRGIN][2] or ""), by[VIRGIN]        # close date moved out
    assert "2027-03-31" in (by[VIRGIN][2] or ""), by[VIRGIN]             # to next year
    print("✓ reasons name the flipped scope component: Cursor's stage entering, Virgin's close date "
          "leaving the window (to 2027-03-31)")


def test_every_in_scope_deal_lands_in_exactly_one_bucket():
    r = _reconcile_fixture()
    prior_in = {str(d["deal_id"]) for d in FX["prior"] if mr.in_scope_all(d, _components())}
    cur_in = {str(d["deal_id"]) for d in FX["current"] if mr.in_scope_all(d, _components())}
    population = prior_in | cur_in
    counted = sum(b["count"] for b in r["buckets"].values())
    seen = [str(d["deal_id"]) for b in r["buckets"].values() for d in b.get("deals", [])]
    # count across buckets == the population size; the listed deals have no duplicates
    assert counted == len(population), (counted, len(population))
    assert len(seen) == len(set(seen)), "a deal was placed in two buckets"
    # bucket values add back to the observed delta, exactly
    assert round(sum(b["value"] for b in r["buckets"].values()), 2) == round(r["observed_delta"], 2)
    print(f"✓ {len(population)} in-scope deals partition across the buckets with no double-count; "
          f"bucket values sum to the observed delta")


def test_exit_outcome_comes_from_status_never_from_absence():
    """Four deals in prior scope, all absent from the current capture. The
    reconciler must read each one's real outcome from current_state — won,
    lost, still-open-rescoped — and, when there is no status at all, must NOT
    guess: it says exited_unknown, and still counts the dollars."""
    comps = {"active": lambda r: r.get("deal_status") == "active",
             "qualifying_stage": lambda r: str(r.get("stage")) == "24682892",
             "close_in_window": lambda r: "2026-08-01" <= str(r.get("close_date"))[:10] <= "2026-10-31"}
    prior = [{"deal_id": d, "company_name": d, "deal_status": "active", "stage": "24682892",
              "close_date": "2026-10-15", "arr_usd": 10000.0} for d in ("W", "L", "O", "U")]
    current = []  # every deal absent from the current universe
    current_state = {
        "W": {"deal_id": "W", "deal_status": "won", "stage": "closedwon", "close_date": "2026-10-15"},
        "L": {"deal_id": "L", "deal_status": "lost", "stage": "closedlost", "close_date": "2026-10-15"},
        "O": {"deal_id": "O", "deal_status": "active", "stage": "24682892", "close_date": "2027-03-31"},
        # "U" deliberately has no current_state entry
    }
    r = mr.reconcile(prior, current, value=lambda x: float(x.get("arr_usd") or 0),
                     scope_components=comps, current_state=current_state)
    by = _by_deal(r)
    assert by["W"][0] == "exited_won", by.get("W")
    assert by["L"][0] == "exited_lost", by.get("L")
    assert by["O"][0] == "exited_still_open_rescoped", by.get("O")
    assert by["U"][0] == "exited_unknown", by.get("U")  # never silently called lost
    # all four still contribute their -$10,000, so the accounting still closes
    assert round(r["reconciled_total"], 2) == -40000.00 and round(r["residual"], 2) == 0.00
    print("✓ absent deals are classified by real status (won / lost / still-open); with no status "
          "the reconciler says exited_unknown, never a guessed outcome — and the dollars still close")


def test_new_is_distinguished_from_rescoped_in():
    """Both add value on the current side, but a deal that did not exist in the
    prior universe is New, while one that existed there out of scope is
    Rescoped in. The distinction needs the prior universe, not just prior
    scope."""
    comps = {"qualifying_stage": lambda r: str(r.get("stage")) == "q"}
    prior = [{"deal_id": "EXIST", "company_name": "Exist", "stage": "meeting", "arr_usd": 5000.0}]
    current = [{"deal_id": "EXIST", "company_name": "Exist", "stage": "q", "arr_usd": 5000.0},
               {"deal_id": "BRAND", "company_name": "Brand", "stage": "q", "arr_usd": 7000.0}]
    r = mr.reconcile(prior, current, value=lambda x: float(x.get("arr_usd") or 0),
                     scope_components=comps)
    by = _by_deal(r)
    assert by["EXIST"] [:2] == ("rescoped_in", 5000.00), by.get("EXIST")
    assert by["BRAND"][:2] == ("new", 7000.00), by.get("BRAND")
    print("✓ a deal present in the prior universe but out of scope is rescoped_in; a deal absent "
          "from the prior universe is new")


def test_value_edit_only_counts_when_in_scope_on_both_sides():
    """A value change while the deal is out of scope on one side is not a value
    edit — it is folded into the entry or exit. Value edited is reserved for a
    deal in scope on both sides whose value moved."""
    comps = {"qualifying_stage": lambda r: str(r.get("stage")) == "q"}
    prior = [{"deal_id": "A", "company_name": "A", "stage": "q", "arr_usd": 100.0},
             {"deal_id": "B", "company_name": "B", "stage": "meeting", "arr_usd": 100.0}]
    current = [{"deal_id": "A", "company_name": "A", "stage": "q", "arr_usd": 150.0},
               {"deal_id": "B", "company_name": "B", "stage": "q", "arr_usd": 999.0}]
    by = _by_deal(mr.reconcile(prior, current, value=lambda x: float(x.get("arr_usd") or 0),
                               scope_components=comps))
    assert by["A"][:2] == ("value_edited", 50.00), by.get("A")   # in scope both -> edit
    assert by["B"][:2] == ("rescoped_in", 999.00), by.get("B")   # entered scope -> whole value
    print("✓ value_edited is only for a deal in scope on both sides; B's change rides its rescope-in")


def test_residual_is_reported_exactly_not_approximately():
    r = _reconcile_fixture()
    # the contract: an exact number, and a boolean, never 'approximately explains'
    assert isinstance(r["residual"], float)
    assert r["residual"] == r["observed_delta"] - r["reconciled_total"]
    assert r["unexplained_residual"]["count"] == 0 and r["unexplained_residual"]["value"] == 0.0
    print("✓ residual is observed_delta - reconciled_total exactly, and the unexplained bucket is "
          "empty for the real case")


if __name__ == "__main__":
    test_the_280k_case_is_reproduced_deal_by_deal()
    test_the_reasons_name_the_real_crm_edit()
    test_every_in_scope_deal_lands_in_exactly_one_bucket()
    test_exit_outcome_comes_from_status_never_from_absence()
    test_new_is_distinguished_from_rescoped_in()
    test_value_edit_only_counts_when_in_scope_on_both_sides()
    test_residual_is_reported_exactly_not_approximately()
    print("\n✅ All tests passed")
