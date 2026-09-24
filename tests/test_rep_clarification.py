#!/usr/bin/env python3
"""
A person named in a question is settled in code before anything runs.

Before: a first name shared by two people ("Jake": Jake H and Jake Stangl)
was left to the model. The dynamic loop got a prompt directive
(format_ambiguous_dimension_note) asking it to say "did you mean...?",
and handlers resolved names with _resolve_owner_email, which took the first
unordered substring match across all 54 personas ("Scott" could be Scott
Bailey, who owns no deals; "an" matched Dan). A name that matched nobody
("Mike") was answered with model-written suggestions that differed between
two runs of the same question.

Now api/rep_clarification.rep_gate() runs right after the classifier, on
the question text:
  - a first name already settled by a full name in the question ("Jake
    Stangl") is not a first-name mention at all;
  - candidates are cut to the handler's population: SDR handlers consider
    SDRs, everything else considers people who own at least one deal;
  - what is left decides: 0 -> decline with a code-written list, 1 ->
    answer with a disclosure line (only when the cut removed someone),
    2-4 -> ask, >4 -> decline with a list.
An ask computes nothing. It is saved in the thread as a pending
clarification; a reply of "1", "Jake H" or "stangl" is matched in code and
the original question reruns with the full name in place.

Fixtures are real: tests/fixtures/rep_clarification_people_2026_09_24.json
holds every user_personas row, the deals table counted by owner and status,
and every sdr_users row, as of 2026-09-24. The questions are the six from
the clarifying-question audit (query_cost_log / learning_log, 2026-08-18 to
2026-09-22) and the two logged false positives.
"""
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from strict_supabase import StrictSupabase  # noqa: E402

try:
    import api.rep_clarification as rc  # noqa: E402
except ImportError:            # pre-fix: the tests fail, not the import
    rc = None

FX = json.loads((REPO / "tests" / "fixtures" / "rep_clarification_people_2026_09_24.json").read_text())


def _tables():
    deals = [{"deal_id": f"{c['owner_email'] or 'unowned'}-{c['deal_status']}-{i}",
              "owner_email": c["owner_email"], "deal_status": c["deal_status"]}
             for c in FX["deal_counts"] for i in range(c["n"])]
    return {"user_personas": [dict(p) for p in FX["personas"]], "deals": deals,
            "sdr_users": [dict(s) for s in FX["sdr_users"]]}


def _people():
    return rc.load_people(StrictSupabase(_tables()))


def _gate(question, handler, extracted=None):
    return rc.rep_gate(question, handler, _people(), extracted_name=extracted)


# ── the six audit cases ────────────────────────────────────────────────────

def test_jakes_deals_asks_between_the_two_deal_owners():
    q = "What's changed with Jake's deals this week?"
    g = _gate(q, "query_pipeline_movement")
    assert g["action"] == "ask", g
    assert g["message"] == (
        "Two people named Jake own deals — reply 1 or 2:\n"
        "1) Jake H (AE, 54 active deals)\n"
        "2) Jake Stangl (SDR, 5 active deals)\n\n"
        "I haven't run anything yet; I'll answer as soon as you pick."), g["message"]
    p = g["pending"]
    assert p["question"] == q and [c["email"] for c in p["candidates"]] == \
        ["jake@growthbook.io", "jake.stangl@growthbook.io"], p
    print("✓ 'Jake's deals' (2026-09-11): asks, in code, between Jake H (54 active) and "
          "Jake Stangl (5 active); nothing is computed")


def test_jake_sdr_question_discloses_the_only_sdr():
    q = "how is Jake tracking this month?"
    g = _gate(q, "query_sdr_metrics")
    assert g["action"] == "disclose", g
    assert g["disclosure"] == "_Taking “Jake” to mean Jake Stangl, the only SDR named Jake._", g
    assert g["question"] == "how is Jake Stangl tracking this month?", g["question"]
    assert g["pin"] == {"sdr_email": "jake.stangl@growthbook.io"}, g["pin"]
    print("✓ 'how is Jake tracking' (SDR metrics, 2026-08-18): answers for Jake Stangl, the "
          "only SDR named Jake, and says so; the handler gets his email")


def test_scott_call_quality_discloses_scott_keller():
    q = "How's Scott's call quality been this month?"
    g = _gate(q, "dynamic_query")
    assert g["action"] == "disclose", g
    assert g["disclosure"] == ("_Taking “Scott” to mean Scott Keller, the only person named "
                               "Scott who owns deals._"), g
    assert g["question"] == "How's Scott Keller's call quality been this month?", g["question"]
    assert g["pin"] == {"owner_email": "scott.keller@growthbook.io",
                        "rep_email": "scott.keller@growthbook.io"}, g["pin"]
    print("✓ 'Scott's call quality' (2026-09-11): Scott Bailey owns no deals, so Scott Keller, "
          "disclosed")


