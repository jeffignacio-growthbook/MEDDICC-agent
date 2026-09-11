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

This is deliberately a naming/pattern check, not a full semantic
verifier: the goal is forcing the question to get asked for every
future primitive, not perfectly verifying the answer every time. A
detection function that doesn't match the naming patterns above (a
"resolver" that can also return an ambiguous/unknown result, for
example — `resolve_dimension_filter` wasn't caught by the scan) can
still slip past it. The retroactive audit that found tonight's three
gaps was a manual read of the code, not this test; the test is the
tripwire for the more obviously-named future case, and a periodic
manual audit is still worth doing.

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
