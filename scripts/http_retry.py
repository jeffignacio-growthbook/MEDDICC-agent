"""
One retry-with-backoff mechanism for outbound API calls.

Extracted 2026-09-23 from transcript_store.fetch_utterances (#28), where it
was proven against real Fireflies/Apollo rate limits, so the HubSpot deals
client could use the same logic instead of a third hand-rolled copy. Both
callers now go through retry_call(); only their policies differ (what's
retryable, and the long wait for a source-specific rate-limit exception).

The schedule:
  - HTTP 429, or an error whose text says "too many requests" / "rate
    limit": LONG wait. Honors a numeric Retry-After (capped at 120s),
    else 15s, 30s, 60s, 120s. A short schedule would just re-hit the
    limit's burst window.
  - anything else the caller counts as retryable: backoff * 2**attempt
    (2s, 4s, 8s, ... by default).
  - the last attempt never sleeps; its exception is re-raised unchanged.

time.sleep is looked up at call time, so tests that swap time.sleep for a
recorder see every wait.
"""
import time


def rate_limit_wait(exc, attempt):
    """Seconds to wait if `exc` is an HTTP 429 or says it's a rate limit,
    else None. Honors a numeric Retry-After header (capped at 120s);
    otherwise 15s, 30s, 60s, 120s."""
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if status != 429:
        # No HTTP status: only explicit phrases count — never a bare "429"
        # substring, which can appear inside a URL / hex call id.
        t = str(exc).lower()
        if status is not None or not ("too many request" in t or "rate limit" in t):
            return None
    try:
        ra = float((getattr(resp, "headers", None) or {}).get("Retry-After"))
        return max(1.0, min(120.0, ra))
    except (TypeError, ValueError):
        return min(120.0, 15.0 * (2 ** attempt))


def retry_call(fn, *, retries, backoff=2.0, retry_if=None, wait_for=None,
               on_retry=None):
    """Call fn() up to `retries` times; return its first successful result.

    retry_if(exc) -> bool: False re-raises immediately (default: retry all).
    wait_for(exc, attempt) -> seconds or None: an override for the wait;
        None falls through to rate_limit_wait(), then to the short backoff.
    on_retry(exc, attempt, wait): called before each sleep (for logging).
    After the last attempt the final exception is re-raised as-is.
    """
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt == retries - 1 or (retry_if is not None and not retry_if(e)):
                raise
            wait = wait_for(e, attempt) if wait_for is not None else None
            if wait is None:
                wait = rate_limit_wait(e, attempt)
            if wait is None:
                wait = backoff * (2 ** attempt)
            if on_retry is not None:
                on_retry(e, attempt, wait)
            time.sleep(wait)
