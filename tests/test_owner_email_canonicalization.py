"""
PENDING_WORK.md High Priority #3 (canonicalization audit follow-up):
query_pipeline_movement's owner_email exact-match fragility (eq against
raw model-extracted text, no case tolerance, no name resolution) was
hardened during the Jake Stangl incident — but the same fragility was
found, unaddressed, in 5 other dedicated handlers during that same
audit. This file tests each handler's fix individually, one at a time,
against its own realistic case — not a single batch test at the end —
given how often a "should be safe" batch change this session turned
out to have a handler-specific wrinkle.

Each handler's fix is checked directly against a fake Supabase
(no live DB), asserting: the resolved filter actually reaches the
underlying query correctly, the existing [..._FILTER] defensive log
line (added earlier this session) still fires and reflects the
resolved value, and a case-mismatched or name-based input now matches
where it silently wouldn't have before.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import api.handlers as handlers_module


class _ListLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


def _run_and_capture(coro_fn, *args, **kwargs):
    handler = _ListLogHandler()
    logger = logging.getLogger("api.handlers")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    result, error = None, None
    try:
        result = asyncio.run(coro_fn(*args, **kwargs))
    except Exception as e:
        error = e
    finally:
        logger.removeHandler(handler)
    return result, error, handler.records


class _FakeSupabase:
    pass


PERSONAS = [
    {"email": "christian@growthbook.io", "name": "Christian", "display_name": "Christian"},
    {"email": "jake.stangl@growthbook.io", "name": "Jake Stangl", "display_name": "Jake Stangl"},
]


# ============================================================
# Handler 1/5: query_pipeline
# ============================================================

def test_query_pipeline_resolves_a_name_not_just_an_email():
    """Before this fix, passing a rep's NAME (not an email) under
    owner_email silently matched nothing — no resolver at all. Now it
    should resolve via _resolve_owner_email() the same way query_rep_
    pipeline/query_deal_health/query_stale_deals already do."""
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "user_personas":
            return PERSONAS
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_pipeline, {"owner_email": "Christian"}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    matches = [r for r in records if "[QUERY_PIPELINE_FILTER]" in r]
    assert matches, f"expected the filter log line — got: {records!r}"
    assert "'ilike', 'owner_email', 'christian@growthbook.io'" in matches[0], (
        f"expected the NAME resolved to the real email and matched "
        f"case-insensitively — got: {matches[0]!r}"
    )
    assert result["filters_applied"]["owner_email"] == "christian@growthbook.io"
    print("✓ query_pipeline resolves a rep NAME to their email (previously matched nothing)")


def test_query_pipeline_matches_case_mismatched_email():
    """A model reproducing an email in different casing than however
    it's stored must still match — ilike, not eq."""
    def fake_select_all(sb, table, columns=None, filters=None):
        return []  # no persona needed; input is already an email

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_pipeline,
            {"owner_email": "Christian@GrowthBook.IO"}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    matches = [r for r in records if "[QUERY_PIPELINE_FILTER]" in r]
    assert matches
    assert "'ilike'" in matches[0], (
        f"expected a case-insensitive ilike match, not eq — got: {matches[0]!r}"
    )
    print("✓ query_pipeline matches a case-mismatched email via ilike")


def test_query_pipeline_with_no_owner_filter_still_works():
    """False-positive check: no owner_email/rep name given at all must
    not add a spurious filter or break the handler."""
    def fake_select_all(sb, table, columns=None, filters=None):
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_pipeline, {}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    matches = [r for r in records if "[QUERY_PIPELINE_FILTER]" in r]
    assert matches
    assert "owner_email" not in matches[0]
    assert result["filters_applied"]["owner_email"] is None
    print("✓ query_pipeline with no owner filter adds no spurious clause")


# ============================================================
# Handler 2/5: query_call_quality (Mode 2 — rep/team pattern)
# ============================================================

