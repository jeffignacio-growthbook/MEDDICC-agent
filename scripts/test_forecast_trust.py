#!/usr/bin/env python3
"""
Baseline tests for assess_forecast_trust() (Step C of the build).

These test the COMPOSING function's own logic — the week-3 gate, the
moving week-lookup, and stability-band/caveat assignment — not the
underlying primitives it composes (assess_deal_risk() and
query_commit_ml_calibration_by_week() have their own test coverage
already: scripts/test_deal_risk_assessor.py and
scripts/test_forecast_analyses.py). Those are mocked here at their
SOURCE module (deal_risk_assessor, forecast_analyses, snapshot_deals,
utils) rather than forecast_trust's own namespace, because
forecast_trust.py imports them locally inside assess_forecast_trust()
on every call — patching the source module's attribute is what
actually takes effect.

Covers the three realistic week bands from the confirmed design:
1. Below week 3 — insufficient_data/too_early, hard gate.
2. Mid-quarter (week 7, "settled" band, directional caveat still
   applies since 7 < 10).
3. Late-quarter (week 12, "late_quarter" band, no directional caveat,
   but the lost-collapse caveat note applies instead).

Step D adds two more tests to this same file (matching
test_forecast_analyses.py's convention of mixing structural and
defect-specific regression tests in one file, rather than splitting):
4. Planted-discrepancy proof that the historical lookup genuinely
   varies by week — not defaulting to one row or a cached value.
5. MOST_LIKELY-only, non-late-stage deal regression test — the single
   most important test here, directly guarding against
   assess_forecast_trust() silently reverting to get_at_risk_deals()'s
   narrower COMMIT-only scope.
"""
import sys
from pathlib import Path
from datetime import date
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "analytics"))

from forecast_trust import assess_forecast_trust, EARLY_QUARTER_GATE_WEEK, CALIBRATION_EVIDENCE_WEEK


sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))
from strict_supabase import StrictSupabase  # noqa: E402


def _mock_deals_sb(deals_data, analyses_data=None):
    """A strict fake (tests/strict_supabase.py) holding `deals` (and
    `analyses`, for assess_deal_risk's MEDDICC fetch): only selected columns
    come back, every filter applies, and a column or table that isn't in the
    real schema raises, as Postgres would. Until 2026-09-24 this was a
    MagicMock chain that returned the same rows to every query whatever it
    selected or filtered."""
    return StrictSupabase({"deals": deals_data, "analyses": analyses_data or []})


def _mock_multi_table_sb(deals_data, analyses_data=None):
    sb = _mock_deals_sb(deals_data, analyses_data)
    return sb, sb, sb


class _NoQuerySB:
    def table(self, name):
        raise AssertionError(f"the week-3 gate must make no queries (asked for {name!r})")


def _fake_calibration_table():
    """A deterministic, DIFFERENT-per-week by_week table so tests can prove
    the right week's row was actually used, not a coincidence."""
    by_week = {}
    for w in range(1, 14):
        by_week[w] = {
            'n_tagged': 50 + w, 'classified': 40 + w,
            'won': 10 + w, 'lost': 5, 'slipped': 25,
            'win_rate': round((10 + w) / (40 + w), 4),
            'reason': None,
        }
    return {
        'by_week': by_week,
        'categories': ['COMMIT', 'MOST_LIKELY'],
        'quarters_analyzed': 4,
        'complete_quarters': ['FY2026 Q3', 'FY2026 Q4', 'FY2027 Q1', 'FY2027 Q2'],
        'min_evidence_count': 30,
    }


