#!/usr/bin/env python3
"""
Eval: multi-company scoring + current-message-entities-win (Ryan live incident).

Three CRO patterns broke, all one shape (handler rejects real input → dynamic
fallback → blows up):

1. Multiple companies in one question — query_rubric_scores_bulk took a single
   `company`, so "Ecco, Zalando, Natera and DEUNA" resolved to nothing. It now
   accepts a companies/company_names list, resolves each via ilike, unions the
   deal_ids (no cap), and returns queried_* fields for the empty rule.
2. Explicit deal IDs in the current message must override thread context —
   should_use_entity_scope returns False when the message pasted IDs.
3. A company named in the current message overrides thread context —
   message_names_known_company detects it.

Plus the guards: the dynamic tool strips heavy text blobs (full_analysis_text),
and the synthesis ceilings/payload caps were raised (complete > truncated).
"""
import sys
import types
import asyncio
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


# A tiny Supabase stand-in for the deals table (ilike + full scan).
class _DealsSB:
    def __init__(self, deals):
        self._deals = deals  # [{deal_id, company_name}]

    def table(self, name):
        return _DealsQuery(self._deals)


class _DealsQuery:
    def __init__(self, deals):
        self._deals = deals
        self._ilike = None

    def select(self, *a, **k):
        return self

    def ilike(self, col, pat):
        self._ilike = pat.strip("%").lower()
        return self

    def range(self, *a, **k):
        return self

    def execute(self):
        rows = self._deals
        if self._ilike is not None:
            rows = [d for d in rows
                    if self._ilike in (d.get("company_name") or "").lower()]
        return types.SimpleNamespace(data=rows)

    def __getattr__(self, _n):
        return lambda *a, **k: self


BOOK = [
    {"deal_id": "60785721693", "company_name": "Ecco - Paid POC"},
    {"deal_id": "61475205473", "company_name": "Zalando - Outbound"},
    {"deal_id": "60053279602", "company_name": "Natera Expansion"},
    {"deal_id": "62620904729", "company_name": "DEUNA New Business"},
]


def test_multi_company_resolves_and_unions():
    from api import handlers
    sb = _DealsSB(BOOK)
    # no analyses rows → scored_count 0, but deals resolve and are reported
    handlers.select_all  # ensure attr exists
    res = asyncio.run(handlers.query_rubric_scores_bulk(
        {"companies": ["Ecco", "Zalando", "Natera", "DEUNA"]}, sb))
    check("all four companies resolved to deal_ids",
          sorted(res["queried_deal_ids"]) == sorted(
              ["60785721693", "61475205473", "60053279602", "62620904729"]))
    check("deal_count reflects the union (4), no cap", res["deal_count"] == 4)
    check("resolved_from_company flagged", res["resolved_from_company"] is True)
    check("queried_companies preserved for the empty rule",
          res["queried_companies"] == ["Ecco", "Zalando", "Natera", "DEUNA"])
    # single company still works (back-compat)
    r1 = asyncio.run(handlers.query_rubric_scores_bulk({"company": "Ecco"}, sb))
    check("single company still resolves", r1["deal_count"] == 1)
    # a name that matches nothing is reported, not invented
    r2 = asyncio.run(handlers.query_rubric_scores_bulk(
        {"companies": ["Nonesuch Ltd"]}, sb))
    check("unmatched name → empty with the name echoed",
          r2["deal_count"] == 0 and "Nonesuch Ltd" in r2["queried_companies"])


def test_current_message_entities_win():
    from api.router import (extract_explicit_deal_ids,
                            should_use_entity_scope, message_names_known_company)

    prior = {"deal_ids": ["60053279602"],  # cached Natera
             "resolved_at": "2999-01-01T00:00:00+00:00"}  # not stale

    check("pasted deal IDs are extracted from the message",
          extract_explicit_deal_ids(
              "score 61045491056, 60665391542 and 62620904729")
          == ["61045491056", "60665391542", "62620904729"])
    check("no false-positive IDs from short numbers",
          extract_explicit_deal_ids("top 5 deals in Q3") == [])

    # explicit IDs in the message → do NOT scope to the thread's Natera
    check("explicit IDs override thread scope",
          not should_use_entity_scope(
              "score 61045491056 and 60665391542", prior))
    # a pronoun follow-up with NO new entities → thread scope still applies
    check("pure pronoun follow-up still uses thread scope",
          should_use_entity_scope("what are their champion scores?", prior))

    # company named in the current message is detected against the book
    sb = _DealsSB(BOOK)
    check("named company in message detected",
          message_names_known_company("lets start with Ecco and Zalando", sb))
    check("brand token of a multi-word deal name detected (Natera Expansion)",
          message_names_known_company("how is Natera tracking?", sb))
    check("no company name → not detected",
          not message_names_known_company("what about those two?", sb))


def test_intent_schema_has_companies():
    from api.router import build_intent_prompt
    p = build_intent_prompt(today="2026-08-24", current_quarter="Q3",
                            history="[]", question="x", roster_text="")
    check("intent schema exposes a companies list field", '"companies"' in p)
    check("schema tells classifier to emit every named company",
          "more than one" in p.lower() or "list of company" in p.lower())


def test_dynamic_tool_strips_heavy_columns():
    from api.tools import HEAVY_COLUMNS
    check("full_analysis_text is a heavy column (stripped from fallback)",
          "full_analysis_text" in HEAVY_COLUMNS)
    check("transcript blobs are heavy", "transcript" in HEAVY_COLUMNS)
    check("scores/bands columns are NOT stripped",
          "champion_score" not in HEAVY_COLUMNS
          and "overall_score" not in HEAVY_COLUMNS)


def test_synthesis_limits_raised():
    from api.router import (SYNTH_MAX_TOKENS, SYNTH_MAX_TOKENS_RETRY,
                            SYNTH_PAYLOAD_CHARS)
    check("synthesis ceiling raised for many-deal answers",
          SYNTH_MAX_TOKENS >= 4000)
    check("retry ceiling higher still", SYNTH_MAX_TOKENS_RETRY >= SYNTH_MAX_TOKENS)
    check("payload cap raised well past the old 3000",
          SYNTH_PAYLOAD_CHARS >= 10000)


def test_empty_rule_covers_resolved_but_unscored():
    from api.router import build_synthesis_prompt
    p = build_synthesis_prompt({"role_group": "executive", "name": "Ryan"}).lower()
    check("empty rule references queried_companies/deal_ids",
          "queried_companies" in p and "queried_deal_ids" in p)
    check("empty rule distinguishes resolved-but-unscored from nonexistent",
          "scored_count" in p and "unscored_deal_ids" in p)


def run():
    print("=" * 72)
    print("MULTI-COMPANY + CURRENT-MESSAGE-ENTITIES-WIN (Ryan live incident)")
    print("=" * 72)
    for title, fn in (
        ("multi-company resolves + unions (no cap)", test_multi_company_resolves_and_unions),
        ("current-message entities override thread", test_current_message_entities_win),
        ("intent schema emits multiple companies", test_intent_schema_has_companies),
        ("dynamic tool strips heavy columns", test_dynamic_tool_strips_heavy_columns),
        ("synthesis ceilings/payload raised", test_synthesis_limits_raised),
        ("empty rule covers resolved-but-unscored", test_empty_rule_covers_resolved_but_unscored),
    ):
        print(f"\n[{title}]")
        fn()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("PASS — multi-company + entity-precedence + guards locked.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