def test_query_call_quality_resolves_a_name_in_team_mode():
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "user_personas":
            return PERSONAS
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_call_quality,
            {"owner_email": "Jake Stangl", "time_window": {}}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    matches = [r for r in records if "[QUERY_CALL_QUALITY_FILTER]" in r]
    assert matches, f"expected the filter log line — got: {records!r}"
    assert "'ilike', 'owner_email', 'jake.stangl@growthbook.io'" in matches[0], (
        f"expected the name resolved and matched case-insensitively — got: {matches[0]!r}"
    )
    print("✓ query_call_quality (team mode) resolves a rep NAME to their email")


def test_query_call_quality_matches_case_mismatched_email_in_team_mode():
    def fake_select_all(sb, table, columns=None, filters=None):
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_call_quality,
            {"owner_email": "Christian@GrowthBook.IO", "time_window": {}}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    matches = [r for r in records if "[QUERY_CALL_QUALITY_FILTER]" in r]
    assert matches
    assert "'ilike'" in matches[0], f"expected ilike, not eq — got: {matches[0]!r}"
    print("✓ query_call_quality (team mode) matches a case-mismatched email via ilike")


def test_query_call_quality_single_call_mode_unaffected():
    """False-positive check: Mode 1 (single call review by company) must
    still work exactly as before — it never used owner_email in its own
    filter, only company_name matching."""
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "deals":
            return [{"deal_id": "d1", "company_name": "Acme Corp",
                      "owner_email": "christian@growthbook.io", "stage": "Discovery"}]
        if table == "calls":
            return [{"call_id": "c1", "call_date": "2026-09-01", "title": "Discovery call",
                      "source": "fireflies", "summary": "Good call."}]
        if table == "call_quality":
            return []
        if table == "objections":
            return []
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_call_quality, {"company": "Acme"}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    assert result["company_name"] == "Acme Corp"
    assert not any("[QUERY_CALL_QUALITY_FILTER]" in r for r in records), (
        "Mode 1 (single-call review) never reaches Mode 2's filter/log line"
    )
    print("✓ query_call_quality Mode 1 (single call by company) is unaffected")


# ============================================================
# Handler 3/5: query_sdr_metrics
# ============================================================

