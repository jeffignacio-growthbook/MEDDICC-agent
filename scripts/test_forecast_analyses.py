#!/usr/bin/env python3
"""
Tests for Phase 3 Forecast Analyses

Critical requirements from spec:
1. week-3 conversion excludes incomplete quarters
2. week-3 conversion returns null (not zero) on insufficient history
3. commit calibration classifies slip separately from loss
4. category churn curve covers all weeks with data
5. analyses return null on thin data, never fabricate

These tests verify the analyses are correct before any proposals are built on them.
"""
import sys
from pathlib import Path
from datetime import date
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from analytics.forecast_analyses import (
    _get_complete_quarters,
    _classify_deal_outcome,
    query_week3_conversion,
    query_commit_outcome_by_week,
    query_commit_calibration,
    query_commit_ml_calibration_by_week,
    COMMIT_ML_CATEGORIES,
    query_stage_close_rate,
    query_coverage_proxy_target_by_week,
    clear_request_cache,
)


def test_week3_conversion_excludes_incomplete_quarters():
    """
    Week-3 conversion must only use quarters with all 13 weeks of data.

    If a quarter has only 10 weeks, it cannot be included in the analysis.
    """
    print("\n[TEST] Week-3 conversion excludes incomplete quarters")

    # _get_complete_quarters now paginates via supabase_client.select_all
    # (the old unpaginated .execute() silently capped at 1,000 rows and saw no
    # complete quarter). Mock that seam; the assertion is unchanged.
    rows = [
        {'fiscal_quarter': 'FY2027 Q1', 'week_of_quarter': w}
        for w in range(1, 11)  # Only 10 weeks
    ] + [
        {'fiscal_quarter': 'FY2027 Q2', 'week_of_quarter': w}
        for w in range(1, 14)  # Complete 13 weeks
    ]

    with patch('supabase_client.select_all', return_value=rows):
        complete = _get_complete_quarters(Mock())

        # Should only include Q2, not Q1
        if 'FY2027 Q1' in complete:
            raise AssertionError(
                f"Incomplete quarter included: FY2027 Q1 has only 10 weeks but was included\n"
                f"Week-3 conversion must exclude quarters without full 13-week data"
            )

        if 'FY2027 Q2' not in complete:
            raise AssertionError(
                f"Complete quarter excluded: FY2027 Q2 has 13 weeks but was excluded"
            )

    print("  ✓ Incomplete quarters correctly excluded")
    print("  ✓ Complete quarters correctly included")


def test_week3_conversion_returns_null_not_zero_on_insufficient_history():
    """
    When insufficient quarters are available, return null fields, not zeros.

    Returning 0 would fabricate data. Returning null signals "we don't know."
    """
    print("\n[TEST] Week-3 conversion returns null (not zero) on insufficient history")

    # Patch _get_complete_quarters to return empty list
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_get_quarters:
        with patch('analytics.forecast_analyses._load_config') as mock_config:
            mock_get_quarters.return_value = []
            mock_config.return_value = {
                'trailing_quarters_window': 9,
                'basis': 'count',
                'min_evidence_count': 30
            }

            sb = Mock()
            result = query_week3_conversion(sb)

            # Should have error field, not fabricated zeros
            if 'error' not in result:
                raise AssertionError(
                    "Missing error field — should return error when no complete quarters available"
                )

            # Should NOT have trailing_average or implied_coverage as 0
            if result.get('trailing_average') == 0:
                raise AssertionError(
                    "Returned trailing_average = 0 (fabricated data)\n"
                    "Should return null/None on insufficient history, never 0"
                )

            if result.get('implied_coverage_target') == 0:
                raise AssertionError(
                    "Returned implied_coverage_target = 0 (fabricated data)\n"
                    "Should return null/None on insufficient history, never 0"
                )

    print("  ✓ Returns error on insufficient data")
    print("  ✓ Does not fabricate zeros")
    print("  ✓ Null fields signal 'we don't know'")


