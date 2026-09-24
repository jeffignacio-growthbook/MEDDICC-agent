#!/usr/bin/env python3
"""
Pipeline routing: query_pipeline / query_waterfall / query_pipeline_movement
claim disjoint wording in the dynamic loop's real tool list.

These three bypass the classifier (unified routing), so the loop's model
picks among them from DYNAMIC_SYSTEM_PROMPT alone. Until 2026-09-24
query_waterfall claimed "what is our pipeline", "show me pipeline" and "how
did pipeline change", overlapping both neighbours. Live, "what does our
pipeline look like this quarter?" went to query_pipeline and "how has
pipeline moved this quarter?" went to query_waterfall.

The split:
  query_pipeline           bare "pipeline" (the default), all active / total,
                           incl. Meeting Set, by stage / rep, coverage
  query_waterfall          qualified pipeline this quarter, waterfall,
                           new / won / lost by week
  query_pipeline_movement  moved / movement / changed / entered / exited

This test reads the tool list the model actually gets. It cannot show what
the model picks: scripts/eval_dynamic_routing.py does that against the real
model for every example phrase checked here.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.router as router  # noqa: E402

THREE = ("query_pipeline", "query_waterfall", "query_pipeline_movement")
UNIFIED = THREE + ("query_stale_deals", "query_rep_pipeline", "query_win_loss", "query_deals_at_risk")

# phrase -> the tool that must own it (and appear as one of its examples)
EXPECTED = {
    "what is our pipeline": "query_pipeline",
    "show me pipeline": "query_pipeline",
    "how much pipeline do we have": "query_pipeline",
    "total pipeline by stage": "query_pipeline",
    "all active pipeline including Meeting Set": "query_pipeline",
    "pipeline by rep": "query_pipeline",
    "what's our pipeline coverage": "query_pipeline",
    "what's our qualified pipeline this quarter": "query_waterfall",
    "show me the pipeline waterfall": "query_waterfall",
    "new, won and lost pipeline by week": "query_waterfall",
    "qualified pipeline for Q3": "query_waterfall",
    "how has pipeline moved this quarter": "query_pipeline_movement",
    "how did pipeline change this month": "query_pipeline_movement",
    "what entered or exited pipeline this quarter": "query_pipeline_movement",
    "which deals moved to Technical Evaluation": "query_pipeline_movement",
}

MOVEMENT_WORDS = re.compile(r"\b(mov(e|ed|ement)|chang(e|ed|es)|enter(ed)?|exit(ed)?)\b", re.I)


def tool_entries(prompt=None):
    """tool name -> its entry text in the dynamic loop's tool list."""
    prompt = prompt or router.DYNAMIC_SYSTEM_PROMPT
    heads = list(re.finditer(r"^  (\w+)\(", prompt, re.M))
    return {m.group(1): prompt[m.start():(heads[i + 1].start() if i + 1 < len(heads) else len(prompt))]
            for i, m in enumerate(heads)}


def claimed_phrases(entry):
    """Quoted phrases a tool claims: its USE THIS bullets and its Examples.
    Never its DO NOT lines (the phrases it hands to other tools), Params or
    RETURNS."""
    out, section = [], None
    for line in entry.splitlines():
        if "USE THIS" in line:
            section = "use"
        elif "Examples:" in line:
            section = "examples"
        elif re.search(r"DO NOT|Params:|RETURNS|DEFAULT|Phrasing patterns", line):
            section = None
        if section:
            out.extend(p.strip().lower() for p in re.findall(r'"([^"]+)"', line))
    return out


def _owners(entries):
    owners = {}
    for tool in UNIFIED:
        for p in claimed_phrases(entries[tool]):
            owners.setdefault(p, set()).add(tool)
    return owners


def test_each_example_phrase_is_claimed_by_exactly_its_tool():
    entries = tool_entries()
    owners = _owners(entries)
    for phrase, tool in EXPECTED.items():
        assert owners.get(phrase.lower()) == {tool}, (phrase, owners.get(phrase.lower()))
    print(f"✓ all {len(EXPECTED)} split phrases are claimed by exactly their tool in the real tool list")


def test_no_phrase_is_claimed_by_two_unified_tools():
    shared = {p: sorted(t) for p, t in _owners(tool_entries()).items() if len(t) > 1}
    assert not shared, shared
    print("✓ no quoted phrase is claimed by two unified-routing tools")


def test_bare_pipeline_defaults_to_query_pipeline_and_movement_words_only_to_movement():
    entries = tool_entries()
    assert "DEFAULT for a bare \"pipeline\" question" in entries["query_pipeline"]
    for tool in ("query_pipeline", "query_waterfall"):
        leaks = [p for p in claimed_phrases(entries[tool]) if MOVEMENT_WORDS.search(p)]
        assert not leaks, (tool, leaks)
    assert not any(p.strip() in {"what is our pipeline", "show me pipeline", "how much pipeline"}
                   for p in claimed_phrases(entries["query_waterfall"]))
    print("✓ query_pipeline is the stated default for bare 'pipeline'; neither it nor "
          "query_waterfall claims moved/changed/entered/exited wording")


if __name__ == "__main__":
    test_each_example_phrase_is_claimed_by_exactly_its_tool()
    test_no_phrase_is_claimed_by_two_unified_tools()
    test_bare_pipeline_defaults_to_query_pipeline_and_movement_words_only_to_movement()
    print("\n✅ All tests passed")
