# Primitive Checklist

**Purpose:** a standing contract every "detection primitive" in this
codebase must satisfy, enforced by `tests/test_primitive_contract.py` —
not just a convention someone has to remember.

## Why this exists

On 2026-09-11, `verify_aggregation_completeness()` correctly detected a
bad total in a live answer, logged it, and shipped the wrong number
anyway — twice, on two different questions, hours apart. The retry
message it built even *named the correct value*, but only told the
model to "recheck your aggregation," inviting it to recompute its own
already-wrong math instead of using the number it had already been
handed.

Once that got fixed, the same session went back and found the *exact
same shape of gap* already sitting in two other checks that had been
built earlier the same night: `verify_snapshot_date_labeling()` and the
ambiguous-dimension-term flag both detected a real problem, logged a
warning, and then shipped the answer completely unchanged — the code
next to them said so explicitly: `# Don't block the answer, just log
for monitoring`. Three primitives, one root cause: "the check fires
correctly" was being treated as "the check is done."

A detection primitive that only logs is not a safety mechanism. It is
a monitoring signal nobody is monitoring, discovered later — usually by
someone grepping logs after a live incident, exactly the multi-hour
investigation gaps this same session spent hardening against.

## What counts as a "detection primitive"

Anything that checks the correctness or completeness of an answer and
can find it wanting: aggregation totals, scratchpad narration,
snapshot-date labeling, dimension-term ambiguity, snapshot-anchor
absence, plausibility violations, and any future one.

This is **not** the same as a primitive that just marks a *mechanism*
having run — `snapshot_anchor_injected`, `dimension_resolver_matched`,
`enrichment_shortcut_fired`, `snapshot_diff_computed`,
`ambiguous_dimension_term_flagged` (the proactive nudge firing, not a
discovered failure) — those don't need a caveat because nothing went
wrong yet. The checklist applies once a check has actually found a
problem.

## The checklist

Before considering a new detection primitive complete, answer both
questions honestly:

1. **Does its failure mode write to a queryable outcome field, not
   just a log line or a JSONB blob?**
   In this codebase that means: the primitive's name is referenced
   directly inside `api/router.py`'s `_compute_query_cost_outcome()` —
   either as its own distinct outcome bucket (preferred — see
   `answered_with_unverified_aggregation`,
   `answered_with_unverified_date_labeling`,
   `answered_with_unaddressed_ambiguity`) or, if the failure already
   routes through `_give_up()`, via a **distinct `reason_tag`** you
   invent for it (see `finalize_synthesis_scratchpad`) rather than
   reusing whatever ambient reason_tag happened to be in scope. Either
   way: a real, flat `query_cost_log` column, filterable directly —
   never something that only shows up if someone reads
   `primitives_fired`'s JSONB by hand.

2. **Does its failure mode ever change what the user sees, or only
   what an engineer sees later?**
   If the check's own retry/correction resolves the problem before
   shipping (the model used the corrected value, stopped narrating,
   named the ambiguous candidate), nothing further is owed — the
   answer isn't wrong anymore. But if it ships *unresolved*, the user
   must see something different than they would have otherwise: a
   plain-language caveat appended to the answer (see the aggregation,
   date-labeling, and ambiguity fixes), or an honest `_give_up()`
   instead of a plausible-looking wrong answer (see the finalize
   scratchpad fix) — never internal jargon (no "resynthesis",
   "budget", "token", "primitive" in anything user-facing).

**If either answer is "only in the log," it's not done.**

## Registry

`api/router.py`'s `FAILURE_MODE_PRIMITIVES` frozenset is the
authoritative, in-code list of every `dynamic_query_loop` primitive
this contract applies to. Adding a new one means adding its key there
— that's what forces the two questions above to actually get asked,
because `tests/test_primitive_contract.py` checks every entry in it
against `_compute_query_cost_outcome()`'s source and confirms it's
actually set somewhere in the file.

## The CI gate

