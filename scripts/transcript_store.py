"""
Shared transcript fetch + assemble + metrics + row-shaping
(STORE_AND_BACKFILL_TRANSCRIPTS). One place both the backfill and the go-forward
ETL wire go through, so the source difference stays HERE and neither caller
branches on source.

Both sources carry per-utterance timestamps — Fireflies in SECONDS, Apollo in
MILLISECONDS — normalised to seconds at this boundary (same principle as
assembling Apollo's fragments: the consumer never knows the source). From the
normalised utterances we compute talk time, question rate, and longest
monologue in the SAME pass that assembles the text, because the stored
transcript has no timestamps and recomputing later would mean re-fetching.
"""
import os
import time
from collections import defaultdict
from datetime import date

FULL = "full"
PARTIAL = "partial"
FRAGMENTS_ONLY = "fragments_only"
UNAVAILABLE = "unavailable"

# An empty result (fetch succeeded, no sentences) on a call older than this is
# TERMINAL — a transcript will never appear (silent/failed recording), so resume
# must stop re-attempting it (else every future pass burns an API call on it).
# On a RECENT call the same emptiness is PENDING — the transcript may still be
# generating — so resume keeps retrying it. Recorders finalise within minutes to
# hours; 3 days is a safe cutoff. unavailable_reason carries the distinction as a
# "terminal:" / "retry:" prefix, read by is_done() — no extra column needed.
STILL_PROCESSING_DAYS = int(os.getenv("TRANSCRIPT_STILL_PROCESSING_DAYS", "3"))
TERMINAL = "terminal:"
RETRY = "retry:"

# A monologue is consecutive speech by one speaker. Interjections from other
# speakers totalling under this many seconds between the speaker's utterances
# are backchannel ("mm-hmm", "right") — they do NOT break the run and are NOT
# credited to its length. This many seconds or more ends the run.
BACKCHANNEL_MAX_SECONDS = 3.0


# ── utterance model ──────────────────────────────────────────────────────────
# Each utterance: {"key": stable speaker id, "name": display name,
#                  "sec": float seconds, "text": str, "q": bool is-question}

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _utterance(key, name, sec, text):
    text = (text or "").strip()
    return {"key": str(key or name or "Unknown"), "name": (name or "Unknown"),
            "sec": max(0.0, sec or 0.0), "text": text,
            "q": text.endswith("?")}


def _fireflies_utterances(sentences):
    """Fireflies sentences: {speaker_name, text, raw_text, start_time, end_time}
    with times in SECONDS. No stable id — key on the name."""
    out = []
    for s in sentences or []:
        st, et = _num(s.get("start_time")), _num(s.get("end_time"))
        sec = (et - st) if (st is not None and et is not None) else 0.0
        name = s.get("speaker_name") or "Unknown"
        out.append(_utterance(name, name, sec, s.get("text") or s.get("raw_text")))
    return out


def _apollo_utterances(conversation):
    """Apollo fragments: {participant_id, participant_name, spoken_sentence,
    start_time, end_time} with times in MILLISECONDS. Key on participant_id."""
    out = []
    for f in (conversation.get("transcript") or []):
        st, et = _num(f.get("start_time")), _num(f.get("end_time"))
        sec = ((et - st) / 1000.0) if (st is not None and et is not None) else 0.0
        name = f.get("participant_name") or f.get("speaker") or "Unknown"
        key = f.get("participant_id") or name
        out.append(_utterance(key, name, sec, f.get("spoken_sentence") or f.get("text")))
    return out


# ── per-source fetch → utterances ────────────────────────────────────────────

class RateLimited(Exception):
    """A transient rate-limit. fetch_utterances retries these with a LONG
    backoff, as opposed to a permanent GraphQL error (returned, not raised)."""


def _is_rate_limit(text):
    t = (text or "").lower()
    return "too many request" in t or "rate limit" in t or "429" in t


