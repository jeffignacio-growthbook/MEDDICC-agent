#!/usr/bin/env python3
"""
Eval: bands as the surfaced signal (FIX_MEDDICC_SCORING_PIPELINE follow-up).

The characterization showed the generator reproduces a component's BAND
run-to-run but not its exact 0-10 integer (6 of 7 components moved ±1, every
move on a band line). The fix is to keep the integer INTERNAL and surface the
band, flagging boundary cases explicitly. This eval pins that contract:

  1. band_label maps scores to red/yellow/green and flags scores that sit on a
     band boundary (3,4,6,7) as borderline, naming the neighbouring band.
  2. band_meets compares at band precision — 5 and 6 both clear a gate of 6
     (the anti-flip property), while a gate of 7 still needs green.
  3. None/blank surfaces as UNREAD, not red (unread ≠ weak).
  4. The handlers attach bands to what they surface (query_rubric_scores_bulk).
  5. The synthesis guard tells the model to surface bands, not /10, and to
     flag borderline components.

Offline; stubs supabase so api.handlers imports without network.
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
    def __init__(self, deals=None, analyses=None):
        self._deals = deals or []
        self._analyses = analyses or []
        self._t = None

    def table(self, name):
        self._t = name
        return self

    def __getattr__(self, name):
        # every PostgREST chain call returns self
        return lambda *a, **k: self

    def execute(self):
        data = {"deals": self._deals, "analyses": self._analyses}.get(self._t, [])
        return types.SimpleNamespace(data=data)


def run():
    from rubric import band_label, band_meets, meddicc_bands, get_band
    print("=" * 72)
    print("BANDS AS THE SURFACED SIGNAL (band precision + borderline flag)")
    print("=" * 72)
    passed = failed = 0

    def check(name, cond):
        nonlocal passed, failed
        if cond:
            passed += 1; print(f"  ✓ {name}")
        else:
            failed += 1; print(f"  ❌ {name}")

    # 1. Band mapping + boundary flagging. Uniform bands: red 0-3, yellow 4-6,
    #    green 7-10 → boundary-adjacent values are 3,4,6,7.
    print("\n[band_label — mapping + borderline]")
    solid_yellow = band_label("champion", 5)
    check("5 → solid yellow, not borderline",
          solid_yellow["band"] == "yellow" and solid_yellow["borderline"] is False
          and solid_yellow["text"] == "yellow")
    top_yellow = band_label("champion", 6)
    check("6 → yellow, borderline near green",
          top_yellow["band"] == "yellow" and top_yellow["borderline"] is True
          and top_yellow["near"] == "green"
          and top_yellow["text"] == "yellow, near the green boundary")
    bot_green = band_label("champion", 7)
    check("7 → green, borderline near yellow",
          bot_green["band"] == "green" and bot_green["near"] == "yellow"
          and bot_green["borderline"] is True)
    bot_yellow = band_label("metrics", 4)
    check("4 → yellow, borderline near red",
          bot_yellow["band"] == "yellow" and bot_yellow["near"] == "red")
    check("2 → solid red, not borderline",
          band_label("metrics", 2) == {"band": "red", "borderline": False,
                                        "near": None, "score": 2, "text": "red"})
    check("10 → green, not borderline (no band above)",
          band_label("pain", 10)["borderline"] is False)

    # 2. None/blank is UNREAD, not weak.
    print("\n[unread ≠ weak]")
    check("None → unread (not red)", band_label("champion", None)["band"] == "unread")
    check("blank string → unread", band_label("champion", "")["band"] == "unread")

    # 3. band_meets: the anti-flip property + real boundaries kept.
    print("\n[band_meets — gate comparison at band precision]")
    check("5 and 6 both clear a gate of 6 (both yellow → no ±1 flip)",
          band_meets("economic_buyer", 5, 6) and band_meets("economic_buyer", 6, 6))
    check("4 clears a gate of 6 (yellow-or-better)", band_meets("champion", 4, 6))
    check("3 (red) fails a gate of 6 (needs yellow)",
          not band_meets("champion", 3, 6))
    check("gate 7 needs green: 6 fails, 7 clears",
          (not band_meets("decision_process", 6, 7))
          and band_meets("decision_process", 7, 7))
    check("gate 4 → yellow floor: 4 clears, 3 fails",
          band_meets("pain", 4, 4) and not band_meets("pain", 3, 4))
    check("missing score never clears a yellow-floor gate",
          not band_meets("champion", None, 4))

    # 4. meddicc_bands over a full component dict.
    print("\n[meddicc_bands — full component map]")
    mb = meddicc_bands({"champion": 6, "economic_buyer": 5, "pain": None,
                        "not_a_component": 9})
    check("champion 6 → borderline text",
          mb["champion"]["text"] == "yellow, near the green boundary")
    check("pain None → unread", mb["pain"]["band"] == "unread")
    check("unknown component dropped", "not_a_component" not in mb)

    # 5. query_rubric_scores_bulk attaches per-component bands (surface signal).
    print("\n[handler surfaces bands]")
    from api.handlers import query_rubric_scores_bulk
    deals = [{"deal_id": "62160567676", "company_name": "LiveSport Media"}]
    analyses = [{"deal_id": "62160567676", "company_name": "LiveSport Media",
                 "overall_score": 48, "metrics_score": 8, "economic_buyer_score": 5,
                 "decision_criteria_score": 7, "decision_process_score": 7,
                 "pain_score": 9, "champion_score": 5, "competition_score": 7,
                 "analyzed_at": "2026-08-20T00:00:00Z"}]
    r = asyncio.run(query_rubric_scores_bulk({"company": "LiveSport"},
                                             MockSB(deals, analyses)))
    row = (r.get("scores") or [{}])[0]
    bands = row.get("bands") or {}
    check("row carries a bands map", isinstance(bands, dict) and len(bands) == 7)
    check("champion surfaced as yellow (internal 5)", bands.get("champion") == "yellow")
    check("metrics surfaced as green (internal 8)", bands.get("metrics") == "green")
    check("scale note tells synthesis to surface bands, not /10",
          "band" in (r.get("scale", {}).get("note", "").lower()))
    check("internal integer still present for trending/hygiene",
          row.get("champion_score") == 5)

    # 6. Synthesis guard instructs banding + borderline.
    print("\n[synthesis guard instructs bands]")
    from api.router import build_synthesis_prompt
    g = build_synthesis_prompt({"role_group": "sales_leadership", "name": "Ryan"}).lower()
    check("guard names the bands", "red" in g and "yellow" in g and "green" in g)
    check("guard says surface bands not the /10 integer",
          "band" in g and ("not" in g and "10" in g))
    check("guard tells the model to flag borderline / near-boundary",
          "borderline" in g or "boundary" in g)

    print("\n" + "=" * 72)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
