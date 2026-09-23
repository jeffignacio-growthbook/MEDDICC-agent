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
        return [], f"fireflies GraphQL: {msg[:140]}", {}
    sents = ((res.get("data") or {}).get("transcript") or {}).get("sentences") or []
    return _fireflies_utterances(sents), None, {}


_BOT_NAME_MARKERS = ("notetaker", "recorder", "meeting bot")


def _internal_domains():
    """organization.internal_domains from config/client.yaml — this
    codebase's own canonical internal/external definition, reused here
    rather than trusting Apollo's own internal/external bucketing."""
    import yaml
    from pathlib import Path
    cfg_path = Path(__file__).parent.parent / "config" / "client.yaml"
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return set()
    domains = (cfg.get("organization") or {}).get("internal_domains") or []
    return {d.lower() for d in domains}


def _extract_apollo_participant_identities(conversation):
    """Real Apollo identity data (confirmed LIVE 2026-09-19, three-run
    investigation — see migration 065's header for the full trail):
    conversation['participants'] = {"internal": [...],
    "external": {account_id: [...]}}, each record carrying a real
    id/name/email/title/account_id. That id is CONFIRMED (live overlap
    check) to be the SAME id used as participant_id in this same
    conversation's transcript fragments — the identical speaker_key this
    module already uses for talk_time_seconds/question_count/speakers.
    No name-matching anywhere in this function.

    Bot/notetaker artifacts (e.g. "Fireflies.ai Notetaker Christi", which
    has email=None) are flagged is_bot=True — never a real participant,
    never scored as one, but not silently dropped either (a caller can
    see it was seen and excluded).

    Returns {participant_id: {"name", "email", "title", "account_id",
    "is_internal", "is_bot"}}. {} if the conversation carries no
    'participants' dict (Fireflies/Gong never call this at all — only
    _fetch_apollo does).
    """
    participants = conversation.get("participants")
    if not isinstance(participants, dict):
        return {}

    records = []
    internal = participants.get("internal")
    if isinstance(internal, list):
        records.extend(p for p in internal if isinstance(p, dict))
    external = participants.get("external")
    if isinstance(external, dict):
        for v in external.values():
            if isinstance(v, list):
                records.extend(p for p in v if isinstance(p, dict))
    elif isinstance(external, list):
        records.extend(p for p in external if isinstance(p, dict))

    internal_domains = _internal_domains()
    out = {}
    for p in records:
        pid = p.get("id")
        if not pid:
            continue
        name = p.get("name") or ""
        email = (p.get("email") or "").strip().lower() or None
        is_bot = email is None and any(m in name.lower() for m in _BOT_NAME_MARKERS)
        is_internal = bool(email and "@" in email
                           and email.split("@", 1)[1] in internal_domains)
        out[pid] = {
            "name": name or None,
            "email": email,
            "title": p.get("title"),
            "account_id": p.get("account_id"),
            "is_internal": is_internal,
            "is_bot": is_bot,
        }
    return out


def _fetch_apollo(call_id, clients):
    client = clients.get("apollo")
    if client is None:
        from apollo_client import ApolloClient
        client = clients["apollo"] = ApolloClient()
    convo = client.get_conversation(call_id)
    identities = _extract_apollo_participant_identities(convo)
    return _apollo_utterances(convo), None, {
        "participant_identities": identities,
        # confirmed live (2026-09-22 terminal-empty gap investigation) that
        # Apollo's conversation carries this field, and that every one of
        # GrowthBook's real empty terminal calls shows a DONE state —
        # letting _empty_reason() use it instead of guessing from age alone.
        "source_state": convo.get("conversation", convo).get("state"),
    }


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
            return [], f"gong adapter unavailable: {type(e).__name__}", {}
    text = client.get_transcript(call_id) or ""
    # One pseudo-utterance carrying the text so it still gets stored/assembled.
    return ([{"key": "gong", "name": "transcript", "sec": 0.0, "text": text,
              "q": False}] if text.strip() else []), None, {}


_FETCHERS = {"fireflies": _fetch_fireflies, "apollo": _fetch_apollo, "gong": _fetch_gong}


