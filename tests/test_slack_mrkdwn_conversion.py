"""
Regression test: answers reach Slack in Slack mrkdwn, not standard markdown.

Why this exists (2026-09-23): Ryan's "pipeline added in the last two
weeks" answer showed in Slack as "**Pipeline Added — Last 2 Weeks**"
with literal asterisks. Nothing between route_question() and the Zapier
POST converted anything, and the dynamic loop's prompt
(DYNAMIC_SYSTEM_PROMPT) never forbids **double** bold. 32 of the 632
answers in conversation_threads had it.

Pins: api/slack_format.to_slack_mrkdwn() converts the exact incident
answer and each construct the model actually uses, leaves Slack-native
text alone (idempotent), and api/main.send_to_zap() applies it to what it
POSTs. It also pins that a converter crash still delivers the answer.
Each check has a planted-bug control.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.main as M
import api.slack_format as SF
from api.slack_format import to_slack_mrkdwn

# The exact answer text the 2026-09-23 16:13 UTC Slack reply carried, from
# conversation_threads (thread_ts 1790179969.377209).
INCIDENT_ANSWER = (
    "**Pipeline Added — Last 2 Weeks (Sep 9–23, 2026)**\n\n"
    "• **24 net-new deals** entered the pipeline across all stages\n"
    "• **$2.73M in ARR** added (from new entries)\n"
    "• **10 deals exited** (won, lost, or disqualified), representing **$977.5K**\n"
    "• **Net pipeline change: +14 deals | +$1.75M ARR**\n\n"
    "**Breakdown of new deals by stage:**\n"
    "• Discovery: 16 new deals (largest contributor)\n"
    "• Scoping: 6 new deals\n"
    "• Awaiting Signature: 1 new deal (*Apify*)\n"
    "• Technical Evaluation: 1 new deal (*KPLER*)\n"
    "• Negotiating: 0 net-new (all 5 entries came from other stages)\n\n"
    "**Notable new entries:** *Twitch*, *Stitch Fix*, *Supercell*, "
    "*The New York Times*, *Bamboo HR*, *Trade Republic*, *CarGurus*, "
    "*Gen™*, *MoneyLion*\n\n"
    "⚡ Discovery is absorbing most new pipeline — watch for conversion "
    "into Scoping over the next 2 weeks to validate deal quality."
)

# (input, expected) for each construct, taken from shapes seen in real answers.
CASES = [
    ("**bold** text", "*bold* text"),
    ("__bold__ text", "*bold* text"),
    ("***both***", "*_both_*"),
    ("~~gone~~", "~gone~"),
    ("# Jake Stangl — MTD Snapshot", "*Jake Stangl — MTD Snapshot*"),
    ("## 📅 Meetings **Booked**", "*📅 Meetings Booked*"),
    ("### Title ###", "*Title*"),
    ("- item one\n- item two", "• item one\n• item two"),
    ("* star item", "• star item"),
    ("+ plus item", "• plus item"),
    ("• *Statsig* — 3 mentions\n  - Amar Bank: flags",
     "• *Statsig* — 3 mentions\n  • Amar Bank: flags"),
    ("| Deal | Overall |\n|---|---|\n| ECCO | **35/70** |\n| Zalando | 18/70 |",
     "*Deal | Overall*\n• ECCO | *35/70*\n• Zalando | 18/70"),
    ("see [the PR](https://github.com/x/y/pull/1)",
     "see <https://github.com/x/y/pull/1|the PR>"),
]

# Slack-native or deliberately untouched text: must pass through unchanged.
UNCHANGED = [
    "*Bold label*\n• *Company* — $1.2M | Negotiating | Oct 30",
    "_not available_ and _(data gap — no close date)_",
    "1. Tomas Alberio — So Shall We (Aug 3)\n2. Bob Flavin — LaFleur",
    "> quoted line",
    "Section one\n\n---\n\nSection two",
    "Growth was -5% and 3 * 4 = 12",
    "Use `**not bold**` literally",
    "```\n**inside a fence**\n- not a bullet\n```",
    "<https://app.hubspot.com/x|dmTECH GmbH> and <@U09PMRV270T>",
    "",
]


def test_incident_answer_converts():
    out = to_slack_mrkdwn(INCIDENT_ANSWER)
    assert "**" not in out, out
    assert out.startswith("*Pipeline Added — Last 2 Weeks (Sep 9–23, 2026)*\n"), out
    assert "• *24 net-new deals* entered" in out
    assert "representing *$977.5K*" in out
    assert "*Notable new entries:* *Twitch*, *Stitch Fix*" in out
    assert "(*Apify*)" in out and "(*KPLER*)" in out  # Slack-native kept
    # Only the ** markers changed: stripping one * per pair gives the input.
    assert out == INCIDENT_ANSWER.replace("**", "*")
    print("✓ exact 2026-09-23 incident answer: 0 '**' left, bullets and *names* intact")


def test_each_construct_converts():
    for src, want in CASES:
        got = to_slack_mrkdwn(src)
        assert got == want, f"{src!r}\n  got  {got!r}\n  want {want!r}"
    print(f"✓ all {len(CASES)} markdown constructs convert to Slack mrkdwn")


def test_slack_native_text_is_untouched_and_conversion_idempotent():
    for src in UNCHANGED:
        assert to_slack_mrkdwn(src) == src, f"changed: {src!r} -> {to_slack_mrkdwn(src)!r}"
    for src, _ in CASES + [(INCIDENT_ANSWER, None)]:
        once = to_slack_mrkdwn(src)
        assert to_slack_mrkdwn(once) == once, f"not idempotent: {src!r}"
    print(f"✓ {len(UNCHANGED)} Slack-native/untouchable inputs unchanged; "
          f"conversion idempotent on all {len(CASES) + 1} converted inputs")


def test_checks_catch_a_broken_converter():
    """Planted bugs: an identity converter, and one that turns *single*
    asterisks into italics, must both fail the checks above."""
    orig = SF.to_slack_mrkdwn
    caught = []
    for name, broken in [
        ("identity", lambda t: t),
        ("single-star-to-italic",
         lambda t: orig(t).replace("*Apify*", "_Apify_").replace("*Company*", "_Company_")),
    ]:
        globals()["to_slack_mrkdwn"] = broken
        try:
            test_incident_answer_converts()
            test_slack_native_text_is_untouched_and_conversion_idempotent()
        except AssertionError:
            caught.append(name)
        finally:
            globals()["to_slack_mrkdwn"] = orig
    assert caught == ["identity", "single-star-to-italic"], caught
    print("✓ planted identity and single-star-to-italic converters both caught")


class _FakeClient:
    posted = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        _FakeClient.posted.append(json)


def _send(text):
    _FakeClient.posted = []
    orig_url, orig_client = M.ZAP_REPLY_URL, M.httpx.AsyncClient
    M.ZAP_REPLY_URL, M.httpx.AsyncClient = "https://example.invalid/hook", _FakeClient
    try:
        asyncio.run(M.send_to_zap("C1", "123.456", text))
    finally:
        M.ZAP_REPLY_URL, M.httpx.AsyncClient = orig_url, orig_client
    assert len(_FakeClient.posted) == 1, _FakeClient.posted
    return _FakeClient.posted[0]


def test_send_to_zap_posts_converted_text():
    body = _send(INCIDENT_ANSWER)
    assert body["text"] == to_slack_mrkdwn(INCIDENT_ANSWER)
    assert "**" not in body["text"]
    assert body["channel_id"] == "C1" and body["thread_ts"] == "123.456"
    print("✓ send_to_zap POSTs the converted text to the Zapier hook")


def test_send_to_zap_check_catches_a_missing_conversion():
    """Planted bug: send_to_zap without the conversion (converter is a no-op)."""
    orig = SF.to_slack_mrkdwn
    SF.to_slack_mrkdwn = lambda t: t
    try:
        body = _send(INCIDENT_ANSWER)
    finally:
        SF.to_slack_mrkdwn = orig
    assert "**" in body["text"], "planted missing-conversion bug not visible"
    print("✓ planted missing conversion in send_to_zap is visible ('**' reaches the POST)")


def test_converter_crash_still_delivers_the_answer():
    orig = SF.to_slack_mrkdwn

    def boom(t):
        raise RuntimeError("planted converter crash")

    SF.to_slack_mrkdwn = boom
    try:
        body = _send(INCIDENT_ANSWER)
    finally:
        SF.to_slack_mrkdwn = orig
    assert body["text"] == INCIDENT_ANSWER
    print("✓ a converter crash still POSTs the answer (unconverted), never drops it")


if __name__ == "__main__":
    test_incident_answer_converts()
    test_each_construct_converts()
    test_slack_native_text_is_untouched_and_conversion_idempotent()
    test_checks_catch_a_broken_converter()
    test_send_to_zap_posts_converted_text()
    test_send_to_zap_check_catches_a_missing_conversion()
    test_converter_crash_still_delivers_the_answer()
    print("\n✅ All tests passed")