def test_week_below_gate_returns_insufficient_data():
    """
    Below EARLY_QUARTER_GATE_WEEK (3), assess_forecast_trust must return
    insufficient_data/too_early and must NOT reach the deals query, risk
    assessment, or calibration lookup at all — the gate is a hard stop,
    not a caveated partial result.
    """
    print("\n[TEST] Week < 3 → insufficient_data/too_early hard gate")

    with patch('utils.get_fiscal_quarter') as mock_gfq, \
         patch('snapshot_deals.get_week_of_quarter') as mock_gwoq, \
         patch('deal_risk_assessor.assess_deal_risk') as mock_risk, \
         patch('forecast_analyses.query_commit_ml_calibration_by_week') as mock_calib:
        mock_gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), 'FY2026 Q3')
        mock_gwoq.return_value = 2  # week 2 — below the gate

        sb = _NoQuerySB()  # .table() raises: the gate must never query
        result = assess_forecast_trust(sb, as_of=date(2026, 8, 10))

        if mock_risk.called:
            raise AssertionError(
                "assess_deal_risk() was called despite the week-2 gate — "
                "the gate must be a hard stop before any downstream query")
        if mock_calib.called:
            raise AssertionError(
                "query_commit_ml_calibration_by_week() was called despite "
                "the week-2 gate — same hard-stop requirement")

    if result.get('status') != 'insufficient_data':
        raise AssertionError(f"Expected status='insufficient_data', got {result.get('status')!r}")
    if result.get('reason') != 'too_early':
        raise AssertionError(f"Expected reason='too_early', got {result.get('reason')!r}")
    if result.get('current_week') != 2:
        raise AssertionError(f"Expected current_week=2, got {result.get('current_week')!r}")
    if result.get('gate_week') != EARLY_QUARTER_GATE_WEEK:
        raise AssertionError(f"Expected gate_week={EARLY_QUARTER_GATE_WEEK}, got {result.get('gate_week')!r}")
    print("  ✓ Gated correctly; no downstream calls made")


def test_mid_quarter_settled_band_with_directional_caveat():
    """
    Week 7 (of 13): inside the "settled" stability band (7-10), but still
    below week 10 — the directional caveat must still apply (the current
    quarter's cohort hasn't had as much time to resolve as the historical
    week-10 cohort had). Historical figures must come from week 7's row,
    not week 10's or any other week's.
    """
    print("\n[TEST] Week 7 → settled band, directional caveat still applies")

    deals_data = [
        {'deal_id': 'd1', 'company_name': 'Acme', 'stage': 'presentationscheduled',
         'create_date': '2026-06-01', 'close_date': '2026-09-15', 'segment': 'Mid-Market',
         'forecast_category': 'COMMIT', 'deal_status': 'active', 'new_arr': 50000, 'expansion_arr': None},
        {'deal_id': 'd2', 'company_name': 'Beta', 'stage': 'decisionmakerboughtin',
         'create_date': '2026-06-15', 'close_date': '2026-09-20', 'segment': 'SMB',
         'forecast_category': 'MOST_LIKELY', 'deal_status': 'active', 'new_arr': None, 'expansion_arr': 20000},
    ]
    sb = _mock_deals_sb(deals_data)
    fake_calib = _fake_calibration_table()
    fake_risk_result = {
        'assessed_deals': [
            {**deals_data[0], 'overall_label': 'high_risk', 'days_open': 100},
            {**deals_data[1], 'overall_label': 'low_risk', 'days_open': 20},
        ],
        'summary': {'total_assessed': 2, 'high_risk': 1, 'moderate_risk': 0,
                    'low_risk': 1, 'insufficient_data': 0},
    }

    with patch('utils.get_fiscal_quarter') as mock_gfq, \
         patch('snapshot_deals.get_week_of_quarter') as mock_gwoq, \
         patch('deal_risk_assessor.assess_deal_risk') as mock_risk, \
         patch('forecast_analyses.query_commit_ml_calibration_by_week') as mock_calib:
        mock_gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), 'FY2026 Q3')
        mock_gwoq.return_value = 7
        mock_risk.return_value = fake_risk_result
        mock_calib.return_value = fake_calib

        result = assess_forecast_trust(sb, as_of=date(2026, 9, 18))

    if result.get('status') != 'ok':
        raise AssertionError(f"Expected status='ok', got {result.get('status')!r}: {result}")
    if result.get('current_week') != 7:
        raise AssertionError(f"Expected current_week=7, got {result.get('current_week')!r}")
    if result.get('stability') != 'settled':
        raise AssertionError(f"Expected stability='settled' for week 7, got {result.get('stability')!r}")
    if result.get('directional_caveat') is not True:
        raise AssertionError(
            f"Expected directional_caveat=True for week 7 (< week {CALIBRATION_EVIDENCE_WEEK}), "
            f"got {result.get('directional_caveat')!r}")

    expected_week7 = fake_calib['by_week'][7]
    if result['historical']['win_rate'] != expected_week7['win_rate']:
        raise AssertionError(
            f"historical.win_rate should be week 7's rate "
            f"({expected_week7['win_rate']}), got {result['historical']['win_rate']}")
    if result['historical']['week'] != 7:
        raise AssertionError(f"historical.week should be 7, got {result['historical']['week']}")

    expected_week10 = fake_calib['by_week'][10]
    if result['calibration_evidence']['win_rate'] != expected_week10['win_rate']:
        raise AssertionError(
            f"calibration_evidence should always be week 10's rate "
            f"({expected_week10['win_rate']}), got {result['calibration_evidence']['win_rate']}")

    if result['pipeline']['deal_count'] != 2:
        raise AssertionError(f"Expected 2 deals in pipeline, got {result['pipeline']['deal_count']}")
    if result['pipeline']['incremental_arr'] != 70000:
        raise AssertionError(f"Expected pipeline incremental_arr=70000, got {result['pipeline']}")
    if result['high_risk_count'] != 1 or result['high_risk_fraction'] != 0.5:
        raise AssertionError(
            f"Expected high_risk_count=1, high_risk_fraction=0.5, got "
            f"{result['high_risk_count']}, {result['high_risk_fraction']}")
    from forecast_trust import plain_baseline_sentence
    if result['note'] != plain_baseline_sentence(expected_week7['win_rate'], 7):
        raise AssertionError(f"Expected the plain-language week-7 caveat, got: {result['note']!r}")
    print("  ✓ Settled band, directional caveat present, week-7 row used (not week 10's)")