`tests/test_primitive_contract.py`, same style as the existing
structural gates in this suite (`test_date_resolution_single_source.py`'s
"no bare `date.today()`" scan, `test_loop_ceiling_sizing.py`'s "no
budget/token language" scan) — a naming/pattern convention check, not
deep semantic analysis. It asserts:

1. Every function across `api/*.py` matching a detection-style naming
   pattern (`verify_*`, `*_verify`, `*_check`, `check_*`,
   `resolve_*ambiguous*`, `scan_*ambiguous*`, `*unfinished_scratchpad*`,
   `*_ambiguity*`) is in a reviewed allowlist (`KNOWN_DETECTION_
   FUNCTIONS`) — a brand new one fails the test until someone
   consciously reviews it against the checklist above and adds it.
2. Every entry in `FAILURE_MODE_PRIMITIVES` is referenced inside
   `_compute_query_cost_outcome()`'s source (queryable, not JSONB-only).
3. Every entry in `FAILURE_MODE_PRIMITIVES` is actually set to `True`
   somewhere in `router.py` (no stale registry entries).
4. The literal retired anti-pattern comment — `"Don't block the
   answer, just log for monitoring"` — never reappears anywhere in
   `api/`. If it does, something regressed to the exact pre-fix shape.
5. **Secondary, coarser scan (added 2026-09-11):** every bracketed
   `[TAG]` on a `logger.info`/`warning`/`error` call across `api/*.py`
   — this codebase's own established logging convention — whose
   *message text* (never the tag itself, which often just encodes an
   unrelated domain noun) contains a keyword suggesting it might report
   a discovered problem (`suspicion`, `gap`, `missing`, `zero row`,
   `defaulted`, `ambigu`, `stale`, `inconsistent`, `mismatch`, `drift`,
   `uncertain`) must be in a reviewed allowlist (`KNOWN_FLAGGED_LOG_
   TAGS`). This exists because item 1's naming scan has a confirmed —
   not hypothetical — blind spot: the zero-rows suspicion note detected
   a real problem, logged it, and shipped the answer unresolved anyway,
   sitting unreviewed because it's inline code inside `dynamic_query_
   loop`'s body with no function name to match. Deliberately noisier by
   design: `KNOWN_FLAGGED_LOG_TAGS` keeps a real false positive
   (`[ENTITY_SCOPE]`'s staleness check, a self-correcting cache-TTL
   mechanism, not a shipped-unresolved failure) rather than tuning the
   keyword list to avoid it — tuning away one false positive risks
   tuning away the next real gap the same way.

This is deliberately a naming/pattern check (both the function-name
scan and the log-tag scan), not a full semantic verifier: the goal is
forcing the question to get asked for every future primitive, not
perfectly verifying the answer every time. The retroactive audit that
found the original three gaps, and the follow-up that found the
zero-rows suspicion gap, were both manual reads of the code, not this
test — the two scans are tripwires for the more obviously-named or
obviously-worded future case, and a periodic manual audit is still
worth doing. Even with both scans, a detection primitive with neither a
matching function name NOR a keyword-matching log message (e.g. a
`resolver` that can silently return an ambiguous/unknown result and
never logs at all, like `resolve_dimension_filter`) can still slip past
both — that specific case was still only found by manual review.

## Scope note: `route_question`'s precomputed-handler path

`api/plausibility.py`'s five checks (`check_rate_bounds`,
`check_subset_relationships`, `check_sum_consistency`,
`check_negative_counts`, `check_metric_registry_divergence`) run
inside `route_question()`'s separate precomputed-handler synthesis
path, not `dynamic_query_loop` — `query_cost_log`'s contract doesn't
cover that path at all (a pre-existing scope boundary, not something
this fix expanded). They were reviewed on discovery by this same audit
and found to already satisfy the checklist above via their own
mechanism: a critical violation replaces the answer outright
(`should_block=True` → `block_message`, with a real
`plausibility_violations` field on the return value) and a
non-critical one is injected into `tool_results["_plausibility_
warnings"]`, which that path's own synthesis prompt explicitly
instructs the model to include in its answer. Neither is the "detect,
log, ship anyway" anti-pattern this checklist exists to prevent — they
were allowlisted in `tests/test_primitive_contract.py`, not exempted
from review.

## Retroactive audit (2026-09-11)

Every primitive built or touched this session, checked against the
list above:

| Primitive | Queryable? | User-visible on unresolved failure? | Status |
|---|---|---|---|
| `aggregation_mismatch_caught` / `aggregation_mismatch_unresolved_after_retry` | ✅ own outcome bucket | ✅ caveat when still wrong after retry | **Fixed** (the original incident) |
| `false_partial_claim_caught` | ✅ `answered_after_resynthesis` bucket | ✅ retry hands the model the real dimension counts; self-corrects or escalates | Passed |
| `scratchpad_rejection_fired` | ✅ `answered_after_resynthesis` bucket | ✅ self-corrects or escalates to `_give_up` (already both queryable and visible) | Passed |
| `verify_snapshot_date_labeling` (`snapshot_date_labeling_unverified`) | ❌ → ✅ own outcome bucket | ❌ → ✅ caveat appended | **Fixed** (found log-only, same shape as the original incident) |
| ambiguous dimension term (`ambiguous_dimension_unaddressed`) | ❌ → ✅ own outcome bucket | ❌ → ✅ compliance check added; caveat naming candidates when the model silently picks one | **Fixed** (detection existed, compliance verification didn't) |
| `_finalize_from_data`'s own synthesis scratchpad leakage (`finalize_scratchpad_caught`) | ❌ → ✅ distinct `reason_tag` | ❌ → ✅ honest `_give_up` instead of shipping leaked reasoning | **Fixed** (no check existed on finalize's own output at all) |
| `api/plausibility.py`'s 5 checks | ✅ (own mechanism, different path) | ✅ (own mechanism, different path) | Passed (different execution path — see scope note above) |

Three genuine gaps found and fixed, all in one pass, following exactly
the pattern proven on the original aggregation-verification incident.

## Reusable Primitives (2026-09-15)

### Placement-Plausibility Check

**Location:** `api/placement_verification.py` → `verify_corrected_value_placement()`

**Purpose:** Two-signal corruption check for any primitive that hands a
corrected value to the model for resynthesis:

- **SIGNAL 1:** Corrected value appears MULTIPLE times in retry answer
  (definite corruption — if the answer has both "Company X: $6.89M" AND
  "Total: $6.89M", the company line is the corruption)
- **SIGNAL 2:** Corrected value appears ONCE, but in suspicious context
  (next to an entity name rather than a summary/total line — implausible
  for one item to equal the aggregate)

**Extracted from:** `api/aggregation_verification.py`'s
`verify_total_placement()` (2026-09-14), which now wraps this reusable
version. The check was originally built to protect aggregation
verification from the Creative CX-style corruption (a $6.89M total for
354 deals attached to a single company), but the underlying mechanism —
"did the model splice this value into the wrong location?" — applies to
ANY corrected value handed to the model, not just aggregation totals.

**Available to:** Any primitive that forces resynthesis with a corrected
value. Examples:
- Aggregation totals (current use)
- Dimension filters (if a corrective filter is handed to the model)
- Snapshot anchors (if corrected dates are handed to the model)
- Any future primitive with the same shape

**Call signature:**
```python
from api.placement_verification import verify_corrected_value_placement

result = verify_corrected_value_placement(
    retry_answer_text=answer_after_forced_resynthesis,
    corrected_value=12345.67,  # The value you handed to the model
    row_count=354,  # Number of underlying items (for error message context)
    tolerance=0.5,  # Numeric comparison threshold
    entity_type="deal"  # What kind of items ("deal", "company", "row", etc.)
)

if not result["placement_ok"]:
    # Misplacement detected
    logger.error(f"Placement corruption: {result['likely_corruption']}")
    # Either force honest fallback or escalate to _give_up()
```

**Returns:**
- `{"placement_ok": True}` if no misplacement detected
- `{"placement_ok": False, "suspect_value": X, "likely_corruption": "..."}` if misplacement detected

**Not a detection primitive itself:** This is a reusable verification
tool, not a primitive that gets registered in `FAILURE_MODE_PRIMITIVES`.
The primitives that CALL it (like `aggregation_placement_corruption` in
`api/router.py`) are what get registered and must satisfy the checklist
above.

### Structured Aggregation Verification (2026-09-16)

**Location:** `api/structured_verification.py` → `verify_structured_aggregations()`

**Purpose:** Deterministic verification of structured handler outputs
against underlying raw data. Complements the existing prose-extraction
verification (`api/aggregation_verification.py`) which works on
model-generated text in `dynamic_query_loop`.

**Integration point:** Dedicated handlers (e.g., `query_pipeline`) call
this BEFORE their return statement. If verification fails, handler
returns error dict instead of corrupted data — honest failure better
than silent wrong answer.

**What it verifies:**
- **Simple aggregations:** total_pipeline (sum), total_deals (count)
- **Group-by aggregations:** by_stage, by_owner (with optional top-N limit)
- **Float precision:** Uses tolerance (default 0.01 = 1 cent) for comparison

**Verification spec format:**
```python
{
    "total_pipeline": {
        "type": "sum",
        "field": "_incremental_value",
        "expected": 20082320.68
    },
    "total_deals": {
        "type": "count",
        "expected": 313
    },
    "by_stage": {
        "type": "group_by",
        "group_field": "_stage_label",
        "aggregations": {"count": "count", "value": "sum:_incremental_value"},
        "expected": {"Discovery": {"count": 50, "value": 5000000}, ...}
    },
    "by_owner": {
        "type": "group_by",
        "group_field": "_owner",
        "aggregations": {"count": "count", "value": "sum:_incremental_value"},
        "expected": {"rep1@example.com": {"count": 30, "value": 3000000}, ...},
        "limit": 10  # Optional top-N
    }
}
```

**Call signature:**
```python
from api.structured_verification import verify_structured_aggregations

verification_result = verify_structured_aggregations(
    underlying_data=incremental_deals,  # Raw deals list with fields
    structured_output={
        "total_pipeline": 20082320.68,
        "total_deals": 313,
        "by_stage": {...},
        "by_owner": {...}
    },
    verification_spec={...},  # See format above
    tolerance=0.01  # Float comparison tolerance
)

if not verification_result["match"]:
    logger.error(f"[STRUCTURED_VERIFY] Aggregation verification failed: "
                 f"{verification_result['discrepancies']}")
    return {
        "error": "aggregation_verification_failed",
        "discrepancies": verification_result["discrepancies"],
        "note": "Aggregation outputs did not match recomputed values..."
    }
```

**Returns:**
- `{"match": True}` if all verifications pass
- `{"match": False, "discrepancies": [...]}` if mismatches found

**Checklist answers:**

1. **Queryable outcome field?** ✅ YES
   - Handler returns `{"error": "aggregation_verification_failed", ...}`
   - Router's evaluator marks as "error" result_quality
   - Logged as `[STRUCTURED_VERIFY]` prefix for monitoring
   - Fails honestly instead of shipping corrupted data

2. **User-visible on unresolved failure?** ✅ YES
   - Handler returns error dict with plain-language note (no internal jargon)
   - Router synthesis receives the error, generates honest "can't answer" response
   - User sees "I don't have data to answer that yet" (router's error handling)
   - NOT a silent wrong answer — verification prevents corrupted data from shipping

**Failure mode: Hard error vs. caveated partial answer**

DELIBERATE DESIGN TRADEOFF (2026-09-16): Verification failure returns a
hard error (no data shown) rather than a caveated partial answer. This is
the safe, honest default — if aggregations don't match recomputed values,
something is genuinely wrong (handler bug, edge case tolerance doesn't
cover, etc.), and shipping ANY data risks the same "plausible-looking
wrong answer" corruption this whole primitive was built to prevent.

**Why hard error is the right default:**
- A wrong total that looks right is worse than "can't answer"
- Verification failure indicates a REAL BUG, not just uncertainty
- Forces the bug to surface immediately (logs + user report) rather than
  silently shipping
- Same principle as aggregation_placement_corruption: escalate to
  `_give_up()` instead of shipping the corrupted retry

**Worth revisiting per-handler in Phase 1b:**
Different handlers may have different failure-mode preferences. Examples:
- `query_pipeline`: Hard error appropriate (core numbers must be right)
- `query_at_risk`: Maybe caveat is better? ("Showing deals, but counts
  may be incomplete — one stage's aggregation looked off")
- `query_win_loss`: Hard error (win rates/conversion critical)

Not a universal answer — document the tradeoff per handler as Phase 1b
spreads this pattern. For now: fail hard and safe is the documented,
deliberate choice, not an implicit one.

**Why this is NOT in FAILURE_MODE_PRIMITIVES:**
This is a handler-level verification gate, not a `dynamic_query_loop`
primitive. It prevents corrupted outputs before they reach synthesis,
rather than catching prose extraction errors during synthesis. The
checklist still applies (queryable + user-visible), but registration is
through handler error returns rather than router outcome tracking.

**Test coverage:**
`tests/test_structured_aggregation_verification.py` proves the trap springs:
- Planted wrong total_pipeline (100K discrepancy) → caught
- Planted missing stage in by_stage → caught
- Planted wrong stage value → caught
- Correct aggregations → no false alarm
- Float tolerance (0.01) → working as designed
- Top-N limit (by_owner top 10) → respected

**First integration:** `api/handlers.py` → `query_pipeline()` (Phase 1a+, 2026-09-16)

## Follow-up audit (2026-09-11, same night)

A fourth gap surfaced answering a direct question about a different
mechanism entirely (the zero-rows suspicion note, asked about
separately from this audit) — this table is the reason it got checked
against the same two questions rather than taken on faith as "obviously
fine because it's advisory."

| Primitive | Queryable? | User-visible on unresolved failure? | Status |
|---|---|---|---|
| zero-rows suspicion (`zero_rows_suspicion_unresolved`) | ❌ → ✅ own outcome bucket (`answered_with_unresolved_zero_row_suspicion`) | ❌ → ✅ compliance check added; caveat when the answer asserts absence with no acknowledgment the filter may be defaulted | **Fixed** (detection + advisory note existed since before this session; compliance verification didn't — same "detect, log, ship anyway" shape as the three found earlier, just never scanned because it's inline code, not a named function `test_primitive_contract.py` can match) |

Found by manually re-reading the code against the checklist, not by the
structural scan — confirms the scan's own documented limitation
("a detection function that doesn't match the naming patterns... can
still slip past it"). `zero_rows_suspicion_flagged` (the note firing at
all, mirroring `ambiguous_dimension_term_flagged`) is deliberately NOT
in `FAILURE_MODE_PRIMITIVES` — it just marks the mechanism having run,
not a discovered-and-shipped problem; only
`zero_rows_suspicion_unresolved` is registered.