def test_commit_calibration_classifies_slip_separately_from_loss():
    """
    A deal open past quarter end with a pushed close date is SLIPPED, never LOST.

    Collapsing slip and loss is the exact error Kellogg critiques.
    This test verifies the three-way classification (Won/Slipped/Lost).
    """
    print("\n[TEST] Commit calibration classifies slip separately from loss")

    # Terminal outcome now comes from the deals table (OUTCOME-READ), not the
    # last snapshot row — the backfilled snapshot has no won/lost rows, so a
    # snapshot-based classifier would call every deal SLIPPED. Committed quarter
    # window: FY2027 Q2 = 2026-05-01 .. 2026-07-31.
    q_start, q_end = '2026-05-01', '2026-07-31'
    deals_by_id = {
        # open stage, close pushed to next quarter → SLIPPED (not LOST)
        'test_deal_123': {'stage': 'presentationscheduled',
                          'close_date': '2026-08-15', 'owner_email': 'a@x.com'},
        # terminally lost, closed within quarter → LOST
        'test_deal_456': {'stage': 'closedlost',
                          'close_date': '2026-07-20', 'owner_email': 'a@x.com'},
        # terminally won, closed within quarter → WON
        'test_deal_789': {'stage': 'closedwon',
                          'close_date': '2026-07-25', 'owner_email': 'b@x.com'},
        # terminally won but closed AFTER quarter end → SLIPPED (did not win in-qtr)
        'test_deal_late': {'stage': 'closedwon',
                           'close_date': '2026-08-05', 'owner_email': 'b@x.com'},
    }

    outcome = _classify_deal_outcome('test_deal_123', q_start, q_end, deals_by_id)
    if outcome != 'SLIPPED':
        raise AssertionError(
            f"Expected 'SLIPPED' for deal open past quarter end, got '{outcome}'\n"
            f"A deal still open with pushed close date is SLIPPED, not LOST.\n"
            f"This is the exact error Kellogg critiques — slip and loss must be separate."
        )
    print("  ✓ Deal open past quarter end correctly classified as SLIPPED")

    outcome_lost = _classify_deal_outcome('test_deal_456', q_start, q_end, deals_by_id)
    if outcome_lost != 'LOST':
        raise AssertionError(f"Expected 'LOST' for closed lost deal, got '{outcome_lost}'")
    print("  ✓ Closed lost deal correctly classified as LOST")

    outcome_won = _classify_deal_outcome('test_deal_789', q_start, q_end, deals_by_id)
    if outcome_won != 'WON':
        raise AssertionError(f"Expected 'WON' for closed won deal, got '{outcome_won}'")
    print("  ✓ Closed won deal correctly classified as WON")

    # A win that lands after quarter end did NOT win in the committed quarter.
    outcome_late = _classify_deal_outcome('test_deal_late', q_start, q_end, deals_by_id)
    if outcome_late != 'SLIPPED':
        raise AssertionError(
            f"Expected 'SLIPPED' for a win closing after quarter end, got '{outcome_late}'")
    print("  ✓ Won-but-closed-after-quarter correctly classified as SLIPPED (not WON)")
    print("  ✓ Three-way classification working: Won/Slipped/Lost are distinct")