def test_late_quarter_week_12_lost_collapse_caveat():
    """
    Week 12 (of 13): "late_quarter" band, directional caveat must NOT
    apply (12 >= week 10), but the lost-collapse caveat note must appear
    instead — a different caveat, not simply "no caveat at all".
    """
    print("\n[TEST] Week 12 → late_quarter band, lost-collapse caveat (not directional)")

    sb = _mock_deals_sb([])  # empty pipeline is fine — this test is about banding/caveat text
    fake_calib = _fake_calibration_table()

    with patch('utils.get_fiscal_quarter') as mock_gfq, \
         patch('snapshot_deals.get_week_of_quarter') as mock_gwoq, \
         patch('deal_risk_assessor.assess_deal_risk') as mock_risk, \
         patch('forecast_analyses.query_commit_ml_calibration_by_week') as mock_calib:
        mock_gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), 'FY2026 Q3')
        mock_gwoq.return_value = 12
        mock_risk.return_value = {
            'assessed_deals': [],
            'summary': {'total_assessed': 0, 'high_risk': 0, 'moderate_risk': 0,
                        'low_risk': 0, 'insufficient_data': 0},
        }
        mock_calib.return_value = fake_calib

        result = assess_forecast_trust(sb, as_of=date(2026, 10, 24))

    if result.get('stability') != 'late_quarter':
        raise AssertionError(f"Expected stability='late_quarter' for week 12, got {result.get('stability')!r}")
    if result.get('directional_caveat') is not False:
        raise AssertionError(
            f"Expected directional_caveat=False for week 12 (>= week "
            f"{CALIBRATION_EVIDENCE_WEEK}), got {result.get('directional_caveat')!r}")
    if 'lost' not in result['note'].lower() or 'collaps' not in result['note'].lower():
        raise AssertionError(
            f"Expected the late-quarter lost-collapse caveat in the note, got: {result['note']!r}")
    if result['historical']['week'] != 12:
        raise AssertionError(f"historical.week should be 12, got {result['historical']['week']}")
    print("  ✓ Late-quarter band correctly distinguished from a plain no-caveat result")


