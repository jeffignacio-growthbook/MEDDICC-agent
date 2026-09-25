#!/usr/bin/env python3
"""
Quarter-health composer: every basis statement the four primitives disclose
survives, verbatim, into every model input built from the composed result.

The failure this guards is tonight's recurring one: a note computed
correctly upstream and silently dropped at a narrowing point nobody
watched (query_pipeline_movement's dropped _synthesis_note; the waterfall
basis; SNAPSHOT_DIFF chopped by the 20,000-char cut). A composer adds a
new narrowing point: it nests four results into one, and the nested
result is bigger than any one of them, so the classifier path's
last-resort character cut and the composer's own trimming of per-deal
lists are both places a note can fall out.

Inputs are the REAL outputs of the four primitives, captured live on
2026-09-25 (tests/fixtures/quarter_health_primitives_2026_09_25.json,
tests/fixtures/capture_quarter_health_primitives.py), never hand-built.

Disclosures are collected INDEPENDENTLY of the composer: every string
under a disclosure-like key (note, *_note, basis, risk_basis,
_synthesis_note, coverage_omitted_reason, reason, scope, period, caveat,
text) anywhere in each raw primitive output, lists included. Each must
reach, for both scenarios (base and downside):
  classifier synthesis   _smart_truncate_for_synthesis(_cap_rows_for_synthesis(r))
                         (route_question step 7, the answer-writing call)
  verify / retry         _smart_truncate_for_synthesis(r) on the uncapped
                         result (step 8 verify pass and the truncation retry)
  dynamic loop           _serialize_tool_result_for_synthesis, the function
                         the loop builds its synthesis input with, under the
                         planned entry-point names (qh.ENTRY_POINTS)
                         registered in STRUCTURED_HANDLERS. The end-to-end
                         loop run (tests/canary_harness.py) needs the names in
                         the loop's tool map too, so it lands with the entry
                         points. Left unregistered, the loop's aggregated
                         view (8,000 chars) drops disclosures: pinned below,
                         so the entry points can't ship without registering.
and the four headline numbers must reach them too. The classifier text
must still parse as JSON: the character cut (router.synth_payload_chars) never fired.
"""
import copy
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "analytics"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.evaluator as evaluator  # noqa: E402
import api.quarter_health as qh  # noqa: E402
import api.router as router  # noqa: E402
from unittest.mock import patch  # noqa: E402

FIXTURE = json.loads((REPO / "tests" / "fixtures" / "quarter_health_primitives_2026_09_25.json").read_text())
PRIMITIVES = ("query_forecast_trust", "query_pipeline", "query_high_priority_deal_risk",
              "query_loss_concentration")
RAW = {k: FIXTURE[k] for k in PRIMITIVES}
DISCLOSURE_KEY = re.compile(r"^(note|basis|risk_basis|_synthesis_note|coverage_omitted_reason|"
                            r"reason|scope|period|caveat|text|.+_note)$")


def _excluded(prim, path):
    """Is this path under a key the composer leaves out of the verdict
    (qh.VERDICT_EXCLUDED)? Those must NOT reach the model."""
    return any(path == f"{prim}.{k}" or path.startswith(f"{prim}.{k}.") or path.startswith(f"{prim}.{k}[")
               for k in qh.VERDICT_EXCLUDED.get(prim, ()))


def collect_disclosures(raw, excluded=False):
    """(primitive, path, text) for every disclosure-like string, any depth:
    the ones that must reach the model, or (excluded=True) the ones under
    qh.VERDICT_EXCLUDED that must not."""
    out = []

    def walk(o, prim, path):
        if isinstance(o, dict):
            for k, v in o.items():
                p = f"{path}.{k}"
                if isinstance(v, str) and v.strip() and DISCLOSURE_KEY.match(k):
                    out.append((prim, p, v))
                walk(v, prim, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, prim, f"{path}[{i}]")

    for prim, result in raw.items():
        walk(result, prim, prim)
    return [d for d in out if _excluded(d[0], d[1]) == excluded]


DISCLOSURES = collect_disclosures(RAW)
EXCLUDED = collect_disclosures(RAW, excluded=True)


def _present(text, haystack):
    return (json.dumps(text)[1:-1] in haystack
            or json.dumps(text, ensure_ascii=False)[1:-1] in haystack
            or text in haystack)


def _compose(scenario, raw=None):
    return qh.compose_from_results(copy.deepcopy(raw or RAW), scenario,
                                   stage_rates=FIXTURE["stage_close_rate"],
                                   deal_rows=FIXTURE["high_risk_deal_rows"])


def _loop_text(composed, scenario, registered=True):
    name = qh.ENTRY_POINTS[scenario]
    reg = {name: ["status"]} if registered else {}
    with patch.dict(evaluator.STRUCTURED_HANDLERS, reg):
        if not registered:
            evaluator.STRUCTURED_HANDLERS.pop(name, None)
        text, _ = router._serialize_tool_result_for_synthesis(copy.deepcopy(composed), name)
    return text


def _model_inputs(composed, scenario):
    limit = router.synth_payload_chars(qh.ENTRY_POINTS[scenario])
    classifier = router._smart_truncate_for_synthesis(
        router._cap_rows_for_synthesis(copy.deepcopy(composed)), limit)
    verify = router._smart_truncate_for_synthesis(copy.deepcopy(composed), limit)
    return {"classifier synthesis": classifier, "verify / retry": verify,
            "dynamic loop": _loop_text(composed, scenario)}


HEADLINE = {
    "forecast ARR": repr(RAW["query_forecast_trust"]["pipeline"]["incremental_arr"]),
    "pipeline total": repr(RAW["query_pipeline"]["total_pipeline"]),
    "high-risk count": f'"high_risk": {RAW["query_high_priority_deal_risk"]["summary"]["high_risk"]}',
    "team loss rate": repr(RAW["query_loss_concentration"]["team_loss_rate"]),
}