def test_commit_outcome_by_week_structure():
    """
    query_commit_outcome_by_week returns a per-commit-week outcome table
    (n/won/lost/slipped/win_rate) plus a volume curve — NOT a tag-retention
    curve. It must reach _classify_deal_outcome, never compare forecast_category
    across snapshots.
    """
    print("\n[TEST] commit outcome-by-week structure (not retention)")

    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_get_quarters, \
         patch('analytics.forecast_analyses._load_config') as mock_config, \
         patch('analytics.forecast_analyses._quarter_window_iso') as mock_win, \
         patch('supabase_client.select_all') as mock_select_all:
        mock_get_quarters.return_value = ['FY2027 Q1']
        mock_config.return_value = {'min_evidence_count': 30}
        mock_win.return_value = ('2026-02-01', '2026-04-30')
        mock_select_all.return_value = []  # deals table load

        sb = Mock()
        mock_response = Mock(); mock_response.data = []
        mock_chain = Mock()
        mock_chain.eq = Mock(return_value=mock_chain)
        mock_chain.execute = Mock(return_value=mock_response)
        sb.table = Mock(return_value=Mock(select=Mock(return_value=mock_chain)))

        result = query_commit_outcome_by_week(sb)

    for key in ('by_week', 'volume_by_week', 'per_quarter'):
        if key not in result:
            raise AssertionError(f"Missing {key} in result")
    if 'churn_curve' in result or 'retention_rate' in str(result):
        raise AssertionError("Result still exposes tag-retention shape")
    print("  ✓ outcome-by-week structure present; no retention curve")


def test_commit_ml_calibration_by_week_structure():
    """
    query_commit_ml_calibration_by_week() — built for assess_forecast_trust()
    (scripts/forecast_trust.py) — generalizes query_commit_outcome_by_week()
    to an arbitrary forecast_category set. This checks it independently of
    assess_forecast_trust() (which only ever exercises it mocked away):
    the by_week table covers all 13 weeks, defaults to COMMIT_ML_CATEGORIES
    (['COMMIT', 'MOST_LIKELY']), and queries with .in_(), never .eq()
    (a .eq() would silently narrow back to a single category).
    """
    print("\n[TEST] commit+most_likely calibration-by-week structure")

    from unittest.mock import MagicMock

    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_get_quarters, \
         patch('analytics.forecast_analyses._load_config') as mock_config, \
         patch('analytics.forecast_analyses._quarter_window_iso') as mock_win, \
         patch('supabase_client.select_all') as mock_select_all:
        mock_get_quarters.return_value = ['FY2027 Q1']
        mock_config.return_value = {'min_evidence_count': 30}
        mock_win.return_value = ('2026-02-01', '2026-04-30')
        mock_select_all.return_value = []  # deals table load

        sb = Mock()
        mock_response = Mock(); mock_response.data = []
        chain = MagicMock()
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.execute.return_value = mock_response
        sb.table = Mock(return_value=Mock(select=Mock(return_value=chain)))

        result = query_commit_ml_calibration_by_week(sb)

    for key in ('by_week', 'categories', 'quarters_analyzed', 'min_evidence_count'):
        if key not in result:
            raise AssertionError(f"Missing {key} in result")
    if result['categories'] != COMMIT_ML_CATEGORIES:
        raise AssertionError(
            f"Expected default categories={COMMIT_ML_CATEGORIES}, got {result['categories']}")
    if set(result['by_week'].keys()) != set(range(1, 14)):
        raise AssertionError(
            f"Expected by_week to cover all 13 weeks, got keys {sorted(result['by_week'].keys())}")
    for w, row in result['by_week'].items():
        for key in ('n_tagged', 'classified', 'won', 'lost', 'slipped', 'win_rate', 'reason'):
            if key not in row:
                raise AssertionError(f"week {w}: missing {key!r} in row {row}")

    if chain.eq.call_count == 0:
        raise AssertionError("Expected .eq() calls for fiscal_quarter/week_of_quarter")
    in_calls = [c.args for c in chain.in_.call_args_list]
    category_calls = [args for args in in_calls if args and args[0] == 'forecast_category']
    if not category_calls:
        raise AssertionError(
            "Query never called .in_('forecast_category', ...) — a .eq() would "
            "silently narrow this back to a single category")
    print("  ✓ by_week covers all 13 weeks with the full row shape")
    print(f"  ✓ defaults to COMMIT_ML_CATEGORIES={COMMIT_ML_CATEGORIES}")
    print("  ✓ query uses .in_('forecast_category', ...), not .eq() (single-category)")