def test_historical_lookup_genuinely_varies_by_week():
    """
    PLANTED-DISCREPANCY TEST: the historical win_rate returned must track
    the ACTUAL current week, not default to one row or a cached value.

    Runs assess_forecast_trust() at four distinct weeks spanning three
    different stability bands (4=forming, 7 & 9=settled, 12=late_quarter),
    against a calibration table where every week has a DELIBERATELY
    different win_rate (_fake_calibration_table()'s w-dependent formula).
    Asserts each call returns EXACTLY that week's rate, AND that the four
    observed rates are not all equal — the second check is what actually
    catches a hardcoded-week or caching bug: a implementation that always
    returned (say) week 7's row would pass a single-week assertion by
    coincidence if that happened to be the week under test, but cannot
    pass this check across four different weeks with four different
    planted values.
    """
    print("\n[TEST] Historical lookup genuinely varies by week (planted discrepancy)")

    fake_calib = _fake_calibration_table()
    weeks_to_check = [4, 7, 9, 12]  # forming, settled, settled, late_quarter
    observed_rates = []

    for week in weeks_to_check:
        sb = _mock_deals_sb([])
        with patch('utils.get_fiscal_quarter') as mock_gfq, \
             patch('snapshot_deals.get_week_of_quarter') as mock_gwoq, \
             patch('deal_risk_assessor.assess_deal_risk') as mock_risk, \
             patch('forecast_analyses.query_commit_ml_calibration_by_week') as mock_calib:
            mock_gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), 'FY2026 Q3')
            mock_gwoq.return_value = week
            mock_risk.return_value = {
                'assessed_deals': [],
                'summary': {'total_assessed': 0, 'high_risk': 0, 'moderate_risk': 0,
                            'low_risk': 0, 'insufficient_data': 0},
            }
            mock_calib.return_value = fake_calib

            result = assess_forecast_trust(sb, as_of=date(2026, 9, 1))

        expected = fake_calib['by_week'][week]['win_rate']
        actual = result['historical']['win_rate']
        if actual != expected:
            raise AssertionError(
                f"Week {week}: expected historical.win_rate={expected} "
                f"(that week's planted value), got {actual} — the lookup is "
                f"not tracking the actual current week")
        if result['historical']['week'] != week:
            raise AssertionError(
                f"Week {week}: expected historical.week={week}, got "
                f"{result['historical']['week']}")
        observed_rates.append(actual)
        print(f"  ✓ week {week}: historical.win_rate = {actual} (matches planted value)")

    if len(set(observed_rates)) == 1:
        raise AssertionError(
            f"All four weeks returned the SAME win_rate ({observed_rates[0]}) — "
            f"this would happen if the lookup silently defaulted to one row "
            f"or cached its first result instead of genuinely varying by week. "
            f"Observed: {observed_rates}")
    print(f"  ✓ All {len(weeks_to_check)} weeks returned genuinely distinct rates: {observed_rates}")


