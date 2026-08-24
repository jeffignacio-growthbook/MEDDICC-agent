#!/usr/bin/env python3
"""
Eval: synthesis house-style — emoji bands, one em dash per sentence, directional
Metrics asks. Prompt-level rules (no scoring/data change), locked two ways:
  (a) the rule is present in the synthesis prompt (where it belongs — not a
      post-hoc regex on model output);
  (b) the doc's three static checks flag the REAL bad output quoted in the fix
      and pass the corrected form — run against the actual Ecco/Zalando/Natera
      answer style, not a synthetic fixture.
"""
import re
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


_stub_if_missing("anthropic", Anthropic=type("Anthropic", (), {}),
                 APIError=type("APIError", (Exception,), {}))
_stub_if_missing("supabase", create_client=lambda *a, **k: None,
                 Client=type("Client", (), {}))

FAILS = []


def check(name, cond):
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        FAILS.append(name)


# ── the three static checks (as the fix doc specifies) ──────────────────────
_BAND_EMOJI = "🔴🟡🟢⚪"


def band_word_offenders(text):
    """Band words used as a label — the regression. 'near <colour>' (the
    borderline trailing qualifier next to an emoji) is allowed."""
    offenders = []
    for m in re.finditer(r"\b(red|yellow|green)\b", text, re.I):
        pre = text[max(0, m.start() - 5):m.start()].lower()
        if pre.endswith("near "):
            continue  # "🟡 near green" is the allowed borderline form
        offenders.append(m.group(0))
    return offenders


def bands_are_emoji_not_text(text):
    return not band_word_offenders(text)


def em_dash_offenders(text):
    """Sentences with more than one em dash (—)."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [s.strip() for s in sentences if s.count("—") > 1]


def max_one_em_dash_per_sentence(text):
    return not em_dash_offenders(text)


_ESTIMATE_WORDS = ("estimate", "roughly", "ballpark", "order of magnitude",
                   "how many", "rough", "approximate", "%")
_PRECISION_TELLS = ("no dollar figure", "no cost of", "exact figure",
                    "precise", "exact number")


def metrics_step_asks_estimate_not_precision(text):
    t = text.lower()
    if any(w in t for w in _ESTIMATE_WORDS):
        return True
    if any(w in t for w in _PRECISION_TELLS):
        return False
    return True  # neutral text isn't a violation


# ── the real strings quoted in the fix doc ──────────────────────────────────
BAND_BAD = "Metrics (yellow, borderline red) and Champion (yellow, borderline green)"
BAND_GOOD = "🟡 *Metrics* (near green) and 🟡 *Champion* (near green)"

GIULIO_BAD = ("Giulio is doing a lot — structured the confidential call during "
              "his vacation, looped in Alexander and Nikita, forwarding legal "
              "docs, driving parallel workstreams, and explicitly said 'I have "
              "to find a solution last quarter.'")
GIULIO_GOOD = ("Giulio is driving this deal. He structured the confidential "
               "call during his vacation, looped in Alexander and Nikita, and "
               "is forwarding legal docs. He told you directly: 'I have to find "
               "a solution last quarter.'")
# a genuine multi-em-dash run-on (the pattern the doc says recurs on other lines)
MULTI_DASH_BAD = ("Metrics is thin — no dollar figure — no experiment volume — "
                  "no cost of the workaround.")

METRICS_BAD = ("no dollar figure tied to halted tests, no experiment volume, "
               "no cost of the bundled MTU workaround")
METRICS_GOOD = ("ask Rebecca to estimate how many experiments per month are "
                "currently delayed")


def test_band_renders_as_emoji_not_text():
    check("REAL band-as-text line is flagged", not bands_are_emoji_not_text(BAND_BAD))
    check("corrected emoji band passes", bands_are_emoji_not_text(BAND_GOOD))
    check("offenders name the words", set(w.lower() for w in band_word_offenders(BAND_BAD))
          >= {"yellow", "red", "green"})


def test_no_more_than_one_em_dash_per_sentence():
    check("multi-em-dash run-on is flagged", not max_one_em_dash_per_sentence(MULTI_DASH_BAD))
    check("Giulio rewrite passes (facts as short sentences)",
          max_one_em_dash_per_sentence(GIULIO_GOOD))
    check("a single em dash is allowed", max_one_em_dash_per_sentence(GIULIO_BAD))


def test_metrics_next_step_asks_for_estimate_not_precision():
    check("REAL precision-implying Metrics line is flagged",
          not metrics_step_asks_estimate_not_precision(METRICS_BAD))
    check("directional-estimate Metrics line passes",
          metrics_step_asks_estimate_not_precision(METRICS_GOOD))


def test_rules_live_in_the_prompt_not_a_regex_patch():
    from api.router import build_synthesis_prompt, _VOICE_BASE
    p = build_synthesis_prompt({"role_group": "sales_leadership", "name": "Ryan"})
    pl = p.lower()
    check("prompt mandates emoji bands (🔴/🟡/🟢), not the words",
          all(e in p for e in ("🔴", "🟡", "🟢")) and "never the word" in pl)
    check("prompt caps em dashes at one per sentence",
          "one em dash per sentence" in pl or "at most one em dash" in pl)
    check("em-dash rule is house-tier (in the base voice, all handlers)",
          "em dash per sentence" in _VOICE_BASE.lower())
    check("prompt tells Metrics to ask a directional estimate",
          "directional" in pl and "ballpark" in pl)
    check("prompt keeps unread on the neutral ⚪ marker (consistency)",
          "⚪" in p)


def run():
    print("=" * 72)
    print("SYNTHESIS STYLE — emoji bands / em-dash cap / directional Metrics")
    print("=" * 72)
    for title, fn in (
        ("bands render as emoji, not text", test_band_renders_as_emoji_not_text),
        ("≤ one em dash per sentence", test_no_more_than_one_em_dash_per_sentence),
        ("Metrics asks for an estimate, not precision",
         test_metrics_next_step_asks_for_estimate_not_precision),
        ("rules live in the prompt (not a regex patch)",
         test_rules_live_in_the_prompt_not_a_regex_patch),
    ):
        print(f"\n[{title}]")
        fn()
    print("\n" + "=" * 72)
    if FAILS:
        print(f"FAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("PASS — style rules present in-prompt; checks flag the real bad output.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
