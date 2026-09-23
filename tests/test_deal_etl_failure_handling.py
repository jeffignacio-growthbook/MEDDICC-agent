"""
Regression test: the deals ETL retries transient HubSpot errors, exits
non-zero when it fails, and never writes "unknown" over good company data.

Why this exists (2026-09-23): scripts/hubspot_deals.py made bare requests
calls (no retry, no 429 handling) and every failure path in
scripts/etl_deals.py printed a message and returned None, so the process
exited 0. Daily Deal ETL runs #18 (2026-08-15), #40 (2026-09-06) and #41
(2026-09-07) each hit "429 Client Error: Too Many Requests" on
/crm/v3/objects/deals/search, fetched 0 deals, committed nothing, and
showed green with the failure alert skipped. A failed company-association
batch was worse than silent: its deals were written with company_id=None,
segment='Unknown', segment_reason='no_company' over their good values. An
owner-fetch failure would have blanked every deal's owner the same way.

Pins (real HubSpotDealsClient, http_retry, etl_deals.main and
SupabaseWriter.upsert_deal; only the HTTP session and Supabase table are
fakes):
  1. 429 is retried (honouring Retry-After), 5xx and dropped connections
     get the short backoff, other 4xx fail at once, and the final error
     propagates unchanged.
  2. A failed deal fetch makes the real process exit non-zero — what
     GitHub Actions turns red on — and a run with no failures exits 0.
  3. A company batch that still fails after retries leaves those deals'
     stored company fields untouched, writes everything else, and exits 1.
  4. An owner-fetch failure is fatal: exit 1, nothing written.
  5. The run summary prints the counts.
Each has a planted-bug control.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import http_retry  # noqa: E402
import hubspot_deals  # noqa: E402
import etl_deals  # noqa: E402
import supabase_client  # noqa: E402

BASE = "https://api.hubapi.com"


# ── fakes ────────────────────────────────────────────────────────────────────

def _response(status, body=None, headers=None, url="https://api.hubapi.com/x"):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body if body is not None else {}).encode()
    r.headers.update(headers or {})
    r.url = url
    return r


DEALS = [
    {"id": "D1", "properties": {"dealname": "One", "dealstage": "s1", "pipeline": "default",
                                "hubspot_owner_id": "1", "incremental_arr": "100000",
                                "amount": "100000", "closedate": "2026-10-01"}},
    {"id": "D2", "properties": {"dealname": "Two", "dealstage": "s1", "pipeline": "default",
                                "hubspot_owner_id": "1", "incremental_arr": "50000",
                                "amount": "50000", "closedate": "2026-11-01"}},
]


class FakeSession:
    """Routes (method, path) to canned HubSpot responses. `fail` maps a path
    to a list of status codes (or exceptions) to serve before succeeding."""

    def __init__(self, fail=None):
        self.fail = {k: list(v) for k, v in (fail or {}).items()}
        self.calls = []
        self.headers = {}

    def request(self, method, url, timeout=None, params=None, json=None):
        path = url[len(BASE):]
        self.calls.append((method, path))
        queue = self.fail.get(path)
        if queue:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            status, hdrs = item if isinstance(item, tuple) else (item, {})
            return _response(status, {"message": "planted"}, hdrs, url)
        if path == "/crm/v3/owners":
            return _response(200, {"results": [{"id": "1", "email": "rep@example.com"}]})
        if path == "/crm/v3/pipelines/deals":
            return _response(200, {"results": [{"stages": [
                {"id": "closedwon", "label": "Closed Won"}, {"id": "s1", "label": "Discovery"}]}]})
        if path == "/crm/v3/objects/deals/search":
            return _response(200, {"results": DEALS})
        if path == "/crm/v4/associations/deals/companies/batch/read":
            return _response(200, {"results": [
                {"from": {"id": d["id"]}, "to": [{"toObjectId": f"C{d['id']}"}]}
                for d in json["inputs"]]})
        if path == "/crm/v3/objects/companies/batch/read":
            return _response(200, {"results": [
                {"id": i["id"], "properties": {"name": f"Co {i['id']}",
                                               "numberofemployees": "5000",
                                               "domain": f"{i['id'].lower()}.com"}}
                for i in json["inputs"]]})
        return _response(404, {"message": f"unrouted {path}"}, url=url)


def _client(fail=None):
    c = hubspot_deals.HubSpotDealsClient(api_key="test")
    c.session = FakeSession(fail)
    hubspot_deals.HubSpotDealsClient._closed_stage_ids = None
    return c


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def upsert(self, row, on_conflict=None):
        self.rows.append(row)
        return self

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def execute(self):
        return type("R", (), {"data": []})()


class FakeWriter(supabase_client.SupabaseWriter):
    rows = []

    def __init__(self):
        self.client = type("C", (), {"table": lambda _s, name: FakeTable(FakeWriter.rows)})()


@contextlib.contextmanager
def _no_sleep(record=None):
    saved = time.sleep
    time.sleep = (record.append if record is not None else (lambda s: None))
    try:
        yield
    finally:
        time.sleep = saved


@contextlib.contextmanager
def _etl_env(client, mode="active"):
    """Run etl_deals.main() against `client`, a temp index dir and FakeWriter."""
    saved = (hubspot_deals.get_hubspot_deals_client, etl_deals.DEALS_DIR,
             supabase_client.SupabaseWriter, sys.argv, os.environ.get("SUPABASE_URL"))
    tmp = tempfile.TemporaryDirectory()
    FakeWriter.rows = []
    hubspot_deals.get_hubspot_deals_client = lambda api_key=None: client
    etl_deals.DEALS_DIR = Path(tmp.name)
    supabase_client.SupabaseWriter = FakeWriter
    sys.argv = ["etl_deals.py"] + ([] if mode == "active" else ["--mode", mode])
    os.environ["SUPABASE_URL"] = "https://fake.invalid"
    try:
        yield Path(tmp.name)
    finally:
        (hubspot_deals.get_hubspot_deals_client, etl_deals.DEALS_DIR,
         supabase_client.SupabaseWriter, sys.argv, url) = saved
        if url is None:
            os.environ.pop("SUPABASE_URL", None)
        else:
            os.environ["SUPABASE_URL"] = url
        tmp.cleanup()


def _run_main(client, mode="active"):
    out = io.StringIO()
    with _etl_env(client, mode) as d, _no_sleep(), contextlib.redirect_stdout(out):
        code = etl_deals.main()
        index = (d / "index.json").read_text() if (d / "index.json").exists() else None
    return code, out.getvalue(), list(FakeWriter.rows), index


# ── 1. retry policy ──────────────────────────────────────────────────────────

def test_429_retried_with_retry_after_then_succeeds():
    c = _client({"/crm/v3/objects/deals/search": [(429, {"Retry-After": "3"})]})
    sleeps = []
    with _no_sleep(sleeps), contextlib.redirect_stdout(io.StringIO()):
        deals = c.get_active_deals()
    assert [d["id"] for d in deals] == ["D1", "D2"]
    assert sleeps == [3.0] and c.retry_count == 1, (sleeps, c.retry_count)
    print("✓ a 429 on deals/search is retried after Retry-After (3s) and the fetch succeeds")


def test_retry_schedule_and_non_retryable_errors():
    c = _client({"/crm/v3/objects/deals/search": [503] * 5})
    sleeps = []
    with _no_sleep(sleeps), contextlib.redirect_stdout(io.StringIO()):
        try:
            c.get_active_deals()
            raise AssertionError("5 × 503 should raise")
        except requests.HTTPError as e:
            assert e.response.status_code == 503
    assert sleeps == [2.0, 4.0, 8.0, 16.0], sleeps

    c = _client({"/crm/v3/objects/deals/search": [429] * 5})
    sleeps = []
    with _no_sleep(sleeps), contextlib.redirect_stdout(io.StringIO()):
        try:
            c.get_active_deals()
        except requests.HTTPError:
            pass
    assert sleeps == [15.0, 30.0, 60.0, 120.0], sleeps

    c = _client({"/crm/v3/objects/deals/search": [requests.ConnectionError("reset")]})
    with _no_sleep(), contextlib.redirect_stdout(io.StringIO()):
        assert len(c.get_active_deals()) == 2

    for status in (400, 401, 404):
        c = _client({"/crm/v3/objects/deals/search": [status]})
        with _no_sleep(), contextlib.redirect_stdout(io.StringIO()):
            try:
                c.get_active_deals()
                raise AssertionError(f"{status} should raise")
            except requests.HTTPError:
                pass
        searches = [p for _, p in c.session.calls if p.endswith("/search")]
        assert len(searches) == 1, f"{status} was retried: {searches}"
    print("✓ 5xx backoff 2/4/8/16s, 429 backoff 15/30/60/120s, connection reset retried, "
          "400/401/404 fail on the first attempt, final error propagates")


def test_retry_check_catches_a_client_that_does_not_retry():
    """Planted bug: _request without retry (the pre-fix client)."""
    c = _client({"/crm/v3/objects/deals/search": [429]})
    saved = hubspot_deals.HubSpotDealsClient.RETRIES
    hubspot_deals.HubSpotDealsClient.RETRIES = 1
    try:
        with _no_sleep(), contextlib.redirect_stdout(io.StringIO()):
            try:
                c.get_active_deals()
                raise AssertionError("planted no-retry client unexpectedly succeeded")
            except requests.HTTPError:
                pass
    finally:
        hubspot_deals.HubSpotDealsClient.RETRIES = saved
    print("✓ planted no-retry client fails on the same 429 (the incident behaviour)")


# ── 2. exit codes ────────────────────────────────────────────────────────────

def test_clean_run_exits_zero_and_prints_summary():
    code, out, rows, index = _run_main(_client())
    assert code == 0, out[-800:]
    assert "RUN SUMMARY (active mode)" in out and "✓ ETL Complete — no failures" in out
    assert "Deals fetched from HubSpot:        2" in out
    assert "Supabase:                          2 upserted, 0 failed" in out
    assert {r["deal_id"] for r in rows} == {"D1", "D2"}
    assert all(r["segment"] != "Unknown" and r["company_id"] for r in rows), rows
    print("✓ clean run: exit 0, summary shows 2 fetched / 2 upserted, company fields populated")


def test_deal_fetch_failure_after_retries_exits_one_and_writes_nothing():
    code, out, rows, index = _run_main(_client({"/crm/v3/objects/deals/search": [429] * 5}))
    assert code == 1, out[-800:]
    assert "❌ Failed to fetch deals" in out
    assert rows == [] and index is None
    print("✓ deals/search still 429 after 5 attempts: exit 1, nothing written")


def _process_exit_code(script):
    env = {k: v for k, v in os.environ.items()
           if k not in ("HUBSPOT_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY")}
    env["PYTHONPATH"] = f"{REPO}:{REPO / 'scripts'}"
    return subprocess.run([sys.executable, str(script)], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120).returncode


def test_real_process_exits_nonzero_on_failure():
    """What GitHub Actions sees: the process exit status of the step."""
    code = _process_exit_code(REPO / "scripts" / "etl_deals.py")
    assert code == 1, f"exit status {code}"
    print("✓ `python scripts/etl_deals.py` with no HUBSPOT_API_KEY exits 1 (Actions step turns red)")


def test_exit_check_catches_the_pre_fix_entry_point():
    """Planted bug: the old `main()` entry point that discards the code."""
    src = (REPO / "scripts" / "etl_deals.py").read_text()
    assert src.rstrip().endswith("sys.exit(main())")
    planted = REPO / "scripts" / "_planted_etl_deals_exit0.py"
    planted.write_text(src.rstrip()[: -len("sys.exit(main())")] + "main()\n")
    try:
        code = _process_exit_code(planted)
    finally:
        planted.unlink()
    assert code == 0, f"planted entry point exited {code}; the check above would be blind"
    print("✓ planted pre-fix entry point exits 0 on the same failure (the incident behaviour)")


# ── 3. partial company-batch failure ─────────────────────────────────────────

def test_failed_company_batch_preserves_stored_company_fields():
    for path in ("/crm/v4/associations/deals/companies/batch/read",
                 "/crm/v3/objects/companies/batch/read"):
        code, out, rows, index = _run_main(_client({path: [500] * 5}))
        assert code == 1, (path, out[-800:])
        assert {r["deal_id"] for r in rows} == {"D1", "D2"}, "other fields must still be written"
        for r in rows:
            for k in etl_deals.COMPANY_DERIVED_FIELDS + ("company_name", "company_slug"):
                assert k not in r, f"{path}: {k}={r[k]!r} would overwrite stored data"
            assert r["arr_usd"] in (100000.0, 50000.0) and r["owner_email"] == "rep@example.com"
        assert "Company data unknown (preserved):  2" in out
        assert "❌ ETL finished with failures (exit 1):" in out
    print("✓ association or company batch failing after retries: stage/ARR/owner written, "
          "company fields not sent, exit 1, summary counts the 2 preserved deals")


def test_index_keeps_previous_company_fields_for_failed_lookups():
    prev = {"deals": {"D1": {"company_name": "Real Co", "company_slug": "real-co",
                             "company_id": "C9", "segment": "Enterprise"}}}
    client = _client({"/crm/v4/associations/deals/companies/batch/read": [500] * 5})
    out = io.StringIO()
    with _etl_env(client) as d, _no_sleep(), contextlib.redirect_stdout(out):
        (d / "index.json").write_text(json.dumps(prev))
        code = etl_deals.main()
        index = json.loads((d / "index.json").read_text())
    assert code == 1
    d1 = index["deals"]["D1"]
    assert (d1["company_name"], d1["company_id"], d1["segment"]) == ("Real Co", "C9", "Enterprise"), d1
    print("✓ index carries D1's previous company fields over instead of writing 'unknown'")


def test_preservation_check_catches_the_pre_fix_overwrite():
    """Planted bug: treat a failed lookup as 'no company' (the old behaviour)."""
    saved = etl_deals._company_lookup_failed
    etl_deals._company_lookup_failed = lambda *a: False
    try:
        code, out, rows, index = _run_main(
            _client({"/crm/v4/associations/deals/companies/batch/read": [500] * 5}))
    finally:
        etl_deals._company_lookup_failed = saved
    assert any(r.get("segment") == "Unknown" and r.get("segment_reason") == "no_company"
               and "company_id" in r and r["company_id"] is None for r in rows), rows
    print("✓ planted pre-fix behaviour writes segment='Unknown', company_id=None "
          "(the corruption the preservation check catches)")


# ── 4. owner fetch ───────────────────────────────────────────────────────────

def test_owner_fetch_failure_is_fatal():
    code, out, rows, index = _run_main(_client({"/crm/v3/owners": [503] * 5}))
    assert code == 1 and rows == [] and index is None, (code, out[-600:])
    assert "❌ Could not fetch active owners" in out
    print("✓ owner fetch failing after retries: exit 1, nothing written "
          "(would otherwise blank every deal's owner)")


if __name__ == "__main__":
    test_429_retried_with_retry_after_then_succeeds()
    test_retry_schedule_and_non_retryable_errors()
    test_retry_check_catches_a_client_that_does_not_retry()
    test_clean_run_exits_zero_and_prints_summary()
    test_deal_fetch_failure_after_retries_exits_one_and_writes_nothing()
    test_real_process_exits_nonzero_on_failure()
    test_exit_check_catches_the_pre_fix_entry_point()
    test_failed_company_batch_preserves_stored_company_fields()
    test_index_keeps_previous_company_fields_for_failed_lookups()
    test_preservation_check_catches_the_pre_fix_overwrite()
    test_owner_fetch_failure_is_fatal()
    print("\n✅ All tests passed")
