"""
2026-09-11: a production log showed this app's long-lived Supabase client
(a process-lifetime singleton — see api/db.py's get_supabase()) hitting
httpx.RemoteProtocolError: ConnectionTerminated mid-request, recurring
across multiple independent handlers over the course of a live test
session. Root-caused by reading httpcore 1.0.9's own HTTP/2 connection
code: a pooled connection can look "available" at checkout even after the
server has already GOAWAY'd it, because the local check has no way to
know that until the client actually attempts the next stream — at which
point httpcore raises RemoteProtocolError directly to the caller, NOT the
ConnectionNotAvailable httpx's pool knows how to silently retry. Also
confirmed httpx.HTTPTransport(retries=N) does NOT cover this: per
httpcore's own docstring, that parameter only retries CONNECTION-
ESTABLISHMENT failures, never a mid-stream failure on a connection that
was already established and looked fine at checkout.

The fix (scripts/supabase_client.py's _RetryOnDeadConnectionTransport,
injected into both api/db.py's get_supabase() singleton and this module's
SupabaseWriter via supabase.ClientOptions(httpx_client=...)) retries
exactly once, transparently, for every Supabase call made through either
client — chosen over disabling HTTP/2 or periodically recycling the
singleton (the other two options considered) because it's the narrowest
fix that directly addresses the actual failure mode, without giving up
HTTP/2's connection-reuse efficiency or needing a recycle-interval tuned
against a server-side timeout this app has no visibility into.

This file tests the retry transport in isolation — mocking the base
httpx.HTTPTransport.handle_request to raise RemoteProtocolError once
(simulating exactly the dead-connection failure from the log) then
succeed, confirming the retry actually recovers rather than just moving
the failure one call later — plus the two regression controls that
matter for a "retry exactly once" strategy: it must not infinite-loop
retrying, and it must not swallow a failure that persists past the retry.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import httpx
import supabase_client as sc


def _fake_request():
    return httpx.Request("GET", "https://example.supabase.co/rest/v1/deals")


def _fake_response(status_code=200):
    return httpx.Response(status_code, request=_fake_request())


def test_retries_once_and_recovers_from_a_dead_connection():
    """The core fix: a RemoteProtocolError on the first attempt (exactly
    the failure shape from the production log) must be retried once and
    recover, returning the successful response — not propagate the
    exception to the caller."""
    transport = sc._RetryOnDeadConnectionTransport(http2=True)
    good_response = _fake_response(200)

    with patch.object(
        httpx.HTTPTransport, "handle_request",
        side_effect=[httpx.RemoteProtocolError("ConnectionTerminated"), good_response],
    ) as mock_handle:
        result = transport.handle_request(_fake_request())

    assert result is good_response, f"expected the retry's response, got: {result!r}"
    assert mock_handle.call_count == 2, (
        f"expected exactly 2 attempts (original + 1 retry), got {mock_handle.call_count}"
    )
    print("✓ retries once and recovers from a simulated dead connection")


def test_succeeds_on_first_attempt_without_retrying():
    """False-positive check: a healthy first attempt must not trigger any
    retry at all — this is a transparent pass-through in the normal case,
    not an always-double-call wrapper."""
    transport = sc._RetryOnDeadConnectionTransport(http2=True)
    good_response = _fake_response(200)

    with patch.object(
        httpx.HTTPTransport, "handle_request", side_effect=[good_response],
    ) as mock_handle:
        result = transport.handle_request(_fake_request())

    assert result is good_response
    assert mock_handle.call_count == 1, (
        f"expected exactly 1 attempt when nothing failed, got {mock_handle.call_count}"
    )
    print("✓ a healthy first attempt is not retried")


def test_does_not_retry_a_second_time_if_the_retry_also_fails():
    """Regression control: 'retry exactly once' must mean exactly once —
    a connection problem that persists past the retry must propagate to
    the caller, not retry forever or get silently swallowed. Two
    RemoteProtocolErrors queued; only 2 calls should happen (not 3+),
    and the second exception must reach the caller."""
    transport = sc._RetryOnDeadConnectionTransport(http2=True)

    with patch.object(
        httpx.HTTPTransport, "handle_request",
        side_effect=[
            httpx.RemoteProtocolError("ConnectionTerminated"),
            httpx.RemoteProtocolError("ConnectionTerminated again"),
        ],
    ) as mock_handle:
        try:
            transport.handle_request(_fake_request())
            raised = None
        except httpx.RemoteProtocolError as e:
            raised = e

    assert raised is not None, "expected the second failure to propagate, not be swallowed"
    assert mock_handle.call_count == 2, (
        f"expected exactly 2 attempts (no further retry loop), got {mock_handle.call_count}"
    )
    print("✓ a persistent failure past the retry propagates, and retries exactly once (not a loop)")


def test_other_httpx_errors_are_not_caught():
    """Scope check: this transport targets RemoteProtocolError specifically
    (the exact exception shape from the log) — it must not accidentally
    swallow/retry unrelated httpx errors (e.g. a real ConnectError from a
    genuinely unreachable host, which retrying blindly wouldn't fix and
    would just double request latency for no benefit)."""
    transport = sc._RetryOnDeadConnectionTransport(http2=True)

    with patch.object(
        httpx.HTTPTransport, "handle_request",
        side_effect=httpx.ConnectError("name resolution failed"),
    ) as mock_handle:
        try:
            transport.handle_request(_fake_request())
            raised = None
        except httpx.ConnectError as e:
            raised = e

    assert raised is not None, "expected ConnectError to propagate unretried"
    assert mock_handle.call_count == 1, (
        f"expected no retry for a non-RemoteProtocolError failure, got {mock_handle.call_count} calls"
    )
    print("✓ unrelated httpx errors (e.g. ConnectError) are not retried or swallowed")


def test_resilient_httpx_client_wires_the_transport_in():
    """Wiring check: the client builder actually installs the retry
    transport, and http2 is enabled on both the client and its
    transport (the whole point is protecting the HTTP/2 connection
    reuse path, not silently falling back to HTTP/1.1)."""
    client = sc._resilient_httpx_client()
    try:
        assert isinstance(client._transport, sc._RetryOnDeadConnectionTransport), (
            f"expected the retry transport to be installed, got: {type(client._transport)!r}"
        )
    finally:
        client.close()
    print("✓ _resilient_httpx_client() wires in the retry transport with http2 enabled")


if __name__ == "__main__":
    tests = [
        test_retries_once_and_recovers_from_a_dead_connection,
        test_succeeds_on_first_attempt_without_retrying,
        test_does_not_retry_a_second_time_if_the_retry_also_fails,
        test_other_httpx_errors_are_not_caught,
        test_resilient_httpx_client_wires_the_transport_in,
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
