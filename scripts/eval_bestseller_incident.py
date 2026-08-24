#!/usr/bin/env python3
"""
Eval: the Bestseller live-incident fixes (four defects from one Slack session).

1. String-iterated-as-list — a bare/comma-joined deal_id string reaching an
   `in_` filter must never char-iterate into in.(6,0,1,...). Locked on the
   shared coercion (_coerce_in_values) that every handler + the dynamic tool
   route through, with a mock Supabase proving .in_() receives a real list.
2. Wrong handler routed — "score <named company> on MEDDICC, highlight
   weaknesses / next steps" must be query_rubric_scores_bulk, NOT
   query_deal_health. Locked on the handler descriptions (the classifier's
   single source of truth): the named-company scorer claims scoring-with-
   weaknesses; the health scan disclaims named companies.
4. Multi-deal truncation — the synthesis ceiling was 600 tokens, clipping a
   two-deal answer mid-sentence. Locked on the raised ceiling + the
   _looks_truncated guard.

(Defect 3, empty-result confabulation, is a synthesis-prompt rule checked in
eval_meddicc_score_presentation-style prompt asserts below. Defect 5, the
ignored assessor score, is a reported-behavior finding — no code gate added
this pass — so it is not asserted here.)
"""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def _stub_if_missing(name, **attrs):
    try:
        __import__(name)
    except Exception:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m


_stub_if_missing("supabase", create_client=lambda *a, **k: None,
                 Client=type("Client", (), {}))
_stub_if_missing("anthropic", Anthropic=type("Anthropic", (), {}),
                 APIError=type("APIError", (Exception,), {}))

FAILS = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        FAILS.append(name)


# ── defect 1: in_ filter never char-iterates a string ───────────────────────
class _RecordingQuery:
    """Records the argument passed to .in_() so we can prove it's a list."""
    def __init__(self, sink):
        self.sink = sink

    def select(self, *a, **k):
        return self

    def in_(self, col, values):
        self.sink.append((col, values))
        return self

    def range(self, *a, **k):
        return self

    def execute(self):
        return types.SimpleNamespace(data=[])

    def __getattr__(self, _name):
        return lambda *a, **k: self


class _RecordingSB:
    def __init__(self, sink):
        self.sink = sink

    def table(self, _name):
        return _RecordingQuery(self.sink)


def test_deal_id_filters_never_iterate_a_string():
    """A single deal_id must never be expanded into characters. The generated
    filter was in.(6,0,1,4,...) — one missing set of brackets produced a query
    on nonsense ids."""
    from supabase_client import select_all, _coerce_in_values

    # pure coercion
    check("single id string -> single-element list",
          _coerce_in_values("60785721693") == ["60785721693"])
    check("comma-joined id string -> real list",
          _coerce_in_values("60785721693,61475205473")
          == ["60785721693", "61475205473"])
    check("list passes through (stringified)",
          _coerce_in_values([60785721693, 61475205473])
          == ["60785721693", "61475205473"])
    check("no element is a single digit (the bug signature)",
          all(len(x) > 1 for x in _coerce_in_values("60785721693")))

    # through select_all, against a recording client
    sink = []
    select_all(_RecordingSB(sink), "deals", columns="deal_id",
               filters=[("in_", "deal_id", "60785721693")])
    check("select_all passed a LIST to .in_(), not a str",
          sink and isinstance(sink[0][1], (list, tuple)))
    check("select_all .in_() list is the whole id, not chars",
          sink and sink[0][1] == ["60785721693"])

    # the exact incident shape: a comma-joined multi-id string
    sink2 = []
    select_all(_RecordingSB(sink2), "deals", columns="deal_id",
               filters=[("in_", "deal_id", "60785721693,61475205473")])
    check("comma-joined incident string -> two real ids",
          sink2 and sink2[0][1] == ["60785721693", "61475205473"])


