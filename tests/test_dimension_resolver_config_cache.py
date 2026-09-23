"""
Regression test: api/dimension_resolver.py parses each config file ONCE
per process, not once per candidate term.

Why this exists (2026-09-23): _load_yaml() opened and re-parsed the YAML
on every call. The per-term helpers (_load_regions, _load_segment_names,
_load_roster, _all_known_values) each call it, and both question scans
try every word and word-pair, so a single question re-parsed
config/client.yaml 180-420 times and config/regions.yaml 92-210 times.
That was 6.8-16.3s per question in the scans alone, and 630 of the 635
YAML parses in one full dynamic_query_loop run on Ryan's
"pipeline added in the last two weeks" question (~16s -> ~0.3s after).

What this pins:
  1. Parse count: many questions through both scans cost at most one
     yaml.safe_load per config file, total.
  2. No behavior change: the cached reader returns exactly what a fresh
     uncached parse returns, and resolve_dimension_filter() gives
     identical results under the cached and an uncached reader.
  3. Mutation safety: a caller mutating what _load_yaml() hands back can't
     corrupt the cached parse.
Each has a planted-bug control proving the check would catch the bug,
rather than passing because it's blind to it.
"""
import collections
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.disable(logging.CRITICAL)

import api.dimension_resolver as D

QUESTIONS = [
    "Tell me the amount of pipeline in $ and number of deals we've added to the pipeline in the last two weeks",
    "Which stale Enterprise deals does jake.stangl@growthbook.io own in EMEA?",
    "How does EMEA compare to AMER this quarter?",
    "What's our win rate in the Mid-Market segment this quarter?",
    "Show me our EMEA pipeline broken down by country",
    "How has James Shannon's pipeline changed this quarter?",
]
TERMS = ["EMEA", "AMER", "NAM", "Enterprise", "Mid-Market", "SMB", "Jake",
         "Scott Keller", "Germany", "renewal", "the", "Zanzibar"]
CONFIG_FILES = ["config/client.yaml", "config/regions.yaml"]


def _uncached_load_yaml(relative_path):
    """The pre-fix reader, verbatim: re-parse on every call."""
    path = D._REPO_ROOT / relative_path
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _count_parses(fn):
    """Run fn() from a cold cache; return {filename: yaml.safe_load count}."""
    D._parse_yaml_once.cache_clear()
    counts = collections.Counter()
    orig = yaml.safe_load

    def spy(stream, *a, **k):
        counts[Path(getattr(stream, "name", "?")).name] += 1
        return orig(stream, *a, **k)

    yaml.safe_load = spy
    try:
        fn()
    finally:
        yaml.safe_load = orig
    return counts


def _scan_all():
    for q in QUESTIONS:
        D.scan_question_for_known_dimension_terms(q)
        D.scan_question_for_ambiguous_dimension_terms(q)


def test_each_config_file_parsed_at_most_once_across_questions():
    counts = _count_parses(_scan_all)
    assert counts, "spy saw no parses at all: the counter is blind"
    over = {f: n for f, n in counts.items() if n > 1}
    assert not over, f"config re-parsed per term again: {dict(counts)}"
    print(f"✓ {len(QUESTIONS)} questions x 2 scans -> parses {dict(counts)}")


def test_parse_counter_catches_the_uncached_reader():
    """Planted bug: put the old per-call reader back. The same counter
    must see many parses, or test 1 proves nothing."""
    orig = D._load_yaml
    D._load_yaml = _uncached_load_yaml
    try:
        counts = _count_parses(
            lambda: D.scan_question_for_known_dimension_terms(QUESTIONS[2]))
    finally:
        D._load_yaml = orig
    assert counts["client.yaml"] > 10 and counts["regions.yaml"] > 5, dict(counts)
    print(f"✓ planted uncached reader detected: {dict(counts)} for one question")


def test_cached_reader_matches_a_fresh_parse():
    D._parse_yaml_once.cache_clear()
    for f in CONFIG_FILES:
        assert D._load_yaml(f) == _uncached_load_yaml(f), f
        assert D._load_yaml(f) == _uncached_load_yaml(f), f"{f} (warm cache)"
    assert D._load_yaml("config/does_not_exist.yaml") == {}
    print("✓ cached _load_yaml == fresh parse for every config file")


def test_resolution_identical_under_cached_and_uncached_reader():
    D._parse_yaml_once.cache_clear()
    cached = {t: D.resolve_dimension_filter(t) for t in TERMS}
    orig = D._load_yaml
    D._load_yaml = _uncached_load_yaml
    try:
        uncached = {t: D.resolve_dimension_filter(t) for t in TERMS}
    finally:
        D._load_yaml = orig
    assert cached == uncached, [t for t in TERMS if cached[t] != uncached[t]]
    statuses = collections.Counter(r.get("error") or f"resolved:{r.get('column')}"
                                   for r in cached.values())
    assert len(statuses) > 1, f"terms don't exercise distinct outcomes: {statuses}"
    print(f"✓ {len(TERMS)} terms resolve identically cached vs uncached "
          f"(outcomes: {dict(statuses)})")


def test_mutating_a_returned_config_cannot_poison_the_cache():
    D._parse_yaml_once.cache_clear()
    before = D._load_yaml("config/regions.yaml")
    handed_out = D._load_yaml("config/regions.yaml")
    handed_out.clear()
    handed_out["region_definitions"] = {"POISON": {}}
    assert D._load_yaml("config/regions.yaml") == before
    assert "EMEA" in D._load_regions()
    print("✓ caller mutation of _load_yaml's result does not reach the cache")


def test_mutation_check_catches_a_shared_cached_object():
    """Planted bug: hand out the cached object itself (no deepcopy). The
    same mutation must now corrupt later reads, or the test above is blind."""
    orig = D._load_yaml
    D._load_yaml = D._parse_yaml_once
    try:
        D._parse_yaml_once.cache_clear()
        D._load_yaml("config/regions.yaml")["region_definitions"] = {"POISON": {}}
        assert "EMEA" not in D._load_regions(), "planted shared-object bug not visible"
    finally:
        D._load_yaml = orig
        D._parse_yaml_once.cache_clear()
    assert "EMEA" in D._load_regions()
    print("✓ planted no-deepcopy bug detected (and cache restored)")


if __name__ == "__main__":
    test_each_config_file_parsed_at_most_once_across_questions()
    test_parse_counter_catches_the_uncached_reader()
    test_cached_reader_matches_a_fresh_parse()
    test_resolution_identical_under_cached_and_uncached_reader()
    test_mutating_a_returned_config_cannot_poison_the_cache()
    test_mutation_check_catches_a_shared_cached_object()
    print("\n✅ All tests passed")