def _fetch_fireflies(call_id, clients):
    client = clients.get("fireflies")
    if client is None:
        from fireflies_client import FirefliesClient
        client = clients["fireflies"] = FirefliesClient()
    q = ("query T($id:String!){ transcript(id:$id){ sentences "
         "{ speaker_name text raw_text start_time end_time } } }")
    res = client._query(q, {"id": call_id})
    if res.get("errors"):
        msg = "; ".join(e.get("message", "")[:80] for e in res["errors"])
        # Fireflies returns rate-limit as a GraphQL error in the response BODY,
        # not an HTTP error — raise so fetch_utterances backs off and retries
        # instead of recording a false 'unavailable'. Other GraphQL errors are
        # permanent for this id → return them.
        if _is_rate_limit(msg):
            raise RateLimited(f"fireflies: {msg[:100]}")
        return [], f"fireflies GraphQL: {msg[:140]}"
    sents = ((res.get("data") or {}).get("transcript") or {}).get("sentences") or []
    return _fireflies_utterances(sents), None


def _fetch_apollo(call_id, clients):
    client = clients.get("apollo")
    if client is None:
        from apollo_client import ApolloClient
        client = clients["apollo"] = ApolloClient()
    convo = client.get_conversation(call_id)
    return _apollo_utterances(convo), None


def _fetch_gong(call_id, clients):
    # Not in GrowthBook's priority; best-effort so the caller stays source-
    # agnostic. Gong's adapter returns assembled text (no per-utterance times),
    # so metrics are unavailable — store the text only.
    client = clients.get("gong")
    if client is None:
        try:
            from adapters.gong_adapter import GongAdapter
            client = clients["gong"] = GongAdapter()
        except Exception as e:
            return [], f"gong adapter unavailable: {type(e).__name__}"
    text = client.get_transcript(call_id) or ""
    # One pseudo-utterance carrying the text so it still gets stored/assembled.
    return ([{"key": "gong", "name": "transcript", "sec": 0.0, "text": text,
              "q": False}] if text.strip() else []), None


_FETCHERS = {"fireflies": _fetch_fireflies, "apollo": _fetch_apollo, "gong": _fetch_gong}


def fetch_utterances(source, call_id, clients, retries=6, backoff=2.0, throttle=0.0):
    """Fetch normalised utterances for one call. Returns (utterances, error).

    `throttle` sleeps before each call to stay under a source's request rate
    (Fireflies rate-limits a fast sequential sweep). A rate-limit backs off
    LONG (15s, 30s, 60s, …) and uses the full retry budget, since the limit is
    a burst window that only clears with real wait; other exceptions use the
    short backoff. After the cap, returns ([], reason)."""
    fetcher = _FETCHERS.get((source or "").lower())
    if fetcher is None:
        return [], f"no transcript fetcher for source '{source}'"
    last = None
    for attempt in range(retries):
        if throttle:
            time.sleep(throttle)
        try:
            return fetcher(call_id, clients)
        except RateLimited as e:
            last = f"RateLimited: {str(e)[:140]}"
            if attempt < retries - 1:
                time.sleep(min(120.0, 15.0 * (2 ** attempt)))
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:140]}"
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    return [], last


# ── assembly + metrics ───────────────────────────────────────────────────────

def assemble_text(utterances):
    """Readable, speaker-attributed lines — identical shape across sources.
    Strips per line so a whitespace-only utterance can't emit a phantom
    '[Name]:   ' line (which would read as text and mis-mark the row FULL)."""
    return "\n".join(f"[{u['name']}]: {u['text'].strip()}"
                     for u in utterances if (u.get("text") or "").strip())


def assemble_apollo(conversation):
    """Kept for callers/tests that pass a raw Apollo conversation dict."""
    return assemble_text(_apollo_utterances(conversation))


