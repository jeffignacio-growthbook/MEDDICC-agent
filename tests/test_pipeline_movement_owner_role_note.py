"""
2026-09-11, two rounds the same night.

Round 1: a live Slack question about Jake Stangl's pipeline movement in
FY2027 Q3 came back as a `data_gap` — the same result as an earlier,
real deals_snapshot-staleness incident investigated the same night,
which had confirmed deals_snapshot is current through 2026-09-07. That
made the zero-row result for Jake Stangl look like a live, reproducible
bug. It wasn't (that part held up): Jake Stangl's roster role is "SDR",
and _pm_owner_role_note() shipped a note explaining the zero rows as
"SDRs structurally can't own deals in owner_email — attribution lives
in a separate sdr_owner_email column."

Round 2: Jeff corrected that premise directly, from firsthand knowledge
of how the team operates — SDRs (Jake Stangl specifically) CAN and DO
own deals pre-handoff, in the exact same owner_email field AEs use. The
schema fact (owner_email = HubSpot deal-owner property; sdr_owner_email
is a separate attribution column) was real; the inference from it
("therefore SDRs never appear as owner_email") was false. A static role
label cannot settle whether a specific rep owns deals at a specific
time — only the data can.

_pm_owner_role_note() was rewritten to never explain a zero-row result
by role alone. It now applies the same staleness-vs-genuine-zero check
any owner deserves: pull this owner_email's FULL deals_snapshot history
with NO quarter/pipeline filter, and let what's actually there decide:

  - no rows ever, for anyone: say exactly that (checkable, not a guess).
  - rows exist only in OTHER quarters/pipelines: zero rows in the
    requested window is real, explained by where their rows actually
    are (handed off, or not yet assigned) — not by role.
  - rows exist that DO match the requested scope: contradicts the
    caller's own zero-row result — flagged as a likely filter-
    construction bug, never smoothed over with a role explanation.

A non-AE role is now only ever a parenthetical aside (deals can move to
an AE via handoff), never a standalone justification.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import api.handlers as handlers_module
from api.handlers import _pm_owner_role_note, query_pipeline_movement


class _FakeSupabase:
    """No .table() support — everything must go through select_all()."""
    pass


def _patch_select_all(fn):
    orig = handlers_module.select_all
    handlers_module.select_all = fn
    return orig


def test_sdr_with_no_history_anywhere_gets_a_checkable_no_history_note():
    """Jake Stangl (SDR), zero deals_snapshot rows at ANY point in
    history — the note must say exactly that (a checkable fact), and
    may mention the SDR role only as an aside, never as the reason."""
    def fake_select_all(sb, table, columns=None, filters=None):
        assert table == "deals_snapshot"
        return []

    orig = _patch_select_all(fake_select_all)
    try:
        note = _pm_owner_role_note(
            _FakeSupabase(), "jake.stangl@growthbook.io",
            "FY2027 Q3", {"866608541"})
    finally:
        handlers_module.select_all = orig

    assert note is not None
    assert "NO deals_snapshot rows" in note
    assert "ANY point in history" in note
    assert "SDR" in note  # role surfaced as color
    assert "structurally" not in note.lower(), (
        "must never claim SDRs structurally can't own deals — that "
        "premise was directly contradicted by how the team operates"
    )


def test_sdr_with_only_other_quarter_history_explains_from_data_not_role():
    """Jake Stangl HAS deals_snapshot rows, but only in a prior quarter
    (already handed off) — the zero-row result for FY2027 Q3 is real,
    and the note must explain it from the actual row history, not from
    "SDRs don't own deals."""
    history_rows = [
        {"snapshot_date": "2026-06-01", "fiscal_quarter": "FY2027 Q1", "pipeline_id": "default"},
        {"snapshot_date": "2026-06-08", "fiscal_quarter": "FY2027 Q1", "pipeline_id": "default"},
    ]

    def fake_select_all(sb, table, columns=None, filters=None):
        return history_rows

    orig = _patch_select_all(fake_select_all)
    try:
        note = _pm_owner_role_note(
            _FakeSupabase(), "jake.stangl@growthbook.io",
            "FY2027 Q3", {"866608541"})
    finally:
        handlers_module.select_all = orig

    assert note is not None
    assert "2 deals_snapshot row(s) on file" in note
    assert "FY2027 Q1" in note
    assert "handed off" in note or "not yet assigned" in note
    assert "structurally" not in note.lower()


