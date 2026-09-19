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

Planted-discrepancy proof that the lookup genuinely varies by week
(not defaulting to one row), and the MOST_LIKELY-only regression test,
are Step D — separate file, separate purpose.
"""
import sys
from pathlib import Path
from datetime import date
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "analytics"))

from forecast_trust import assess_forecast_trust, EARLY_QUARTER_GATE_WEEK, CALIBRATION_EVIDENCE_WEEK


def _mock_deals_sb(deals_data):
    """A Supabase mock whose .table('deals').select(...)...execute() chain
    returns the given rows, for whatever combination of .in_/.eq/.gte/.lte
    assess_forecast_trust's own query happens to call."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.in_.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.lte.return_value = chain
    chain.execute.return_value = Mock(data=deals_data)
    sb = Mock()
    sb.table = Mock(return_value=chain)
    return sb


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

        sb = Mock()  # deliberately no .table() wired up — must never be called
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
         'forecast_category': 'COMMIT', 'deal_status': 'active', 'amount': 50000},
        {'deal_id': 'd2', 'company_name': 'Beta', 'stage': 'decisionmakerboughtin',
         'create_date': '2026-06-15', 'close_date': '2026-09-20', 'segment': 'SMB',
         'forecast_category': 'MOST_LIKELY', 'deal_status': 'active', 'amount': 20000},
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
    if result['pipeline']['amount'] != 70000:
        raise AssertionError(f"Expected pipeline amount=70000, got {result['pipeline']['amount']}")
    if result['high_risk_count'] != 1 or result['high_risk_fraction'] != 0.5:
        raise AssertionError(
            f"Expected high_risk_count=1, high_risk_fraction=0.5, got "
            f"{result['high_risk_count']}, {result['high_risk_fraction']}")
    if 'directional' not in result['note'].lower():
        raise AssertionError(f"Expected a directional caveat in the note text, got: {result['note']!r}")
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


def main():
    tests = [
        test_week_below_gate_returns_insufficient_data,
        test_mid_quarter_settled_band_with_directional_caveat,
        test_late_quarter_week_12_lost_collapse_caveat,
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
