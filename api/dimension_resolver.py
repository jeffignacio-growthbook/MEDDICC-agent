"""
Proactive dimension-term resolution.

2026-09-11: every dimension-related bug this week — a fabricated "EMEA
isn't a tracked region," a missing region/segment filter that slipped
past synthesis — was caught REACTIVELY, after the model had already
guessed wrong and, in the fabrication case, guessed wrong out loud to
the user. dimension_verification.py's verify_dimension_coverage() is a
valuable backstop (kept, unchanged, as defense in depth), but a backstop
only catches a miss after it happens; it can't stop a model from
asserting something false about a value it never bothered to look up.

resolve_dimension_filter() answers "what column/value does this term
actually mean?" against the SAME governed sources already built for
that question elsewhere in this codebase — regions.yaml (also used by
dimension_verification.load_known_dimensions()), client.yaml's
segmentation.bands (the same bands scripts/utils.py's segment logic
uses), and client.yaml's team.members (the same roster
scripts/seed_user_personas.py seeds from) — deterministically, in
memory, with no DB or LLM call. Wired into dynamic_query_loop BEFORE the
model's first tool call (see scan_question_for_known_dimension_terms()
and its call site in api/router.py), it turns "the model guesses which
column/value a term means, sometimes wrong" into "the exact filter
clause is handed to the model as a directive it never had to guess."
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_REPO_ROOT = Path(__file__).parent.parent

# Segment/region values that collide with common English words ("row",
# "unknown"). resolve_dimension_filter() still resolves them correctly
# on a deliberate, explicit call — the ambiguity only matters for
# scan_question_for_known_dimension_terms()'s opportunistic whole-
# question scan, which skips injecting a directive for these specific
# values so an unrelated sentence ("a row of data", "status unknown")
# can't be mistaken for a dimension mention. See that function's
# docstring for why every other known value is safe to scan for
# case-insensitively (they aren't ordinary English words).
_SCAN_COLLISION_DENYLIST = {("region", "ROW"), ("segment", "Unknown")}


def _load_yaml(relative_path: str) -> dict:
    path = _REPO_ROOT / relative_path
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_regions() -> Dict[str, dict]:
    """region_code -> {"label": ..., "countries": [...]}, from
    config/regions.yaml's region_definitions — the same source
    dimension_verification.load_known_dimensions() reads."""
    return _load_yaml("config/regions.yaml").get("region_definitions", {}) or {}


def _load_segment_names() -> List[str]:
    """Segment band names, from config/client.yaml's segmentation.bands
    — the actual configured bands (SMB / Mid-Market / Enterprise /
    Unknown for this client), not a second hand-maintained copy."""
    bands = _load_yaml("config/client.yaml").get("segmentation", {}).get("bands", []) or []
    return [b["name"] for b in bands if isinstance(b, dict) and b.get("name")]


def _load_roster() -> List[Dict[str, str]]:
    """[{"name": ..., "email": ..., "role": ...}, ...] from
    config/client.yaml's team.members — the same roster
    scripts/seed_user_personas.py seeds the live user_personas table
    from. Members without both a name and an email are skipped (can't
    resolve a filter from an incomplete entry)."""
    members = _load_yaml("config/client.yaml").get("team", {}).get("members", []) or []
    return [m for m in members if isinstance(m, dict) and m.get("name") and m.get("email")]


def _normalize(term: str) -> str:
    """Case-insensitive, whitespace/hyphen/possessive-insensitive
    comparison key — 'Mid-Market', 'mid market', and 'MID-MARKET' must
    all resolve the same way, since a model or a user typing a question
    won't reliably match the config file's exact punctuation.

    2026-09-11: "Jake's deals" never fired DIMENSION_RESOLVE at all —
    not an untested ambiguous-match branch, a real coverage gap.
    scan_question_for_known_dimension_terms()'s tokenizer (by design)
    keeps apostrophes as word characters so it can extract a whole term
    in one pass, which means "Jake's" reaches this function as a single
    token, not "Jake" — and nothing stripped the possessive before
    comparing against the roster's first-name entries. Stripping a
    trailing 's or bare trailing ' here means every comparison this
    module does (region/segment/roster, in both directions) treats
    "Jake's", "Jake", and "JAKE'S" identically, without the tokenizer
    or its caller needing to know about possessives at all.
    """
    t = term.strip().lower()
    t = re.sub(r"'s$", "", t)
    t = re.sub(r"'$", "", t)
    return re.sub(r"[\s\-]+", " ", t)


def _region_candidates(term: str) -> List[Dict[str, Any]]:
    norm = _normalize(term)
    for region_code in _load_regions():
        if _normalize(region_code) == norm:
            return [{"column": "region", "operator": "eq", "value": region_code}]
    return []


def _segment_candidates(term: str) -> List[Dict[str, Any]]:
    norm = _normalize(term)
    for name in _load_segment_names():
        if _normalize(name) == norm:
            return [{"column": "segment", "operator": "eq", "value": name}]
    return []


def _roster_candidates(term: str) -> List[Dict[str, Any]]:
    """Matches a full name ('Scott Keller') or a first name ('Christian')
    against the roster. A first name shared by more than one team member
    ('Jake Stangl' and 'Jake H' both answer to 'Jake') returns one
    candidate per match, which resolve_dimension_filter() turns into an
    'ambiguous' error rather than guessing which Jake was meant."""
    norm = _normalize(term)
    matches = []
    for member in _load_roster():
        name = member["name"]
        name_norm = _normalize(name)
        first_norm = _normalize(name.split()[0]) if name.split() else ""
        if name_norm == norm or (first_norm and first_norm == norm):
            matches.append({
                "column": "owner_email", "operator": "eq", "value": member["email"],
                "matched_name": name,
            })
    return matches


def _all_known_values() -> List[str]:
    values = list(_load_regions().keys())
    values += _load_segment_names()
    values += [m["name"] for m in _load_roster()]
    return values


def resolve_dimension_filter(mentioned_term: str,
                              question_context: Optional[dict] = None) -> dict:
    """
    Resolve a term the model extracted from a question ("EMEA",
    "Enterprise", "Christian") into the exact filter clause to use,
    against the governed sources — deterministically, never by having
    the model guess which column or value it means.

    Args:
        mentioned_term: the raw term as it appeared in (or was extracted
            from) the question.
        question_context: reserved for future disambiguation (e.g.
            preferring an owner match when the question also asks about
            "deals" versus a region match when it asks about
            "pipeline") — unused today; every current ambiguity
            (same first name shared by two reps) has no additional
            context that would resolve it, so this parameter exists to
            keep the signature stable when that need arises rather than
            to do anything yet.

    Returns exactly one of:
        {"column": ..., "operator": "eq", "value": ...}
            — an unambiguous match against region, segment, or roster.
        {"error": "ambiguous", "candidates": [...]}
            — more than one governed value matches (e.g. "Jake" against
              both Jake Stangl and Jake H). Each candidate has the same
              shape as the success case, plus "matched_name" for roster
              matches.
        {"error": "unknown_value", "known_values": [...]}
            — the term matches nothing in any governed source.
            known_values is the full union of region/segment/roster
            names actually configured, so a caller (or the model, via
            the injected directive) can see what IS available instead
            of being told only that this one term failed.
    """
    if not mentioned_term or not mentioned_term.strip():
        return {"error": "unknown_value", "known_values": _all_known_values()}

    candidates = (
        _region_candidates(mentioned_term)
        + _segment_candidates(mentioned_term)
        + _roster_candidates(mentioned_term)
    )

    if len(candidates) == 1:
        result = dict(candidates[0])
        result.pop("matched_name", None)
        return result

    if len(candidates) > 1:
        return {"error": "ambiguous", "candidates": candidates}

    return {"error": "unknown_value", "known_values": _all_known_values()}


def scan_question_for_known_dimension_terms(question: str) -> List[Dict[str, Any]]:
    """
    Try resolving every plausible term or two-word phrase in `question`
    against the governed sources, keeping only the ones that resolve to
    an unambiguous filter. Over-inclusive by design: resolving a term is
    an in-memory config lookup, not a DB or LLM call, so trying every
    word/word-pair in a question and keeping only real hits costs
    nothing and can't miss a real region/segment/rep mention to an
    imperfect "does this look like a dimension term" heuristic.

    Ambiguous terms (a shared first name) are deliberately NOT injected
    as a directive here — telling the model "use owner_email=eq.X" when
    X is a guess between two reps would just relocate the guess from
    the model to this function. They're silently skipped; if the
    question's own wording doesn't disambiguate, the model still has to
    ask or pick a reasonable default, same as it does for any other
    genuine ambiguity. A value in _SCAN_COLLISION_DENYLIST (a governed
    value that also happens to be an ordinary English word, like the
    "ROW" region or "Unknown" segment) is also skipped here, so a
    sentence merely containing "row" or "unknown" doesn't inject a
    dimension directive that was never intended — see the denylist's
    own docstring above.

    Returns: [{"term": "EMEA", "column": "region", "operator": "eq",
               "value": "EMEA"}, ...], deduplicated by (column, value)
    so a term mentioned twice only produces one directive.
    """
    words = re.findall(r"[A-Za-z][A-Za-z\-']*", question or "")
    candidate_terms = set(words)
    for i in range(len(words) - 1):
        candidate_terms.add(f"{words[i]} {words[i + 1]}")

    resolved = []
    seen_keys = set()
    for term in sorted(candidate_terms):
        result = resolve_dimension_filter(term, question_context={"question": question})
        if "error" in result:
            continue
        key = (result["column"], result["value"])
        if key in _SCAN_COLLISION_DENYLIST or key in seen_keys:
            continue
        seen_keys.add(key)
        resolved.append({"term": term, **result})
    return resolved


def scan_question_for_ambiguous_dimension_terms(question: str) -> List[Dict[str, Any]]:
    """
    Companion to scan_question_for_known_dimension_terms(): finds terms
    in `question` that match MORE THAN ONE governed value (e.g. "Jake"
    matching both Jake Stangl and Jake H) instead of silently discarding
    them.

    2026-09-11: "Jake's deals" never fired DIMENSION_RESOLVE at all,
    for two stacked reasons. First, the possessive form never reached
    the roster comparison as bare "Jake" (see _normalize()'s docstring
    for that fix). Second, even once it does, an ambiguous match used
    to be dropped by scan_question_for_known_dimension_terms() with no
    trace anywhere — not logged, not surfaced to the model, nothing.
    That left the model with zero signal that "Jake" was a name it
    needed to be careful about, and nothing stopped it from silently
    picking one Jake (or inventing an owner_email outright) with the
    same unearned confidence this whole resolver exists to prevent.
    This surfaces the ambiguity itself as a directive instead: the
    model is told exactly which candidates matched and must say so or
    ask, rather than guessing.

    Returns: [{"term": "Jake's", "candidates": [...]}, ...],
    deduplicated by the sorted set of candidate values so the same
    ambiguous person mentioned twice only produces one entry.
    """
    words = re.findall(r"[A-Za-z][A-Za-z\-']*", question or "")
    candidate_terms = set(words)
    for i in range(len(words) - 1):
        candidate_terms.add(f"{words[i]} {words[i + 1]}")

    ambiguous = []
    seen_keys = set()
    for term in sorted(candidate_terms):
        result = resolve_dimension_filter(term, question_context={"question": question})
        if result.get("error") != "ambiguous":
            continue
        key = tuple(sorted(c["value"] for c in result["candidates"]))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        ambiguous.append({"term": term, "candidates": result["candidates"]})
    return ambiguous


def format_ambiguous_dimension_note(ambiguous: List[Dict[str, Any]]) -> str:
    """Format scan_question_for_ambiguous_dimension_terms()'s output as
    a directive telling the model NOT to guess — same "hand it a fact,
    don't make it guess" pattern as format_dimension_resolution_note(),
    but for the case where the fact is "this term doesn't resolve to
    exactly one value." Returns "" when nothing is ambiguous."""
    if not ambiguous:
        return ""
    lines = []
    for a in ambiguous:
        names = ", ".join(
            c.get("matched_name") or c["value"] for c in a["candidates"]
        )
        lines.append(
            f"- {a['term']!r} matches more than one person on the roster "
            f"({names}) — do not guess which one"
        )
    return (
        "AMBIGUOUS TERMS (matched more than one governed value — do NOT "
        "silently pick one): if the question doesn't disambiguate some "
        'other way, say so explicitly in your answer (e.g. "there are '
        'two reps named Jake — did you mean Jake Stangl or Jake H?") '
        "rather than guessing:\n" + "\n".join(lines)
    )


def format_dimension_resolution_note(resolved: List[Dict[str, Any]]) -> str:
    """Format scan_question_for_known_dimension_terms()'s output as a
    directive for the model, same pattern as SNAPSHOT ANCHORS in
    api/router.py's dynamic_query_loop — a fact handed to the model
    up front, not left for it to guess or discover the hard way.
    Returns "" when there's nothing to report (no known terms found)."""
    if not resolved:
        return ""
    lines = [
        f"- the question mentions {r['term']!r} — use "
        f"{r['column']}.{r['operator']}.{r['value']}"
        for r in resolved
    ]
    return (
        "RESOLVED DIMENSION FILTERS (looked up against the governed "
        "region/segment/roster config, not a guess): these terms in the "
        "question map to exact filter clauses — use them verbatim, do "
        "not re-derive or second-guess them:\n" + "\n".join(lines)
    )