def fetch_utterances(source, call_id, clients, retries=6, backoff=2.0, throttle=0.0):
    """Fetch normalised utterances for one call. Returns (utterances, error, extra).

    `extra` carries source-specific data beyond the shared utterance
    model — today only {"participant_identities": {...}} from Apollo
    (see _extract_apollo_participant_identities); every other source
    returns {}. Callers that don't need it can ignore the third value.

    `throttle` sleeps before each call to stay under a source's request rate
    (Fireflies rate-limits a fast sequential sweep). A rate-limit backs off
    LONG (15s, 30s, 60s, …) and uses the full retry budget, since the limit is
    a burst window that only clears with real wait; other exceptions use the
    short backoff. After the cap, returns ([], reason, {})."""
    fetcher = _FETCHERS.get((source or "").lower())
    if fetcher is None:
        return [], f"no transcript fetcher for source '{source}'", {}
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
            wait = _http_rate_limit_wait(e, attempt)
            if wait is not None:
                # HTTP 429 (Apollo REST, or Fireflies at the HTTP layer):
                # same LONG backoff as an in-body rate limit — the short
                # 2s..32s schedule below would just re-hit the window.
                last = f"RateLimited(HTTP 429): {str(e)[:130]}"
                if attempt < retries - 1:
                    time.sleep(wait)
                continue
            last = f"{type(e).__name__}: {str(e)[:140]}"
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    return [], last, {}


def _http_rate_limit_wait(exc, attempt):
    """Seconds to wait if `exc` is an HTTP 429, else None. Honors a numeric
    Retry-After header (capped at 120s); otherwise 15s, 30s, 60s, 120s."""
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


# Apollo conversation `state` values confirmed (2026-09-22 terminal-empty gap
# investigation, apollo_client.py's own search_conversations_by_company
# precedent) to mean Apollo's own processing has actually finished. A state
# outside this set (e.g. still transcribing) means Apollo itself says it
# isn't done yet — that's real, positive evidence, and must never be
# overridden by an age guess.
APOLLO_DONE_STATES = {"completed", "insights_generated"}


def _empty_reason(call_date, source_state=None):
    """Classify an empty result as TERMINAL (no transcript will ever appear)
    or RETRY (may still be processing).

    When the source itself exposes a real completion signal (today, Apollo's
    conversation `state`), that signal wins outright: a state outside
    APOLLO_DONE_STATES means Apollo says it hasn't finished processing yet,
    so this is RETRY regardless of call age — a call must never be declared
    terminal on a guess while the source itself is still saying "not done".

    Without such a signal (Fireflies exposes none), fall back to the age
    heuristic: an empty result on an OLD call is TERMINAL, a RECENT one is
    RETRY (may still be processing)."""
    if source_state is not None and source_state not in APOLLO_DONE_STATES:
        return f"{RETRY} no transcript yet (source state={source_state!r}, not finished processing)"
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


def build_transcript_row(source, call_id, utterances, error=None, call_date=None, extra=None):
    """Shape one call_transcripts row from normalised utterances: assembled
    text + metrics, or an honest 'unavailable' row. Enforces NULL-never-empty
    and the unavailable_reason invariant the schema also checks. The empty-row
    reason is TERMINAL vs RETRY by call age (see STILL_PROCESSING_DAYS) so a
    genuinely-empty old call stops being re-fetched every pass.

    `extra`: the third element fetch_utterances() returns — only Apollo
    ever sets extra["participant_identities"]; every other source leaves
    it absent, so participant_identities is always explicitly None on
    the row for non-Apollo sources (migration 065 — Apollo-only by
    design, never a backfill gap to close for Fireflies/Gong). Apollo also
    sets extra["source_state"] (its conversation `state`), consulted by
    _empty_reason() before it falls back to the age heuristic."""
    extra = extra or {}
    text = assemble_text(utterances or [])
    base = {"call_id": str(call_id), "source": source,
            "participant_identities": extra.get("participant_identities")}
    if text.strip():
        return {**base, "transcript": text, "transcript_quality": FULL,
                "unavailable_reason": None, "char_count": len(text),
                **compute_metrics(utterances)}
    # A transient fetch error is always retryable; a clean-but-empty result is
    # terminal-or-pending by the source's own state if it exposes one, else age.
    reason = f"{RETRY} {error}" if error else _empty_reason(call_date, extra.get("source_state"))
    return {**base, "transcript": None, "transcript_quality": UNAVAILABLE,
            "unavailable_reason": reason, "char_count": 0, **_EMPTY_METRICS}