def test_query_sdr_metrics_resolves_a_name_via_sdr_name():
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "user_personas":
            return PERSONAS
        if table == "sdr_users":
            return [{"tool": "apollo", "tool_user_id": "u1",
                      "user_name": "Jake Stangl", "user_email": "jake.stangl@growthbook.io"}]
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_sdr_metrics,
            {"sdr_name": "Jake Stangl",
             "time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "period"}},
            _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    sdr_users_lines = [r for r in records if "[QUERY_SDR_METRICS_FILTER]" in r and "sdr_users" in r]
    assert sdr_users_lines, f"expected the sdr_users filter log line — got: {records!r}"
    assert "'ilike', 'user_email', 'jake.stangl@growthbook.io'" in sdr_users_lines[0], (
        f"expected the name resolved to the real email — got: {sdr_users_lines[0]!r}"
    )
    print("✓ query_sdr_metrics resolves a name passed as sdr_name to their email")


def test_query_sdr_metrics_matches_case_mismatched_email_at_both_call_sites():
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "sdr_users":
            return [{"tool": "apollo", "tool_user_id": "u1",
                      "user_name": "Christian", "user_email": "christian@growthbook.io"}]
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_sdr_metrics,
            {"sdr_email": "Christian@GrowthBook.IO",
             "time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "period"}},
            _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    filter_lines = [r for r in records if "[QUERY_SDR_METRICS_FILTER]" in r]
    assert len(filter_lines) == 2, f"expected both call sites to log — got: {filter_lines!r}"
    for line in filter_lines:
        assert "'ilike'" in line, f"expected ilike at both call sites — got: {line!r}"
    print("✓ query_sdr_metrics matches a case-mismatched email at both call sites (sdr_users, meetings)")


def test_query_sdr_metrics_still_errors_cleanly_with_no_sdr_identified():
    def fake_select_all(sb, table, columns=None, filters=None):
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_sdr_metrics, {}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    assert result.get("error") == "No SDR email provided"
    print("✓ query_sdr_metrics still errors cleanly when no SDR can be identified at all")


# ============================================================
# Handler 4/5: query_sdr_pipeline_sourced
# ============================================================
# Real config/client.yaml has sdr_tools.pipeline_attribution.method =
# "sdr_field" (sdr_field="bdr_owner") — so the live branch filters on
# sdr_owner_email. Tested against the real config, not a mock, since
# that's what actually runs in production.

def test_query_sdr_pipeline_sourced_resolves_a_name():
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "user_personas":
            return PERSONAS
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_sdr_pipeline_sourced,
            {"sdr_name": "Jake Stangl",
             "time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "period"}},
            _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    matches = [r for r in records if "[QUERY_SDR_PIPELINE_SOURCED_FILTER]" in r]
    assert matches, f"expected the filter log line — got: {records!r}"
    assert "'ilike', 'sdr_owner_email', 'jake.stangl@growthbook.io'" in matches[0], (
        f"expected the name resolved and matched via ilike on the "
        f"configured sdr_field attribution column — got: {matches[0]!r}"
    )
    print("✓ query_sdr_pipeline_sourced resolves a name to their email "
          "(sdr_field attribution method)")


def test_query_sdr_pipeline_sourced_matches_case_mismatched_email():
    def fake_select_all(sb, table, columns=None, filters=None):
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_sdr_pipeline_sourced,
            {"sdr_email": "Christian@GrowthBook.IO",
             "time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "period"}},
            _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    matches = [r for r in records if "[QUERY_SDR_PIPELINE_SOURCED_FILTER]" in r]
    assert matches
    assert "'ilike'" in matches[0], f"expected ilike, not eq — got: {matches[0]!r}"
    print("✓ query_sdr_pipeline_sourced matches a case-mismatched email via ilike")


def test_query_sdr_pipeline_sourced_with_no_sdr_filter_returns_all():
    """False-positive check: sdr_email is optional — omitting it must
    not add a spurious filter or break the handler (returns all SDRs).

    Captures the actual `filters` list the handler passes to select_all
    (rather than string-parsing the log line, which was fragile and hard
    to read) and asserts directly on its contents: no ("ilike"/"eq", col,
    value) tuple naming either attribution column, only the unconditional
    __not_null__ marker on sdr_owner_email."""
    captured_filters = []

    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "deals":
            captured_filters.append(filters)
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_sdr_pipeline_sourced,
            {"time_window": {"start": "2026-08-01", "end": "2026-09-08", "label": "period"}},
            _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    assert captured_filters, "expected select_all to be called against 'deals'"
    filters = captured_filters[0]
    value_filters = [f for f in filters if f[0] in ("eq", "ilike")]
    matched_cols = {f[1] for f in value_filters}
    assert "sdr_owner_email" not in matched_cols and "owner_email" not in matched_cols, (
        f"expected no eq/ilike clause on either attribution column when no "
        f"sdr_email is given — got filters: {filters!r}"
    )
    assert ("__not_null__", "sdr_owner_email") in filters, (
        f"expected the unconditional __not_null__ marker to still be present — got: {filters!r}"
    )
    print("✓ query_sdr_pipeline_sourced with no SDR filter returns all SDRs, no spurious clause")


# ============================================================
# Handler 5/5: query_stale_deals
# ============================================================
# owner_email here was already resolved via _resolve_owner_email() before
# tonight, but the audit note calling it "already fixed" missed that a
# name resolves to user_personas.email VERBATIM (no case-folding) — so
# the downstream eq filter could still miss on a casing mismatch, same
# gap as the other 4 handlers. The other, larger gap flagged by the
# audit: `stage` reached its eq filter completely raw, with no
# canonicalization against deals.stage's actual raw-HubSpot-id storage.

def _capture_deals_filters(coro_fn, params):
    captured = []

    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "deals":
            captured.append(filters)
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(coro_fn, params, _FakeSupabase())
    finally:
        handlers_module.select_all = orig
    return result, error, records, captured


def test_query_stale_deals_resolves_stage_label_to_stage_id():
    """A model extracting "Technical Evaluation" from free text must
    match deals.stage's actual storage (the raw HubSpot id
    'presentationscheduled'), not the human-readable label."""
    result, error, records, captured = _capture_deals_filters(
        handlers_module.query_stale_deals, {"stage": "Technical Evaluation"})

    assert error is None, f"handler raised: {error!r}"
    assert captured, "expected select_all to be called against 'deals'"
    filters = captured[0]
    assert ("eq", "stage", "presentationscheduled") in filters, (
        f"expected the label resolved to its raw stage_id — got filters: {filters!r}"
    )
    print("✓ query_stale_deals resolves a human-readable stage label to its raw stage_id")


def test_query_stale_deals_stage_lookup_is_case_insensitive():
    result, error, records, captured = _capture_deals_filters(
        handlers_module.query_stale_deals, {"stage": "technical evaluation"})

    assert error is None, f"handler raised: {error!r}"
    filters = captured[0]
    assert ("eq", "stage", "presentationscheduled") in filters, (
        f"expected a case-mismatched label to still resolve — got filters: {filters!r}"
    )
    print("✓ query_stale_deals's stage resolution is case-insensitive")


def test_query_stale_deals_unknown_stage_passes_through_unchanged():
    """False-positive check: a stage value matching neither the raw-id nor
    the label table must still reach the filter unchanged (not silently
    dropped), so an already-correct or genuinely-unrecognized value keeps
    today's behavior rather than becoming a new failure mode."""
    result, error, records, captured = _capture_deals_filters(
        handlers_module.query_stale_deals, {"stage": "Some Made Up Stage"})

    assert error is None, f"handler raised: {error!r}"
    filters = captured[0]
    assert ("eq", "stage", "Some Made Up Stage") in filters, (
        f"expected the unrecognized value to pass through unchanged — got filters: {filters!r}"
    )
    print("✓ query_stale_deals passes through an unrecognized stage value unchanged")


def test_query_stale_deals_owner_email_matches_via_ilike():
    def fake_select_all(sb, table, columns=None, filters=None):
        if table == "user_personas":
            return PERSONAS
        return []

    orig = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result, error, records = _run_and_capture(
            handlers_module.query_stale_deals,
            {"owner_email": "Christian@GrowthBook.IO"}, _FakeSupabase())
    finally:
        handlers_module.select_all = orig

    assert error is None, f"handler raised: {error!r}"
    matches = [r for r in records if "[QUERY_STALE_DEALS_FILTER]" in r]
    assert matches, f"expected the filter log line — got: {records!r}"
    assert "'ilike', 'owner_email'" in matches[0], (
        f"expected owner_email to be matched via ilike, not eq — got: {matches[0]!r}"
    )
    print("✓ query_stale_deals matches owner_email via ilike (case-tolerant post-resolution)")


if __name__ == "__main__":
    tests = [
        test_query_pipeline_resolves_a_name_not_just_an_email,
        test_query_pipeline_matches_case_mismatched_email,
        test_query_pipeline_with_no_owner_filter_still_works,
        test_query_call_quality_resolves_a_name_in_team_mode,
        test_query_call_quality_matches_case_mismatched_email_in_team_mode,
        test_query_call_quality_single_call_mode_unaffected,
        test_query_sdr_metrics_resolves_a_name_via_sdr_name,
        test_query_sdr_metrics_matches_case_mismatched_email_at_both_call_sites,
        test_query_sdr_metrics_still_errors_cleanly_with_no_sdr_identified,
        test_query_sdr_pipeline_sourced_resolves_a_name,
        test_query_sdr_pipeline_sourced_matches_case_mismatched_email,
        test_query_sdr_pipeline_sourced_with_no_sdr_filter_returns_all,
        test_query_stale_deals_resolves_stage_label_to_stage_id,
        test_query_stale_deals_stage_lookup_is_case_insensitive,
        test_query_stale_deals_unknown_stage_passes_through_unchanged,
        test_query_stale_deals_owner_email_matches_via_ilike,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