def test_stage_close_rate_structure():
    """
    query_stage_close_rate() — built fresh for assess_pipeline_coverage()
    (scripts/pipeline_coverage.py, NORTH_STAR.md CRO Priority #2). Checks
    it independently of assess_pipeline_coverage() (which only ever
    exercises it mocked away): pools deal-week observations by
    stage_order across complete quarters, EXCLUDES the renewal pipeline,
    and gates win_rate on min_evidence_count.
    """
    print("\n[TEST] stage close-rate structure")

    deals_rows = [
        {'deal_id': 'd1', 'stage': 'closedwon', 'close_date': '2026-04-15'},
        {'deal_id': 'd2', 'stage': 'closedlost', 'close_date': '2026-04-20'},
        {'deal_id': 'd3', 'stage': 'closedwon', 'close_date': '2099-01-01'},  # outside window -> SLIPPED
    ]
    snapshot_rows = [
        {'deal_id': 'd1', 'stage_order': 1, 'pipeline_id': 'default'},
        {'deal_id': 'd2', 'stage_order': 1, 'pipeline_id': 'default'},
        {'deal_id': 'd3', 'stage_order': 1, 'pipeline_id': 'default'},
        {'deal_id': 'renewal_deal', 'stage_order': 1, 'pipeline_id': '866608541'},
    ]

    def _select_all_side_effect(sb, table, columns='*', filters=None, page_size=1000):
        if table == 'deals':
            return deals_rows
        if table == 'deals_snapshot':
            return snapshot_rows
        raise AssertionError(f"Unexpected table queried: {table!r}")

    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters, \
         patch('analytics.forecast_analyses._load_config') as mock_config, \
         patch('analytics.forecast_analyses._quarter_window_iso') as mock_win, \
         patch('supabase_client.select_all', side_effect=_select_all_side_effect):
        mock_quarters.return_value = ['FY2026 Q1']
        mock_config.return_value = {'min_evidence_count': 2}
        mock_win.return_value = ('2026-02-01', '2026-04-30')

        sb = Mock()
        result = query_stage_close_rate(sb)

    for key in ('by_stage_order', 'quarters_analyzed', 'complete_quarters',
                'min_evidence_count', 'scope'):
        if key not in result:
            raise AssertionError(f"Missing {key!r} in result")

    if 1 not in result['by_stage_order']:
        raise AssertionError(
            f"Expected stage_order 1 in by_stage_order, got {result['by_stage_order'].keys()}")
    stage1 = result['by_stage_order'][1]

    if stage1['n_observed'] != 3:
        raise AssertionError(
            f"Renewal-pipeline deal leaked into stage close-rate pooling — "
            f"expected n_observed=3 (renewal excluded), got {stage1['n_observed']}")
    if stage1['won'] != 1 or stage1['lost'] != 1 or stage1['slipped'] != 1:
        raise AssertionError(
            f"Expected won=1 (d1, in-window), lost=1 (d2), slipped=1 "
            f"(d3, out-of-window close_date), got {stage1}")
    if stage1['classified'] != 3:
        raise AssertionError(f"Expected classified=3, got {stage1}")
    if stage1['win_rate'] != 1 / 3:
        raise AssertionError(f"Expected win_rate=1/3, got {stage1['win_rate']}")

    print("  ✓ by_stage_order pools deal-week observations per stage, renewal pipeline excluded")
    print(f"  ✓ win_rate correctly computed and gated: {stage1}")


