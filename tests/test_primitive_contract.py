"""
2026-09-11: the standing contract every detection primitive in
dynamic_query_loop must satisfy, enforced structurally rather than left
as a convention someone has to remember.

Tonight's own history is the reason this exists: verify_aggregation_
completeness()'s mismatch was correctly detected and then shipped
wrong TWICE, live, before anyone noticed the retry message never
actually corrected anything. verify_snapshot_date_labeling() and the
ambiguous-dimension-term check had the SAME defect (detect, log, ship
anyway) sitting unnoticed until this same session's retroactive audit
found them. Three different primitives, one root cause: "the check
fires correctly" was being treated as "the check is done," with no
structural gate forcing anyone to ask whether the failure it detects
is actually queryable and actually visible to the user.

See PRIMITIVE_CHECKLIST.md for the full checklist. This test enforces
the two questions it asks, exactly like the existing structural gates
in this suite (test_date_resolution_single_source.py's "no bare
date.today()" scan, test_loop_ceiling_sizing.py's "no budget/token
language" scan) — a naming/pattern convention check, not deep semantic
analysis. The goal is forcing the question to get asked for every
future primitive, not perfectly verifying the answer every time.
"""
import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import api.router as router

REPO_ROOT = Path(__file__).parent.parent
API_DIR = REPO_ROOT / "api"

# Every cost_state["primitives_fired"] key representing a "detection
# primitive" per PRIMITIVE_CHECKLIST.md's definition — a check that can
# find the answer wanting, as opposed to a primitive that only marks a
# mechanism having run. Hand-curated (not auto-derived from naming,
# which is too fuzzy to trust for classification) but every key in it
# is checked structurally below. See api/router.py's own
# FAILURE_MODE_PRIMITIVES for the authoritative, in-code copy this test
# imports directly rather than re-declaring — a second hand-maintained
# list here could drift from what the code actually contains.
FAILURE_MODE_PRIMITIVES = router.FAILURE_MODE_PRIMITIVES

# Detection-style function names already reviewed against the
# checklist as of this fix (2026-09-11). A NEW function matching the
# naming patterns below and not in this set fails the test — forcing
# whoever added it to consciously answer PRIMITIVE_CHECKLIST.md's two
# questions and extend this allowlist (and, if it's a real correctness
# check, api/router.py's FAILURE_MODE_PRIMITIVES) rather than shipping
# a new checker with silent detection and no enforced consequence.
KNOWN_DETECTION_FUNCTIONS = {
    # dynamic_query_loop's own primitives — see FAILURE_MODE_PRIMITIVES
    # above for how each satisfies the contract via query_cost_log.
    "verify_aggregation_completeness",
    "verify_dimension_coverage",
    "verify_snapshot_date_labeling",
    "scan_question_for_ambiguous_dimension_terms",
    "_looks_like_unfinished_scratchpad",
    # check_dimension_filtered: an internal helper INSIDE verify_
    # dimension_coverage (dimension_verification.py) — not an
    # independent primitive; covered by that function's own review.
    "check_dimension_filtered",
    # api/plausibility.py's 5 checks: found by this test's scan, but
    # pre-existing and NOT wired into dynamic_query_loop — they run
    # inside route_question()'s separate precomputed-handler synthesis
    # path, which query_cost_log's contract doesn't cover (a
    # pre-existing scope boundary, not something this fix expanded).
    # Reviewed on discovery and found to already satisfy the SAME
    # checklist, just via a different mechanism than cost_state/
    # query_cost_log: a critical violation replaces the answer outright
    # (should_block=True -> block_message, with a real
    # plausibility_violations field on the return value) and a
    # non-critical one is injected into tool_results["_plausibility_
    # warnings"], which route_question's own synthesis prompt
    # explicitly instructs the model to include in its answer. Never
    # the "detect, log, ship anyway" anti-pattern this fix retires.
    "check_metric_registry_divergence",
    "check_negative_counts",
    "check_rate_bounds",
    "check_subset_relationships",
    "check_sum_consistency",
}

