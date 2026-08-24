#!/usr/bin/env python3
"""
Eval: MEDDICC synthesis leads with evidence, not boundary mechanics
(FIX_SYNTHESIS_BOUNDARY_LANGUAGE).

Live LiveSport output led every borderline component with band mechanics
("green, near the yellow boundary … sitting on the edge") and attached generic
follow-ups ("worth pressure-testing: can they mobilize internal support?") that
fit any deal. The evidence that produced the scores wasn't used.

PART 1 locks the synthesis PROMPT contract: the guard now makes evidence the
subject of the sentence and the boundary a trailing flag, bans generic
follow-ups, and makes "plain fact IS the sentence" a hard rule.

PART 2 is the OUTPUT floor: two heuristic checkers (the spec's two tests) run
against the spec's WRONG and RIGHT examples. These are a floor, not a semantic
guarantee — a human read of a few regenerated outputs is the real acceptance
test — but they catch the exact regression seen in production.
"""
import re
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f


# ── PART 2 checkers (reusable output linters; a floor, not a guarantee) ──────

_BOUNDARY_OPENERS = ("near the", "borderline read", "sitting on the edge",
                     "on the edge", "near a band", "on the band line")
_GENERIC_FOLLOWUP = ("pressure-test", "pressure-testing", "worth validating that",
                     "can they mobilize", "worth confirming whether",
                     "worth exploring whether")


def _opening_clause(line: str) -> str:
    """The part of a component line before its first em-dash / colon-label /
    sentence break — i.e. what the sentence LEADS with."""
    s = line.strip()
    # drop a leading "Component:" label so we judge what follows it
    s = re.sub(r"^[-*\s]*[A-Z][A-Za-z /]{2,30}:\s*", "", s)
    for sep in ("—", " - ", ". "):
        if sep in s:
            s = s.split(sep, 1)[0]
            break
    return s.strip()


def leads_with_boundary_language(line: str) -> bool:
    """True if a component description OPENS with band mechanics instead of a
    fact. The boundary may still appear later as a trailing note."""
    opener = _opening_clause(line).lower()
    if any(p in opener for p in _BOUNDARY_OPENERS):
        return True
    # a bare band word as the whole opener ("green, confirmed but on the edge")
    # with no concrete fact (proper noun or number) is also leading with mechanics
    if re.match(r"^(red|yellow|green)\b", opener) and not _has_specific_fact(opener):
        return True
    return False


def _has_specific_fact(text: str) -> bool:
    """Heuristic: a mid-sentence capitalised token (a name/product) or a digit
    signals a concrete fact rather than pure band mechanics."""
    if re.search(r"\d", text):
        return True
    toks = re.findall(r"\S+", text)
    for i, t in enumerate(toks):
        if i == 0:
            continue  # sentence-initial cap doesn't count
        if re.match(r"[A-Z][A-Za-z’'.-]{1,}", t):
            return True
    return False


def has_generic_followup(text: str) -> bool:
    """True if a next-step/question uses a stock phrase WITHOUT anchoring it to a
    named person/product/fact in the same sentence."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        low = sentence.lower()
        if any(p in low for p in _GENERIC_FOLLOWUP):
            if not _has_specific_fact(sentence):
                return True
    return False


# ── PART 1: the prompt contract ─────────────────────────────────────────────

def test_prompt_makes_evidence_the_subject():
    from api.router import build_synthesis_prompt
    prompt = build_synthesis_prompt({"role_group": "operational",
                                     "name": "Jeff"})
    # collapse all whitespace (newlines + indentation) so substring checks are
    # robust to how the guard text happens to wrap.
    low = re.sub(r"\s+", " ", prompt).lower()
    r = []
    r.append(("borderline sentence is built from the component's evidence first",
              "built from the component's evidence first" in low))
    r.append(("boundary is a trailing note, not the opening clause",
              "trailing note" in low and "not the opening clause" in low))
    r.append(("boundary must not be the reason for a recommendation",
              "not the reason given for a recommendation" in low))
    r.append(("shows the WRONG (boundary-as-subject) example",
              "boundary as the subject" in low))
    r.append(("shows the RIGHT (evidence-as-subject) example",
              "evidence as the subject" in low))
    r.append(("empty/generic evidence => say evidence is thin, not boundary",
              "evidence is limited" in low or "evidence is thin" in low))
    r.append(("plain fact from evidence IS the sentence (hard rule)",
              "the plain fact from evidence is the sentence" in low))
    r.append(("band label is metadata attached after",
              "metadata attached after" in low))
    r.append(("bans generic follow-up questions",
              "banned" in low and "fits every deal" in low))
    r.append(("requires a specific person/call/fact per next step",
              "reference something specific from that deal's evidence" in low))
    # untouched invariants
    r.append(("UNREAD-vs-weak rule still present",
              "unread" in low and "not that it is weak" in low))
    r.append(("band-distribution overall rule still present",
              "band distribution" in low))
    return r


def test_checkers_flag_the_wrong_examples():
    """The spec's WRONG examples must trip the checkers; the RIGHT ones must
    pass. This is the regression the fix targets, from the doc verbatim."""
    wrong_live_eb = ("Economic Buyer: green, near the yellow boundary — "
                     "confirmed, but sitting on the edge. This is a borderline "
                     "read — one bad call or an org change and it tips yellow.")
    wrong_champ = ("Champion: yellow, near the green boundary — this is a "
                   "borderline read.")
    right = ("Tomáš is running procurement and coordinating the CPO, but he's "
             "also the one raising the pricing objection — no evidence he's "
             "advocating for you internally. (Borderline yellow/green.)")
    wrong_q = "Worth pressure-testing: can they mobilize internal support?"
    right_q = ("Confirm Tomáš is advocating for GrowthBook with the CPO, not "
               "just running a fair evaluation between us and Optimizely.")
    return [
        ("live EB line flagged as boundary-led",
         leads_with_boundary_language(wrong_live_eb)),
        ("champion boundary line flagged as boundary-led",
         leads_with_boundary_language(wrong_champ)),
        ("evidence-led line NOT flagged", not leads_with_boundary_language(right)),
        ("generic 'pressure-testing … mobilize' question flagged",
         has_generic_followup(wrong_q)),
        ("specific Tomáš/CPO question NOT flagged", not has_generic_followup(right_q)),
        ("evidence-led line has no generic follow-up", not has_generic_followup(right)),
    ]


def run():
    print("=" * 72)
    print("MEDDICC SYNTHESIS — evidence-first, boundary as trailing flag")
    print("=" * 72)
    passed = failed = 0
    for title, fn in (
        ("PART 1 — synthesis prompt contract", test_prompt_makes_evidence_the_subject),
        ("PART 2 — output checkers vs the spec's WRONG/RIGHT examples",
         test_checkers_flag_the_wrong_examples),
    ):
        print(f"\n[{title}]")
        for label, ok in fn():
            if ok:
                passed += 1; print(f"  ✓ {label}")
            else:
                failed += 1; print(f"  ❌ {label}")
    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("NOTE: PART 2 is a floor (banned-phrase + specific-fact heuristic), "
          "not a semantic guarantee.\nA human read of regenerated LiveSport + one "
          "other deal is the real acceptance test.")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
