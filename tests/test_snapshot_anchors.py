"""
Regression test for the second date-resolution defect found 2026-09-10:
dynamic_query_loop answering "which deals changed stage in the last 2 weeks
in EMEA" used a snapshot_date filter of gte.2026-07-08 for a question asked
on 2026-09-10 — a ~64 day miss, not the ~23-30 day miss from the first
(resolve_time_window "n" field) bug already fixed.

Root cause: unlike waterfall_weekly (filtered directly by gte/lte on the
resolved time_window) or query_pipeline_movement's _pm_view_movement (which
computes target_date = current - requested_days in code), a deals_snapshot
"changed stage" question needs TWO specific snapshot_date values to diff.
Nothing ever told the model which second (prior) date to use — the "Time
context: ... = start to end" line only gives a single range — so the model
picked its own, ungrounded, second date entirely by free-form reasoning.

resolve_snapshot_anchors() (api/router.py) closes this gap: given the
already-resolved time_window, it deterministically looks up the two real
snapshot_date values closest to time_window.start and time_window.end and
hands them to the model as fixed values instead of letting it invent one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.router import resolve_snapshot_anchors


class _FakeQuery:
    """Mimics the chainable supabase-py query builder for deals_snapshot.

    Each method just records what was asked for; the actual filter/sort/
    limit pipeline runs in execute(), matching how a real query would
    apply lte/order/limit server-side (unlike a naive mock that mutates
    the row list at each chained call, which would apply limit() before
    the lte() cutoff and silently truncate the wrong rows)."""

    def __init__(self, dates):
        self._dates = dates
        self._cutoff = None
        self._desc = False
        self._limit = None

    def select(self, *_a, **_kw):
        return self

    def lte(self, _column, cutoff):
        self._cutoff = cutoff
        return self

    def order(self, _column, desc=False):
        self._desc = desc
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        matching = [d for d in self._dates if self._cutoff is None or d <= self._cutoff]
        matching = sorted(matching, reverse=self._desc)
        if self._limit is not None:
            matching = matching[:self._limit]

        class _Result:
            pass
        r = _Result()
        r.data = [{"snapshot_date": d} for d in matching]
        return r


class _FakeSupabase:
    def __init__(self, snapshot_dates):
        self._snapshot_dates = snapshot_dates

    def table(self, name):
        assert name == "deals_snapshot"
        return _FakeQuery(list(self._snapshot_dates))


def test_anchors_pick_the_correct_snapshot_for_last_2_weeks():
    """With real snapshot dates on file and a correctly-resolved 14-day
    time_window (2026-08-27 to 2026-09-10), the anchors must be the
    snapshots closest to those two dates — not something ~64 days back."""
    sb = _FakeSupabase([
        "2026-07-01", "2026-07-08", "2026-07-29",
        "2026-08-14", "2026-08-17", "2026-08-28", "2026-09-10",
    ])
    time_window = {"start": "2026-08-27", "end": "2026-09-10"}

    note = resolve_snapshot_anchors(sb, time_window)

    # "On or before" semantics (same convention _pm_view_movement already
    # uses): the window starts 2026-08-27, and 2026-08-28 is one day AFTER
    # that, so the correct prior anchor is the last snapshot on or before
    # it — 2026-08-17 — not 2026-08-28 and certainly not 2026-07-08.
    assert "current_snapshot_date=2026-09-10" in note, note
    assert "prior_snapshot_date=2026-08-17" in note, note
    assert "2026-07-08" not in note, (
        f"Anchor note must not regress to the ~64-day-old wrong anchor: {note}"
    )
    print("✓ snapshot anchors match the resolved 14-day window, not a stale guess")


def test_anchors_empty_when_time_window_incomplete():
    """No start/end (e.g. handler called without a resolved window) must not
    crash — it should just skip giving an anchor, not fabricate one."""
    sb = _FakeSupabase(["2026-09-10"])
    assert resolve_snapshot_anchors(sb, {}) == ""
    assert resolve_snapshot_anchors(sb, {"start": "2026-08-27"}) == ""
    print("✓ missing time_window fields degrade to no anchor, not a guess")


def test_anchors_explicit_no_data_signal_when_no_snapshot_exists_before_cutoff():
    """The case most likely to have been undertested: a newly onboarded
    client or a real gap in snapshot history, where there simply is no
    snapshot far enough back to answer the question.

    This must NOT come back as "" (silence) — silence is exactly what let
    the model quietly invent its own comparison date last time. It must be
    an explicit, unambiguous "NO DATA AVAILABLE" instruction telling the
    model to say it can't answer, not a signal indistinguishable from "no
    anchor logic applies here at all"."""
    sb = _FakeSupabase(["2026-09-01", "2026-09-10"])
    time_window = {"start": "2026-01-01", "end": "2026-09-10"}

    note = resolve_snapshot_anchors(sb, time_window)

    assert note != "", (
        "A real time_window with no data that far back must return an "
        "explicit signal, not silence — silence is indistinguishable from "
        "'this function doesn't apply' and risks the model inventing a "
        "date again, exactly like the original bug."
    )
    assert "NO DATA AVAILABLE" in note, note
    assert "2026-01-01" in note and "2026-09-10" in note, (
        f"No-data note should name the window that couldn't be satisfied: {note}"
    )
    assert "current_snapshot_date=" not in note, (
        f"Must not fabricate a partial/fallback anchor: {note}"
    )
    print("✓ no data before the window start yields an explicit no-data signal, not silence")


def test_anchors_explicit_no_data_signal_on_lookup_failure():
    """A DB error resolving anchors must fail the same way as 'no data' —
    loud and explicit — never silently falling through to let the model
    invent its own dates because the lookup itself broke."""
    class _ExplodingSupabase:
        def table(self, _name):
            raise RuntimeError("connection reset")

    time_window = {"start": "2026-08-27", "end": "2026-09-10"}
    note = resolve_snapshot_anchors(_ExplodingSupabase(), time_window)

    assert "NO DATA AVAILABLE" in note, (
        f"A lookup failure must surface as an explicit no-data signal, got: {note!r}"
    )
    print("✓ a snapshot-lookup failure also produces an explicit no-data signal")


if __name__ == "__main__":
    test_anchors_pick_the_correct_snapshot_for_last_2_weeks()
    test_anchors_empty_when_time_window_incomplete()
    test_anchors_explicit_no_data_signal_when_no_snapshot_exists_before_cutoff()
    test_anchors_explicit_no_data_signal_on_lookup_failure()
    print("\n✅ All tests passed")
