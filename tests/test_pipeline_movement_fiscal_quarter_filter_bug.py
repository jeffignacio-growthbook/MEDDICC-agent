"""
2026-09-11, round 3 of the Jake Stangl incident. Jeff confirmed directly
against live data: Jake Stangl has 10 active deals_snapshot rows on the
2026-09-08 snapshot alone, with fiscal_quarter='FY2027 Q3' (confirmed
literal), pipeline_id='default', owner_email='jake.stangl@growthbook.io'
— exactly the population query_pipeline_movement's filter should match
— and the live query returned zero.

Investigation ruled out two of Jeff's four hypotheses from code/config
inspection alone:

  - pipeline_id exclusion (#2): config/client.yaml's pipelines.excluded
    lists ONLY the renewal pipeline (866608541). "default" is the
    INCLUDED pipeline. The default-scope branch only ever appends
    `neq pipeline_id 866608541` — it cannot exclude "default" rows.
  - a leftover stage_id filter (#4): the raw filters list sent to
    select_all() for the DB-level query never included a stage_id
    clause at any point — confirmed absent by reading the construction
    top to bottom, not inferred.

The remaining, structurally real risk is exact-match string drift on
values a model extracts from free text, never canonicalized before an
`eq` filter:

  - fiscal_quarter (#3): api/router.py's own classifier prompt
    documents TWO different quarter-label conventions a few lines
    apart — "'FY2027 Q2' style label" for this handler's fiscal_quarter
    param, and "Q3_FY2027" (reversed, underscored) for a DIFFERENT
    handler's period_label param used by rep_attainment/rep_pipeline.
    Nothing stopped a model from blending the two, and a wrong space,
    underscore, or reversed year/quarter order returns zero rows with
    no error — indistinguishable from a real gap.
  - owner_email (#1): matched with `eq`, so any casing difference
    between however a model reproduces an email and whatever casing
    HubSpot's sync actually wrote returns zero silently.

Fix: _pm_normalize_fiscal_quarter() canonicalizes any FY/Q ordering,
separator, or case into the exact stored form before the DB filter;
owner_email now matches via `ilike` (case-insensitive exact match, no
wildcards) instead of `eq`. These tests reproduce Jeff's exact
confirmed case end-to-end and prove both hardenings independently, plus
confirm _pm_owner_role_note() (built for the "genuinely no data" case)
does not fire once real matching rows exist — its logic never runs at
all once `rows` is non-empty, but this pins that behavior explicitly
rather than leaving it as an inference.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import api.handlers as handlers_module
from api.handlers import _pm_normalize_fiscal_quarter, query_pipeline_movement

# Jeff's exact confirmed shape: 10 rows, 2026-09-08, FY2027 Q3, default
# pipeline, all sharing stage_id 79653122, owned by Jake Stangl.
JAKE_STANGL_SEPT8_ROWS = [
    {
        "deal_id": f"700000{i:04d}",
        "snapshot_date": "2026-09-08",
        "pipeline_id": "default",
        "stage_id": "79653122",
        "stage_order": 3,
        "close_date": "2026-11-15",
        "owner_email": "jake.stangl@growthbook.io",
        "snapshot_source": "prospective",
        "backfill_confidence": "exact",
        "week_of_quarter": 6,
        "fiscal_quarter": "FY2027 Q3",
    }
    for i in range(10)
]


class _FakeSupabase:
    pass


def _make_scoped_select_all(rows, call_log):
    """Simulates deals_snapshot honoring eq/neq/ilike the way Postgres
    actually would, so the test proves the FILTER LOGIC works, not just
    that a canned fixture gets echoed back regardless of what's asked."""
    def fake_select_all(sb, table, columns=None, filters=None):
        call_log.append({"table": table, "columns": columns, "filters": filters})
        result = list(rows)
        for op, col, val in (filters or []):
            if op == "eq":
                result = [r for r in result if str(r.get(col)) == str(val)]
            elif op == "neq":
                result = [r for r in result if str(r.get(col)) != str(val)]
            elif op == "ilike":
                result = [r for r in result
                          if str(r.get(col) or "").lower() == str(val).lower()]
        return result
    return fake_select_all