def test_the_collector_sees_the_known_disclosures():
    paths = {p for _, p, _ in DISCLOSURES}
    for must in ("query_forecast_trust.risk_basis",
                 "query_pipeline.business_definition_note",
                 "query_pipeline.zero_arr_deals.note", "query_pipeline.meeting_set_unsized.note",
                 "query_high_priority_deal_risk.basis", "query_loss_concentration.note",
                 "query_loss_concentration.ghost_deal_share.note",
                 "query_loss_concentration.stage_of_loss.administrative_stage_share.note",
                 "query_loss_concentration.period"):
        assert must in paths, must
    assert any(p.startswith("query_loss_concentration.by_rep[") for p in paths)
    assert {p for _, p, _ in EXCLUDED} == {"query_forecast_trust.note",
                                          "query_forecast_trust.calibration_evidence.note",
                                          "query_pipeline._synthesis_note"}, EXCLUDED
    print(f"✓ collector: {len(DISCLOSURES)} disclosure strings across the 4 real primitive outputs, "
          "plus the 3 left out of the verdict (the historical cohort's note and calibration evidence, "
          "query_pipeline's standalone note with the unweighted ratio)")


def _check_survival(scenario, raw=None):
    composed = _compose(scenario, raw)
    inputs = _model_inputs(composed, scenario)
    json.loads(inputs["classifier synthesis"])      # the character cut never fired
    json.loads(inputs["verify / retry"])
    missing = [(name, prim, path) for name, text in inputs.items()
               for prim, path, s in DISCLOSURES if not _present(s, text)]
    assert not missing, f"{len(missing)} disclosures dropped, e.g. {missing[:5]}"
    leaked = [(name, path) for name, text in inputs.items()
              for _, path, s in EXCLUDED if _present(s, text)]
    assert not leaked, f"left-out-of-verdict text reached the model: {leaked}"
    for label, needle in HEADLINE.items():
        for name, text in inputs.items():
            assert needle in text, (scenario, label, name)
    return composed, inputs


def test_every_disclosure_survives_the_base_composition():
    composed, inputs = _check_survival("base")
    sizes = {k: len(v) for k, v in inputs.items()}
    print(f"✓ base: all {len(DISCLOSURES)} disclosures and the 4 headline numbers reach "
          f"classifier synthesis, verify/retry and the dynamic loop, uncut ({sizes})")


def test_every_disclosure_survives_the_downside_composition():
    composed, _ = _check_survival("downside")
    assert "downside" in composed
    print(f"✓ downside: all {len(DISCLOSURES)} disclosures and the 4 headline numbers survive "
          "alongside the worst-case block")


def test_survival_holds_when_the_per_deal_lists_are_ten_times_longer():
    """The composed view must be bounded by construction, not by today's
    data volume: inflate every per-deal list tenfold and check nothing is
    cut."""
    raw = copy.deepcopy(RAW)
    raw["query_forecast_trust"]["assessed_deals"] *= 10
    raw["query_high_priority_deal_risk"]["assessed_deals"] *= 10
    raw["query_pipeline"]["deals"] *= 10
    raw["query_pipeline"]["zero_arr_deals"]["deals"] *= 10
    for scenario in qh.SCENARIOS:
        _check_survival(scenario, raw)
    print("✓ with every per-deal list 10x longer, both scenarios still arrive uncut with every "
          "disclosure")


ROW_KEYS = re.compile(r"\.(text|period|reason|scope)$")


def test_every_basis_note_is_lifted_ahead_of_the_primitives():
    """Survival today could rest on the payload happening to fit. The
    structural guarantee is that every basis note (everything but the
    per-row text lines and short labels, which stay with their rows) sits
    in disclosed_bases, serialised before `primitives`, where no tail cut
    reaches, and once only (the primitive keeps a pointer)."""
    for scenario in qh.SCENARIOS:
        c = _compose(scenario)
        keys = list(c)
        assert keys.index("disclosed_bases") < keys.index("figures") < keys.index("primitives"), keys
        lifted = {b["text"] for b in c["disclosed_bases"]}
        notes = [(p, s) for _, p, s in DISCLOSURES if not ROW_KEYS.search(p)]
        missing = [p for p, s in notes if s not in lifted]
        assert not missing, missing
        prims = json.dumps(c["primitives"])
        still_inline = [p for p, s in notes if json.dumps(s)[1:-1] in prims]
        assert not still_inline, still_inline
    print(f"✓ all {len(notes)} basis notes are lifted verbatim into disclosed_bases, ahead of figures "
          "and primitives, and not duplicated inline")


def test_unregistered_entry_point_would_drop_disclosures():
    """Why the entry points must be in STRUCTURED_HANDLERS: otherwise the
    loop reads the result through its row-aggregation view, bounded at
    8,000 chars, and disclosures fall out."""
    for scenario in qh.SCENARIOS:
        text = _loop_text(_compose(scenario), scenario, registered=False)
        missing = [p for _, p, s in DISCLOSURES if not _present(s, text)]
        assert missing, "expected the unregistered path to drop something"
    print(f"✓ unregistered, the loop's aggregated view drops disclosures ({len(missing)} in the "
          "downside case): the entry points must be registered as structured handlers")


if __name__ == "__main__":
    test_the_collector_sees_the_known_disclosures()
    test_every_disclosure_survives_the_base_composition()
    test_every_disclosure_survives_the_downside_composition()
    test_survival_holds_when_the_per_deal_lists_are_ten_times_longer()
    test_every_basis_note_is_lifted_ahead_of_the_primitives()
    test_unregistered_entry_point_would_drop_disclosures()
    print("\n✅ All tests passed")
