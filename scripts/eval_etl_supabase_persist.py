#!/usr/bin/env python3
"""
Eval: etl_calls.py Supabase persist (post-8/21 transcript gap, causes B + D).
Offline — the Supabase writer and the transcript fetcher are stubbed.

Invariants:
  B. The same call id fetched by two paths (ApolloAdapter + legacy
     fetch_apollo_incremental) reaches Supabase ONCE, last copy wins, so a
     bulk_upsert_calls batch can never carry a duplicate key (Postgres 21000).
  D. Nothing is swallowed. A failed calls upsert for one company does not
     stop other companies or the transcript persist; every outcome
     (text / unavailable / deferred / write failed / skipped because the
     parent row failed) is counted per source and shows up in the report
     that goes to $GITHUB_STEP_SUMMARY; a lost write makes the run fail.
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

import etl_calls  # noqa: E402
from etl_calls import (dedupe_calls_by_id, persist_to_supabase, persist_failed,  # noqa: E402
                       format_persist_report, write_step_summary)


class FakeSB:
    """Records upserts; raises like Postgres/PostgREST where told to."""

    def __init__(self, fail_calls_for=(), fail_transcripts=False):
        self.fail_calls_for = set(fail_calls_for)
        self.fail_transcripts = fail_transcripts
        self.call_batches, self.transcript_rows = [], []

    def bulk_upsert_calls(self, calls, company_name):
        ids = [str(c["id"]) for c in calls]
        if len(ids) != len(set(ids)):
            raise RuntimeError("{'code': '21000', 'message': 'ON CONFLICT DO UPDATE "
                               "command cannot affect row a second time'}")
        if company_name in self.fail_calls_for:
            raise RuntimeError("{'code': 'PGRST204', 'message': \"Could not find the "
                               "'competitors_mentioned' column of 'calls'\"}")
        self.call_batches.append(ids)
        return len(calls)

    def bulk_upsert_transcripts(self, rows, chunk=25):
        if self.fail_transcripts:
            raise RuntimeError("connection terminated")
        self.transcript_rows.extend(rows)
        return len(rows)


def fake_fetch(texts):
    """texts: call_id -> str (text) | '' (no content) | Exception-ish ('ERR:...')."""
    def fetch(source, call_id, clients):
        v = texts.get(call_id, "hello there")
        if v.startswith("ERR:"):
            return [], v[4:], {}
        if not v:
            return [], None, {}
        return [{"key": "a", "name": "Rep", "sec": 3.0, "text": v, "q": False}], None, {}
    return fetch


def _call(cid, source, title="X", date="2026-09-21", summary="s"):
    return {"id": cid, "source": source, "title": title, "date": date, "summary": summary}


def test_duplicate_apollo_id_reaches_supabase_once():
    cases = []
    adapter_copy = _call("apo1", "apollo", summary="native apollo summary")
    legacy_copy = _call("apo1", "apollo", summary="haiku summary")
    legacy_copy["host"] = "rep@growthbook.io"
    cbc = {"bet365": {"company": "Bet365", "calls": [
        _call("ff1", "fireflies"), adapter_copy, legacy_copy]}}
    removed = dedupe_calls_by_id(cbc)
    ids = [c["id"] for c in cbc["bet365"]["calls"]]
    cases.append(("one duplicate removed", removed == 1))
    cases.append(("apo1 appears exactly once", ids.count("apo1") == 1))
    kept = [c for c in cbc["bet365"]["calls"] if c["id"] == "apo1"][0]
    cases.append(("last copy (legacy, what write_cache keeps) wins",
                  kept.get("summary") == "haiku summary" and kept.get("host")))
    sb = FakeSB()
    stats = persist_to_supabase(cbc, sb, fetch=fake_fetch({}),
                                build=_build())
    cases.append(("no 21000 — calls upsert succeeded", stats["calls"]["failed"] == 0))
    cases.append(("both calls persisted", stats["calls"]["upserted"] == 2))

    # Cross-company: same id under two slugs is still one row.
    cbc2 = {"a": {"company": "A", "calls": [_call("dup", "apollo")]},
            "b": {"company": "B", "calls": [_call("dup", "apollo"), _call("z", "fireflies")]}}
    dedupe_calls_by_id(cbc2)
    total = sum(1 for d in cbc2.values() for c in d["calls"] if c["id"] == "dup")
    cases.append(("cross-company duplicate collapsed to one", total == 1))

    # Without the dedupe, the stub reproduces the production 21000 — proves
    # the test would catch a regression.
    raw = {"x": {"company": "X", "calls": [_call("d", "apollo"), _call("d", "apollo")]}}
    st = persist_to_supabase(raw, FakeSB(), fetch=fake_fetch({}), build=_build())
    cases.append(("undeduped batch reproduces 21000 and is COUNTED as failed",
                  st["calls"]["failed"] == 2 and "21000" in st["calls"]["failures"][0][2]))
    return cases


def _build():
    from transcript_store import build_transcript_row
    return build_transcript_row


def test_one_company_failure_does_not_drop_the_rest():
    cases = []
    cbc = {"good": {"company": "Good", "calls": [_call("g1", "fireflies"), _call("g2", "apollo")]},
           "bad": {"company": "Bad", "calls": [_call("b1", "fireflies")]},
           "late": {"company": "Late", "calls": [_call("l1", "fireflies")]}}
    sb = FakeSB(fail_calls_for={"Bad"})
    stats = persist_to_supabase(cbc, sb, fetch=fake_fetch({}), build=_build())
    cases.append(("companies after the failing one still upserted",
                  ["l1"] in sb.call_batches and ["g1", "g2"] in sb.call_batches))
    cases.append(("calls counted 3/4 upserted, 1 failed",
                  stats["calls"]["upserted"] == 3 and stats["calls"]["failed"] == 1))
    written = {r["call_id"] for r in sb.transcript_rows}
    cases.append(("transcripts still written for every call with a parent row",
                  written == {"g1", "g2", "l1"}))
    ff = stats["transcripts"]["fireflies"]
    cases.append(("failed-parent call counted skipped_parent_failed (FK), not silently dropped",
                  ff["skipped_parent_failed"] == 1))
    cases.append(("run is marked FAILED", persist_failed(stats)))
    return cases


def test_every_state_is_counted_and_reported():
    cases = []
    cbc = {"acme": {"company": "Acme", "calls": [
        _call("t1", "fireflies"), _call("t2", "fireflies"),
        _call("u1", "fireflies"),                 # no content
        _call("d1", "fireflies"),                 # transient fetch error
        _call("a1", "apollo"), _call("a2", "apollo", date="2026-01-01")]}}
    texts = {"u1": "", "d1": "ERR:RateLimited: fireflies: Too many requests",
             "a2": ""}
    stats = persist_to_supabase(cbc, FakeSB(), fetch=fake_fetch(texts), build=_build())
    ff, ap = stats["transcripts"]["fireflies"], stats["transcripts"]["apollo"]
    cases.append(("fireflies: attempted 4, text 2, unavailable 1, deferred 1",
                  (ff["attempted"], ff["text"], ff["unavailable"], ff["deferred"]) == (4, 2, 1, 1)))
    cases.append(("apollo: attempted 2, text 1, unavailable 1",
                  (ap["attempted"], ap["text"], ap["unavailable"]) == (2, 1, 1)))
    cases.append(("a lone deferred fetch does NOT fail the run (self-heal retries it)",
                  not persist_failed(stats)))
    rep = format_persist_report(stats)
    cases.append(("report has one column per state",
                  "| source | attempted | written | text | unavailable | deferred | write failed | skipped (parent failed) |" in rep))
    cases.append(("report row carries the real fireflies counts",
                  "| fireflies | 4 | 3 | 2 | 1 | 1 | 0 | 0 |" in rep))
    cases.append(("report carries the totals row", "| **total** | 6 | 5 | 3 | 2 | 1 | 0 | 0 |" in rep))
    cases.append(("report names the deferred reason", "Too many requests" in rep))
    cases.append(("report says OK", "✅ OK" in rep))
    return cases


def test_transcript_write_failure_is_loud():
    cases = []
    cbc = {"acme": {"company": "Acme", "calls": [_call("t1", "fireflies"), _call("a1", "apollo")]}}
    stats = persist_to_supabase(cbc, FakeSB(fail_transcripts=True), fetch=fake_fetch({}), build=_build())
    cases.append(("write failures counted per source",
                  stats["transcripts"]["fireflies"]["write_failed"] == 1
                  and stats["transcripts"]["apollo"]["write_failed"] == 1))
    cases.append(("run is marked FAILED", persist_failed(stats)))
    rep = format_persist_report(stats)
    cases.append(("report names the upsert error", "connection terminated" in rep))
    cases.append(("report says FAILED", "❌ FAILED" in rep))
    return cases


def test_total_fetch_outage_fails_the_run():
    cases = []
    cbc = {"acme": {"company": "Acme", "calls": [_call(f"c{i}", "apollo") for i in range(3)]}}
    texts = {f"c{i}": "ERR:HTTPError: 401 Unauthorized" for i in range(3)}
    stats = persist_to_supabase(cbc, FakeSB(), fetch=fake_fetch(texts), build=_build())
    cases.append(("every fetch for a source deferring (>=3) = outage = FAILED",
                  persist_failed(stats)))
    return cases


def test_step_summary_written_and_main_exits_nonzero_on_loss():
    cases = []
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as f:
        path = f.name
    old = os.environ.get("GITHUB_STEP_SUMMARY")
    os.environ["GITHUB_STEP_SUMMARY"] = path
    try:
        write_step_summary("### hello")
        cases.append(("step summary appended", "### hello" in Path(path).read_text()))
    finally:
        if old is None:
            os.environ.pop("GITHUB_STEP_SUMMARY", None)
        else:
            os.environ["GITHUB_STEP_SUMMARY"] = old
        os.unlink(path)
    # The old swallow is gone from main(): no bare "Supabase write failed" print.
    src = (REPO / "scripts" / "etl_calls.py").read_text()
    cases.append(("old swallowing except removed from main()",
                  "Supabase write failed: {e}" not in src
                  and "Transcript persist failed (calls unaffected)" not in src))
    cases.append(("__main__ propagates the exit code", "sys.exit(main())" in src))
    return cases


def _run_backfill_stubbed(calls, done_rows, texts, **kw):
    """Run backfill_transcripts.backfill() against in-memory tables."""
    import supabase_client
    import transcript_store
    import backfill_transcripts as bt

    written = []

    class W:
        client = object()

        def bulk_upsert_transcripts(self, rows):
            written.extend(rows)
            return len(rows)

    def select_all(client, table, columns="*", filters=None, page_size=1000):
        if table == "call_transcripts":
            return done_rows
        src = [f[2] for f in (filters or []) if f[1] == "source"][0]
        return [c for c in calls if c["source"] == src]

    fetch_calls = []

    def fetch(source, cid, clients, throttle=0.0, **_):
        fetch_calls.append(cid)
        v = texts.get(cid, "real words")
        if v.startswith("ERR:"):
            return [], v[4:], {}
        return ([{"key": "a", "name": "Rep", "sec": 2.0, "text": v, "q": False}] if v else []), None, {}

    saved = (supabase_client.SupabaseWriter, supabase_client.select_all,
             transcript_store.fetch_utterances, bt._sources)
    supabase_client.SupabaseWriter = W
    supabase_client.select_all = select_all
    transcript_store.fetch_utterances = fetch
    bt._sources = lambda: ["fireflies", "apollo"]
    try:
        grand = bt.backfill(dry_run=False, **kw)
    finally:
        (supabase_client.SupabaseWriter, supabase_client.select_all,
         transcript_store.fetch_utterances, bt._sources) = saved
    return grand, written, fetch_calls


def test_self_heal_is_capped_and_breaks_on_rate_limit():
    import backfill_transcripts as bt
    cases = []
    calls = ([{"call_id": f"f{i:03d}", "source": "fireflies", "call_date": f"2026-09-{(i % 28) + 1:02d}"}
              for i in range(100)]
             + [{"call_id": f"a{i}", "source": "apollo", "call_date": "2026-09-21"} for i in range(5)])
    done = [{"call_id": "f000", "transcript_quality": "full", "unavailable_reason": None}]

    grand, written, fetched = _run_backfill_stubbed(calls, done, {}, limit=40,
                                                    newest_first=True, max_consecutive_deferrals=5)
    ff = grand["fireflies"]
    cases.append(("cap: at most 40 fireflies attempted in one run", ff["attempted"] == 40))
    cases.append(("cap: pending before = 99 (100 minus 1 done)", ff["pending"] == 99))
    cases.append(("already-done call never re-fetched", "f000" not in fetched))
    ff_dates = [c["call_date"] for c in calls if c["call_id"] in set(fetched) and c["source"] == "fireflies"]
    cases.append(("newest-first: the 40 attempted are the most recent call dates",
                  min(ff_dates) >= sorted([c["call_date"] for c in calls
                                           if c["source"] == "fireflies" and c["call_id"] != "f000"],
                                          reverse=True)[39]))
    rep = bt.format_backfill_report(grand, False, 40, 5)
    cases.append(("report: fireflies row shows 99 pending before, 40 written, 59 pending after",
                  "| fireflies | 99 | 40 | 40 | 0 | 0 | 40 | 59 | no |" in rep))

    # Rate limit: every fetch defers → stop after 5, not 40 × full backoff.
    rl = {c["call_id"]: "ERR:RateLimited: fireflies: Too many requests" for c in calls}
    grand, written, fetched = _run_backfill_stubbed(calls, [], rl, limit=40,
                                                    newest_first=True, max_consecutive_deferrals=5)
    ff = grand["fireflies"]
    cases.append(("circuit breaker: fireflies stops after 5 consecutive deferrals",
                  ff["attempted"] == 5 and ff["stopped"].startswith("circuit breaker")))
    cases.append(("breaker is per source: apollo still processed",
                  grand["apollo"]["attempted"] == 5))
    cases.append(("deferred calls are NOT written (left absent to retry)",
                  not any(r["call_id"].startswith("f") for r in written)))
    rep = bt.format_backfill_report(grand, False, 40, 5)
    cases.append(("report shows the trip and the reason",
                  "circuit breaker: 5 consecutive deferrals" in rep and "Too many requests" in rep))
    return cases


TESTS = [
    test_self_heal_is_capped_and_breaks_on_rate_limit,
    test_duplicate_apollo_id_reaches_supabase_once,
    test_one_company_failure_does_not_drop_the_rest,
    test_every_state_is_counted_and_reported,
    test_transcript_write_failure_is_loud,
    test_total_fetch_outage_fails_the_run,
    test_step_summary_written_and_main_exits_nonzero_on_loss,
]


def run():
    failed = 0
    for t in TESTS:
        print(f"\n{t.__name__}")
        try:
            cases = t()
        except Exception as e:
            import traceback
            traceback.print_exc()
            cases = [(f"raised {type(e).__name__}: {e}", False)]
        for label, ok in cases:
            print(f"  {'PASS' if ok else 'FAIL'}  {label}")
            failed += 0 if ok else 1
    print(f"\n{'ALL PASS' if not failed else f'{failed} FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
