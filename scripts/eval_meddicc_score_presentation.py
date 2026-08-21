#!/usr/bin/env python3
"""
Eval: MEDDICC score presentation (FIX_MEDDICC_SCORE_PRESENTATION).

Two live defects in the LiveSport Slack answer:
  1. A hallucinated 8th component ("Paper Process — data gap"). This client is
     MEDDICC (7 components in rubric.py); Paper Process is an MEDDPICC letter
     the synthesis model invented because nothing told it the component set.
  2. overall_score rendered as "38/100" when it is the SUM of 7 components
     (max 70) — 38/70 = 54%, not 38%. A 16-point error that reframed a
     mid-pack deal as weak.

PART 1 — the synthesis prompt now names exactly the rubric components, forbids
inventing any, and states the 0-70 scale.
PART 2 — query_rubric_scores_bulk returns the score already labelled with its
denominator, so synthesis never has to guess.
"""
import sys
import types
import asyncio
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

if "supabase" not in sys.modules:
    _f = types.ModuleType("supabase")
    _f.create_client = lambda *a, **k: None
    _f.Client = type("Client", (), {})
    sys.modules["supabase"] = _f


class MockSB:
    def __init__(self, deals, analyses):
        self._deals, self._analyses = deals, analyses
        self._t = None

    def table(self, name):
        self._t = name
        return self

    def select(self, *a, **k):
        return self

    def __getattr__(self, name):
        return lambda *a, **k: self

    def execute(self):
        return types.SimpleNamespace(
            data=self._deals if self._t == "deals" else self._analyses)


def test_synthesis_cannot_name_a_component_outside_config():
    """The synthesis output may only reference components defined in
    rubric.py. A MEDDPICC-shaped model will invent Paper Process from the
    acronym if the prompt does not constrain it."""
    from api.router import build_synthesis_prompt
    try:
        from api.rubric import RUBRIC
    except ImportError:
        from rubric import RUBRIC

    prompt = build_synthesis_prompt({"role_group": "operational",
                                     "name": "Jeff"}).lower()
    results = []

    # Every real component's display name is named as in-scope.
    from api.router import _MEDDICC_DISPLAY
    names = [_MEDDICC_DISPLAY.get(k, k.replace("_", " ").title())
             for k in RUBRIC.keys()]
    results.append(("names all %d rubric components" % len(names),
                    all(n.lower() in prompt for n in names)))

    # Forbids inventing components, and names the classic offender.
    results.append(("forbids inventing components",
                    ("do not add" in prompt or "only components" in prompt
                     or "these are the only" in prompt)))
    results.append(("explicitly rules out Paper Process",
                    "paper process" in prompt))

    # States the 0-70 scale AND explicitly warns off /100.
    results.append(("states the /70 scale", "/70" in prompt or "0-70" in prompt))
    results.append(("explicitly warns against the /100 scale",
                    "not 0-100" in prompt or "not /100" in prompt
                    or "never rescale to 100" in prompt))
    return results


def test_overall_score_returned_with_denominator():
    """Handlers return the max alongside the score. A bare 38 was rendered as
    38/100 by synthesis when the real scale is 38/70 — a 16-point error in the
    reported percentage."""
    from api.handlers import query_rubric_scores_bulk, MEDDICC_OVERALL_MAX
    deals = [{"deal_id": "62160567676", "company_name": "LiveSport Media"}]
    # components 4+3+8+6+9+4+4 = 38
    analyses = [{
        "deal_id": "62160567676", "company_name": "LiveSport Media",
        "overall_score": 38, "metrics_score": 4, "economic_buyer_score": 3,
        "decision_criteria_score": 8, "decision_process_score": 6,
        "pain_score": 9, "champion_score": 4, "competition_score": 4,
        "analyzed_at": "2026-08-19T00:00:00Z",
    }]
    r = asyncio.run(query_rubric_scores_bulk({"company": "LiveSport"},
                                             MockSB(deals, analyses)))
    row = (r.get("scores") or [{}])[0]
    ov = row.get("overall") or {}
    results = [
        ("MEDDICC_OVERALL_MAX is 70", MEDDICC_OVERALL_MAX == 70),
        ("score row carries an 'overall' object", bool(ov)),
        ("overall.max == 70", ov.get("max") == 70),
        ("overall.display == '38/70'", ov.get("display") == "38/70"),
        ("overall.pct == 54 (not 38)", ov.get("pct") == 54),
        ("top-level scale note present",
         (r.get("scale") or {}).get("overall_max") == 70),
    ]
    return results


def run():
    print("=" * 72)
    print("MEDDICC SCORE PRESENTATION — component guard + labelled scale")
    print("=" * 72)
    passed = failed = 0
    for title, fn in (
        ("PART 1 — synthesis constrained to rubric components",
         test_synthesis_cannot_name_a_component_outside_config),
        ("PART 2 — overall_score returned with denominator",
         test_overall_score_returned_with_denominator),
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