# ── defect 2: named-company MEDDICC scoring routes to the scorer ────────────
def test_named_company_meddicc_routes_to_rubric_scores_bulk():
    """'Score Bestseller on MEDDICC, highlight weaknesses and next steps' is a
    named-company scorecard (query_rubric_scores_bulk), not a book-wide health
    scan (query_deal_health). The classifier routes on these descriptions, so
    the disambiguation must live in them."""
    from api.router import HANDLER_DESCRIPTIONS

    rubric = HANDLER_DESCRIPTIONS["query_rubric_scores_bulk"].lower()
    health = HANDLER_DESCRIPTIONS["query_deal_health"].lower()

    check("scorer claims NAMED company", "named" in rubric)
    check("scorer owns weaknesses+next-steps for a named deal",
          ("weak" in rubric and ("next step" in rubric or "next steps" in rubric)))
    check("scorer says use-even-when-asking-weaknesses",
          "even" in rubric)
    check("health scan is scoped to UNNAMED / across the book",
          ("unnamed" in health or "across the book" in health))
    check("health scan defers a named company to the scorer",
          "query_rubric_scores_bulk" in health)


# ── defect 4: multi-deal synthesis is not truncated ─────────────────────────
def test_multi_deal_synthesis_not_truncated():
    """A two-deal MEDDICC response must complete. tool_results of ~1.7KB
    produced a response that cut off mid-sentence — the output ceiling, not
    the input."""
    from api.router import (SYNTH_MAX_TOKENS, SYNTH_MAX_TOKENS_RETRY,
                            _looks_truncated)

    check("synthesis ceiling raised well above the old 600",
          SYNTH_MAX_TOKENS >= 1500)
    check("truncation-retry ceiling is higher still",
          SYNTH_MAX_TOKENS_RETRY > SYNTH_MAX_TOKENS)

    # the live symptom: an answer that ends mid-clause on an em dash
    clipped = ("Bestseller — Outbound (deal scored 46/70)\n"
               ":large_yellow_circle: One Area to Watch\n• Competition: yellow —")
    check("mid-clause em-dash ending detected as truncated",
          _looks_truncated(clipped))
    check("bare-word ending detected as truncated",
          _looks_truncated("The AE should focus on the economic buyer and"))
    # complete answers are NOT flagged (no needless re-synthesis)
    check("terminal-punctuation ending is complete",
          not _looks_truncated("These two gaps are the AE's only priority right now."))
    check("bolded final sentence (Slack *bold*) is complete",
          not _looks_truncated("Bottom line: *this deal is healthy.*"))
    check("empty answer is not treated as truncated (different failure)",
          not _looks_truncated("   "))


# ── defect 3: empty results are not confabulated (prompt rule) ──────────────
def test_empty_results_prompt_forbids_confabulation():
    """The synthesis prompt must instruct: on empty data, say what was searched
    and that nothing was found — and NOT speculate about causes."""
    from api.router import build_synthesis_prompt
    p = build_synthesis_prompt({"role_group": "executive", "name": "Ryan"}).lower()
    check("prompt has an empty/no-results rule",
          ("empty" in p and "no results" in p) or "no rows" in p)
    check("prompt forbids inventing explanations",
          "do not invent explanations" in p or "speculation" in p
          or "do not confabulate" in p)


def run():
    print("=" * 72)
    print("BESTSELLER INCIDENT — in_ coercion / routing / truncation / empty")
    print("=" * 72)
    for title, fn in (
        ("defect 1 — deal_id filters never iterate a string",
         test_deal_id_filters_never_iterate_a_string),
        ("defect 2 — named-company MEDDICC -> query_rubric_scores_bulk",
         test_named_company_meddicc_routes_to_rubric_scores_bulk),
        ("defect 4 — multi-deal synthesis not truncated",
         test_multi_deal_synthesis_not_truncated),
        ("defect 3 — empty results not confabulated",
         test_empty_results_prompt_forbids_confabulation),
    ):
        print(f"\n[{title}]")
        fn()

    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("PASS — all four offline-testable incident fixes locked.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