# Naming patterns a "detection-style" function is likely to match.
# Deliberately a naming/pattern convention, not semantic analysis — see
# this file's module docstring and PRIMITIVE_CHECKLIST.md for why that
# tradeoff is intentional. Known limitation: a detection function named
# without one of these markers (e.g. a "resolver" that can also return
# an ambiguous/unknown result, like resolve_dimension_filter) won't be
# caught by this scan — the retroactive manual audit this session did
# is what actually found tonight's three gaps, this test is the
# tripwire for the more obviously-named future case.
_DETECTION_NAME_RE = re.compile(
    r'^(?:async\s+)?def\s+('
    r'verify_\w+|\w+_verify|'
    r'\w+_check|check_\w+|'
    r'resolve_\w*ambiguous\w*|scan_\w*ambiguous\w*|'
    r'\w*unfinished_scratchpad\w*|\w*_ambiguity\w*'
    r')\s*\(',
    re.MULTILINE,
)

# The exact anti-pattern this whole fix retires: detect, log, ship
# anyway. If this string ever reappears anywhere in api/, that's a
# regression to the pre-fix shape for the exact three primitives this
# session found it in.
_BANNED_LOG_ONLY_COMMENT = "Don't block the answer, just log for monitoring"


def _scan_detection_functions():
    """{function_name: filename} for every function across api/*.py
    matching a detection-style naming pattern."""
    found = {}
    for path in sorted(API_DIR.glob("*.py")):
        text = path.read_text()
        for m in _DETECTION_NAME_RE.finditer(text):
            found[m.group(1)] = path.name
    return found


def test_no_new_unreviewed_detection_functions():
    found = _scan_detection_functions()
    unreviewed = sorted(set(found) - KNOWN_DETECTION_FUNCTIONS)
    assert not unreviewed, (
        f"New detection-style function(s) found with no entry in this "
        f"test's KNOWN_DETECTION_FUNCTIONS allowlist: "
        f"{[(name, found[name]) for name in unreviewed]}. Before "
        f"considering it complete, answer PRIMITIVE_CHECKLIST.md's two "
        f"questions: (a) does its failure mode write to a queryable "
        f"outcome field (or reason_tag), not just a log line or a "
        f"JSONB blob? (b) does its failure mode ever change what the "
        f"user sees? If either is 'only in the log', it's not done. "
        f"Once it is, add it to this allowlist (and, if it's a real "
        f"correctness check with an unresolved-failure path, to "
        f"api/router.py's FAILURE_MODE_PRIMITIVES)."
    )
    print(f"✓ no unreviewed detection-style functions "
          f"({len(found)} known, all accounted for)")


def test_known_detection_functions_are_still_present():
    """Sanity check on the allowlist itself: every name in it must
    still exist somewhere in api/ — catches the allowlist going stale
    after a rename/removal rather than silently over-approving."""
    found = _scan_detection_functions()
    missing = sorted(KNOWN_DETECTION_FUNCTIONS - set(found))
    assert not missing, (
        f"KNOWN_DETECTION_FUNCTIONS names no longer found by the scan "
        f"(renamed or removed?): {missing}"
    )
    print("✓ every allowlisted detection function still exists")


# ══════════════════════════════════════════════════════════════════════
# Secondary, coarser scan: flagged log tags (2026-09-11)
# ══════════════════════════════════════════════════════════════════════
# The name-based scan above has a confirmed, not hypothetical, blind
# spot: the zero-rows suspicion note (api/router.py's dynamic_query_
# loop) detected a real problem, logged it, and shipped the answer
# unresolved anyway — the exact anti-pattern this whole file exists to
# catch — and sat there unreviewed because it's inline code with no
# function name for _DETECTION_NAME_RE to match. It was only found by
# someone asking about it directly and manually re-walking the
# checklist.
#
# This is a second net cast wider on purpose: this codebase's own
# established convention is a bracketed [TAG] at the start of every
# logger.info/warning/error message (grep any file in api/ — it's
# everywhere). Rather than trying to name-match inline code (there's no
# name to match), flag any such tagged log call whose MESSAGE TEXT
# (never the tag itself, which often encodes an unrelated domain noun
# like "STALE_DEALS" the handler/table name) contains a keyword that
# suggests it might be reporting a discovered problem. Far noisier than
# the function-name scan by design: KNOWN_FLAGGED_LOG_TAGS below keeps
# a real, deliberately-preserved false positive ([ENTITY_SCOPE]'s
# staleness check, a self-correcting cache-TTL mechanism, not a
# shipped-unresolved failure) rather than tuning the keyword list to
# avoid it — tuning away one false positive risks tuning away the next
# real gap, which is exactly how the zero-rows suspicion note went
# unreviewed for as long as it did.
_FLAGGED_LOG_KEYWORDS = (
    "suspicion", "gap", "missing", "zero row", "zero-row", "defaulted",
    "ambigu", "stale", "inconsistent", "mismatch", "drift", "uncertain",
)