def test_normalize_handles_the_canonical_form_as_a_no_op():
    assert _pm_normalize_fiscal_quarter("FY2027 Q3") == "FY2027 Q3"


def test_normalize_fixes_reversed_quarter_first_convention():
    """The exact OTHER convention visible in the same classifier prompt,
    for a different param (period_label): 'Q3_FY2027'."""
    assert _pm_normalize_fiscal_quarter("Q3_FY2027") == "FY2027 Q3"
    assert _pm_normalize_fiscal_quarter("Q3 FY2027") == "FY2027 Q3"
    assert _pm_normalize_fiscal_quarter("Q3-FY2027") == "FY2027 Q3"


def test_normalize_fixes_missing_space_and_separators():
    assert _pm_normalize_fiscal_quarter("FY2027Q3") == "FY2027 Q3"
    assert _pm_normalize_fiscal_quarter("FY2027-Q3") == "FY2027 Q3"
    assert _pm_normalize_fiscal_quarter("FY2027_Q3") == "FY2027 Q3"


def test_normalize_is_case_insensitive():
    assert _pm_normalize_fiscal_quarter("fy2027 q3") == "FY2027 Q3"


def test_normalize_leaves_unparseable_input_unchanged():
    assert _pm_normalize_fiscal_quarter("this quarter") == "this quarter"
    assert _pm_normalize_fiscal_quarter(None) is None
    assert _pm_normalize_fiscal_quarter("") == ""


def test_jake_stangl_exact_confirmed_case_returns_all_10_rows():
    """The exact case Jeff confirmed live: canonical fiscal_quarter,
    exact-case owner_email, no explicit pipeline_id (default scope)."""
    calls = []
    orig = handlers_module.select_all
    handlers_module.select_all = _make_scoped_select_all(JAKE_STANGL_SEPT8_ROWS, calls)
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "movement",
                "fiscal_quarter": "FY2027 Q3",
                "owner_email": "jake.stangl@growthbook.io",
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig

    assert result.get("data_gaps") in (None, []) or "no snapshot rows" not in str(
        result.get("data_gaps")), (
        f"expected the 10 confirmed rows to be found — got: {result.get('data_gaps')}"
    )
    assert result["query_stats"]["rows_loaded"] == 10, (
        f"expected all 10 of Jake Stangl's confirmed Sept 8 rows to load "
        f"— got {result['query_stats']['rows_loaded']}"
    )


def test_reversed_fiscal_quarter_format_no_longer_zeroes_out_real_rows():
    """The specific defect this fixes: a model extracting the quarter in
    the OTHER convention visible in its own prompt ('Q3_FY2027' instead
    of 'FY2027 Q3') must still find the real rows, not silently return
    zero."""
    calls = []
    orig = handlers_module.select_all
    handlers_module.select_all = _make_scoped_select_all(JAKE_STANGL_SEPT8_ROWS, calls)
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "movement",
                "fiscal_quarter": "Q3_FY2027",
                "owner_email": "jake.stangl@growthbook.io",
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig

    assert result["fiscal_quarter"] == "FY2027 Q3", (
        "the normalized label must be what's used and reported, not the "
        "raw reversed form"
    )
    assert result["query_stats"]["rows_loaded"] == 10


def test_case_mismatched_owner_email_no_longer_zeroes_out_real_rows():
    """A model reproducing the email in different casing than however
    HubSpot's sync wrote it must still match — case-insensitive exact
    match (ilike, no wildcards), not eq."""
    calls = []
    orig = handlers_module.select_all
    handlers_module.select_all = _make_scoped_select_all(JAKE_STANGL_SEPT8_ROWS, calls)
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "movement",
                "fiscal_quarter": "FY2027 Q3",
                "owner_email": "Jake.Stangl@GrowthBook.IO",
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig

    assert result["query_stats"]["rows_loaded"] == 10


