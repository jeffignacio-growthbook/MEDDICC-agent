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

2026-09-12 (PENDING_WORK.md Low Priority #14/#16): also resolves
New Business / Expansion / Upsell / Renewal deal-type terms — unlike
the fictional `pipeline` dimension dimension_verification.py's
load_known_dimensions() removed (no real column ever backed it), these
map to real, already-existing columns (deals.new_arr, deals.
expansion_arr — both since migration 007 — and deals.pipeline_id
against client.yaml's configured renewal_pipeline_ids), so no
migration is needed. See _deal_type_candidates()'s own docstring for
the exact mapping and why it's deliberately NOT the same definition as
api/field_semantics.py's is_renewal_base()/is_incremental_pipeline()
(a different, GRR/NRR-specific distinction). These terms are also NOT
mutually exclusive — a deal can be Renewal AND Expansion at once — see
format_dimension_resolution_note()'s handling of that.
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


def _load_renewal_pipeline_id() -> Optional[str]:
    """The renewal pipeline id, from config/client.yaml's
    pipeline.value_field.renewal_pipeline_ids — the exact same config
    path scripts/utils.py, scripts/analytics/compute_forecast.py, and
    api/handlers_renewal.py already read this from (grep confirms no
    other path is used anywhere in this repo). Only the first
    configured id is used: this client has exactly one renewal
    pipeline, and resolve_dimension_filter()'s single-eq-value shape
    has no way to express more than one anyway — the same single-value
    assumption api/handlers_renewal.py already makes
    ("Use first renewal pipeline")."""
    ids = (
        _load_yaml("config/client.yaml")
        .get("pipeline", {})
        .get("value_field", {})
        .get("renewal_pipeline_ids", []) or []
    )
    return str(ids[0]) if ids else None


# column, operator, value for each deal-type alias that maps directly
# (no live config lookup needed) — "renewal" is handled separately
# below since its value comes from client.yaml, not a fixed literal.
#
# Deliberately NOT the same definition as api/field_semantics.py's
# is_renewal_base()/is_incremental_pipeline(): those encode a stricter,
# GRR/NRR-specific distinction (renewal BASE requires renewal_revenue
# > 0 in addition to the renewal pipeline id; "pipeline"/incremental
# ARR excludes pure renewal base). This maps the plain-English TERM a
# question uses ("Expansion deals", "Renewal deals") to what it most
# naturally means for an ad-hoc question — literally "carries expansion
# ARR" and "sits in the Renewal pipeline" — not the narrower subset
# GRR/NRR math needs. Two different, deliberately separate definitions
# for two different purposes; not an inconsistency.
_DEAL_TYPE_ALIASES = {
    "new business": ("new_arr", "gt", 0),
    "new": ("new_arr", "gt", 0),
    "expansion": ("expansion_arr", "gt", 0),
    "upsell": ("expansion_arr", "gt", 0),
}

# "new" alone is far too common an English word to scan a whole
# question for opportunistically (same reasoning as the ROW region /
# Unknown segment values in _SCAN_COLLISION_DENYLIST above — "what's
# new this week" or "any new updates" must not inject a new_arr
# directive). It still resolves correctly on a deliberate, explicit
# call to resolve_dimension_filter() — this only affects the scan.
# Kept as its own set (not folded into _SCAN_COLLISION_DENYLIST, which
# is keyed by (column, value)) because "new business" and "new" both
# resolve to the exact same (column, value) pair, and denylisting that
# pair there would incorrectly also block the "new business" scan.
_SCAN_DENYLISTED_TERMS = {"new"}


def _deal_type_candidates(term: str) -> List[Dict[str, Any]]:
    """New Business / Expansion / Upsell / Renewal — see the module
    docstring and _DEAL_TYPE_ALIASES' own comment for the exact mapping
    and why it's independent from field_semantics.py's GRR/NRR
    definitions. Tagged with "category": "deal_type" so
    format_dimension_resolution_note() can add the non-mutual-
    exclusivity and historical-data-gap guidance these terms need but
    region/segment/roster terms don't."""
    norm = _normalize(term)

    if norm == "renewal":
        renewal_pipeline_id = _load_renewal_pipeline_id()
        if renewal_pipeline_id:
            return [{"column": "pipeline_id", "operator": "eq",
                      "value": renewal_pipeline_id, "category": "deal_type"}]
        return []

    if norm in _DEAL_TYPE_ALIASES:
        column, operator, value = _DEAL_TYPE_ALIASES[norm]
        return [{"column": column, "operator": operator, "value": value,
                  "category": "deal_type"}]

    return []


def _all_known_values() -> List[str]:
    values = list(_load_regions().keys())
    values += _load_segment_names()
    values += [m["name"] for m in _load_roster()]
    values += ["New Business", "Expansion", "Upsell", "Renewal"]
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
        {"column": ..., "operator": "eq" | "gt", "value": ...}
            — an unambiguous match against region, segment, roster, or
              deal-type. A deal-type match also carries
              "category": "deal_type" (see _deal_type_candidates()) so
              callers building the injected directive can add the
              non-mutual-exclusivity / historical-gap guidance those
              terms specifically need.
        {"error": "ambiguous", "candidates": [...]}
            — more than one governed value matches (e.g. "Jake" against
              both Jake Stangl and Jake H). Each candidate has the same
              shape as the success case, plus "matched_name" for roster
              matches.
        {"error": "unknown_value", "known_values": [...]}
            — the term matches nothing in any governed source.
            known_values is the full union of region/segment/roster/
            deal-type names actually configured, so a caller (or the
            model, via the injected directive) can see what IS
            available instead of being told only that this one term
            failed.
    """
    if not mentioned_term or not mentioned_term.strip():
        return {"error": "unknown_value", "known_values": _all_known_values()}

    candidates = (
        _region_candidates(mentioned_term)
        + _segment_candidates(mentioned_term)
        + _roster_candidates(mentioned_term)
        + _deal_type_candidates(mentioned_term)
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
    own docstring above. Same reasoning for _SCAN_DENYLISTED_TERMS
    (currently just "new" — too common an English word to opportunistically
    scan for, unlike "new business" as a whole phrase).

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
        if _normalize(term) in _SCAN_DENYLISTED_TERMS:
            continue
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


# The fixed date migration 064 was applied and deals_snapshot.new_arr/
# expansion_arr started being populated (see that migration's own
# data_dictionary description) — a fixed historical fact, not something
# to compute from "today", since it never moves forward with the
# calendar.
_ARR_COMPONENTS_SNAPSHOT_CUTOFF = "2026-09-11"


def format_dimension_resolution_note(resolved: List[Dict[str, Any]]) -> str:
    """Format scan_question_for_known_dimension_terms()'s output as a
    directive for the model, same pattern as SNAPSHOT ANCHORS in
    api/router.py's dynamic_query_loop — a fact handed to the model
    up front, not left for it to guess or discover the hard way.
    Returns "" when there's nothing to report (no known terms found).

    2026-09-12: deal-type terms (category == "deal_type") get two
    pieces of extra guidance region/segment/roster terms don't need:
    1. NON-MUTUAL-EXCLUSIVITY — fires only when 2+ deal-type terms are
       resolved together (e.g. "Renewal and Expansion deals"). A deal
       can independently match more than one (a renewal that also
       carries expansion ARR is BOTH), so combining them must mean
       "match ANY of them" (a union), not "match ALL of them at once"
       (an AND/intersection) — the opposite of how multiple region/
       segment terms combine (an "EMEA Enterprise" question DOES mean
       the intersection). Without this, the model would default to the
       AND pattern it already uses everywhere else and silently under-
       count.
    2. HISTORICAL DATA GAP — fires only for the new_arr/expansion_arr-
       backed terms (New Business, Expansion, Upsell — not Renewal,
       which uses pipeline_id and has no such gap). deals_snapshot only
       has these columns populated from _ARR_COMPONENTS_SNAPSHOT_CUTOFF
       forward (migration 064); a point-in-time historical question
       needing an earlier snapshot must say so honestly rather than
       reading a NULL/missing value as zero or absent. The `deals`
       table itself (current pipeline, or any closed deal by
       close_date) has no such gap — these columns exist there since
       migration 007 — and the note says so explicitly.
    """
    if not resolved:
        return ""
    lines = [
        f"- the question mentions {r['term']!r} — use "
        f"{r['column']}.{r['operator']}.{r['value']}"
        for r in resolved
    ]
    note = (
        "RESOLVED DIMENSION FILTERS (looked up against the governed "
        "region/segment/roster/deal-type config, not a guess): these "
        "terms in the question map to exact filter clauses — use them "
        "verbatim, do not re-derive or second-guess them:\n" + "\n".join(lines)
    )

    deal_type_terms = [r for r in resolved if r.get("category") == "deal_type"]
    if len(deal_type_terms) >= 2:
        note += (
            "\n\nDEAL-TYPE TERMS ARE NOT MUTUALLY EXCLUSIVE: a single "
            "deal can independently match more than one of the "
            "deal-type filters above (e.g. a renewal deal that also "
            "carries expansion ARR is BOTH Renewal and Expansion at "
            "once). Since more than one is mentioned here, query each "
            "one's condition and report the UNION — deals matching ANY "
            "of them — do NOT combine the filters into one query "
            "requiring a deal to satisfy all of them simultaneously "
            "unless the question explicitly asks for the overlap."
        )

    arr_component_terms = [r for r in deal_type_terms
                            if r["column"] in ("new_arr", "expansion_arr")]
    if arr_component_terms:
        note += (
            f"\n\nHISTORICAL DATA GAP: new_arr/expansion_arr are only "
            f"populated on deals_snapshot for snapshot dates on or "
            f"after {_ARR_COMPONENTS_SNAPSHOT_CUTOFF} — if answering "
            f"this requires a deals_snapshot row from before that date, "
            f"this breakdown is NOT available for it; say so honestly "
            f"rather than treating a missing/null value as zero or "
            f"absent. The `deals` table itself (current pipeline, or "
            f"any closed deal by close_date) is unaffected by this gap "
            f"and always has real, current values."
        )

    return note