def test_mike_is_declined_with_a_code_written_list():
    q = "How is Mike doing on talk time ratio?"
    g = _gate(q, "dynamic_query", extracted="Mike")
    assert g["action"] == "decline", g
    owners = ("Ashley Stirrup, Cary, Chris Sanders, Christian, Dan, Graham McNicoll, Iain McNicoll, "
              "Ivan Gomez, Jake H, Jake Stangl, James Shannon, Jeff Ignacio, Jennifer, "
              "Marcel Geldner, Matthew Du Pont, Scott Keller")
    assert g["message"] == (
        "I don't see anyone named Mike who owns deals, so I haven't guessed. "
        f"People who own deals: {owners}. Ask again with one of those names."), g["message"]
    # the same question twice gets the same answer: nothing model-written
    assert _gate(q, "dynamic_query", extracted="Mike")["message"] == g["message"]
    print("✓ 'Mike' (2026-09-22, asked twice, two different model-suggested names): declined "
          "with the same code-written list of deal owners both times")


def test_sarah_johnson_is_declined():
    q = "Show me rep coaching opportunities for Sarah Johnson"
    g = _gate(q, "query_coaching_priorities", extracted="Sarah Johnson")
    assert g["action"] == "decline", g
    assert g["message"].startswith("I don't see anyone named Sarah Johnson who owns deals, "
                                   "so I haven't guessed."), g["message"]
    print("✓ 'Sarah Johnson' (2026-09-22): nobody by that name; declined with the list")


def test_undefined_metric_question_is_not_this_gate():
    """'What is the prospective conversion rate?' (2026-09-06) was the
    audit's sixth case: an undefined METRIC, not a person. This gate names
    people only; it must stay out of the way."""
    g = _gate("What is the prospective conversion rate?", "dynamic_query")
    assert g["action"] == "proceed" and g["question"] == "What is the prospective conversion rate?", g
    print("✓ 'prospective conversion rate' (2026-09-06): no person named, gate proceeds "
          "(the undefined-metric decline is not part of this gate)")


# ── the two logged false positives ─────────────────────────────────────────

def test_full_name_settles_the_first_name():
    for q, handler in (("What are Jake Stangl's open deals?", "dynamic_query"),
                       ("How many dials did Jake Stangl make last week?", "query_sdr_metrics")):
        g = _gate(q, handler)
        assert g["action"] == "proceed" and g["question"] == q, (q, g)
        assert g["pin"] == ({"sdr_email": "jake.stangl@growthbook.io"} if handler == "query_sdr_metrics"
                            else {"owner_email": "jake.stangl@growthbook.io",
                                  "rep_email": "jake.stangl@growthbook.io"}), g["pin"]
    print("✓ 'Jake Stangl' named in full: no ask, no disclosure, his email pinned")


def test_dynamic_loop_scan_no_longer_flags_a_settled_first_name():
    from api.dimension_resolver import scan_question_for_ambiguous_dimension_terms as scan
    assert scan("What are Jake Stangl's open deals?") == []
    assert scan("Compare Jake H and Jake Stangl") == []
    assert [a["term"] for a in scan("What's changed with Jake's deals this week?")] == ["Jake's"]
    print("✓ dynamic-loop ambiguity scan: 'Jake Stangl' / 'Jake H' in full no longer flag 'Jake' "
          "(the two logged false positives); a bare 'Jake' still does")


# ── the rules around the edges ─────────────────────────────────────────────