def test_most_likely_only_non_late_stage_deal_appears_in_cohort():
    """
    THE MOST IMPORTANT TEST IN THIS BATCH.

    A deal tagged forecast_category='MOST_LIKELY' that is NOT late-stage
    (not Negotiating/Awaiting Signature) must still appear in
    assess_forecast_trust()'s assessed cohort. This is the direct
    regression guard for the gap found during Step A:
    get_at_risk_deals() hardcodes forecast_category='COMMIT' in its own
    query, so a MOST_LIKELY-only, non-late-stage deal would be silently
    invisible to it. assess_forecast_trust() was deliberately built with
    its OWN query instead of calling get_at_risk_deals() — this test
    fails loudly if a future refactor ever routes it back through that
    narrower path.

    Uses the REAL, unmocked deal_risk_assessor.assess_deal_risk() (only
    the calibration lookup and week/quarter resolution are mocked) so
    this is a genuine end-to-end check that the deal survives the whole
    pipeline, not just that a mock was told to include it.
    """
    print("\n[TEST] MOST_LIKELY-only, non-late-stage deal appears in the assessed cohort")

    from deal_risk_assessor import LATE_STAGE_IDS
    non_late_stage = 'presentationscheduled'
    if non_late_stage in LATE_STAGE_IDS:
        raise AssertionError(
            f"Test setup error: {non_late_stage!r} is a late-stage id "
            f"({LATE_STAGE_IDS}) — pick a genuinely non-late-stage stage "
            f"or this test doesn't prove what it claims to")

    test_deal = {
        'deal_id': 'ml_only_test_deal',
        'company_name': 'Most Likely Only Co',
        'stage': non_late_stage,
        'create_date': '2026-08-05',
        'close_date': '2026-09-30',
        'segment': 'Mid-Market',
        'forecast_category': 'MOST_LIKELY',
        'deal_status': 'active',
        'new_arr': 42000,
    }

    sb, deals_chain, analyses_chain = _mock_multi_table_sb(
        deals_data=[test_deal], analyses_data=[])
    fake_calib = _fake_calibration_table()

    with patch('utils.get_fiscal_quarter') as mock_gfq, \
         patch('snapshot_deals.get_week_of_quarter') as mock_gwoq, \
         patch('forecast_analyses.query_commit_ml_calibration_by_week') as mock_calib:
        mock_gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), 'FY2026 Q3')
        mock_gwoq.return_value = 7  # settled band, clean mid-quarter week
        mock_calib.return_value = fake_calib
        # deal_risk_assessor.assess_deal_risk is DELIBERATELY NOT mocked here.

        result = assess_forecast_trust(sb, as_of=date(2026, 9, 18))

    if result.get('status') != 'ok':
        raise AssertionError(f"Expected status='ok', got {result.get('status')!r}: {result}")

    if result['pipeline']['deal_count'] != 1:
        raise AssertionError(
            f"Expected the MOST_LIKELY-only deal in the pipeline query "
            f"result, got deal_count={result['pipeline']['deal_count']}")

    assessed_ids = [d['deal_id'] for d in result['assessed_deals']]
    if 'ml_only_test_deal' not in assessed_ids:
        raise AssertionError(
            f"THE MOST_LIKELY-only, non-late-stage deal did NOT appear in "
            f"assessed_deals ({assessed_ids}) — this means the primitive "
            f"has silently reverted to a COMMIT-only (or late-stage-only) "
            f"scope, the exact regression this test exists to catch")
    print(f"  ✓ MOST_LIKELY-only deal 'ml_only_test_deal' found in assessed_deals")

    # Prove it via the QUERY, not just the mocked data. This assertion is
    # load-bearing, not redundant with the assessed_deals check above:
    # verified by planting a COMMIT-only regression here and re-running —
    # the mock still returned the test deal regardless (a Mock doesn't
    # simulate real Postgres filtering), so the assessed_deals check alone
    # passed even with the bug reintroduced. Only this query-shape check
    # actually caught it.
    in_filters = [f for q in sb.queries if q["table"] == "deals" for f in q["filters"]
                  if f[0] == "in" and f[1] == "forecast_category"]
    category_calls = [(f[1], f[2]) for f in in_filters]
    if not category_calls:
        raise AssertionError("assess_forecast_trust() never called .in_('forecast_category', ...)")
    categories_queried = category_calls[0][1]
    if 'MOST_LIKELY' not in categories_queried or 'COMMIT' not in categories_queried:
        raise AssertionError(
            f"Expected the deals query to filter on BOTH COMMIT and "
            f"MOST_LIKELY, got: {categories_queried}")
    print(f"  ✓ Underlying query used forecast_category IN {categories_queried} "
          f"(not COMMIT-only)")


