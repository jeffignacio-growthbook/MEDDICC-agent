#!/usr/bin/env python3
"""
Plausibility checker: days_past_benchmark is a signed offset, not a count.

2026-09-23 23:05 UTC, the first live forecast_trust answer after the
deals.amount fix: the answer carried the "worth verifying" banner because
check_negative_counts() flagged 11 "negative" values. It treats every
numeric key containing "days" as a duration that can't be below zero.
days_past_benchmark is days_open minus the segment's 75th-percentile cycle
benchmark (scripts/deal_risk_assessor.py). Negative means the deal is still
inside its benchmark, which is valid (it's what makes a deal low_risk). The
same holds for days_past_close / days_past_original_close. The values only
surfaced now because until the fix forecast_trust never returned a result.

Checked by hand: Apify (64836805007), SMB, created 2026-09-09, 14 days open
on 2026-09-23 against the 138-day SMB benchmark, so 14 - 138 = -124, exactly
what was flagged.

What is still implausible and must still be flagged:
  - a days_past_benchmark with no valid benchmark next to it;
  - a days_past_benchmark that isn't days_open - cycle_benchmark_days;
  - a negative real duration (days_open, age_days, ...).

Fixture: the 21 real deals from that answer, as of 2026-09-23.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "api"))

import plausibility  # noqa: E402

# (company, segment, days_open, cycle_benchmark_days) for the 21 deals in
# the 2026-09-23 23:05 answer (deals table, as of 2026-09-23).
REAL_DEALS = [
    ("Bike24", "SMB", 378, 138), ("Freie Presse", "SMB", 369, 138),
    ("facile.it", "Mid-Market", 358, 168), ("Taxfix", "Mid-Market", 257, 168),
    ("Boylesports", "Enterprise", 245, 214), ("Mistral", "SMB", 245, 138),
    ("Trade Me", "Mid-Market", 238, 168), ("Cochlear Ltd", "Enterprise", 237, 214),
    ("Skyscanner", "Mid-Market", 229, 168), ("Derive", "SMB", 219, 138),
    ("Square", "Enterprise", 188, 214), ("InPost", "Enterprise", 139, 214),
    ("Taskrabbit", "Mid-Market", 120, 168), ("ClickHouse", "Mid-Market", 98, 168),
    ("Zoro", "Mid-Market", 93, 168), ("BESTSELLER", "Enterprise", 90, 214),
    ("BlaBlaCar", "Mid-Market", 65, 168), ("Little Caesars", "Enterprise", 55, 214),
    ("Voyage Privé FR", "Mid-Market", 50, 168), ("CODE.ID", "Mid-Market", 28, 168),
    ("Apify", "SMB", 14, 138),
]


def _deal(company, segment, days_open, bench, **over):
    d = {"company_name": company, "segment": segment, "days_open": days_open,
         "cycle_benchmark_days": bench, "days_past_benchmark": days_open - bench}
    d.update(over)
    return d


def _result(deals):
    return {"status": "ok", "pipeline": {"deal_count": len(deals)}, "assessed_deals": deals}


def _messages(data):
    violations, _ = plausibility.run_all_checks(data, "query_forecast_trust")
    return [v.message for v in violations]


def test_real_forecast_trust_result_has_no_false_violations():
    deals = [_deal(*d) for d in REAL_DEALS]
    negatives = sorted(d["days_past_benchmark"] for d in deals if d["days_past_benchmark"] < 0)
    assert negatives == [-159, -140, -124, -124, -118, -103, -75, -75, -70, -48, -26], negatives
    apify = next(d for d in deals if d["company_name"] == "Apify")
    assert apify["days_past_benchmark"] == 14 - 138 == -124
    msgs = _messages(_result(deals))
    assert msgs == [], msgs
    print("✓ the 21 real deals from the 23:05 answer (11 within benchmark, negative offsets): "
          "no violations, so no banner")


def test_missing_or_invalid_benchmark_is_flagged():
    # positive offset (200 - 138 = +62), so only a benchmark check can flag it
    for bench in (None, 0, -5):
        d = _deal("Planted", "SMB", 200, 138)
        d["cycle_benchmark_days"] = bench
        msgs = _messages(_result([d]))
        assert any("without a valid cycle_benchmark_days" in m for m in msgs), (bench, msgs)
    d = _deal("Planted", "SMB", 200, 138)
    del d["cycle_benchmark_days"]
    assert any("without a valid cycle_benchmark_days" in m for m in _messages(_result([d])))
    print("✓ days_past_benchmark with a missing, zero or negative benchmark is flagged")


def test_offset_that_does_not_match_the_arithmetic_is_flagged():
    d = _deal("Apify", "SMB", 14, 138, days_past_benchmark=124)   # sign flipped
    msgs = _messages(_result([d]))
    assert any("days_open - cycle_benchmark_days" in m for m in msgs), msgs
    print("✓ a days_past_benchmark that isn't days_open - benchmark (e.g. sign flipped) is flagged")


def test_negative_real_durations_and_counts_are_still_flagged():
    msgs = _messages(_result([_deal("Future", "SMB", -3, 138)]))
    assert any("days_open is negative" in m for m in msgs), msgs
    assert any("deal_count is negative" in m for m in _messages({"pipeline": {"deal_count": -1}}))
    assert any("age_days is negative" in m for m in _messages({"rows": [{"age_days": -2}]}))
    print("✓ control: negative days_open, age_days and deal_count are still flagged")


def test_other_signed_day_offsets_are_not_flagged():
    msgs = _messages({"rows": [{"days_past_close": -12, "days_past_original_close": -40}]})
    assert msgs == [], msgs
    print("✓ days_past_close / days_past_original_close (negative = not yet past close) not flagged")


if __name__ == "__main__":
    test_real_forecast_trust_result_has_no_false_violations()
    test_missing_or_invalid_benchmark_is_flagged()
    test_offset_that_does_not_match_the_arithmetic_is_flagged()
    test_negative_real_durations_and_counts_are_still_flagged()
    test_other_signed_day_offsets_are_not_flagged()
    print("\n✅ All tests passed")
