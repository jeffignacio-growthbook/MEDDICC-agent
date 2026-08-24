#!/usr/bin/env python3
"""
Eval: the progressive roll-up draft round-trips through the EXISTING HubSpot score
extractor (PROGRESSIVE_SCORING_SPEC, Phase 5).

The roll-up write path reuses hubspot._extract_scores_from_analysis (and the note
+ Supabase writers that call it) by rendering a markdown draft. If render_md's
'Score: N/10' lines and component labels don't parse back to the same numbers,
HubSpot/Supabase would silently record the wrong score. This locks that contract:
render_md(rolled) -> _extract_scores_from_analysis -> identical per-component
scores, correct overall, and null -> 0.
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


_stub_if_missing("pytz", timezone=lambda *a, **k: None, utc=None)
_stub_if_missing("anthropic", Anthropic=type("Anthropic", (), {}), APIError=type("APIError", (Exception,), {}))
_stub_if_missing("supabase", create_client=lambda *a, **k: None, Client=type("Client", (), {}))

import rollup_deal_scores as rd  # noqa: E402
import call_scorer as cs  # noqa: E402
from hubspot_deals import HubSpotDealsClient  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {name}: {got!r}")
    if not ok:
        print(f"      want: {want!r}")
        FAILS.append(name)


def _rolled(**scores):
    """Build a roll_up-shaped dict; unspecified components are null."""
    out = {k: {"score": None, "evidence": None, "call_id": None, "call_date": None} for k in cs.COMPONENT_KEYS}
    for k, s in scores.items():
        out[k] = {"score": s, "evidence": f"evidence for {k}", "call_id": "c1", "call_date": "2026-08-05"}
    return out


def run():
    rolled = _rolled(metrics=8, economic_buyer=6, decision_criteria=7,
                     decision_process=8, pain=9, champion=3, competition=9)
    # champion=3, pain=9 span red..green; leave nothing null in this first case.
    md = rd.render_md("Livesport", "62160567676", rolled, ncalls=4)

    hs = HubSpotDealsClient.__new__(HubSpotDealsClient)
    parsed = hs._extract_scores_from_analysis(md)

    print("round-trip render_md -> _extract_scores_from_analysis")
    check("metrics", parsed["metrics_score"], "8")
    check("economic_buyer", parsed["economic_buyer_score"], "6")
    check("decision_criteria", parsed["decision_criteria_score"], "7")
    check("decision_process", parsed["decision_process_score"], "8")
    check("pain", parsed["pain_score"], "9")
    check("champion (red band value survives)", parsed["champion_score"], "3")
    check("competition", parsed["competition_score"], "9")
    check("overall = sum", parsed["overall_score"], str(8 + 6 + 7 + 8 + 9 + 3 + 9))

    # Null component renders as 0 and contributes nothing to the overall.
    rolled2 = _rolled(metrics=7, pain=8, champion=5)  # others null
    md2 = rd.render_md("Acme", "1", rolled2, ncalls=2)
    parsed2 = hs._extract_scores_from_analysis(md2)
    print("null components -> 0")
    check("economic_buyer null -> 0", parsed2["economic_buyer_score"], "0")
    check("decision_process null -> 0", parsed2["decision_process_score"], "0")
    check("overall = sum of non-null", parsed2["overall_score"], str(7 + 8 + 5))

    # component_details shape + status mapping for write_component_scores.
    det = rd.component_details(rolled)
    print("component_details")
    check("champion status red -> unknown", det["champion"]["status"], "unknown")
    check("economic_buyer 6 -> partial", det["economic_buyer"]["status"], "partial")
    check("pain 9 -> identified", det["pain"]["status"], "identified")
    det2 = rd.component_details(rolled2)
    check("null -> score 0 in details", det2["economic_buyer"]["score"], 0)
    check("null -> status unknown", det2["economic_buyer"]["status"], "unknown")

    check("overall() helper matches", rd.overall(rolled), 8 + 6 + 7 + 8 + 9 + 3 + 9)
    check("band boundaries", (rd.band(3), rd.band(4), rd.band(6), rd.band(7)),
          ("red", "yellow", "yellow", "green"))

    if FAILS:
        print(f"\nFAIL — {len(FAILS)}: {', '.join(FAILS)}")
        return 1
    print("\nPASS — roll-up draft round-trips to identical scores; null->0; details/status correct.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