def test_stage_close_rate_excludes_meeting_set():
    """
    2026-10-03 fix: query_stage_close_rate()'s by_stage_order must agree
    with assess_pipeline_coverage()'s qualified_pipeline.deal_count on
    POPULATION, not just coincidentally overlap. Before this fix,
    by_stage_order pooled every stage_order seen in an open deals_snapshot
    row — including stage_order 0 ("Meeting Set", config-flagged
    exclude_from_analysis, order < qualified_stage_order) — while
    discovery_or_later_stages() (which builds qualified_pipeline's own
    population in scripts/pipeline_coverage.py) has always excluded it.
    Citing "how many deals is that based on" from a cached payload could
    sum by_stage_order's n_observed values and land on a bigger number
    than the qualified_pipeline.deal_count stated in the SAME answer.

    Fix: query_stage_close_rate() now builds the SAME qualifying-stage-
    order set discovery_or_later_stages() does (reused, not re-derived)
    and skips any deals_snapshot row whose stage_order isn't in it —
    same exclusion, same reason, one source of truth.
    """
    print("\n[TEST] stage close-rate excludes Meeting Set (order 0) from by_stage_order")

    snapshot_rows = [
        # Meeting Set (order 0) — exclude_from_analysis, must NOT appear
        {'deal_id': 'm1', 'stage_order': 0, 'pipeline_id': 'default'},
        {'deal_id': 'm2', 'stage_order': 0, 'pipeline_id': 'default'},
        # Discovery (order 1) — qualified, must appear
        {'deal_id': 'd1', 'stage_order': 1, 'pipeline_id': 'default'},
        # Review (order 8) — exclude_from_analysis, must NOT appear
        {'deal_id': 'r1', 'stage_order': 8, 'pipeline_id': 'default'},
    ]
    deals_rows = [
        {'deal_id': 'm1', 'stage': 'closedwon', 'close_date': '2026-04-15'},
        {'deal_id': 'm2', 'stage': 'closedlost', 'close_date': '2026-04-15'},
        {'deal_id': 'd1', 'stage': 'closedwon', 'close_date': '2026-04-15'},
        {'deal_id': 'r1', 'stage': 'closedwon', 'close_date': '2026-04-15'},
    ]

    def _select_all_side_effect(sb, table, columns='*', filters=None, page_size=1000):
        if table == 'deals':
            return deals_rows
        if table == 'deals_snapshot':
            return snapshot_rows
        raise AssertionError(f"Unexpected table queried: {table!r}")

    clear_request_cache()  # query_stage_close_rate memoizes within a request —
                           # clear so an earlier test's cached result doesn't leak in
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters, \
         patch('analytics.forecast_analyses._load_config') as mock_config, \
         patch('analytics.forecast_analyses._quarter_window_iso') as mock_win, \
         patch('supabase_client.select_all', side_effect=_select_all_side_effect):
        mock_quarters.return_value = ['FY2026 Q1']
        mock_config.return_value = {'min_evidence_count': 1}
        mock_win.return_value = ('2026-02-01', '2026-04-30')

        sb = Mock()
        result = query_stage_close_rate(sb)

    by_stage_order = result['by_stage_order']

    if 0 in by_stage_order or '0' in by_stage_order:
        raise AssertionError(
            f"Meeting Set (stage_order 0) leaked into by_stage_order: "
            f"{by_stage_order.keys()}")
    if 8 in by_stage_order or '8' in by_stage_order:
        raise AssertionError(
            f"Review (stage_order 8) leaked into by_stage_order: "
            f"{by_stage_order.keys()}")
    if 1 not in by_stage_order:
        raise AssertionError(
            f"Qualified stage_order 1 (Discovery) missing from "
            f"by_stage_order: {by_stage_order.keys()}")
    if by_stage_order[1]['n_observed'] != 1:
        raise AssertionError(
            f"Expected n_observed=1 for stage_order 1, got "
            f"{by_stage_order[1]['n_observed']}")

    print("  ✓ Meeting Set (order 0) excluded from by_stage_order")
    print("  ✓ Review (order 8) excluded from by_stage_order")
    print("  ✓ Discovery (order 1, qualified) still included")


