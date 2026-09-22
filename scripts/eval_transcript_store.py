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
        utts, err, extra = ts.fetch_utterances("_faketest", "c1", {}, retries=1)
    finally:
        ts._FETCHERS.pop("_faketest", None)
    cases.append(("rate-limited fetch returns an error, not empty-success",
                  utts == [] and err and "RateLimited" in err and extra == {}))
    return cases


def test_terminal_vs_retryable_empty():
    """An empty result on an OLD call is terminal (resume stops re-attempting);
    on a RECENT call it's pending/retry; a transient error is retry. is_done()
    encodes the distinction so a genuinely-empty old call isn't re-fetched every
    pass forever."""
    from datetime import date
    from transcript_store import build_transcript_row, is_done, UNAVAILABLE, FULL
    cases = []

    old = build_transcript_row("fireflies", "c1", [], call_date="2020-01-01")
    cases.append(("empty + old call → terminal reason",
                  old["unavailable_reason"].startswith("terminal:")))
    cases.append(("terminal empty is DONE (not re-attempted)",
                  is_done(UNAVAILABLE, old["unavailable_reason"]) is True))

    recent = build_transcript_row("fireflies", "c2", [], call_date=date.today().isoformat())
    cases.append(("empty + recent call → retry reason",
                  recent["unavailable_reason"].startswith("retry:")))
    cases.append(("recent/pending empty is NOT done (re-attempted)",
                  is_done(UNAVAILABLE, recent["unavailable_reason"]) is False))

    err = build_transcript_row("apollo", "c3", [], error="RateLimited: boom")
    cases.append(("transient error → retry reason, not done",
                  err["unavailable_reason"].startswith("retry:")
                  and is_done(UNAVAILABLE, err["unavailable_reason"]) is False))

    cases.append(("full row is done", is_done(FULL, None) is True))
    cases.append(("legacy unavailable reason (no prefix) → re-attempted",
                  is_done(UNAVAILABLE, "no transcript text returned") is False))
    return cases


def test_apollo_state_overrides_age_for_terminal_classification():
    """2026-09-22 terminal-empty gap investigation: Jeff flagged 90 calls
    marked terminal-empty as suspicious. Live evidence (dispatched CI
    diagnostic against real Apollo/Fireflies data) proved the age-only
    heuristic got all 90 right — but only by luck, since it never actually
    checked whether the source had finished processing. Apollo's
    conversation `state` (confirmed live: all 3 real Apollo terminal rows
    show 'insights_generated') is a real completion signal that must now
    override an age guess: an old call whose source `state` says
    processing ISN'T finished must be RETRY, never TERMINAL — the exact
    bug shape Jeff's original hypothesis described (a still-processing
    call wrongly written off forever), now closed with real evidence
    instead of assumed away."""
    from datetime import date, timedelta
    from transcript_store import _empty_reason, build_transcript_row, TERMINAL, RETRY
    cases = []
    old_date = (date.today() - timedelta(days=300)).isoformat()

    # PLANT THE OLD BUG: before this fix, _empty_reason took only call_date —
    # calling it with the pre-fix signature (no state argument at all) on this
    # exact old+still-processing case is what shipped as production behavior.
    # It DOES get this wrong (this is the bug, reproduced against the real
    # function, not a hypothetical) — confirming there's a real regression to
    # guard, not a strawman.
    pre_fix_reason = _empty_reason(old_date)
    cases.append(("OLD BUG reproduced: age-only classification wrongly marks "
                  "a call terminal with zero knowledge of source state",
                  pre_fix_reason.startswith(TERMINAL)))

    # CONFIRM THE FIX: the same old call, now WITH Apollo's real state signal
    # showing processing isn't finished, must be RETRY — never terminal on an
    # age guess while the source itself says "not done".
    fixed_reason = _empty_reason(old_date, source_state="processing")
    cases.append(("FIX: old call + Apollo state NOT in APOLLO_DONE_STATES → "
                  "retry, age guess overridden by real signal",
                  fixed_reason.startswith(RETRY) and "processing" in fixed_reason))

    # A DONE Apollo state (the real shape of all 90 live terminal calls) still
    # correctly terminal-izes an old call — the fix changes nothing for the
    # calls that actually are genuinely empty.
    done_reason = _empty_reason(old_date, source_state="insights_generated")
    cases.append(("Apollo state IN APOLLO_DONE_STATES → still terminal by age "
                  "(no regression for genuinely-empty old calls)",
                  done_reason.startswith(TERMINAL)))

    # Fireflies never sets source_state (no such field found) → unaffected,
    # falls through to the same age heuristic as before.
    ff_reason = _empty_reason(old_date, source_state=None)
    cases.append(("no source_state (Fireflies) → unchanged age-based terminal",
                  ff_reason.startswith(TERMINAL)))

    # End-to-end through build_transcript_row: extra["source_state"] set by
    # _fetch_apollo actually reaches the classification, not just the helper.
    row = build_transcript_row("apollo", "c1", [], call_date=old_date,
                               extra={"source_state": "processing"})
    cases.append(("build_transcript_row: extra['source_state'] reaches "
                  "_empty_reason end-to-end (not just the unit helper)",
                  row["unavailable_reason"].startswith(RETRY)))

    row_done = build_transcript_row("apollo", "c2", [], call_date=old_date,
                                    extra={"source_state": "completed"})
    cases.append(("build_transcript_row: 'completed' state still terminal-izes",
                  row_done["unavailable_reason"].startswith(TERMINAL)))
    return cases