# Matches logger.info/warning/error(f"[TAG] message text" [f"more text"]*)
# — handles this codebase's common style of an f-string message split
# across several adjacent, implicitly-concatenated string literals.
# Group 1 is the bracketed tag; group 2 is everything after it, up to
# the call's closing quote — the text this scan's keyword check runs
# against (the tag itself is excluded deliberately, see above).
_LOG_TAG_CALL_RE = re.compile(
    r'logger\.(?:info|warning|error)\(\s*f?"(\[[A-Z][A-Z0-9_]*\])'
    r'((?:[^"]*"\s*\n?\s*f?")*[^"]*)"',
    re.MULTILINE,
)

# Every bracketed log TAG this scan currently finds, reviewed against
# PRIMITIVE_CHECKLIST.md's two questions. A NEW tag not listed here
# fails the test until someone reads the surrounding code and adds an
# entry with the verdict — "false positive, here's why" is a complete,
# valid entry; it does not have to mean a fix is needed.
KNOWN_FLAGGED_LOG_TAGS = {
    # Real gap, found and fixed 2026-09-11 — see PRIMITIVE_CHECKLIST.md's
    # "Follow-up audit". Now has a compliance check and its own outcome
    # bucket (zero_rows_suspicion_unresolved /
    # answered_with_unresolved_zero_row_suspicion).
    "[SUSPICION]",
    # False positive: a cache-freshness/TTL check (prior-turn entities
    # older than 30 minutes force rediscovery) — not a detection
    # primitive under this checklist's own definition, since it
    # self-corrects immediately and deterministically (returns False,
    # forcing a fresh lookup) rather than ever shipping a stale answer.
    # Matched only because "stale" is in its own vocabulary, not
    # because it exhibits "detect, log, ship anyway".
    "[ENTITY_SCOPE]",
    # The proactive nudge firing (ambiguous_dimension_term_flagged) —
    # not a discovered failure, the same category PRIMITIVE_CHECKLIST.md
    # already excludes by design ("What counts as a detection
    # primitive"). The compliance check on whether it was ADDRESSED is
    # the separate [SYNTHESIS_VERIFY] tag, reviewed below.
    "[DIMENSION_RESOLVE]",
    # Shared log line several already-compliant checks emit from
    # (aggregation mismatch, snapshot-date-labeling, ambiguous-
    # dimension, zero-rows-suspicion) — not one primitive, a tag
    # several reviewed primitives happen to share.
    "[SYNTHESIS_VERIFY]",
    # MANDATORY GATE: forces a retry with an explicit required query
    # before an answer ever ships — the forced iteration IS the visible
    # consequence; there is no unresolved-and-shipped path here at all.
    "[DIMENSION_VERIFY]",
    # forced_anchor_fetch_fired / finalize's own scratchpad handling —
    # reviewed primitives from the original retroactive audit
    # (queryable, self-corrects or escalates to _give_up).
    "[FINALIZE]",
    # diff_company_name_backfill_fired — reviewed: logs a real gap it
    # then backfills or reports, never a silent ship.
    "[SNAPSHOT_DIFF]",
    # snapshot_anchor_injected's blocking path — forces the loop to
    # fetch the missing anchor before proceeding; the block IS the
    # consequence, not a silent log.
    "[ENRICHMENT_LOOKUP]",
}


def _scan_flagged_log_tags():
    """{tag: filename} for every bracketed-tag logger call across
    api/*.py whose MESSAGE text (not the tag) contains a keyword
    suggesting it might report a discovered problem, rather than
    ordinary status/progress logging."""
    found = {}
    for path in sorted(API_DIR.glob("*.py")):
        text = path.read_text()
        for m in _LOG_TAG_CALL_RE.finditer(text):
            tag, msg = m.group(1), m.group(2)
            if any(k in msg.lower() for k in _FLAGGED_LOG_KEYWORDS):
                found[tag] = path.name
    return found