def test_population_and_count_rules():
    # Chris: Chris Sanders owns a deal, Chris Newton (external) doesn't
    assert _gate("How is Chris doing?", "dynamic_query")["action"] == "disclose"
    # an SDR question about an AE: nobody left, declined, and says why
    g = _gate("How many dials did Scott make?", "query_sdr_metrics", extracted="Scott")
    assert g["action"] == "decline", g
    assert g["message"] == ("I don't see an SDR named Scott, so I haven't guessed. SDRs: Jake Stangl. "
                            "(Scott Bailey and Scott Keller are in the directory but aren't SDRs.) "
                            "Ask again with one of those names."), g["message"]
    # "August" is a month; August Allard owns no deals, so it isn't a mention
    assert _gate("What closed in August?", "dynamic_query")["action"] == "proceed"
    # a single-person first name with nobody cut: settled silently
    g = _gate("What's in Christian's pipeline?", "dynamic_query")
    assert g["action"] == "proceed" and g["pin"]["owner_email"] == "christian@growthbook.io", g
    # two people, same full name, both own deals: ask, emails shown
    g = _gate("What is Matthew Du Pont working on?", "dynamic_query")
    assert g["action"] == "ask" and "matt@growthbook.io" in g["message"] \
        and "matt.dupont@growthbook.io" in g["message"], g
    # more than 4 left: decline with the list
    many = [{"name": f"Alex {s}", "email": f"alex{i}@x.io", "role": "ae", "deals": 1, "active": 1,
             "is_sdr": False} for i, s in enumerate("ABCDE")]
    g = rc.rep_gate("How is Alex doing?", "dynamic_query", many)
    assert g["action"] == "decline" and g["message"].startswith(
        "“Alex” matches 5 people who own deals: Alex A, Alex B, Alex C, Alex D, Alex E."), g
    # the deals read failing cuts nobody (asks rather than guesses)
    blind = [dict(p, deals=0, active=0, deal_counts_known=False) for p in _people()]
    assert rc.rep_gate("How's Scott's call quality?", "dynamic_query", blind)["action"] == "ask"
    # the router's cheap pre-check: no first name, no extracted name, nothing loaded
    names = [p["name"] for p in FX["personas"]]
    assert not rc.might_name_someone("What's the pipeline?", names, None)
    assert rc.might_name_someone("how is jake tracking?", names, None)
    assert rc.might_name_someone("How is Mike doing?", names, "Mike")
    # an extracted name the question doesn't contain is ignored (no hallucinated mention)
    assert _gate("What's the pipeline?", "dynamic_query", extracted="Mike")["action"] == "proceed"
    print("✓ population cut (Chris → Chris Sanders; SDR question about Scott declined with why), "
          "a month named August ignored, a unique first name settled silently, same-name "
          "duplicates asked with emails, >4 declined, unmentioned extracted names ignored")


# ── the pending clarification ──────────────────────────────────────────────

def test_reply_matching():
    p = _gate("What's changed with Jake's deals this week?", "query_pipeline_movement")["pending"]
    for reply, email in (("1", "jake@growthbook.io"), ("2", "jake.stangl@growthbook.io"),
                         ("2.", "jake.stangl@growthbook.io"), ("Jake H", "jake@growthbook.io"),
                         ("stangl", "jake.stangl@growthbook.io"), ("Jake Stangl", "jake.stangl@growthbook.io"),
                         ("jake@growthbook.io", "jake@growthbook.io")):
        c = rc.match_reply(reply, p)
        assert c and c["email"] == email, (reply, c)
    for reply in ("3", "jake", "which of those are at risk?", "both", "h"):
        assert rc.match_reply(reply, p) is None, reply
    assert rc.apply_choice(p, rc.match_reply("1", p)) == "What's changed with Jake H's deals this week?"
    print("✓ replies '1', '2.', 'Jake H', 'stangl', a full name or an email pick a candidate; "
          "'3', 'jake', 'both' or a new question do not")


def test_pending_is_only_live_until_the_next_question_or_expiry():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    p = {"question": "q", "candidates": [], "expires_at": (now + timedelta(hours=1)).isoformat()}
    entry = {"role": rc.PENDING_ROLE, "content": json.dumps(p)}
    ask = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "Two people..."}, entry]
    assert rc.find_pending(ask, now=now) == p
    assert rc.find_pending(ask + [{"role": "user", "content": "x"},
                                  {"role": "assistant", "content": "y"}], now=now) is None
    assert rc.find_pending(ask, now=now + timedelta(hours=2)) is None
    assert rc.find_pending([], now=now) is None
    print("✓ a pending clarification is live only until the next question is asked, or 24h")


# ── end to end through route_question ──────────────────────────────────────

class _FakeLLM:
    def __init__(self, intents):
        self.intents, self.prompts = intents, []

    def complete(self, messages=None, system=None, max_tokens=None, **kw):
        self.prompts.append(messages[0]["content"])
        # the classifier prompt carries the question (and the thread history):
        # answer for the longest known question it contains
        q = sorted((k for k in self.intents if k in messages[0]["content"]), key=len)
        return type("R", (), {"text": json.dumps(self.intents[q[-1]] if q else {})})()


def _route(question, history, intents, loop_answer="ANSWER"):
    import api.router as router
    from api.db import save_thread
    llm = _FakeLLM(intents)
    seen = []

    async def fake_loop(question=None, params=None, **kw):
        seen.append({"question": question, "params": dict(params or {})})
        return {"answer": loop_answer, "tool_results": {}}

    sb = StrictSupabase({**_tables(), "conversation_threads": []})
    with patch.object(router.LLMClient, "from_config", return_value=llm), \
         patch.object(router, "dynamic_query_loop", fake_loop), \
         patch.object(router, "message_names_known_company", lambda q, sb: False):
        r = asyncio.run(router.route_question(question=question, user_id="U1", persona=None,
                                              history=history, sb=sb, thread_ts="T1"))
    save_thread(sb, "T1", "C1", list(history), question, r.get("answer", ""),
                dict(r.get("tool_results", {})), r.get("handler_name", ""),
                pending_clarification=r.get("pending_clarification"))
    saved = [w for w in sb.writes if w["table"] == "conversation_threads"][-1]
    return r, seen, json.loads(saved["payload"]["history"])