def test_apollo_participant_identities_extraction():
    """Apollo's real participants shape ({"internal": [...], "external":
    {account_id: [...]}}), confirmed live 2026-09-19: keyed by id (the
    same id confirmed live to match participant_id in transcript
    fragments), is_internal derived from email domain against
    config/client.yaml (this codebase's own canonical definition, not
    Apollo's own internal/external bucketing), bot/notetaker artifacts
    flagged is_bot=True — seen and excluded, never silently dropped."""
    from transcript_store import _extract_apollo_participant_identities
    cases = []

    convo = {"participants": {
        "internal": [
            {"id": "p1", "name": "Christian Liebenow",
             "email": "christian@growthbook.io", "title": "Account Executive",
             "account_id": "acct1"},
            {"id": "p2", "name": "Fireflies.ai Notetaker Christi", "email": None},
        ],
        "external": {
            "acctX": [
                {"id": "p3", "name": "Shawn Hansen",
                 "email": "shansen@a24films.com", "account_id": "acctX"},
            ],
        },
    }}
    out = _extract_apollo_participant_identities(convo)

    cases.append(("keyed by id (matches transcript fragment participant_id)",
                  set(out.keys()) == {"p1", "p2", "p3"}))
    cases.append(("real GrowthBook email -> is_internal True, not a bot",
                  out["p1"]["is_internal"] is True and out["p1"]["is_bot"] is False))
    cases.append(("external email -> is_internal False, email preserved",
                  out["p3"]["is_internal"] is False
                  and out["p3"]["email"] == "shansen@a24films.com"))
    cases.append(("notetaker bot (email=None, name matches marker) -> "
                  "is_bot True, seen not dropped",
                  "p2" in out and out["p2"]["is_bot"] is True
                  and out["p2"]["email"] is None))
    cases.append(("bot is never accidentally classified internal",
                  out["p2"]["is_internal"] is False))
    cases.append(("no 'participants' dict -> {} (Fireflies/Gong never call this)",
                  _extract_apollo_participant_identities({}) == {}
                  and _extract_apollo_participant_identities({"participants": None}) == {}))
    return cases


def test_build_transcript_row_carries_participant_identities():
    """participant_identities flows through build_transcript_row via
    `extra`, explicitly None (not omitted) for non-Apollo sources — a
    caller can always rely on the key being present, never a KeyError."""
    from transcript_store import build_transcript_row
    cases = []

    ident = {"p1": {"name": "A", "email": "a@growthbook.io", "title": None,
                    "account_id": None, "is_internal": True, "is_bot": False}}
    r = build_transcript_row("apollo", "c1", [_utt("p1", "A", 1.0, "hi")],
                             extra={"participant_identities": ident})
    cases.append(("apollo row carries participant_identities",
                  r["participant_identities"] == ident))

    r2 = build_transcript_row("fireflies", "c2", [_utt("A", "Ann", 1.0, "hi")])
    cases.append(("fireflies row has participant_identities explicitly None, "
                  "not omitted (migration 065 — Apollo-only by design)",
                  "participant_identities" in r2 and r2["participant_identities"] is None))

    r3 = build_transcript_row("apollo", "c3", [])  # no extra passed at all
    cases.append(("apollo row with no extra arg -> None, not a KeyError",
                  r3["participant_identities"] is None))
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
        ("terminal vs retryable empty (resume stops re-fetching old empties)", test_terminal_vs_retryable_empty),
        ("apollo state overrides age for terminal classification (2026-09-22 gap fix)",
         test_apollo_state_overrides_age_for_terminal_classification),
        ("apollo participant_identities extraction (id-keyed, bot-flagged)", test_apollo_participant_identities_extraction),
        ("build_transcript_row carries participant_identities", test_build_transcript_row_carries_participant_identities),
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