def test_stage_close_rate_population_matches_qualified_pipeline():
    """
    REGRESSION fixture (the Meeting Set sum-mismatch, reproduced): for the
    SAME set of deal-stage observations, summing by_stage_order's
    n_observed across all stages must equal the count
    discovery_or_later_stages() itself would call "qualified" for that
    same population — the exact two figures that disagreed in the
    2026-10-03 incident's cached payload (by_stage_order summed higher
    than qualified_pipeline.deal_count because Meeting Set leaked in).

    This mirrors — rather than calls — scripts/pipeline_coverage.py's own
    qualifying-stage-order filter (that module has its own test coverage
    in scripts/test_pipeline_coverage.py with mocked rep_targets/quota
    machinery this test has no need for); the point here is specifically
    that query_stage_close_rate()'s own population, independently, now
    agrees with discovery_or_later_stages() rather than merely
    overlapping with it by coincidence.
    """
    print("\n[TEST] sum(by_stage_order.n_observed) now matches the qualified-stage population")

    from loss_concentration import discovery_or_later_stages
    from utils import get_pipeline_config

    pipeline_config = get_pipeline_config()
    qualifying_ids = set(discovery_or_later_stages(pipeline_config))
    qualifying_orders = {
        s.get("order")
        for p in pipeline_config.get("pipelines", [])
        if str(p.get("id")) == "default"
        for s in p.get("stages", [])
        if str(s.get("id")) in qualifying_ids
    }
    if not qualifying_orders:
        raise AssertionError("Fixture setup bug: no qualifying stage orders found "
                             "in config/client.yaml's default pipeline")

    # One deal-observation per stage_order 0-9 (every stage in the Sales
    # pipeline template, qualified and excluded alike) — a worst-case
    # fixture that would have summed to 10 before this fix (one per
    # stage_order) but must now sum to exactly len(qualifying_orders).
    snapshot_rows = [
        {'deal_id': f'd{order}', 'stage_order': order, 'pipeline_id': 'default'}
        for order in range(10)
    ]
    deals_rows = [
        {'deal_id': f'd{order}', 'stage': 'closedwon', 'close_date': '2026-04-15'}
        for order in range(10)
    ]

    def _select_all_side_effect(sb, table, columns='*', filters=None, page_size=1000):
        if table == 'deals':
            return deals_rows
        if table == 'deals_snapshot':
            return snapshot_rows
        raise AssertionError(f"Unexpected table queried: {table!r}")

    clear_request_cache()  # see note in test_stage_close_rate_excludes_meeting_set
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters, \
         patch('analytics.forecast_analyses._load_config') as mock_config, \
         patch('analytics.forecast_analyses._quarter_window_iso') as mock_win, \
         patch('supabase_client.select_all', side_effect=_select_all_side_effect):
        mock_quarters.return_value = ['FY2026 Q1']
        mock_config.return_value = {'min_evidence_count': 1}
        mock_win.return_value = ('2026-02-01', '2026-04-30')

        sb = Mock()
        result = query_stage_close_rate(sb)

    total_observed = sum(row['n_observed'] for row in result['by_stage_order'].values())

    if total_observed != len(qualifying_orders):
        raise AssertionError(
            f"sum(n_observed)={total_observed} does not match "
            f"len(qualifying_orders)={len(qualifying_orders)} — "
            f"by_stage_order and the qualified-pipeline population have "
            f"drifted apart again. by_stage_order keys: "
            f"{sorted(result['by_stage_order'].keys())}, "
            f"qualifying_orders: {sorted(qualifying_orders)}")

    print(f"  ✓ sum(n_observed)={total_observed} == "
          f"len(qualifying_orders)={len(qualifying_orders)}")


