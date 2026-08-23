#!/usr/bin/env python3
"""
Eval: transcript store (STORE_AND_BACKFILL_TRANSCRIPTS, Phase 5). Offline.

The three named invariants:
  1. Handlers reading `calls` must not join/select from call_transcripts — the
     split exists so ~20 handlers keep their current query cost.
  2. A call with no transcript stores NULL + an unavailable_reason, never "".
  3. Apollo transcripts are stored speaker-attributed and readable, not as a
     raw fragment list — a consumer must not need to know the source.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def test_calls_queries_never_select_transcript():
    """No api handler references call_transcripts, and no `calls` select pulls a
    transcript column. Keeps the hot `calls` path cheap."""
    cases = []
    handlers = (REPO / "api" / "handlers.py").read_text()
    cases.append(("api/handlers.py never touches call_transcripts",
                  "call_transcripts" not in handlers))
    # No `calls` query selects a transcript column (guards accidental widening).
    import re
    bad = re.findall(r'table\(\s*[\'"]calls[\'"]\s*\).*?transcript', handlers, re.DOTALL)
    cases.append(("no calls-table query selects a transcript column", not bad))
    # The whole api/ package stays clear of the transcript table for now.
    api_hits = [p.name for p in (REPO / "api").glob("*.py")
                if "call_transcripts" in p.read_text()]
    cases.append(("no api/*.py reads call_transcripts (split intact)", not api_hits))
    return cases


def _utt(key, name, sec, text):
    return {"key": key, "name": name, "sec": sec, "text": text,
            "q": text.strip().endswith("?")}


def test_transcript_null_never_empty_string():
    """No utterances → NULL transcript, 'unavailable' quality, a reason,
    char_count 0. Real utterances → assembled text stored, 'full'. Never ''."""
    from transcript_store import build_transcript_row, FULL, UNAVAILABLE
    cases = []

    for label, utts in (("no utterances", []),
                        ("only-blank utterances", [_utt("A", "A", 1.0, "   ")])):
        r = build_transcript_row("fireflies", "c1", utts, error=None)
        ok = (r["transcript"] is None and r["transcript_quality"] == UNAVAILABLE
              and r["unavailable_reason"] and r["char_count"] == 0
              and r["talk_time_seconds"] == {} and r["sentence_count"] == 0)
        cases.append((f"{label} → NULL + unavailable + reason (never '')", ok))

    r = build_transcript_row("fireflies", "c2",
                             [_utt("A", "Ann", 1.0, "hello"), _utt("B", "Bob", 1.0, "hi there")])
    cases.append(("real utterances → assembled text, full, char_count=len",
                  r["transcript"] == "[Ann]: hello\n[Bob]: hi there"
                  and r["transcript_quality"] == FULL
                  and r["char_count"] == len(r["transcript"])
                  and r["unavailable_reason"] is None))

    r = build_transcript_row("apollo", "c3", [], error="ReadTimeout: boom")
    cases.append(("fetch error preserved as unavailable_reason",
                  r["transcript"] is None and "ReadTimeout" in r["unavailable_reason"]))
    return cases


def test_metrics_from_utterances():
    """Unit normalization (FF seconds, Apollo ms), per-speaker talk time +
    question count keyed on the stable id, and the backchannel monologue rule."""
    from transcript_store import (_fireflies_utterances, _apollo_utterances,
                                   compute_metrics, longest_monologue)
    cases = []

    # Fireflies: seconds. 5.2 - 4.24 = 0.96s.
    ff = _fireflies_utterances([
        {"speaker_name": "Ann", "text": "How are you?", "start_time": "4.24", "end_time": "5.2"}])
    cases.append(("fireflies duration in seconds (0.96)", abs(ff[0]["sec"] - 0.96) < 0.01))
    cases.append(("fireflies keyed on name", ff[0]["key"] == "Ann"))
    cases.append(("question mark → q True", ff[0]["q"] is True))

    # Apollo: ms → seconds. 43610 - 43050 = 560ms = 0.56s. Keyed on participant_id.
    ap = _apollo_utterances({"transcript": [
        {"participant_id": "p1", "participant_name": "Bob",
         "spoken_sentence": "Good.", "start_time": "43050.0", "end_time": "43610.0"}]})
    cases.append(("apollo ms→seconds (0.56)", abs(ap[0]["sec"] - 0.56) < 0.01))
    cases.append(("apollo keyed on participant_id, name alongside",
                  ap[0]["key"] == "p1" and ap[0]["name"] == "Bob"))

    # Per-speaker talk time + question count.
    utts = [_utt("rep", "Rep", 3.0, "What's your timeline?"),
            _utt("rep", "Rep", 2.0, "And your budget?"),
            _utt("cust", "Cust", 5.0, "About Q3.")]
    m = compute_metrics(utts)
    cases.append(("talk time per speaker", m["talk_time_seconds"] == {"rep": 5.0, "cust": 5.0}))
    cases.append(("question count per speaker (rep 2, cust 0)",
                  m["question_count"] == {"rep": 2}))
    cases.append(("speakers name lookup", m["speakers"] == {"rep": "Rep", "cust": "Cust"}))
    cases.append(("total speech seconds", m["total_speech_seconds"] == 10.0))
    cases.append(("sentence_count", m["sentence_count"] == 3))

    # Monologue: A 10s, B "mm-hmm" 1s (backchannel <3s), A 10s → run A = 20s.
    # Then B 5s (>=3s) breaks it; A 2s after. Longest = 20s, speaker A.
    mono = [_utt("A", "A", 10.0, "..."), _utt("B", "B", 1.0, "mm-hmm"),
            _utt("A", "A", 10.0, "..."), _utt("B", "B", 5.0, "Actually, wait —"),
            _utt("A", "A", 2.0, "ok")]
    sec, key = longest_monologue(mono)
    cases.append(("backchannel <3s does not break the run (A=20s)", sec == 20.0 and key == "A"))

    # Two backchannels summing >=3s DO break: A 10s, B 2s, B 2s (sum 4>=3).
    mono2 = [_utt("A", "A", 10.0, "..."), _utt("B", "B", 2.0, "right"),
             _utt("B", "B", 2.0, "sure")]
    sec2, key2 = longest_monologue(mono2)
    cases.append(("interruptions summing ≥3s break the run (A=10s)", sec2 == 10.0 and key2 == "A"))
    return cases


def test_apollo_transcript_is_assembled_not_fragments():
    """Apollo fragments → readable speaker-attributed lines, not a raw list."""
    from transcript_store import assemble_apollo
    convo = {"transcript": [
        {"participant_name": "Christian", "spoken_sentence": "Hey, Jay."},
        {"participant_name": "Jay", "spoken_sentence": "Hi Christian."},
        {"speaker": "Christian", "text": "Happy Friday."},       # alt field names
        {"participant_name": "Jay", "spoken_sentence": "   "},    # blank dropped
    ]}
    out = assemble_apollo(convo)
    cases = [
        ("assembles [speaker]: text lines", out ==
         "[Christian]: Hey, Jay.\n[Jay]: Hi Christian.\n[Christian]: Happy Friday."),
        ("blank fragment dropped", "[Jay]:  " not in out and out.count("\n") == 2),
        ("not a python list / not JSON fragments",
         not out.strip().startswith("[{") and "spoken_sentence" not in out),
    ]
    return cases


def test_rate_limit_is_retryable_not_recorded():
    """A rate-limit is a transient error the fetch layer RAISES (so it retries
    with backoff) and the backfill DEFERS (writes no row), rather than recording
    a false 'unavailable' that resume would skip. Guards the Fireflies-sweep bug."""
    import transcript_store as ts
    cases = []
    cases.append(("detects 'Too many requests'",
                  ts._is_rate_limit("Too many requests. Please retry")))
    cases.append(("detects '429'", ts._is_rate_limit("HTTP 429")))
    cases.append(("plain 'not found' is not a rate limit",
                  not ts._is_rate_limit("transcript not found")))

    # A fetcher that rate-limits → fetch_utterances returns an ERROR (so the
    # backfill defers), never utterances. retries=1 keeps the test instant.
    ts._FETCHERS["_faketest"] = lambda cid, clients: (_ for _ in ()).throw(
        ts.RateLimited("fireflies: Too many requests"))
    try:
        utts, err = ts.fetch_utterances("_faketest", "c1", {}, retries=1)
    finally:
        ts._FETCHERS.pop("_faketest", None)
    cases.append(("rate-limited fetch returns an error, not empty-success",
                  utts == [] and err and "RateLimited" in err))
    return cases


def run():
    print("=" * 72)
    print("TRANSCRIPT STORE — split intact, NULL≠'', Apollo assembled (Phase 5)")
    print("=" * 72)
    passed = failed = 0
    for title, fn in (
        ("calls queries never select transcript", test_calls_queries_never_select_transcript),
        ("transcript NULL never empty string", test_transcript_null_never_empty_string),
        ("apollo transcript assembled not fragments", test_apollo_transcript_is_assembled_not_fragments),
        ("metrics: units, per-speaker talk/questions, backchannel monologue", test_metrics_from_utterances),
        ("rate-limit is retryable + deferred, not recorded", test_rate_limit_is_retryable_not_recorded),
    ):
        print(f"\n[{title}]")
        for label, ok in fn():
            if ok:
                passed += 1; print(f"  ✓ {label}")
            else:
                failed += 1; print(f"  ❌ {label}")
    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