def longest_monologue(utterances):
    """(seconds, speaker_key) of the longest continuous single-speaker run,
    treating sub-BACKCHANNEL_MAX_SECONDS interjections as non-breaking
    backchannel (not credited to the run). See BACKCHANNEL_MAX_SECONDS."""
    best_sec, best_key = 0.0, None
    owner = None
    run_sec = 0.0          # owner's spoken seconds in the current run
    interrupt_sec = 0.0    # other-speaker seconds since the owner last spoke
    for u in utterances:
        if owner is None:
            owner, run_sec, interrupt_sec = u["key"], u["sec"], 0.0
        elif u["key"] == owner:
            run_sec += u["sec"]
            interrupt_sec = 0.0            # owner reclaimed the floor
        else:
            interrupt_sec += u["sec"]
            if interrupt_sec >= BACKCHANNEL_MAX_SECONDS:
                if run_sec > best_sec:
                    best_sec, best_key = run_sec, owner
                owner, run_sec, interrupt_sec = u["key"], u["sec"], 0.0
            # else: backchannel — ignore, keep the owner's run open
    if run_sec > best_sec:
        best_sec, best_key = run_sec, owner
    return round(best_sec, 1), best_key


def compute_metrics(utterances):
    """Per-speaker talk time + question count + longest monologue, from
    normalised utterances (seconds)."""
    talk, questions, names = defaultdict(float), defaultdict(int), {}
    for u in utterances:
        talk[u["key"]] += u["sec"]
        names[u["key"]] = u["name"]
        if u["q"]:
            questions[u["key"]] += 1
    mono_sec, mono_key = longest_monologue(utterances)
    return {
        "talk_time_seconds": {k: round(v, 1) for k, v in talk.items()},
        "question_count": dict(questions),
        "speakers": names,
        "total_speech_seconds": round(sum(talk.values()), 1),
        "longest_monologue_seconds": mono_sec,
        "longest_monologue_speaker": names.get(mono_key),
        "sentence_count": len(utterances),
    }


_EMPTY_METRICS = {
    "talk_time_seconds": {}, "question_count": {}, "speakers": {},
    "total_speech_seconds": None, "longest_monologue_seconds": None,
    "longest_monologue_speaker": None, "sentence_count": 0,
}


def _empty_reason(call_date):
    """Classify an empty result as TERMINAL (old call — no transcript will ever
    appear) or RETRY (recent call — may still be processing), by call age."""
    try:
        age = (date.today() - date.fromisoformat(str(call_date)[:10])).days
    except Exception:
        age = None
    if age is not None and age > STILL_PROCESSING_DAYS:
        return f"{TERMINAL} no transcript ({age}d-old call, none will appear)"
    return f"{RETRY} no transcript yet (recent call, may still be processing)"


def is_done(quality, reason):
    """A call_transcripts row is DONE (resume should NOT re-attempt it) when it
    has text, or when it is a TERMINAL empty. A RETRY/pending empty, or an
    absent row, is re-attempted. Single authority shared by the backfill's
    resume set and the tests."""
    if quality != UNAVAILABLE:
        return True
    return bool(reason) and reason.startswith(TERMINAL)


def build_transcript_row(source, call_id, utterances, error=None, call_date=None):
    """Shape one call_transcripts row from normalised utterances: assembled
    text + metrics, or an honest 'unavailable' row. Enforces NULL-never-empty
    and the unavailable_reason invariant the schema also checks. The empty-row
    reason is TERMINAL vs RETRY by call age (see STILL_PROCESSING_DAYS) so a
    genuinely-empty old call stops being re-fetched every pass."""
    text = assemble_text(utterances or [])
    base = {"call_id": str(call_id), "source": source}
    if text.strip():
        return {**base, "transcript": text, "transcript_quality": FULL,
                "unavailable_reason": None, "char_count": len(text),
                **compute_metrics(utterances)}
    # A transient fetch error is always retryable; a clean-but-empty result is
    # terminal-or-pending by age.
    reason = f"{RETRY} {error}" if error else _empty_reason(call_date)
    return {**base, "transcript": None, "transcript_quality": UNAVAILABLE,
            "unavailable_reason": reason, "char_count": 0, **_EMPTY_METRICS}