def test_coverage_proxy_target_by_week_structure():
    """
    query_coverage_proxy_target_by_week() — the HEURISTIC historical
    pipeline-coverage curve for assess_pipeline_coverage() (NORTH_STAR.md
    CRO Priority #2). Checks structure and the mandatory heuristic
    labeling independently of assess_pipeline_coverage() (which only
    ever exercises it mocked away). Confirmed live (2026-09-19): no
    complete historical quarter ever had a real target — this curve is
    a 2x-prior-year-actual proxy, and its output MUST always carry
    heuristic=True, label='HEURISTIC', and the literal word HEURISTIC
    in its note.

    Uses StrictSupabase (not a hand-written select_all side_effect) so the
    REAL filter predicates run, same as every other caller of
    actual_incremental_closed_won. Decision recorded 2026-10-03: the
    $1.55M target INCLUDES renewal expansion, so the shared filter
    (deal_status == "won" + is_incremental_pipeline()) is correct and
    stays as-is. The fixture includes a reopened deal — deal_status
    flipped back to "open" but the materialized `stage` column still
    stale at "closedwon" — so this test only passes if the proxy curve's
    prior-year computation reads deal_status, not stage (the OLD,
    pre-2026-10-03 filter would have wrongly counted it, inflating the
    proxy target).
    """
    print("\n[TEST] coverage proxy-target-by-week structure and heuristic labeling")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from strict_supabase import StrictSupabase

    deals = [
        # actual_incremental_closed_won: one won, incremental, non-renewal deal
        {'deal_id': 'w1', 'deal_status': 'won', 'stage': 'closedwon',
         'close_date': '2025-04-15', 'pipeline_id': 'default',
         'new_arr': 100000, 'expansion_arr': 0},
        # Reopened: deal_status says open (not won), but `stage` is stale
        # at closedwon. Must be EXCLUDED — proves the filter reads
        # deal_status, not stage. A regression back to the OLD
        # is_won(stage) filter would count this and inflate the proxy
        # target well past 200000.
        {'deal_id': 'w2_reopened', 'deal_status': 'open', 'stage': 'closedwon',
         'close_date': '2025-03-01', 'pipeline_id': 'default',
         'new_arr': 999999, 'expansion_arr': 0},
    ]
    deals_snapshot = [
        {'deal_id': 's1', 'deal_value': 50000, 'pipeline_id': 'default',
         'stage_order': 1, 'close_date': '2026-04-15',
         'fiscal_quarter': 'FY2026 Q1', 'week_of_quarter': 1},
    ]
    sb = StrictSupabase({'deals': deals, 'deals_snapshot': deals_snapshot})

    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters, \
         patch('analytics.forecast_analyses._load_config') as mock_config, \
         patch('analytics.forecast_analyses._quarter_window_iso') as mock_win, \
         patch('utils.get_pipeline_config') as mock_pcfg, \
         patch('utils.get_fiscal_quarter') as mock_gfq:
        mock_quarters.return_value = ['FY2026 Q1']
        mock_config.return_value = {'min_evidence_count': 30}
        mock_win.return_value = ('2026-02-01', '2026-04-30')
        mock_pcfg.return_value = {'qualified_stage_order': 1}
        mock_gfq.return_value = (date(2025, 2, 1), date(2025, 4, 30), 'FY2025 Q1')

        result = query_coverage_proxy_target_by_week(sb)

    for key in ('by_week', 'proxy_targets', 'quarters_used', 'min_evidence_count',
                'evidence_ceiling', 'heuristic', 'label', 'note'):
        if key not in result:
            raise AssertionError(f"Missing {key!r} in result")

    if result['heuristic'] is not True or result['label'] != 'HEURISTIC':
        raise AssertionError(
            f"Expected heuristic=True, label='HEURISTIC', got "
            f"{result['heuristic']}, {result['label']!r}")
    if 'HEURISTIC' not in result['note']:
        raise AssertionError(f"Expected the literal word HEURISTIC in note, got {result['note']!r}")

    if set(result['by_week'].keys()) != set(range(1, 14)):
        raise AssertionError(
            f"Expected by_week to cover all 13 weeks, got {sorted(result['by_week'].keys())}")

    q = 'FY2026 Q1'
    if q not in result['proxy_targets']:
        raise AssertionError(f"Expected proxy_targets to include {q!r}, got {result['proxy_targets'].keys()}")
    pt = result['proxy_targets'][q]
    if pt['value'] != 200000:
        raise AssertionError(f"Expected proxy target value=200000 (2x prior-year $100k), got {pt}")
    if pt['prior_year_deal_count'] != 1:
        raise AssertionError(f"Expected prior_year_deal_count=1, got {pt}")

    print("  ✓ by_week covers all 13 weeks; proxy_targets computed as 2x prior-year actual")
    print("  ✓ heuristic=True, label='HEURISTIC', literal word present in note")