def test_dollars_are_incremental_arr_from_real_columns():
    """
    2026-09-23: the deals query selected `amount`, a column that has never
    existed in `deals`, so every production call failed ("column
    deals.amount does not exist", 7 Postgres log errors 2026-09-21 23:55 -
    2026-09-23 00:23 UTC). The mocks here returned whatever keys the test
    wanted, so they passed. Now the dollars are incremental_arr() (new_arr +
    expansion_arr, the quota basis); count, sum and risk all use the same
    incremental deals (is_incremental_pipeline, as Gate 3), and deals with
    no incremental ARR (pure renewals) are reported, not silently counted.
    """
    print("\n[TEST] Dollars = incremental_arr() from real columns; same population for count/sum/risk")
    deals_data = [
        {'deal_id': 'n1', 'company_name': 'NewCo', 'stage': 's', 'create_date': '2026-06-01',
         'close_date': '2026-09-15', 'segment': 'SMB', 'forecast_category': 'COMMIT',
         'deal_status': 'active', 'pipeline_id': 'default', 'new_arr': 30000, 'expansion_arr': None},
        {'deal_id': 'x1', 'company_name': 'ExpandCo', 'stage': 's', 'create_date': '2026-06-01',
         'close_date': '2026-09-20', 'segment': 'SMB', 'forecast_category': 'MOST_LIKELY',
         'deal_status': 'active', 'pipeline_id': '866608541', 'new_arr': None, 'expansion_arr': 12000,
         'renewal_revenue': 90000},
        {'deal_id': 'r1', 'company_name': 'RenewCo', 'stage': 's', 'create_date': '2026-06-01',
         'close_date': '2026-09-25', 'segment': 'SMB', 'forecast_category': 'COMMIT',
         'deal_status': 'active', 'pipeline_id': '866608541', 'new_arr': None, 'expansion_arr': None,
         'renewal_revenue': 200000},
    ]
    sb = _mock_deals_sb(deals_data)
    risk_inputs = []

    def fake_risk(deals, _sb):
        risk_inputs.append([d['deal_id'] for d in deals])
        return {'assessed_deals': [], 'summary': {'total_assessed': len(deals), 'high_risk': 0}}

    with patch('utils.get_fiscal_quarter') as mock_gfq, \
         patch('snapshot_deals.get_week_of_quarter') as mock_gwoq, \
         patch('deal_risk_assessor.assess_deal_risk', side_effect=fake_risk), \
         patch('forecast_analyses.query_commit_ml_calibration_by_week') as mock_calib:
        mock_gfq.return_value = (date(2026, 8, 1), date(2026, 10, 31), 'FY2027 Q3')
        mock_gwoq.return_value = 8
        mock_calib.return_value = _fake_calibration_table()
        result = assess_forecast_trust(sb, as_of=date(2026, 9, 23))

    # The cohort query is the first select (a COMMIT close-date hygiene query
    # follows it, 2026-09-24); no query may select `amount`.
    all_selects = [cols for cols in sb.selected("deals")]
    for cols in all_selects:
        if 'amount' in cols:
            raise AssertionError(f"deals has no `amount` column; a query selects {cols}")
    selected = all_selects[0]
    if not {'new_arr', 'expansion_arr'} <= set(selected):
        raise AssertionError(f"incremental_arr() needs new_arr and expansion_arr; selected {selected}")
    p = result['pipeline']
    if p.get('incremental_arr') != 42000 or p.get('deal_count') != 2:
        raise AssertionError(f"Expected 2 incremental deals worth $42,000 (renewal base excluded), got {p}")
    if p.get('excluded_no_incremental_arr') != 1:
        raise AssertionError(f"The pure-renewal deal must be reported as excluded, got {p}")
    if risk_inputs != [['n1', 'x1']]:
        raise AssertionError(f"Risk must be assessed on the same 2 deals as the count and sum, got {risk_inputs}")
    print("  ✓ selects new_arr/expansion_arr (no `amount`); $42,000 over 2 deals; "
          "pure renewal excluded and reported; risk on the same 2 deals")


def main():
    tests = [
        test_week_below_gate_returns_insufficient_data,
        test_mid_quarter_settled_band_with_directional_caveat,
        test_late_quarter_week_12_lost_collapse_caveat,
        test_historical_lookup_genuinely_varies_by_week,
        test_most_likely_only_non_late_stage_deal_appears_in_cohort,
        test_dollars_are_incremental_arr_from_real_columns,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"\n  ❌ FAILED: {e}")

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = len(tests) - len(failed)
    print(f"\nTotal tests: {len(tests)}")
    print(f"  ✓ Passed: {passed}")

    if failed:
        print(f"  ✗ Failed: {len(failed)}")
        print("\nFailed tests:")
        for name, error in failed:
            print(f"  - {name}")
            print(f"    {error[:200]}")
        return 1

    print("\n✅ All assess_forecast_trust() baseline tests passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
