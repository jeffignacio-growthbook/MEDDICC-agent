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


def test_transcript_null_never_empty_string():
    """No text → NULL transcript, 'unavailable' quality, a reason, char_count 0.
    Real text → stored, 'full', char_count=len. Never an empty string."""
    from transcript_store import build_transcript_row, FULL, UNAVAILABLE
    cases = []

    for label, text in (("empty string", ""), ("whitespace", "   \n  "),
                        ("None", None)):
        r = build_transcript_row("fireflies", "c1", text, error=None)
        ok = (r["transcript"] is None and r["transcript_quality"] == UNAVAILABLE
              and r["unavailable_reason"] and r["char_count"] == 0)
        cases.append((f"{label} → NULL + unavailable + reason (never '')", ok))

    r = build_transcript_row("fireflies", "c2", "[A]: hello\n[B]: hi there")
    cases.append(("real text → stored, full, char_count=len, no reason",
                  r["transcript"] == "[A]: hello\n[B]: hi there"
                  and r["transcript_quality"] == FULL
                  and r["char_count"] == len(r["transcript"])
                  and r["unavailable_reason"] is None))

    # A supplied error is preserved as the unavailable reason.
    r = build_transcript_row("apollo", "c3", "", error="ReadTimeout: boom")
    cases.append(("fetch error preserved as unavailable_reason",
                  r["transcript"] is None and "ReadTimeout" in r["unavailable_reason"]))
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


def run():
    print("=" * 72)
    print("TRANSCRIPT STORE — split intact, NULL≠'', Apollo assembled (Phase 5)")
    print("=" * 72)
    passed = failed = 0
    for title, fn in (
        ("calls queries never select transcript", test_calls_queries_never_select_transcript),
        ("transcript NULL never empty string", test_transcript_null_never_empty_string),
        ("apollo transcript assembled not fragments", test_apollo_transcript_is_assembled_not_fragments),
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
