#!/usr/bin/env python3
"""
Deal value rule: Incremental ARR, amount fallback, Renewal ARR.

GrowthBook's deal value is Incremental ARR (new_revenue + expansion_revenue),
verified equal to HubSpot's incremental_arr for all 1,523 deals where HubSpot
populates it. Two rules the plain NULL-safe sum got wrong:

  1. All components blank/null -> Incremental ARR is unknown, not zero, so
     fall back to amount. A component present and zero is a real value and
     must NOT trigger the fallback.
  2. Renewal-pipeline deals are Incremental ARR + Renewal ARR
     (renewal_revenue). incremental_arr carries only the expansion above the
     renewed base, so renewals without expansion computed to 0.

Usage:
    PYTHONPATH=scripts:api:. python3 scripts/eval_deal_value.py
"""
import sys
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from utils import compute_deal_value, get_value_properties

CONFIG = yaml.safe_load((REPO_ROOT / 'config/client.yaml').read_text())
RENEWAL = '866608541'


def test_incremental_arr_is_the_value():
    """new_revenue + expansion_revenue, NULL-safe."""
    print("\n[TEST] Incremental ARR is the value")
    assert compute_deal_value({'new_revenue': '40000', 'expansion_revenue': '0'},
                              CONFIG, pipeline_id='default') == 40000
    assert compute_deal_value({'new_revenue': '30000', 'expansion_revenue': '10000'},
                              CONFIG, pipeline_id='default') == 40000
    # Currency formatting must survive.
    assert compute_deal_value({'new_revenue': '$1,500.50'},
                              CONFIG, pipeline_id='default') == 1500.50
    print("  ✓ components summed NULL-safely")


def test_blank_incremental_arr_falls_back_to_amount():
    """All components blank -> amount. Never silently zero."""
    print("\n[TEST] Blank Incremental ARR falls back to amount")
    assert compute_deal_value({'amount': '75000'},
                              CONFIG, pipeline_id='default') == 75000
    for blank in (None, '', 'null'):
        got = compute_deal_value(
            {'new_revenue': blank, 'expansion_revenue': blank, 'amount': '50000'},
            CONFIG, pipeline_id='default')
        assert got == 50000, f"blank={blank!r} should fall back, got {got}"
    print("  ✓ blank/None/'null' components fall back to amount")


def test_present_zero_does_not_trigger_fallback():
    """A component present and zero is a real $0, not missing data.

    This is the line between the two: falling back on a real zero would
    invent revenue from the amount field, which is not the value field.
    """
    print("\n[TEST] Present-zero does not trigger the fallback")
    got = compute_deal_value(
        {'new_revenue': '0', 'expansion_revenue': '0', 'amount': '99999'},
        CONFIG, pipeline_id='default')
    assert got == 0, f"a real zero must stay zero, got {got}"
    # One component present, the other blank -> still no fallback.
    got = compute_deal_value(
        {'new_revenue': '0', 'expansion_revenue': None, 'amount': '99999'},
        CONFIG, pipeline_id='default')
    assert got == 0, f"one present component is enough to suppress fallback, got {got}"
    print("  ✓ real zeros are preserved; amount is not substituted")


def test_renewal_adds_renewal_arr():
    """Renewal deals are Incremental ARR + Renewal ARR."""
    print("\n[TEST] Renewal deals add Renewal ARR")
    assert compute_deal_value(
        {'new_revenue': '0', 'expansion_revenue': '40000',
         'renewal_revenue': '54000'}, CONFIG, pipeline_id=RENEWAL) == 94000
    # The case that previously computed to 0: renewal with no expansion.
    assert compute_deal_value(
        {'new_revenue': '0', 'expansion_revenue': '0',
         'renewal_revenue': '242000'}, CONFIG, pipeline_id=RENEWAL) == 242000
    print("  ✓ renewal without expansion is no longer valued at 0")


def test_renewal_arr_ignored_outside_renewal_pipeline():
    """renewal_revenue must not inflate new-business deals."""
    print("\n[TEST] Renewal ARR ignored outside the renewal pipeline")
    props = {'new_revenue': '0', 'expansion_revenue': '0',
             'renewal_revenue': '242000'}
    assert compute_deal_value(props, CONFIG, pipeline_id='default') == 0
    # No pipeline_id: cannot know it is a renewal, so value as new business
    # rather than guessing.
    assert compute_deal_value(props, CONFIG, pipeline_id=None) == 0
    print("  ✓ renewal component applies only to renewal_pipeline_ids")


def test_renewal_falls_back_only_when_both_blank():
    """Falling back while also adding Renewal ARR would double-count.

    amount equals the renewed base for 89% of renewals carrying both
    prior_arr and amount, so amount is the base, not an increment.
    """
    print("\n[TEST] Renewal falls back only when both are blank")
    assert compute_deal_value({'amount': '175000'},
                              CONFIG, pipeline_id=RENEWAL) == 175000
    # Renewal ARR present -> no fallback, no double count.
    got = compute_deal_value({'renewal_revenue': '54000', 'amount': '54000'},
                             CONFIG, pipeline_id=RENEWAL)
    assert got == 54000, f"must not add amount on top of Renewal ARR, got {got}"
    print("  ✓ no double-counting of the renewed base")


def test_etl_fetches_every_value_property():
    """A component the ETL never fetches reads as blank forever.

    renewal_revenue was absent from every fetch list in the repo, which is
    why renewal deals valued at 0.
    """
    print("\n[TEST] ETL fetches every value property")
    props = get_value_properties(CONFIG)
    vf = CONFIG['pipeline']['value_field']
    for name in (list(vf['components']) + [vf['fallback']]
                 + list(vf['renewal_components'])):
        assert name in props, f"{name} missing from get_value_properties()"

    # And the analytics fetch list must actually request them.
    fetch_src = (REPO_ROOT / 'scripts/hubspot_deals.py').read_text()
    for name in props:
        assert f"'{name}'" in fetch_src, \
            f"{name} is a value property but hubspot_deals.py never fetches it"
    print(f"  ✓ {props} all fetched")


def main():
    print("=" * 70)
    print("DEAL VALUE RULE TESTS")
    print("=" * 70)
    tests = [
        test_incremental_arr_is_the_value,
        test_blank_incremental_arr_falls_back_to_amount,
        test_present_zero_does_not_trigger_fallback,
        test_renewal_adds_renewal_arr,
        test_renewal_arr_ignored_outside_renewal_pipeline,
        test_renewal_falls_back_only_when_both_blank,
        test_etl_fetches_every_value_property,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    print()
    print("=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