def test_sdr_with_matching_active_rows_flags_a_likely_bug_not_a_role_excuse():
    """Jake Stangl HAS deals_snapshot rows that DO match the requested
    fiscal_quarter and an in-scope pipeline — this contradicts a zero-
    row result from the caller's own filtered query, so the note must
    flag a likely filter-construction bug instead of explaining the
    zero rows away by role. This is the scenario Jeff's item 3 called
    out explicitly."""
    history_rows = [
        {"snapshot_date": "2026-09-07", "fiscal_quarter": "FY2027 Q3", "pipeline_id": "default"},
    ]

    def fake_select_all(sb, table, columns=None, filters=None):
        return history_rows

    orig = _patch_select_all(fake_select_all)
    try:
        note = _pm_owner_role_note(
            _FakeSupabase(), "jake.stangl@growthbook.io",
            "FY2027 Q3", {"866608541"})
    finally:
        handlers_module.select_all = orig

    assert note is not None
    assert "DOES have" in note
    assert "filter-construction bug" in note
    assert "SDR" not in note, (
        "a real contradiction must be flagged plainly, not softened "
        "with role color"
    )


def test_ae_zero_row_gets_the_same_data_driven_treatment_no_role_aside():
    """An AE (no non-AE role) with genuinely no history anywhere gets
    the same no-history note, with no role aside at all — the fix isn't
    SDR-specific, it's owner-agnostic."""
    def fake_select_all(sb, table, columns=None, filters=None):
        return []

    orig = _patch_select_all(fake_select_all)
    try:
        note = _pm_owner_role_note(
            _FakeSupabase(), "jake@growthbook.io",
            "FY2027 Q3", {"866608541"})
    finally:
        handlers_module.select_all = orig

    assert note is not None
    assert "NO deals_snapshot rows" in note
    assert "roster role is" not in note, "an AE should get no role aside at all"


def test_empty_owner_email_gets_no_note():
    def fake_select_all(sb, table, columns=None, filters=None):
        raise AssertionError("should not query when owner_email is empty")

    orig = _patch_select_all(fake_select_all)
    try:
        assert _pm_owner_role_note(_FakeSupabase(), None, "FY2027 Q3", set()) is None
        assert _pm_owner_role_note(_FakeSupabase(), "", "FY2027 Q3", set()) is None
    finally:
        handlers_module.select_all = orig


def test_diagnostic_query_failure_yields_no_note_rather_than_a_guess():
    def fake_select_all(sb, table, columns=None, filters=None):
        raise RuntimeError("boom")

    orig = _patch_select_all(fake_select_all)
    try:
        note = _pm_owner_role_note(
            _FakeSupabase(), "jake.stangl@growthbook.io",
            "FY2027 Q3", {"866608541"})
    finally:
        handlers_module.select_all = orig

    assert note is None, "a failed diagnostic query must not produce a guessed note"


def test_query_pipeline_movement_end_to_end_folds_the_note_into_data_gaps():
    """Drives the real handler with the main owner-filtered query
    returning zero rows, and the (separate) full-history diagnostic
    query returning only prior-quarter rows — reproducing the "already
    handed off" shape end-to-end and confirming the resulting data_gaps
    text is data-driven, not role-driven."""
    calls = []

    def fake_select_all(sb, table, columns=None, filters=None):
        calls.append({"table": table, "columns": columns, "filters": filters})
        filter_pairs = {(f[1], f[2]) for f in (filters or [])}
        if ("fiscal_quarter", "FY2027 Q3") in filter_pairs:
            return []  # the main, scoped query: nothing this quarter
        # the unscoped diagnostic query (owner_email only): prior-quarter history
        return [{"snapshot_date": "2026-06-01", "fiscal_quarter": "FY2027 Q1",
                  "pipeline_id": "default"}]

    orig = _patch_select_all(fake_select_all)
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

    assert len(calls) >= 2, "expected both the scoped query and the diagnostic query"
    gap_text = result["data_gaps"][0]
    assert "jake.stangl@growthbook.io" in gap_text
    assert "FY2027 Q1" in gap_text
    assert "structurally" not in gap_text.lower()
    assert "can't own deals" not in gap_text.lower()


if __name__ == "__main__":
    tests = [
        test_sdr_with_no_history_anywhere_gets_a_checkable_no_history_note,
        test_sdr_with_only_other_quarter_history_explains_from_data_not_role,
        test_sdr_with_matching_active_rows_flags_a_likely_bug_not_a_role_excuse,
        test_ae_zero_row_gets_the_same_data_driven_treatment_no_role_aside,
        test_empty_owner_email_gets_no_note,
        test_diagnostic_query_failure_yields_no_note_rather_than_a_guess,
        test_query_pipeline_movement_end_to_end_folds_the_note_into_data_gaps,
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