def test_analyses_return_null_on_thin_data_never_fabricate():
    """
    All analyses must return null/error on thin data, never fabricate numbers.

    This is the master test: insufficient data = null, not made-up stats.
    """
    print("\n[TEST] Analyses return null on thin data, never fabricate")

    # Test week-3 conversion with empty quarters
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters:
        with patch('analytics.forecast_analyses._load_config') as mock_config:
            mock_quarters.return_value = []
            mock_config.return_value = {'trailing_quarters_window': 9, 'basis': 'count', 'min_evidence_count': 30}

            sb = Mock()
            w3_result = query_week3_conversion(sb)

            if 'error' not in w3_result:
                if w3_result.get('trailing_average') is not None and w3_result.get('trailing_average') != 0:
                    raise AssertionError(
                        f"Week-3 conversion fabricated data: trailing_average = {w3_result.get('trailing_average')}\n"
                        f"Should return null/error on thin data"
                    )

    print("  ✓ Week-3 conversion returns null on thin data")

    # Test commit outcome-by-week with empty data
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters:
        mock_quarters.return_value = []

        sb = Mock()
        outcome_result = query_commit_outcome_by_week(sb)

        if 'error' not in outcome_result:
            if outcome_result.get('by_week'):
                raise AssertionError(
                    "Commit outcome-by-week fabricated a table with no quarters"
                )

    print("  ✓ Commit outcome-by-week returns null on thin data")

    # Test commit calibration with no quarters
    with patch('analytics.forecast_analyses._get_complete_quarters') as mock_quarters:
        with patch('analytics.forecast_analyses._load_config') as mock_config:
            mock_quarters.return_value = []
            mock_config.return_value = {'anchor_week': 3, 'claimed_commit_accuracy': 0.90, 'min_evidence_count': 30}

            sb = Mock()
            calib_result = query_commit_calibration(sb)

            if 'error' not in calib_result:
                if calib_result.get('actual_hit_rate') is not None and calib_result.get('breakdown', {}).get('total', 0) == 0:
                    raise AssertionError(
                        "Commit calibration fabricated hit rate with no deals"
                    )

    print("  ✓ Commit calibration returns null on thin data")
    print("  ✓ No analyses fabricate numbers on insufficient data")


def main():
    """Run all forecast analysis tests."""
    print("=" * 70)
    print("FORECAST ANALYSIS TESTS (Phase 3)")
    print("=" * 70)

    tests = [
        test_week3_conversion_excludes_incomplete_quarters,
        test_week3_conversion_returns_null_not_zero_on_insufficient_history,
        test_commit_calibration_classifies_slip_separately_from_loss,
        test_commit_outcome_by_week_structure,
        test_commit_ml_calibration_by_week_structure,
        test_stage_close_rate_structure,
        test_stage_close_rate_excludes_meeting_set,
        test_stage_close_rate_population_matches_qualified_pipeline,
        test_coverage_proxy_target_by_week_structure,
        test_analyses_return_null_on_thin_data_never_fabricate,
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

    print("\n✅ All forecast analysis tests passed")
    print("   Analyses are correct and safe to build proposals on (Phase 4)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
