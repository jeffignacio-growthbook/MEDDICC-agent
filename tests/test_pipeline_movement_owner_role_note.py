"""
2026-09-11 (live incident): a Slack question about Jake Stangl's pipeline
movement in FY2027 Q3 came back as a `data_gap` — the exact same result as
an earlier, real deals_snapshot-staleness incident investigated the same
night. That earlier investigation confirmed deals_snapshot is current
through 2026-09-07, so the surface symptom ("no data for this rep") looked
like a live, reproducible bug in query_pipeline_movement's filter
construction.

It wasn't. Root cause, confirmed via code + config inspection (no live DB
access needed): Jake Stangl's role in config/client.yaml's team roster is
"SDR", not "Account Executive". deals_snapshot.owner_email is populated
from HubSpot's deal-owner property (scripts/etl_deals.py's
hubspot_owner_id mapping) — the AE who owns the deal record. SDR/BDR
attribution lives in a completely separate column, deals.sdr_owner_email
(migration 031), which is never copied into deals_snapshot at all (see
_PM_SNAPSHOT_COLUMNS). An SDR structurally has no rows to find under
owner_email filtering — "zero rows" is the CORRECT answer to "does this
SDR own any pipeline deals directly", not a bug or a data gap.

The actual defect was in the message: `query_pipeline_movement`'s empty-
result path returned a bare "no snapshot rows for FY2027 Q3 (owner
jake.stangl@growthbook.io)" data_gap, indistinguishable from a genuine
staleness/coverage problem. _pm_owner_role_note() closes that gap: when
the filtered owner_email matches a non-AE roster role, the data_gap now
explains WHY zero rows is expected and points at the right query
(SDR/sourced-deal metrics) instead.

These tests pin: (1) the role-note helper's behavior directly against the
real config/client.yaml roster (Jake Stangl -> SDR note fires, Jake H ->
AE, no note, unrecognized/empty email -> no note), and (2) that
query_pipeline_movement's empty-result data_gap actually includes the
note end-to-end when Supabase returns zero rows for an SDR's owner_email
filter.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import api.handlers as handlers_module
from api.handlers import _pm_owner_role_note, query_pipeline_movement


def test_sdr_email_gets_a_role_note():
    note = _pm_owner_role_note("jake.stangl@growthbook.io")
    assert note is not None, "Jake Stangl (SDR) should get an explanatory note"
    assert "Jake Stangl" in note
    assert "SDR" in note
    assert "an SDR" in note, f"expected correct article 'an SDR', got: {note!r}"
    assert "not a data or snapshot problem" in note


def test_ae_email_gets_no_role_note():
    note = _pm_owner_role_note("jake@growthbook.io")
    assert note is None, "Jake H (AE) should NOT get a non-AE role note"


def test_unrecognized_email_gets_no_role_note():
    assert _pm_owner_role_note("nobody@growthbook.io") is None


def test_empty_email_gets_no_role_note():
    assert _pm_owner_role_note(None) is None
    assert _pm_owner_role_note("") is None


def test_email_matching_is_case_insensitive():
    note = _pm_owner_role_note("JAKE.STANGL@GrowthBook.IO")
    assert note is not None
    assert "Jake Stangl" in note


class _FakeSupabase:
    """No .table() support — query_pipeline_movement must reach the empty-
    result path purely through select_all() returning [], never falling
    through to a real DB call."""
    pass


def test_query_pipeline_movement_surfaces_the_role_note_end_to_end():
    """Drives the real handler with Supabase stubbed to return zero
    deals_snapshot rows for an SDR's owner_email filter — reproducing the
    exact live incident shape (fiscal_quarter=FY2027 Q3,
    owner_email=jake.stangl@growthbook.io) — and confirms the returned
    data_gaps text explains the role mismatch instead of reading as a
    bare, ambiguous staleness signal.
    """
    calls = []

    def fake_select_all(sb, table, columns=None, filters=None):
        calls.append({"table": table, "columns": columns, "filters": filters})
        return []

    orig_select_all = handlers_module.select_all
    handlers_module.select_all = fake_select_all
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
        handlers_module.select_all = orig_select_all

    assert calls, "expected query_pipeline_movement to call select_all"
    snapshot_call = calls[0]
    assert snapshot_call["table"] == "deals_snapshot"
    filter_pairs = {(f[1], f[2]) for f in snapshot_call["filters"]}
    assert ("fiscal_quarter", "FY2027 Q3") in filter_pairs
    assert ("owner_email", "jake.stangl@growthbook.io") in filter_pairs

    assert result["result"] is None
    assert len(result["data_gaps"]) == 1
    gap_text = result["data_gaps"][0]
    assert "jake.stangl@growthbook.io" in gap_text
    assert "Jake Stangl is an SDR" in gap_text, (
        f"expected the role note to be folded into data_gaps, got: {gap_text!r}"
    )
    assert "not a data or snapshot problem" in gap_text


def test_query_pipeline_movement_ae_zero_rows_has_no_role_note():
    """Negative control: an AE with genuinely zero rows (e.g. a real gap,
    or a rep with no open pipeline that quarter) must NOT get the SDR/BDR
    explanatory text tacked on — the note is role-specific, not a generic
    suffix on every empty owner-filtered result."""
    def fake_select_all(sb, table, columns=None, filters=None):
        return []

    orig_select_all = handlers_module.select_all
    handlers_module.select_all = fake_select_all
    try:
        result = asyncio.run(query_pipeline_movement(
            {
                "view": "movement",
                "fiscal_quarter": "FY2027 Q3",
                "owner_email": "jake@growthbook.io",
            },
            _FakeSupabase(),
        ))
    finally:
        handlers_module.select_all = orig_select_all

    gap_text = result["data_gaps"][0]
    assert "jake@growthbook.io" in gap_text
    assert "SDR" not in gap_text
    assert "is an" not in gap_text and "is a " not in gap_text


if __name__ == "__main__":
    tests = [
        test_sdr_email_gets_a_role_note,
        test_ae_email_gets_no_role_note,
        test_unrecognized_email_gets_no_role_note,
        test_empty_email_gets_no_role_note,
        test_email_matching_is_case_insensitive,
        test_query_pipeline_movement_surfaces_the_role_note_end_to_end,
        test_query_pipeline_movement_ae_zero_rows_has_no_role_note,
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