def test_role_note_does_not_fire_once_real_matching_rows_exist():
    """_pm_owner_role_note() was built for the genuinely-zero-rows case.
    Once the fiscal_quarter/owner_email fixes above let the real 10 rows
    through, the empty-result branch (and therefore the role note) must
    never execute at all — pinned explicitly by asserting select_all is
    called exactly once (the main query only; no diagnostic follow-up
    query), and that no role-note text appears anywhere in the result."""
    calls = []
    orig = handlers_module.select_all
    handlers_module.select_all = _make_scoped_select_all(JAKE_STANGL_SEPT8_ROWS, calls)
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "movement",
                "fiscal_quarter": "FY2027 Q3",
                "owner_email": "jake.stangl@growthbook.io",
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig

    assert len(calls) == 1, (
        f"once real rows are found, no diagnostic follow-up query (the "
        f"one _pm_owner_role_note runs) should ever fire — got {len(calls)} "
        f"select_all call(s)"
    )
    serialized = str(result)
    assert "roster role is" not in serialized
    assert "NO deals_snapshot rows" not in serialized
    assert "filter-construction bug" not in serialized


class _ListLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


def test_the_fully_constructed_filter_is_logged_byte_exact_before_the_query():
    """2026-09-11, round 4: the investigation into the original zero-row
    mystery was blocked at the root by never having the ACTUAL outgoing
    filter clause to compare against known-good data — every hypothesis
    had to be checked blind, from code inspection alone. This pins the
    fix: a single INFO-level log line, emitted unconditionally right
    before the Supabase call, carrying the exact table/columns/filters
    that will be sent — every operator, column, and value via !r, so a
    stray space or case difference is visible in the log line itself,
    not summarized away. Next time this handler returns zero rows
    unexpectedly, the Railway log has the byte-exact query to compare
    against the DB directly."""
    handler = _ListLogHandler()
    handlers_logger = logging.getLogger("api.handlers")
    handlers_logger.addHandler(handler)
    handlers_logger.setLevel(logging.INFO)

    calls = []
    orig = handlers_module.select_all
    handlers_module.select_all = _make_scoped_select_all(JAKE_STANGL_SEPT8_ROWS, calls)
    try:
        asyncio.run(query_pipeline_movement(
            {
                "view": "movement",
                "fiscal_quarter": "FY2027 Q3",
                "owner_email": "jake.stangl@growthbook.io",
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig
        handlers_logger.removeHandler(handler)

    matches = [r for r in handler.records if "[PIPELINE_MOVEMENT_QUERY]" in r]
    assert len(matches) == 1, (
        f"expected exactly one query-logging line — got {len(matches)}: {matches!r}"
    )
    line = matches[0]
    assert "table='deals_snapshot'" in line
    assert "'eq', 'fiscal_quarter', 'FY2027 Q3'" in line
    assert "'ilike', 'owner_email', 'jake.stangl@growthbook.io'" in line
    assert "'neq', 'pipeline_id', '866608541'" in line, (
        "the renewal-pipeline exclusion must appear explicitly — this is "
        "exactly the clause a partially-captured request might have hidden"
    )


if __name__ == "__main__":
    tests = [
        test_normalize_handles_the_canonical_form_as_a_no_op,
        test_normalize_fixes_reversed_quarter_first_convention,
        test_normalize_fixes_missing_space_and_separators,
        test_normalize_is_case_insensitive,
        test_normalize_leaves_unparseable_input_unchanged,
        test_jake_stangl_exact_confirmed_case_returns_all_10_rows,
        test_reversed_fiscal_quarter_format_no_longer_zeroes_out_real_rows,
        test_case_mismatched_owner_email_no_longer_zeroes_out_real_rows,
        test_role_note_does_not_fire_once_real_matching_rows_exist,
        test_the_fully_constructed_filter_is_logged_byte_exact_before_the_query,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