def test_no_new_unreviewed_flagged_log_tags():
    found = _scan_flagged_log_tags()
    unreviewed = sorted(set(found) - KNOWN_FLAGGED_LOG_TAGS)
    assert not unreviewed, (
        f"New log tag(s) with message text suggesting a discovered "
        f"problem, not yet reviewed against PRIMITIVE_CHECKLIST.md: "
        f"{[(tag, found[tag]) for tag in unreviewed]}. This is the "
        f"coarse, inline-code-aware companion to test_no_new_unreviewed_"
        f"detection_functions — deliberately noisier (false positives "
        f"are expected and fine), added because the zero-rows suspicion "
        f"note sat unreviewed for exactly this reason: no function name "
        f"for the precise scan to match. Read the surrounding code,  "
        f"answer the checklist's two questions, then add the tag to "
        f"KNOWN_FLAGGED_LOG_TAGS with a one-line verdict — 'false "
        f"positive, here's why' is a complete, valid entry."
    )
    print(f"✓ no unreviewed flagged log tags ({len(found)} known, all accounted for)")


def test_known_flagged_log_tags_are_still_present():
    """Sanity check on the allowlist itself, same reasoning as
    test_known_detection_functions_are_still_present."""
    found = _scan_flagged_log_tags()
    missing = sorted(KNOWN_FLAGGED_LOG_TAGS - set(found))
    assert not missing, (
        f"KNOWN_FLAGGED_LOG_TAGS tags no longer found by the scan "
        f"(renamed, removed, or reworded past the keyword list?): {missing}"
    )
    print("✓ every allowlisted flagged log tag still exists")


def test_every_failure_mode_primitive_is_referenced_in_outcome_computation():
    """The first half of the contract: a detection primitive's failure
    signal must be a real, queryable field — referenced directly inside
    _compute_query_cost_outcome(), never left as something only
    discoverable by reading primitives_fired's JSONB blob by hand."""
    outcome_source = inspect.getsource(router._compute_query_cost_outcome)
    not_referenced = [
        key for key in sorted(FAILURE_MODE_PRIMITIVES)
        if key not in outcome_source
    ]
    assert not not_referenced, (
        f"FAILURE_MODE_PRIMITIVES entries not referenced anywhere in "
        f"_compute_query_cost_outcome()'s source, so their failure is "
        f"only visible in primitives_fired's JSONB, not the coarse "
        f"outcome field: {not_referenced}. See PRIMITIVE_CHECKLIST.md."
    )
    print(f"✓ all {len(FAILURE_MODE_PRIMITIVES)} failure-mode primitives "
          f"are referenced in _compute_query_cost_outcome()")


def test_every_failure_mode_primitive_is_actually_set_somewhere():
    """Sanity check: every primitive in the registry must actually be
    SET to True somewhere in router.py — catches a stale registry entry
    for a primitive that was renamed or removed at its call site but
    left behind in FAILURE_MODE_PRIMITIVES."""
    router_source = Path(router.__file__).read_text()
    not_set = [
        key for key in sorted(FAILURE_MODE_PRIMITIVES)
        if f'"primitives_fired"]["{key}"] = True' not in router_source
    ]
    assert not not_set, (
        f"FAILURE_MODE_PRIMITIVES entries never actually set to True "
        f"anywhere in api/router.py — stale registry entries: {not_set}"
    )
    print("✓ every failure-mode primitive is actually set somewhere in router.py")


def test_the_log_only_anti_pattern_never_reappears():
    """The exact anti-pattern this whole fix retires: detect, log a
    warning, ship the answer unchanged anyway. This string is the
    literal comment that sat next to all three primitives this session
    found and fixed — if it reappears anywhere in api/, something
    regressed to the pre-fix shape."""
    offenders = []
    for path in sorted(API_DIR.glob("*.py")):
        if _BANNED_LOG_ONLY_COMMENT in path.read_text():
            offenders.append(path.name)
    assert not offenders, (
        f"Found the retired 'detect but never act' anti-pattern comment "
        f"in: {offenders}. Every detection primitive's failure must "
        f"either self-correct via a retry, or leave a caveat/give-up "
        f"the user actually sees — see PRIMITIVE_CHECKLIST.md."
    )
    print("✓ the retired log-only anti-pattern comment does not reappear anywhere")


if __name__ == "__main__":
    tests = [
        test_no_new_unreviewed_detection_functions,
        test_known_detection_functions_are_still_present,
        test_no_new_unreviewed_flagged_log_tags,
        test_known_flagged_log_tags_are_still_present,
        test_every_failure_mode_primitive_is_referenced_in_outcome_computation,
        test_every_failure_mode_primitive_is_actually_set_somewhere,
        test_the_log_only_anti_pattern_never_reappears,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"✗ {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\n✅ All {len(tests)} tests passed")