def test_end_to_end_ask_then_reply_reruns_the_original_question():
    q = "What's changed with Jake's deals this week?"
    intents = {q: {"handler": "query_pipeline_movement", "confidence": 0.9,
                   "params": {"owner_email": "jake@growthbook.io"}},     # the classifier's silent pick
               "What's changed with Jake H's deals this week?": {
                   "handler": "query_pipeline_movement", "confidence": 0.9,
                   "params": {"owner_email": "jake@growthbook.io"}}}
    r, seen, hist = _route(q, [], intents)
    assert r["handler_name"] == "rep_clarification_ask" and r["answer"].startswith(
        "Two people named Jake own deals — reply 1 or 2:"), r
    assert seen == [], "nothing may run before the user picks"
    assert hist[-1]["role"] == rc.PENDING_ROLE, hist
    from api.db import get_api_history
    assert all(m["role"] in ("user", "assistant") for m in get_api_history(hist))

    r2, seen2, hist2 = _route("1", hist, intents)
    assert r2["answer"] == "ANSWER" and r2.get("resolved_question") == \
        "What's changed with Jake H's deals this week?", r2
    assert [s["question"] for s in seen2] == ["What's changed with Jake H's deals this week?"]
    assert seen2[0]["params"]["owner_email"] == "jake@growthbook.io"
    assert rc.find_pending(hist2) is None
    print("✓ end to end: 'Jake's deals' asks and runs nothing; the pending ask is saved in the "
          "thread (never sent to the model); reply '1' reruns the original question as "
          "'Jake H's deals' with jake@growthbook.io pinned")


def test_end_to_end_disclosure_is_prefixed_and_email_pinned():
    q = "How's Scott's call quality been this month?"
    intents = {q: {"handler": "dynamic_query", "confidence": 0.9,
                   "params": {"rep_email": "scott@growthbook.io"}},       # wrong Scott
               "How's Scott Keller's call quality been this month?": {
                   "handler": "dynamic_query", "confidence": 0.9, "params": {}}}
    r, seen, _ = _route(q, [], intents)
    assert r["answer"] == ("_Taking “Scott” to mean Scott Keller, the only person named Scott "
                           "who owns deals._\n\nANSWER"), r["answer"]
    assert seen[0]["question"] == "How's Scott Keller's call quality been this month?"
    assert seen[0]["params"]["rep_email"] == "scott.keller@growthbook.io", seen[0]["params"]
    print("✓ end to end: 'Scott' is answered for Scott Keller, the disclosure line is prefixed "
          "in code, and the classifier's wrong Scott email is overwritten")


def test_end_to_end_decline_runs_nothing():
    q = "How is Mike doing on talk time ratio?"
    intents = {q: {"handler": "dynamic_query", "confidence": 0.9, "params": {"rep_name": "Mike"}}}
    r, seen, hist = _route(q, [], intents)
    assert r["handler_name"] == "rep_name_declined" and seen == [], r
    assert r["answer"].startswith("I don't see anyone named Mike who owns deals"), r["answer"]
    assert rc.find_pending(hist) is None
    print("✓ end to end: 'Mike' is declined with the code-written list; nothing runs, nothing pending")


def test_classifier_asks_for_the_name_as_written():
    import api.router as router
    p = router.build_intent_prompt(today="2026-09-24", current_quarter="FY2027 Q3", history="[]",
                                   question="x", roster_text="")
    assert '"rep_name"' in p, "the classifier must extract the person's name verbatim"
    print("✓ the classifier schema has rep_name (the name exactly as written) for the gate to check")


# ── handlers' own name lookup ──────────────────────────────────────────────

def test_resolve_owner_email_never_guesses():
    import api.handlers as H
    sb = StrictSupabase(_tables())
    cases = {"Jake": None, "Scott": "scott.keller@growthbook.io", "Chris": "chris@growthbook.io",
             "an": None, "Ryan": None, "Jake Stangl": "jake.stangl@growthbook.io",
             "Cary": "cary@growthbook.io", "Mike": None}
    for name, want in cases.items():
        got, note = H._resolve_owner_email({"rep_name": name}, sb)
        assert got == want, (name, got, note)
    got, note = H._resolve_owner_email({"rep_name": "Jake"}, sb)
    assert "Jake H" in note and "Jake Stangl" in note, note
    print("✓ _resolve_owner_email: 'Jake' → none (names both), 'Scott' → Scott Keller (Bailey owns "
          "no deals), 'Chris' → Chris Sanders, 'an'/'Ryan'/'Mike' → none; no substring or "
          "first-unordered-match guess")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} tests passed")
