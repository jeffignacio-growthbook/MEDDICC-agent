"""
Shared transcript fetch + assemble + row-shaping (STORE_AND_BACKFILL_TRANSCRIPTS).

One place both the backfill and the go-forward ETL wire go through, so the
source difference (Fireflies GraphQL sentences vs Apollo conversation fragments
vs Gong) stays HERE and neither caller branches on source. Consumers store one
shape: speaker-attributed `[Speaker]: line` text, or an honest 'unavailable'
row — never an empty string, never raw fragments.
"""
import time

# quality levels stored in call_transcripts.transcript_quality
FULL = "full"
PARTIAL = "partial"
FRAGMENTS_ONLY = "fragments_only"
UNAVAILABLE = "unavailable"


# ── per-source fetch → assembled text ────────────────────────────────────────
# Each returns (text, error): text is assembled speaker-attributed lines (""
# when none), error is a short reason string when the fetch itself failed.

def _fetch_fireflies(call_id, clients):
    client = clients.get("fireflies")
    if client is None:
        from fireflies_client import FirefliesClient
        client = clients["fireflies"] = FirefliesClient()
    sentences = client.get_transcript_sentences(call_id)
    return client.assemble_transcript(sentences), None


def _fetch_apollo(call_id, clients):
    client = clients.get("apollo")
    if client is None:
        from apollo_client import ApolloClient
        client = clients["apollo"] = ApolloClient()
    convo = client.get_conversation(call_id)
    return assemble_apollo(convo), None


def assemble_apollo(conversation: dict) -> str:
    """Apollo returns transcript as participant_name / spoken_sentence fragments.
    Assemble the SAME readable, speaker-attributed shape Fireflies produces —
    the coaching consumer must not need to know which tool recorded the call."""
    lines = []
    for entry in (conversation.get("transcript") or []):
        speaker = entry.get("participant_name") or entry.get("speaker") or "Unknown"
        text = (entry.get("spoken_sentence") or entry.get("text") or "").strip()
        if text:
            lines.append(f"[{speaker}]: {text}")
    return "\n".join(lines)


def _fetch_gong(call_id, clients):
    # Gong is not in GrowthBook's source priority and needs ACCESS_LEVEL='rich';
    # support it best-effort so the backfill stays source-agnostic.
    client = clients.get("gong")
    if client is None:
        try:
            from adapters.gong_adapter import GongAdapter
            client = clients["gong"] = GongAdapter()
        except Exception as e:
            return "", f"gong adapter unavailable: {type(e).__name__}"
    text = client.get_transcript(call_id) or ""
    return text, None


_FETCHERS = {"fireflies": _fetch_fireflies, "apollo": _fetch_apollo, "gong": _fetch_gong}


def fetch_transcript(source: str, call_id: str, clients: dict,
                     retries: int = 3, backoff: float = 2.0):
    """Fetch + assemble a transcript for one call. Returns (text, error).

    Retries transient failures with exponential backoff; after the cap it
    returns ('', reason) so the caller records an 'unavailable' row and keeps
    going — one bad call never aborts the backfill (codebase style rule)."""
    fetcher = _FETCHERS.get((source or "").lower())
    if fetcher is None:
        return "", f"no transcript fetcher for source '{source}'"
    last = None
    for attempt in range(retries):
        try:
            text, err = fetcher(call_id, clients)
            return (text or ""), err
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:140]}"
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    return "", last


def classify(text: str) -> str:
    """Honest quality label. We can reliably distinguish 'have readable text'
    from 'nothing came back'; we do NOT fabricate a partial/fragments split we
    have no signal for. Returns FULL when there is assembled text, else
    UNAVAILABLE. (PARTIAL/FRAGMENTS_ONLY stay in the enum for a future signal.)"""
    return FULL if (text or "").strip() else UNAVAILABLE


def build_transcript_row(source: str, call_id: str, text: str,
                         error: str = None) -> dict:
    """Shape one call_transcripts row. Enforces the invariants the schema also
    checks: NULL (never "") when there's no text, and an unavailable_reason
    whenever the transcript is NULL."""
    text = (text or "").strip()
    if text:
        return {
            "call_id": str(call_id), "source": source,
            "transcript": text, "transcript_quality": classify(text),
            "unavailable_reason": None, "char_count": len(text),
        }
    reason = error or "no transcript text returned (still processing or no content)"
    return {
        "call_id": str(call_id), "source": source,
        "transcript": None, "transcript_quality": UNAVAILABLE,
        "unavailable_reason": reason, "char_count": 0,
    }
