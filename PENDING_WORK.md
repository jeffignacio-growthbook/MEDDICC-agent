# Pending Work

**Last Updated:** 2026-09-12 (Low Priority #17 fixed — a live "what's our current New Business pipeline" question shipped 11 Upcoming Renewal/Renewal Engaged deals under a "New Business Pipeline" heading with no caveat; confirmed structurally (via the response's unique query_pipeline()-only shape) that tonight's new deal-type resolver (#16) was NOT involved — dedicated handlers never reach it, only dynamic_query_loop does; root cause was query_pipeline()'s own pipeline_filter exclusion logic, unchanged since the handler's first commit (b75a3c1, 2026-09-06): `"renewal" in pipeline_id.lower()` can never match, since pipeline_id is always the raw numeric id ("default"/"866608541") and never contains the word "renewal" — so pipeline_filter="new_business" silently excluded nothing (the live symptom) and pipeline_filter="renewal" silently excluded everything (the previously-undiscovered opposite-direction failure, always returning zero); fixed with an exact-value comparison against field_semantics._RENEWAL_PIPELINE_ID, the same constant is_incremental_pipeline() already trusts two lines above in the same function; also extended the handler's [QUERY_PIPELINE_FILTER] log line to actually log stage_filter/pipeline_filter, which had never been logged at all and was itself a real gap hit while investigating this; verified via new tests/test_query_pipeline_pipeline_filter_bug.py (4 tests, confirmed to actually fail against the pre-fix code via git stash before confirming the fix passes); full suite (37 files) passes. Low Priority #16 fixed — wired a REAL New Business/Expansion/Upsell/Renewal deal-type mapping into `resolve_dimension_filter()` (api/dimension_resolver.py), the same proactive-resolution pattern already proven for region/segment/roster, using data that already exists (deals.new_arr/expansion_arr since migration 007, deals.pipeline_id against client.yaml's configured renewal pipeline) — no migration needed, unlike #15's still-open materialized-column follow-up; explicitly NOT the same definition as field_semantics.py's GRR/NRR-specific is_renewal_base()/is_incremental_pipeline() (documented inline to avoid the appearance of a contradiction); handles two nuances explicitly rather than leaving them implicit — deal-type terms are NOT mutually exclusive (a renewal deal can also carry expansion ARR), so format_dimension_resolution_note() now injects a union-not-intersection directive whenever 2+ deal-type terms are mentioned together (the opposite of how region+segment combine); and deals_snapshot.new_arr/expansion_arr are only populated from migration 064's 2026-09-11 rollout forward, so a second directive honestly flags that gap for a pre-cutoff historical question rather than reading a missing value as zero, while `deals` itself (current pipeline/closed deals) is unaffected; deliberately scoped to proactive resolution only, not dimension_verification.py's reactive backstop, since that gate's required-query builder is hardcoded eq-only and doesn't fit a gt-on-a-different-column mapping — a real, separate refactor if ever needed; verified via new tests/test_deal_type_dimension_resolver.py (14 tests: 11 unit-level plus 3 end-to-end driving the real dynamic_query_loop against the exact 3 example questions from the ask — current New Business pipeline, win rate on Expansion deals, combined Renewal+Expansion — each confirmed to resolve the correct filter and ship a real answer, with Renewal+Expansion confirmed to query as two separate calls, never ANDed together); full suite (36 files) passes. Added Low Priority #15 — scoped, NOT started: adding a real, materialized `deal_type` column (`deals`/`deals_snapshot`) so "New Business ARR" questions become genuinely, safely filterable instead of either falsely-verified (the #14 bug) or honestly-unanswerable (#14's fix). Explicitly deferred per instruction — the mandatory prerequisite is confirming the real determining logic with Jeff first (2-way New Business/Expansion via `renewal_revenue`, or a genuinely 4-way New Business/Renewal/Upsell/Cross-Sell split needing a different HubSpot signal entirely — don't assume, same discipline as the Incremental ARR formula clarification before migration 064), plus whether to backfill `deals_snapshot` given deal type likely doesn't drift post-creation unlike region/segment/ARR. Standing lesson from #13 attached: register in `data_dictionary` in the same migration, confirm applied to production before shipping dependent code. No code written yet. Low Priority #14 fixed — while confirming the #12 fix against a real Slack question, found that the `pipeline` dimension `dimension_verification.py` was "verifying" (New Business/Renewal/Upsell/Cross-Sell) was never backed by a real column in any table — confirmed via every migration touching deals/deals_snapshot/waterfall_weekly plus `scripts/discover_properties.py`'s own comment that deal_type "don't exist in Supabase deals table"; `api/tools.py`'s `filter_table()` silently drops a filter on any unregistered column rather than erroring, so a "corrective" `pipeline='New Business'` filter was silently discarded before reaching Postgres while `queries_run` (and thus verification) recorded it as applied — a false-positive "verified" state that shipped a confidently wrong-scoped answer (an all-deal-types "Sales Pipeline" total mislabeled as "New business") with no warning at all; this bug predates the #12 fix and would have caused the same silent mis-scoping at any of the original 5 sites, but #12 made the symptom worse for the finalization path specifically (previously an honest warning when it couldn't retry; now a false-positive "successful" retry with no warning); fixed by removing the fictional `pipeline` entry from `known_dimensions` outright (documented as a deliberate gap — no real column can back it even in principle, since the actual New Business vs. Expansion signal comes from `renewal_revenue` null/0 vs >0, a 2-way split not expressible as a single eq filter) and adding a general structural safeguard so `check_dimension_filtered()` cross-checks a claimed filter's column against the table's actual registered-queryable columns (threaded `sb` through all 7 real call sites) before ever trusting it — closing the general mechanism for any future dimension, not just this one; `tests/test_dimension_verify_finalize_retry.py`'s two #12 tests ported from the removed `pipeline` dimension to the real `region` dimension, plus 3 new tests (pipeline confirmed removed; unregistered-column filter never falsely verifies; registered-column filter still verifies normally); full suite (33 files) + both standalone root-level scripts with the old 3-arg signature still pass. Low Priority #12 root-caused and fixed — the dimension-verification dead-end. Confirmed via exact-string match that `format_verification_error()` has exactly one call site in `api/router.py`: the finalization path inside `_finalize_from_data()`, whose own log line claimed "Cannot retry (budget exhausted)" unconditionally, but `_finalize_from_data()` is actually invoked from 10 different reason_tags and only `iterations_exhausted` genuinely means the budget ran out — the other 9 (including `no_progress`, the one that reproduced the live "New Business" incident) can fire with plenty of budget left, so the gate was giving up unconditionally on a false premise; fixed by forcing `verify_dimension_coverage()`'s deterministic `required_query` directly (same "force one corrective fetch" pattern already used for the missing-snapshot-anchor and diff-company-name-backfill cases in this same function) before ever giving up — a successful forced fetch + resynthesis now ships a real, corrected answer, and only if that still fails does the loop give up, with an explicit, complete message stating both the original diagnostic AND that an automatic retry was attempted and failed, never a bare warning with nothing after it; reproduced the exact original scenario as a new fixture (`tests/test_dimension_verify_finalize_retry.py`, 2 tests: forced-fetch-succeeds ships the corrected answer, forced-fetch-fails ships the honest complete message) and confirmed both; full suite (33 files) green locally. Previous entry, retained for history: Low Priority #13 fixed and logged as a standing process gap — migration `064` was written and pushed in the same commit as code that depended on it, but was never actually applied to the live database (this repo's migrations require manual application via `setup_supabase.py` or the SQL Editor, no auto-apply on push); the gap was caught only because `weekly-snapshot.yml` was manually triggered to verify the fix, and that live run failed for real — `postgrest.exceptions.APIError: Could not find the 'expansion_arr' column`, writing ZERO snapshot rows that day since Postgres rejects a whole upsert batch on an unknown column; would have recurred on the real Monday 02:00 UTC scheduled run had it not been caught first; audited `weekly-analytics.yml`/`recompute-forecast.yml` and confirmed neither had actually run during the vulnerable window, so nothing else broke; resolved once the migration was applied directly via the SQL Editor — re-triggered `weekly-snapshot.yml`, 443 rows written, `new_arr` populated on 373/443 and `expansion_arr` on 368/443 with real captured values (e.g. a genuine $200,000 Expansion ARR on a live renewal deal) confirming the recompute genuinely works in production; standing rule logged going forward: any migration a commit's code depends on must be confirmed applied to production BEFORE that commit's dependent code ships, not after; added Low Priority #12 — a dimension-verification `⚠️ Verification failed... Required query...` warning observed live while testing the historical ARR questions dead-ended without forcing the retry it's supposed to trigger; not reproduced or root-caused in this session, explicitly logged separately from #9/#10/#11 since it's unrelated to the schema fix that surfaced it; a same-night code read of all 5 `verify_dimension_coverage()` call sites in `api/router.py` found 4 correctly force a retry and 1 (the finalization path) deliberately doesn't by design — open question is whether the observed dead end hit that legitimate no-retry path or a genuinely different, unwired check, needs the actual failing question/transcript to resolve; Low Priority #11 fully closed — migration `064_add_arr_components_to_snapshot.sql` adds `new_arr`/`expansion_arr` to `deals_snapshot` (nullable, NOT backfilled — historical rows genuinely don't have this data and stay NULL, per the region/segment point-in-time lesson) with `data_dictionary` registration in the SAME migration (per the region/segment registration-gap lesson); `snapshot_deals.py` populates both going forward; `compute_forecast.py`'s Site 2 now recomputes Incremental ARR from the new columns when present, falling back per-deal to `deal_value` (still null-propagated) for legacy rows or genuinely-blank components; confirmed via migration 045's own documented rationale that `renewal_revenue` is deliberately, correctly left unpopulated (an earlier investigation concluded `deal_value` already includes it for renewal deals) and left it completely untouched despite surfacing in the same investigation; added two new eval scripts (`eval_compute_forecast_arr_recompute.py`, `eval_snapshot_deals_arr_fields.py`) giving `compute_forecast.py` and `snapshot_deals.py` their first-ever real end-to-end test coverage — both files previously had zero automated tests anywhere in the repo, confirmed via grep, a gap this fix closes as a side effect; Low Priority #9 fully closed — all 4 items fixed, each its own standalone commit, each verified against a live CI re-run in sequence (runs #61-#64 on `claude/dazzling-brown-rxeaje`): the `query_rep_pipeline` `NameError` (a real live production bug — every call to this handler crashed since `b75a3c1`, unrelated to CI), the `eval_fallback_message.py` stale mock, the `slack_sdk` dependency gap (investigated and confirmed genuinely used by a real, wired `run-calibration.yml` workflow — added the dependency rather than deleting anything), and `_honest_miss()`'s `TypeError` — which on inspection turned out to hide a second, deeper issue: fixing just the type mismatch didn't make the eval pass, because `_honest_miss()`'s real message never stated the facts its own sibling `_result_summary()` computes and was docstring'd as being "for the honest-miss message" but was only ever wired into an internal log line; shipped as a deliberate user-facing behavior change (`_honest_miss()` now threads `_result_summary(tool_results)` into what the user actually sees), with before/after message text and a new dedicated test (`tests/test_honest_miss_includes_facts.py`); `TEST 0` came back fully green in live CI (run #64) for the first time all night; that same run immediately surfaced a new, separate, real metric-logic bug in `TEST 0b` (forecast correctness — the renewal pipeline's conversion denominator isn't scoped independently from the default pipeline) — logged fresh as Low Priority #10, explicitly NOT fixed tonight since it's real business logic deserving unhurried investigation, not a stale mock or dead import; added Low Priority #8 — confirming the URGENT safety fix worked via a live CI re-run surfaced a genuinely pre-existing, unrelated finding: `eval_handler_descriptions.py` has been failing on 5 undocumented handler-adjacent functions (`compute_cycle_time`, `compute_at_risk_deals`, `canonical_stage`, `load_scope_config`, `is_deal_in_analytics_scope`) to `scripts/eval_handler_descriptions.py`'s `KNOWN_NON_HANDLERS` exclusion set rather than writing them fake handler descriptions, since `HANDLER_DESCRIPTIONS` is the live routing classifier's own menu and a real entry for any of these would let it get dispatched a live question with the wrong call signature; verified 35/35 handlers now match locally; running `TEST 0`'s full eval sequence to verify this surfaced 4 more independent, pre-existing, unrelated bugs further down the same script sequence — see new Low Priority #9 — so `TEST 0` is not expected to be fully green yet even after this fix; added Low Priority #8 — confirming the URGENT safety fix worked via a live CI re-run surfaced a genuinely pre-existing, unrelated finding: `eval_handler_descriptions.py` has been failing on 5 undocumented handler-adjacent functions since `b75a3c1` (2026-09-06), invisible until now only because the `ClientOptions` crash blocked CI before it ever reached that check; not urgent, not caused by tonight's work, confirmed via `git blame`; 🚨 URGENT SAFETY FIX: a live CI run of `gate-tests.yml` failed twice, identically, with `ImportError: cannot import name 'ClientOptions' from 'supabase' (unknown location)` at `api/db.py`'s import — added earlier the same night for the Supabase retry-transport fix — killing every downstream test; since Railway's deploy process plausibly does a similarly fresh install, this risked crashing the live app on its next deploy. Fixed by moving the `ClientOptions` import inside `create_resilient_supabase_client()`'s own try block (`scripts/supabase_client.py`), lazy not top-level, so any import-time failure degrades to a plain client with no retry protection instead of crashing — see `tests/test_supabase_client_fallback.py` (forces the exact failure and confirms a working client still comes back) and new High Priority #4 for the not-yet-root-caused "why does GitHub's runner resolve this differently" investigation, explicitly not blocking on it; shipped `resolve_execution_cost_estimate()` (`api/router.py`) — a pre-execution cost estimate for `dynamic_query_loop`, calibrated against 13 real `query_cost_log` rows pulled via `scripts/query_cost_log_calibration.sql`, warning on an expensive-looking question before running anything; every estimate self-reports low confidence given the tiny calibration sample, tracked as Low Priority #7 for recalibration once more traffic accumulates; also fixed a `.github/workflows/gate-tests.yml` naming collision from an earlier round tonight — two unrelated CI steps were both labeled "TEST 1b"; closed the loop on High Priority #2's open question: confirmed the RemoteProtocolError/ConnectionTerminated connection bug is NOT the explanation for the original Jake Stangl incident — the incident's own captured evidence was a completed request/response, structurally incompatible with a connection that died mid-stream, and no code path exists where that error could silently become an empty result. Status unchanged (MITIGATED, NOT ROOT-CAUSED) and now explicitly deprioritized — not actively being chased, re-open only if it recurs; added Low Priority #6, a known unclosed blind spot in `PRIMITIVE_CHECKLIST.md`'s two structural scans — a resolver-style function that returns ambiguous/unknown with no log call at all on that path, like `resolve_dimension_filter`, is invisible to both the function-name scan and the bracketed-log-tag scan added the same night; closing it needs a bigger lift, either a logging convention or real control-flow static analysis, not scoped or started; fixed a 4th detection-primitive gap found the same night, same file: the zero-rows suspicion note in `dynamic_query_loop` detected a suspicious enumeration-question zero-row result and logged an advisory note, but never verified the model acted on it before shipping — added a compliance check + its own outcome bucket (`answered_with_unresolved_zero_row_suspicion`), registered in `FAILURE_MODE_PRIMITIVES`, see `PRIMITIVE_CHECKLIST.md`'s "Follow-up audit" section; also fixed an unrelated stale test found along the way — `tests/test_zero_rows_suspicion.py`'s 3rd test had been failing since 2026-09-06 checking the wrong location for missing-value prompt guidance that was deliberately relocated to `api/router.py`'s `DYNAMIC_SYSTEM_PROMPT`, not lost; also fixed the recurring Supabase `httpx.RemoteProtocolError: ConnectionTerminated` connection issue found via a live test session — a long-lived singleton client hitting a known httpx/HTTP2 gotcha, fixed with a retry-once transport, see `scripts/supabase_client.py`'s `_RetryOnDeadConnectionTransport`; added `PRIMITIVE_CHECKLIST.md` — a standing, CI-enforced contract every detection primitive must satisfy, retroactively applied to fix 3 primitives found log-only with the same "detect but never act" gap the original aggregation-verification incident had; added High Priority #3, a follow-up audit of every other dedicated handler for the same owner-email exact-match risk found in query_pipeline_movement — defensive logging shipped everywhere, deeper canonicalization fix still pending per-handler; added High Priority #2, a query_pipeline_movement zero-row bug for an SDR that is MITIGATED but NOT root-caused — two hypotheses hardened, two more ruled out, the actual trigger still unconfirmed; added Low Priority #5, a confirmed-inert `synthesis_aggregation_fix.py` at the repo root that should be deleted or marked historical; ⚠️ see High Priority #0, a committed DB credential needs rotation)
**Purpose:** Single tracking mechanism for all documented-but-not-implemented work

---

## ✅ Recently Completed

### Region + Segment Waterfall Segmentation (2026-09-08)
**Status:** ✅ PRODUCTION VERIFIED (with one caveat - see below)

**Completed Work:**
- [x] Schema changes: Added region and segment columns to waterfall_weekly
- [x] Updated primary key to (week_ending, pipeline_id, region, segment)
- [x] Created compute_waterfall_segmented.py with region/segment grouping
- [x] Applied is_test_deal() hygiene filter (1 test deal filtered)
- [x] Registered both columns in data_dictionary as queryable
- [x] Full historical backfill: 56 weeks (2025-08-11 to 2026-09-08), gap closed
- [x] Added synthesis prompt instruction for question-substitution flagging
- [x] **Production deployment:** Updated weekly-analytics workflow to call segmented script
- [x] **Manual workflow trigger:** Confirmed working in production (run 34272039649)
- [x] **Gap closure:** Backfilled missing Aug 24/28 weeks (38 additional rows)

**Production Verification Results:**
- **Fix 1 (Workflow):** ✅ Manually triggered, waterfall step succeeded, Sep 8 data generated
- **Fix 2 (Data):** ✅ 56 weeks complete, no gaps (Aug 2025 → Sep 2026), EMEA 2-week comparison working
- **Fix 3 (Honesty):** ⚠️ **Deployed but not production-tested** - instruction in place but hasn't fired against incomplete data yet

**Fix 3 Caveat:**
The "absence of data ≠ zero movement" refusal behavior is correctly written and deployed in `api/router.py`, but unverified against a real trigger since the gap it was built for is now closed. The next time any comparison period has incomplete data (new region, newly-added segment, future sync gap), that's the real test. Worth checking then rather than assuming it works because the instruction reads correctly.

**When to verify Fix 3:**
- New region added to classification (no historical waterfall data yet)
- New segment introduced mid-stream (Unknown → classified retroactively)
- Future snapshot/waterfall sync gap (missed cron, infrastructure issue)
- Check: Does synthesis refuse to present movement metrics, or does it present "$0 net change" with caveat?

**Results:**
- 56 weeks of segmented history (2025-08-11 to 2026-09-08)
- Region distribution: NAM 218, EMEA 175, APAC 165, LATAM 145, UNKNOWN 128, ROW 103
- Segment distribution: SMB 292, Enterprise 232, Mid-Market 228, Unknown 182
- EMEA 2-week comparison: $4.35M (Aug 24) → $4.21M (Sep 8) = -$144K (-3.3%)
- Aug 24/28 gap closed: 19 rows each (all regions × segments)

**Commits:**
- b4f1765 (initial segmentation)
- 6aee7ae (synthesis pattern)
- 763c537 (production deployment fix)
- 6136438 (verification documentation)

**Documentation:**
- REGION_WATERFALL_GAP.md (original gap diagnosis)
- REGION_DATA_DICTIONARY_FIX.md (data dictionary registration)
- WATERFALL_SEGMENTATION_COMPLETE.md (initial completion proof)
- WATERFALL_PRODUCTION_VERIFIED.md (production verification proof)

---

### Test Data Hygiene (2026-09-08)
**Status:** ✅ COMPLETE

- [x] Implement `is_test_deal()` function (commit b8f63eb)
- [x] Wire into `filter_table()` for automatic exclusion (commit fd2c29e)
- [x] Test patterns: "Test"/"Test Org", "-test", "test-", " test", "teste"
- [x] Legitimate companies excluded: TestGorilla, User Testing Inc, Testbirds

**Coverage:** 11 test deals (0.58% of database) now auto-excluded from all dynamic_query results

**Documentation:** TEST_DATA_HYGIENE_RULE.md

---

## 🚧 In Progress

None currently.

---

## ✅ Recently Completed (Continued)

### aggregate_results Empty Data Bug (2026-09-09)
**Status:** ✅ COMPLETE - Implemented and verified

**Issue:** LLM passes empty array instead of step reference, causing 66.7% failure rate on aggregate_results calls

**Completed work:**
- [x] Root cause analysis (prompt ambiguity: "list OR step reference")
- [x] Pattern verification (only aggregate_results affected, no other tools)
- [x] User impact verification (Sept 6 answer: $110K Q3 expansion - CORRECT despite bug)
- [x] Three-layer fix implemented:
  1. Prompt fix: Remove ambiguity, force step references (api/router.py:1120-1140)
  2. Validation fix: Reject empty data, invalid refs, missing columns (api/tools.py:156-171)
  3. Logging fix: Warn on resolution failures (api/router.py:2070-2118)
- [x] Test suite: 13/13 validation tests passing
- [x] Commits: a121c62

**Impact assessment:**
- Sept 6 query verified: Answer was accurate ($110K actual = $110K delivered)
- Sept 9 query: Budget exhaustion (visible symptom, not silent failure)
- No real user harm, but 66.7% failure rate unacceptable
- **Verdict: LOW impact (verified), but HIGH priority fix (silent failure mode)**

**Documentation:**
- AGGREGATE_RESULTS_BUG_REPORT.md (full investigation)
- AGGREGATE_RESULTS_FIX_IMPLEMENTATION.md (implementation guide)
- SEPT6_SILENT_FAILURE_IMPACT.md (verified LOW impact)
- FALLBACK_BUDGET_ERROR_ANALYSIS.md (original investigation)
- test_aggregate_results_validation.py (13/13 passing)

**Monitoring:** Watch fallback_log for 7 days to confirm 0% failure rate post-fix

---

### Synthesis Aggregation Gap (2026-09-09)
**Status:** ✅ COMPLETE - Implemented, tested, and verified

**Issue:** Synthesis anchoring on subset instead of aggregating all retrieved rows, causing:
1. Missing week: Aug 28 $120K activity dropped when recent weeks show $0
2. Missing segment: SMB -$100K dropped from Aug 28 breakdown
3. False claims: "partial week" invented when all 4 segments present

**Completed work:**
- [x] Root cause analysis: Synthesis under-representing retrieved data
- [x] Fix 1 (b830d2d): Added explicit aggregation instruction
- [x] Fix 2 (0bdd0a5): Strengthened zero vs missing distinction
- [x] Test suite: Created test_synthesis_fix.py (10/10 verification checks)
- [x] Live testing: Verified against known failure case
- [x] Post-generation verification: Detects false "partial/pending" claims

**Test results (live query "How has EMEA pipeline moved in the last 2 weeks"):**
- ✅ Week-by-week breakdown (no anchoring on recent)
- ✅ All activities reported ($20K won + $100K lost)
- ✅ Correct net calculation (-$120K)
- ✅ No false "partial week" or "pending" claims
- ⚠️  Segment names implicit (by value, not label) - stylistic difference, data complete

**Impact assessment:**
- Original bug: Dropped $100K SMB loss (data loss)
- After fix: Both activities reported, no false claims
- **Verdict: Core bug FIXED, minor stylistic difference acceptable**

**Documentation:**
- SYNTHESIS_FIX_TEST_RESULTS.md (comprehensive test report)
- test_results_analysis.md (detailed analysis)
- reconcile_new_emea_answer.py (regression detection)
- check_sep7_data.py (verified Sep 7 completeness)
- test_synthesis_fix.py (verification logic)
- test_live_synthesis_fix.py (live test runner)
- synthesis_aggregation_fix.py (fix specification)

**Commits:**
- b830d2d (initial aggregation fix)
- 0bdd0a5 (strengthened zero vs missing instruction)

**Monitoring:** Watch production for 7 days to confirm:
1. No false "partial/pending" claims (verification layer will log)
2. Segment name omission not causing user confusion
3. Week aggregation working across all time-range queries

**⚠️ CAVEAT ADDED 2026-09-10:** The date-resolution audit below found that
"the last 2 weeks" in this test's own query resolved to roughly a 30-day
window (Aug 17 – Sep 8), not 14 days, because the classifier's time_window
schema had no field for the day count. The synthesis-completeness fix
above is still correct — synthesis DID faithfully report everything that
came back — but "everything that came back" was itself the wrong period
for "the last 2 weeks." The -$120K figure and the Aug 17/Aug 24/Aug 28/Sep 7
week list should be re-verified now that the date-resolution fix is
deployed, against a genuinely 14-day window, before being cited again as
a settled number.

---

### Budget Exhaustion on Snapshot-Diff Questions (2026-09-11)
**Status:** ✅ COMPLETE - Round-trip eliminated, shortcut generalized, new CI gate added

**Issue:** With the date/snapshot-anchor fixes from 2026-09-10 confirmed
working (correct anchors, correct diff logic), a "which deals changed
stage in EMEA/Enterprise" question still blew the token budget — the same
root cause flagged two days ago (unnecessary round-trips), only partially
addressed then.

**Root cause #1 (eliminates a round-trip):** `deals_snapshot.region` and
`deals_snapshot.segment` have existed in Postgres since migration 060
(2026-09-08) and have been populated by `snapshot_deals.py` ever since —
but 060 never registered them in `data_dictionary`, which is the ONLY
thing `get_schema_context()` reads to decide what the dynamic query loop
can see. The model's stated belief ("the snapshot data doesn't include
segment or region columns") was true of what it was shown, false of the
real table — a **data-dictionary registration gap**, the same class of
bug as an earlier `deals.region` registration miss, recurring on a
different table because registering a new column is a separate,
skippable step from the migration that adds it.

**Root cause #2 (extends an existing shortcut):** `deals_snapshot` still
has no `company_name`, so a third call (naming the matched deal_ids) is
genuinely unavoidable — but it fell through to a fresh full-budget loop
iteration instead of synthesizing immediately, the same problem the
existing `dimension_retry_succeeded` shortcut already solved for a
different shape.

**Completed work:**
- [x] `scripts/migrations/062_register_snapshot_region_segment_in_
      dictionary.sql` — registers both columns (not yet applied to the
      live database as of this writing; the Supabase account connected to
      this session doesn't include this project — needs to be run via the
      correct account or pasted into the SQL Editor directly)
- [x] `api/schema_context.py` + `api/router.py` prompt: explicit
      `deals_snapshot` table description and system-prompt guidance
      stating region/segment/owner_email are already point-in-time
      columns there, and company_name is the one thing it lacks
- [x] `_is_id_scoped_enrichment_call()` (api/router.py): generalizes the
      immediate-synthesis shortcut to any `filter_table` call whose only
      real selectivity is a `deal_id` filter against IDs a prior step
      already found
- [x] **New CI gate, same shape as the date-resolution gate, for this bug
      class specifically:** `tests/test_data_dictionary_registration.py`
      (offline, forward-looking — new migrations only) +
      `scripts/check_data_dictionary_coverage.py` (live, authoritative,
      catches historical gaps too) + `config/data_dictionary_exclusions.
      yaml` (explicit-exception ledger, same idea as `# ALLOW-RAW-DATE-
      MATH:`). Wired into `gate-tests.yml` as TEST 0e (offline) and
      TEST 1b (live, deliberately NOT soft-fail — requires
      `SUPABASE_DB_URL` in the `Agent` environment's secrets)
- [x] Verified the offline gate actually catches a violation (planted a
      fake migration adding an unregistered column, confirmed failure,
      removed it) — same discipline as the date-resolution gate's
      self-test

**Important asymmetry documented in the gate itself:** unlike the date-
resolution gate (fully static — "does this code call
resolve_time_window()" is knowable from source), "is this column
registered" is NOT knowable from the repo alone, because registration
also happens by running `scripts/backfill_data_dictionary.py` live
against the database with no migration-file trace. A static check against
full history found 42 of 44 historical column additions "missing" —
almost all false positives. The offline gate is therefore forward-looking
only (migrations after 062); the live script is the actual source of
truth for historical coverage.

**Token accounting:** computed via the loop's own chars/4 budget
estimator against real measured constants (not a live-run measurement —
no Railway/live DB access this session). See chat history for the full
derivation; summary: the worked incident shape projects to ~37K of the
40K budget by the third call if the loop continues past it, vs. ~26K with
the fix stopping there. Confirmation is the next live occurrence of this
question, not this projection.

**Separately found while checking this (not part of the fix, logged
above under High Priority #0):** `MIGRATION_047_REQUIRED.md` had a live
database password committed in plaintext since 2026-09-06. Removed from
the file's current content; still in git history; database password not
yet rotated.

---

### Date Resolution Single-Source-of-Truth Audit (2026-09-10)
**Status:** ✅ COMPLETE - Four instances fixed, structural CI gate added

**Issue:** "Last 2 weeks" and similar relative-time phrases resolved to
wrong date windows in multiple, independently-broken places, discovered
one at a time across three follow-up questions on the same live incident:
1. `query_pipeline_movement`'s `_pm_view_movement` checked a
   `time_window.type == "relative_days"` shape nothing ever produced —
   silently fell back to "compare whichever two snapshots exist."
2. The classifier's `time_window` JSON schema had no `n` field for
   `period=last_N_days`, so `resolve_time_window()` silently defaulted to
   30 days for any "last N days/weeks" phrase.
3. `dynamic_query_loop`'s `deals_snapshot` "changed stage" comparisons
   needed a second (prior) date the resolved window didn't provide, so
   the model invented one (off by ~64 days in the reported case).
4. Found auditing the above: `resolve_time_window()` itself called
   `date.today()` (server UTC) while `client.yaml`'s reporting timezone
   is `America/New_York` — disagreeing with itself for part of every
   evening. Same root cause, one layer deeper.

**Completed work:**
- [x] Fix 1 (30a91b7): `_pm_view_movement` derives `requested_days` from
      the resolved time_window instead of dead-code param shape; added
      snapshot-freshness flag
- [x] Fix 2 (30a91b7): classifier schema gained an explicit `n` field for
      `period=last_N_days`
- [x] Fix 3 (c0fe81f): `resolve_snapshot_anchors()` deterministically
      resolves both comparison dates for `deals_snapshot` point-in-time
      questions instead of leaving the second one to the model; explicit
      "NO DATA AVAILABLE" signal (not silence) when no snapshot exists
      that far back or the lookup fails
- [x] Fix 4 (90d3bdf): `resolve_time_window()`, `current_quarter_label()`,
      and `get_fiscal_quarter()`'s `as_of=None` default all switched to
      `today_in_reporting_tz()`; same fix applied to the classifier's
      literal "Today is {today}" prompt text and a stat helper
- [x] Full audit of every `timedelta(days=...)` and `date.today()` site in
      `api/` — each classified as a real parallel implementation (migrated
      through `resolve_time_window()`) or a legitimate exception (tagged
      `# ALLOW-RAW-DATE-MATH: <reason>`)
- [x] `tests/test_date_resolution_single_source.py`: grep-based structural
      gate wired into `gate-tests.yml` (offline, no credentials) — fails
      the build on any new bare `date.today()` or unmarked
      `timedelta(days=...)` in `api/`. Verified it actually catches a
      planted violation before removing it.
- [x] `tests/test_time_window_resolution.py` and `tests/test_snapshot_
      anchors.py` extended to cover the reporting-timezone case and an
      explicit no-data signal (4 tests total in the latter)

**Confirmed NOT affected:** `scripts/analytics/compute_waterfall_
segmented.py` (the 952/954 backfill reconciliation) calls none of the
functions touched by Fix 4 — it never resolves "today" at all, only reads
real `snapshot_date` values already in the table and pairs up consecutive
ones. Re-running it post-fix will not change its result.

**Residual items found but NOT fixed in this pass (see Backlog below):**
- `scripts/analytics/snapshot_deals.py` stamps new snapshots with raw
  `date.today()`, and both snapshot crons run at 2am UTC — inside the
  window where UTC has already rolled to a new day but `America/New_York`
  hasn't. Out of scope for this audit (scoped to `api/`, not batch ETL),
  but directly relevant to "could stored snapshot_date values already be
  off by a day" — see Backlog #4.
- Rep-name-to-email matching in `dynamic_query_loop` is a structurally
  similar "model fills a gap from provided context" pattern, but lower
  risk (closed-list lookup, not computation) — see Backlog #3.

**Commits:** 30a91b7, c0fe81f, 90d3bdf

---

## 📋 Backlog

### High Priority

#### 0. URGENT — Live Database Password Committed in Plaintext
**Issue:** The literal production Postgres password was committed in
plaintext in THREE places:
- `MIGRATION_047_REQUIRED.md` (commit b75a3c1, 2026-09-06) — a full
  connection string in a troubleshooting doc
- `measure_stage_probabilities.py` and `measure_review_exclusion_impact.py`
  — both hardcoded the literal password as a string literal to detect and
  fix an unescaped `!` in `SUPABASE_DB_URL`, rather than handling the `!`
  generically

Audit note: a plain `grep -r` for the password string across the whole
repo (not just the file that prompted the check) is what found the other
two — worth doing the same sweep for any OTHER credential fragments,
not just this one value.

**Status:** PARTIALLY ADDRESSED — all three files fixed (password removed
from the doc; both scripts changed to URL-encode `!` generically instead
of hardcoding the credential) as of 2026-09-11, but:
1. **The database password itself has NOT been rotated.** It was exposed
   in a public-ish commit for 5 days; treat it as compromised and rotate
   it regardless of whether anyone is known to have used it.
2. **It is still present in git history** (commit b75a3c1 and every
   commit after it until the redaction). Removing it from the current
   file does not remove it from history — anyone with clone access to
   this repo (or its history via GitHub) can still retrieve it with
   `git log -p` or `git show b75a3c1`. A real fix requires either a
   history rewrite (`git filter-repo` or BFG Repo-Cleaner, force-pushed,
   coordinated with everyone who has a clone) or, more simply, treating
   the credential as permanently burned and rotated — at which point the
   old value in history is harmless to leave, since it no longer grants
   access.

**Recommended order:** rotate the database password FIRST (closes the
actual exposure immediately, no coordination needed), then decide at
leisure whether scrubbing git history is worth the disruption (force-push
+ everyone re-clones) given the credential it protects is already dead.

**Work required:**
1. Rotate the Supabase/Postgres database password now.
2. Update `SUPABASE_DB_URL` (and any other place the connection string is
   stored — GitHub Secrets, local `.env` files, CI) with the new password.
3. Decide on git-history remediation (rewrite vs. accept-as-dead-credential).
4. Audit other docs/scripts for the same pattern (a connection string
   pasted into a markdown troubleshooting doc "to show it worked") —
   this is an easy mistake to repeat.

**Complexity:** Low effort for the rotation itself; the history question
is a judgment call, not a coding task.

---

#### 1. Snapshot ETL Phantom Exits Bug
**Issue:** Deals occasionally missing from single week's snapshot, causing "phantom exits" in waterfall

**Status:** IDENTIFIED, NOT FIXED

**Evidence:**
- 952 of 954 group/week combinations reconcile perfectly (99.8% success rate)
- 2 remaining mismatches traced to phantom exits:
  - Deal 38816659085: Present in 2026-04-06 snapshot ($20K), missing from 2026-04-13, reappears in 2026-04-20 (ROW/SMB)
  - Deal 59860100786: Present in 2026-05-18 snapshot ($40K), missing from 2026-05-25, eventually closes won in August (EMEA/Mid-Market)

**Impact:** Low frequency (0.2% of weeks affected), but creates unreconcilable gaps
- Deals silently exit waterfall without triggering any movement category (not won, not lost, not ARR change)
- Beginning + net_change ≠ ending for affected group/weeks
- Reconciliation check correctly fails on affected weeks (working as designed)

**Root cause:** Snapshot ETL (scripts/snapshot_deals.py) occasionally excludes active deals from snapshot
- Deals don't match any exclusion criteria (not closed, not test deals, etc.)
- Missing deals reappear in subsequent snapshots
- Pattern suggests intermittent ETL bug, not systematic filter

**What was fixed (2026-09-08):**
1. ✅ Won/lost detection (hybrid function with property_history + close_date fallback)
2. ✅ Net_change formula (removed moved_forward/moved_backward double-counting)
3. ✅ Snapshot enrichment (region/segment backfilled to 85-95%)
4. ✅ Precedence masking bug (removed precedence system, independent movement tracking)
5. ✅ ARR delta calculation (fixed to track DELTA not VALUE, added newly_arr_bearing category)

**Work required:**
1. Audit snapshot_deals.py ETL logic for conditions that could intermittently exclude deals
2. Check for race conditions, API pagination issues, or HubSpot API filters
3. Add completeness check: compare deal_ids between consecutive snapshots, flag disappear-then-reappear patterns
4. Once fixed, re-backfill affected weeks (2026-04-13, 2026-05-25, any others found)

**Complexity:** Medium effort (requires ETL audit + HubSpot API investigation)

**Reconciliation check status:**
- ✅ Check remains STRICT (correctly fails on phantom exits)
- ✅ Outputs specific deal_ids causing mismatches
- ✅ Failing check points at real, tracked bug (not silenced)

**Documentation:** (this session's investigation)

---

#### 2. query_pipeline_movement Zero-Row Mystery (Jake Stangl incident) — MITIGATED, NOT ROOT-CAUSED, DEPRIORITIZED

**Issue:** A live Slack question about Jake Stangl's FY2027 Q3 pipeline
movement returned a zero-row result from `query_pipeline_movement`
(api/handlers.py) — a dedicated, HIGH-confidence (0.85) handler, not
the dynamic-query fallback path. Jeff confirmed directly against live
data that this was wrong: Jake Stangl has 10 CONFIRMED ACTIVE
deals_snapshot rows on the 2026-09-08 snapshot alone
(fiscal_quarter='FY2027 Q3', pipeline_id='default',
owner_email='jake.stangl@growthbook.io', deal_status='active') —
exactly the population this handler's filter should have matched.

**Status:** MITIGATED, NOT CONFIRMED ROOT-CAUSED. Two real, defensible
hardening fixes have shipped (commit ecbd115), but neither has been
proven to be what actually caused this specific incident, because the
one piece of direct evidence available — the captured live HTTP
request — already showed the two values these fixes target
(fiscal_quarter, owner_email) as byte-correct at time of capture. If
this recurs after these fixes, that is the signal they were not the
actual cause and the two hypotheses below (not yet ruled out) should
be checked first.

**Hypotheses examined, all six, via code/config inspection only (no
live DB access available in this sandbox):**

1. **owner_email format/case mismatch** — the captured request already
   showed the correct, exact-case email reaching the filter. Not
   confirmed as the cause of this incident, but hardened anyway
   (`eq` → `ilike`, case-insensitive exact match) since exact-match
   comparisons on model-reproduced text are fragile in general.
2. **pipeline_id exclusion also excluding 'default'** — RULED OUT.
   `config/client.yaml`'s `pipelines.excluded` lists only the renewal
   pipeline (866608541); `default` is the *included* pipeline and the
   exclusion branch only ever appends `neq pipeline_id 866608541`.
3. **fiscal_quarter format/whitespace drift** — the captured request
   already showed the literal correct value ("FY2027 Q3") reaching the
   filter. Not confirmed as the cause of THIS incident, but a real,
   demonstrable structural risk regardless: `api/router.py`'s own
   classifier prompt documents two conflicting quarter-label
   conventions ("FY2027 Q2" for this handler's `fiscal_quarter` vs.
   the reversed "Q3_FY2027" for a different handler's `period_label`)
   a few lines apart. Hardened via `_pm_normalize_fiscal_quarter()`.
4. **a leftover stage_id filter** — RULED OUT. The raw `filters` list
   sent to `select_all()` for the DB-level query never includes a
   stage_id clause anywhere in this function; confirmed absent by
   reading the construction top to bottom, not inferred.
5. **deal_status exact-match mismatch** ('active' vs 'Active'/'open'/
   etc.) — RULED OUT, definitively. `query_pipeline_movement` does not
   select `deal_status` (see `_PM_SNAPSHOT_COLUMNS`'s own comment: "...
   deal_status and fiscal_quarter [as a read-back column] ... were
   dropped ...") and does not filter on it anywhere in this function.
   The column is structurally absent from this handler's query, so it
   cannot be the cause regardless of what value is actually stored.
6. **snapshot_date selection picking a date with no matching rows** —
   RULED OUT for the specific zero-row symptom reported (the exact
   message "no snapshot rows for {fiscal_quarter} (owner {email})").
   `query_pipeline_movement`'s raw DB query never filters by
   snapshot_date at all — it pulls every snapshot_date within the
   fiscal_quarter/owner/pipeline scope in one call. All snapshot_date
   handling (grid/source selection, picking the latest date) happens
   entirely in Python, AFTER the `if not rows:` gate, and only runs
   when `rows` is already non-empty. It cannot be why the raw query
   itself returned zero rows.

**What remains genuinely open:** all six hypotheses are now either
ruled out or unconfirmed-but-hardened, and NONE of them, on the
evidence available (the captured request showing correct values),
explains why the raw `select_all()` call returned zero rows against a
confirmed-populated table. Possibilities not checkable from this
sandbox (no live Supabase/Railway access):
- **Deploy lag** — whether the code actually running on Railway at
  the time of the incident matched this repo's HEAD at all, vs. an
  older or hotfixed version with a since-reverted bug.
- **Row-level security** on `deals_snapshot` in Supabase silently
  restricting what the service role can see under some condition.
- **A supabase-py/postgrest-py library version issue** in how chained
  `.eq()`/`.neq()`/`.ilike()` filter calls compose on the query
  builder — not verifiable through static reading of this
  repo's application code alone.
- **The captured request was incomplete/truncated** — the visible URL
  fragment only showed `fiscal_quarter` and `owner_email`; the full,
  untruncated query string (including the pipeline_id neq clauses)
  was never seen directly, so a subtlety there can't be fully ruled
  out either.

**Instrumentation shipped (2026-09-11, round 4):** all four remaining
hypotheses (deploy lag, RLS, a supabase-py/postgrest-py filter-chaining
quirk, an incomplete original capture) require live production access
to resolve — none are checkable from a sandbox, so the investigation
could not move forward through more code inspection. Added a single
unconditional INFO-level log line in `query_pipeline_movement`, right
before the Supabase call: `[PIPELINE_MOVEMENT_QUERY] table=... columns=...
filters=...`, every column/operator/value via `!r` for byte-exact
visibility. Costs nothing when the handler works correctly. The next
time this handler returns a zero-row result unexpectedly, the Railway
log will show EXACTLY what was sent to Supabase — closing the one gap
that blocked this investigation from the start: never having the
actual outgoing query to compare against known-good data. Covered by
`test_the_fully_constructed_filter_is_logged_byte_exact_before_the_query`
in tests/test_pipeline_movement_fiscal_quarter_filter_bug.py.

**Added finding (2026-09-11, round 5):** Confirmed the connection-retry
bug (`httpx.RemoteProtocolError: ConnectionTerminated`, found and fixed
2026-09-11) is NOT the explanation for this original incident. The
original incident's own captured evidence showed a byte-correct,
COMPLETED request/response — structurally incompatible with a
connection that died mid-stream (no code path exists where a
`RemoteProtocolError` silently becomes an empty-rows result; it
propagates as a visible, logged handler error instead — see
`_run_precomputed_handler()`'s exception handling in `api/router.py`,
and `select_all()`/`query_pipeline_movement`'s complete absence of any
try/except around the Supabase call that could swallow it). This rules
out one more plausible-looking cause without resolving the actual one.

**Status (unchanged): MITIGATED, NOT ROOT-CAUSED.** No recurrence
confirmed since the canonicalization fixes landed. Deprioritized — not
actively being chased. Re-open if it recurs; the
`[PIPELINE_MOVEMENT_QUERY]` debug line remains in place to capture the
exact filter clause if it does.

**Work required (if this recurs):**
1. Pull the `[PIPELINE_MOVEMENT_QUERY]` log line for the failing
   request from Railway — it now carries the exact filters sent, no
   need to reconstruct them from a partial capture.
2. Confirm Railway's deployed commit SHA matches this repo's HEAD at
   the time of the incident.
3. Check Supabase RLS policies on `deals_snapshot` for the service
   role used by this app.
4. Run the exact same filtered request directly against Supabase
   (curl/psql) outside the application, to isolate app-layer vs.
   database-layer causes.

**Complexity:** Low effort per individual check above; the blocker is
purely lack of live production/DB access from this working environment,
not investigative complexity.

**Documentation:** this session's investigation; fixes in
tests/test_pipeline_movement_fiscal_quarter_filter_bug.py and
tests/test_pipeline_movement_owner_role_note.py.

---

#### 3. Dedicated Handlers: Owner-Email Canonicalization Gap (audit follow-up)

**⭐ RECOMMENDED NEXT SESSION START (flagged 2026-09-11):** best-scoped
open item in this file — direct sequel to the query_pipeline_movement
incident, a real candidate root cause already proven once (the exact
same exact-match fragility fixed there), and a closed, named list of
5 handlers rather than an open-ended investigation.

**Issue:** Following the `query_pipeline_movement` incident (#2 above),
an audit of every OTHER dedicated handler in `api/handlers.py` that
builds its own direct Supabase filters (not routed through
`dynamic_query_loop`) found several that filter `owner_email`/
`sdr_email` with an exact-match `eq` against a raw value from `params`
— i.e. whatever a model extracted from free text — with no case-fold
and no roster resolution via `_resolve_owner_email()`. This is the
same risk class as `query_pipeline_movement`'s bug, just not yet
confirmed to have caused an incident in any of these specific handlers.

**Status:** ✅ CANONICALIZATION APPLIED (2026-09-11, same night as the
logging pass — see `tests/test_owner_email_canonicalization.py`).
Fixed one handler at a time, each tested individually against its own
realistic case before moving to the next, per the session's own
"batch changes hide handler-specific wrinkles" lesson from the earlier
`query_pipeline_movement` and primitive-contract rounds.

1. `query_pipeline` (~2014) — now routes through
   `_resolve_owner_email()` (accepts a name or an email) and filters
   via `ilike` instead of `eq`.
2. `query_call_quality` (~3531, team/rep mode) — same fix; Mode 1
   (single call by company) untouched.
3. `query_sdr_metrics` (~1714) — same fix at BOTH call sites
   (`sdr_users.user_email` and `meetings.owner_email`).
4. `query_sdr_pipeline_sourced` (~1627) — same fix on whichever
   attribution column is active (`sdr_owner_email` or `owner_email`
   per `config/client.yaml`'s `sdr_tools.pipeline_attribution.method`);
   the no-SDR-filter path (returns all SDRs) verified to add no
   spurious clause.
5. `query_stale_deals` (~2749) — two fixes, not one: (a) the audit note
   above called `owner_email` "already fixed" because it's resolved via
   `_resolve_owner_email()`, but missed that a name resolves to
   `user_personas.email` VERBATIM (no case-fold) — switched the
   downstream filter from `eq` to `ilike` to close that residual gap
   too; (b) `stage` now goes through a new `_resolve_stage_id()` helper
   (`api/handlers.py`, next to `_resolve_owner_email()`) that resolves a
   model-extracted human label (e.g. "Technical Evaluation") to the raw
   HubSpot stage id actually stored in `deals.stage`
   (`presentationscheduled`) — case-insensitively — via
   `api/field_semantics.py`'s `_LABEL_TO_STAGE_ID`/`_ALIAS_TO_CANONICAL`
   tables (generated from the same `config/field_semantics.yaml` source
   of truth as `STAGE_MAP`), falling through unchanged for a value
   matching neither table.

`query_rep_pipeline`, `query_deal_health`, `query_team_leaderboard`,
`query_coverage` were left as-is (lower risk — already call
`_resolve_owner_email()`, or use deterministically-computed rather than
free-text values), matching the audit's original scoping.

**Not verified live:** no live Supabase/Railway/production log access
in this sandbox at any point in this session — none of these fixes (nor
the original `query_pipeline_movement` mitigation) has been confirmed
against real production data. The `[PIPELINE_MOVEMENT_QUERY]` debug
line shipped for the Jake Stangl incident could not be checked for
recurrence either, for the same reason.

**Documentation:** `tests/test_owner_email_canonicalization.py` (16
tests, one section per handler); `tests/test_handler_filter_logging.py`
updated (one pre-existing test's target field changed since
`query_pipeline`'s `owner_email` is now deliberately normalized, and
`query_stale_deals`'s `stage` now passes through `_resolve_stage_id()`
too, though its specific test value matches neither lookup table so the
byte-exact logging assertion still holds); logging fix from the earlier
pass unchanged.

---

#### 4. Why Does GitHub Actions' Hosted Runner Fail to Import `ClientOptions` from `supabase`?

**Issue:** A live GitHub Actions run of `gate-tests.yml` (ubuntu-latest,
a fresh `pip install -r requirements.txt` with no venv) failed twice in
a row, identically (ruled out as a one-run flake via `rerun_failed_jobs`)
with:

```
ImportError: cannot import name 'ClientOptions' from 'supabase' (unknown location)
```

at `api/db.py`'s top-level `from supabase import create_client, Client,
ClientOptions` — the import added earlier the same night for the
Supabase dead-connection retry-transport fix. This killed every single
downstream test in the workflow (everything after `TEST 0` reported
"skipped," never actually running).

**Could NOT be reproduced** despite real effort: this sandbox's own
long-lived environment imports `ClientOptions` fine; a genuinely fresh,
isolated `python3 -m venv` + `pip install -r requirements.txt` using
the EXACT same pinned versions CI's own install log reported
(`supabase==2.31.0`, `postgrest==2.31.0`, and every other transitive
version matching byte-for-byte) also imports cleanly. No shadowing
`supabase` file or directory exists anywhere in this repo that could
create a namespace-package collision (the `(unknown location)` phrasing
in the error is the specific signature of Python resolving `supabase`
to a namespace package with no real `__init__.py`, rather than the
actual installed package — but the trigger for that happening
specifically on GitHub's hosted runner remains unidentified).

**Status:** MITIGATED, NOT ROOT-CAUSED — same shape as High Priority
#2. `create_resilient_supabase_client()` (`scripts/supabase_client.py`)
now imports `ClientOptions` lazily, inside a try block, so this same
failure (or any other import-time problem building the resilient
client) degrades to a plain client with no retry protection instead of
crashing the app outright — see the commit that added this fix and
`tests/test_supabase_client_fallback.py`. This closes the actual risk
(an app that can't start, plausibly including on a live Railway
deploy) without requiring the root cause to be understood first — a
degraded-but-running app beats a dead one. Not blocking on the
investigation below; logged so it isn't lost.

**Likely candidates, not yet checked (needs live access to GitHub's
runner environment or a way to inspect it, neither available from this
sandbox):**
- A stale or corrupted entry in GitHub's hosted-runner pip cache for
  this specific `supabase==2.31.0` wheel, distinct from PyPI's own
  (correct) copy — would explain why a fresh venv here, presumably
  pulling from PyPI directly rather than any GitHub-side cache, doesn't
  reproduce it.
- A version pin mismatch between what `requirements.txt` declares
  (`supabase>=2.0.0`, an open range) and what the runner's environment
  ACTUALLY resolved and installed, despite the install log's own
  stdout claiming `supabase-2.31.0` — worth confirming with a
  `pip show supabase` step added temporarily to the workflow, printed
  immediately before the failing import, to rule out the log itself
  being misleading.
- An environment variable or `PYTHONPATH` interaction specific to
  GitHub Actions' `ubuntu-latest` runner image (this workflow sets
  `PYTHONPATH=.:scripts:api:scripts/analytics` for its Python steps)
  that affects import resolution differently than a plain local `venv`
  activation does — not yet isolated to a specific mechanism.

**Work:** Add a temporary diagnostic step to `gate-tests.yml` (e.g.
`pip show supabase`, `python3 -c "import supabase; print(supabase.__file__, supabase.__path__)"`)
on a throwaway branch to actually observe what CI's runner resolves
`supabase` to, before removing it — the fastest way to distinguish
between the three candidates above rather than continuing to guess from
this sandbox, which has already been shown not to reproduce the issue.

**Complexity:** Unknown until the diagnostic step above actually runs
in CI — could be a one-line pip-cache-clearing fix, or something
requiring more investigation. Not urgent: the fallback fix means this
investigation is purely about understanding a mitigated risk, not
closing an open one.

---

### Low Priority

#### 1. Zero-Day Cycle Time Deals
**Issue:** 4 deals with negative or zero cycle time (data quality artifacts)

**Impact:** Low (already filtered by `is_valid_cycle_deal()` in handlers, but exist in raw data)

**Work:** Investigate and clean up at source (HubSpot or ETL)

**Complexity:** Low effort

---

#### 2. Forecast Analysis Bugs (Status Unconfirmed)
**Issue:** 2 old bugs mentioned in forecast_analyses.py

**Work:** Confirm if still present, fix if needed

**Complexity:** TBD (need to confirm existence first)

---

#### 3. Rep-Name-to-Email Matching Has No Deterministic Backstop
**Issue:** `dynamic_query_loop`'s system prompt hands the model a small
`roster_text` list and instructs it to match a first name ("Jake") to an
email itself — the same "model fills a gap from provided context" shape
as the date-resolution bug class, just for names instead of dates.

**Status:** NOT BROKEN (no known incident) — flagged during the
2026-09-10 date-resolution audit as a residual, lower-priority risk, not
chased further because there was no evidence it had actually misfired.

**Why lower risk than the date bug:** it's a lookup against a small,
fully-enumerated, explicitly-provided list, not open-ended computation —
much smaller error surface. Stage names and `pipeline_id` are similarly
safe (grounded via `enum_values` in the schema context).

**Residual risk:** two roster members sharing a first name, or a
close-but-wrong fuzzy match, has no deterministic tie-breaker or
verification step.

**Work (if ever prioritized):** add a deterministic exact/ambiguous-match
check before the model reasons about a name, similar in spirit to
`_resolve_owner_email()` (already used by classifier-routed handlers) —
surface "which Jake did you mean?" instead of silently picking one.

**Complexity:** Low-to-medium (roster is already loaded as `roster_text`)

---

#### 4. Snapshot ETL Stamps snapshot_date with Server-UTC date.today()
**Issue:** `scripts/analytics/snapshot_deals.py` uses raw `date.today()`
(not `today_in_reporting_tz()`) to decide which calendar date to stamp on
a newly-written `deals_snapshot` row. Both snapshot crons
(`weekly-snapshot.yml`: `0 2 * * 1`, `nightly.yml`: `0 2 * * *`) run at
2am UTC — during EDT (UTC-4), that's 10pm the previous day in
`America/New_York`, i.e. inside the exact window where server UTC and the
reporting timezone disagree on "today."

**Status:** IDENTIFIED, NOT FIXED — found while confirming the
2026-09-10 date-resolution fix didn't affect this week's reconciled
waterfall numbers (it doesn't; see the audit entry above). This is a
separate, pre-existing issue, out of scope for that audit (scoped to the
live `api/` Q&A path, not batch ETL).

**Impact:** Every scheduled snapshot is stamped with a date that may be
one calendar day ahead of the reporting-timezone "today" it actually ran
in. Constant and systematic (always the same direction), unlike the
larger multi-week misses fixed in the audit above — worth checking
whether this explains any single-day boundary artifacts in the waterfall
(possibly related to, but distinct from, the Phantom Exits bug above,
which is about a deal being missing from a snapshot, not the snapshot's
own date being wrong).

**Work:** Switch `scripts/analytics/snapshot_deals.py`'s `today =
date.today()` to `today_in_reporting_tz()`, consistent with the rest of
the system post-audit. Decide whether to backfill/re-stamp existing rows
or only fix new snapshots going forward.

**Complexity:** Low effort to fix; needs a decision on backfill scope
before touching historical data.

---

#### 5. `synthesis_aggregation_fix.py` (repo root) Is Dead, Unmarked Reference Material

**Issue:** `synthesis_aggregation_fix.py` at the repo root contains an
old `verify_synthesis_aggregation()` function and a
`SYNTHESIS_PROMPT_ENHANCED` string from the original 2026-09-09
synthesis-aggregation-gap fix. It is not imported anywhere — confirmed
via a repo-wide grep for both the filename and the function name, which
only turned up this file itself and two references in
`PENDING_WORK.md`/`SYNTHESIS_FIX_TEST_RESULTS.md` describing it as the
original "fix specification" (a design doc). The actual fix was carried
into `api/router.py`'s live prompt text directly, and this file was
never wired in.

**Status:** CONFIRMED INERT AND HARMLESS (verified 2026-09-11 while
sanity-checking that the new `verify_aggregation_completeness()` code-
level gate — see Recently Completed below — fully replaced the old
prompt-only check rather than running alongside it). Not a functional
bug. The risk is purely investigative cost: a file at the repo root
named like it should matter, containing a function named
`verify_synthesis_aggregation` that looks similar enough to the new
`verify_aggregation_completeness()` to raise "wait, are there two of
these?" the next time someone (human or agent) greps for aggregation
logic — the same shape of cost the plaintext committed DB password
(High Priority #0) imposed before it was found, just lower stakes.

**Work:** Either delete the file outright (it has no runtime role and
its content is superseded by the live implementation in
`api/router.py` + `api/aggregation_verification.py`), or, if it's
worth keeping for historical reference, add a one-line header comment
marking it explicitly superseded/historical and pointing at the files
that actually run today.

**Complexity:** Trivial (delete, or add a comment) — low priority
because it costs nothing while it sits there; the point is to close it
out before it becomes a real "what is this and is it still live"
investigation for someone without this context.

---

#### 6. Primitive-Contract Gate Has a Known, Unclosed Blind Spot: Silent Resolvers

**Issue:** `PRIMITIVE_CHECKLIST.md`'s two structural scans
(`tests/test_primitive_contract.py`) — the function-name scan
(`test_no_new_unreviewed_detection_functions`) and the bracketed-log-tag
scan added the same night (`test_no_new_unreviewed_flagged_log_tags`) —
both require SOME textual signal to catch a detection primitive: a name
matching the naming patterns, or a `logger.*` call with a flagged
keyword in its message. `resolve_dimension_filter` (api/router.py) is
the standing counter-example: a resolver-style function that can return
an ambiguous/unknown result on some code path with **no log call at
all** on that path. Neither scan can see it, by construction — there is
nothing for either regex to match against.

**Status:** NOT FIXED, tracked here so it isn't forgotten. Not urgent —
`resolve_dimension_filter` itself was already found and reviewed by
manual audit (see `PRIMITIVE_CHECKLIST.md`), so this isn't an active,
unreviewed bug; it's a gap in the STRUCTURAL GATE'S coverage that would
let a *future* silent resolver slip through both of tonight's scans
undetected, the same way the zero-rows suspicion note slipped through
the first scan before tonight's follow-up added the second.

**Work:** Closing this needs one of two meaningfully bigger approaches
than tonight's keyword scan:
(a) Make it a convention (and, ideally, enforce it) that every
    resolver-style function logs its outcome unconditionally — including
    the ambiguous/unknown branch, not just the success path — so the
    existing bracketed-log-tag scan would then have something to match
    against. Lowest-lift of the two, but relies on the convention
    actually being followed at every future call site, which is
    exactly the kind of "someone has to remember" gap this whole
    checklist exists to replace with structure.
(b) A different, heavier static check: for every function matching a
    resolver-style naming pattern, verify every early-return branch in
    its body has an associated log call. This is closer to real control-
    flow analysis (walking a function's AST for return statements and
    checking each one's containing block for a preceding/wrapping log
    call) than the simple regex/keyword scans built tonight, and is a
    meaningfully bigger lift — likely its own small project rather than
    an extension of `test_primitive_contract.py`.

**Complexity:** Low-medium for (a) as a convention change plus a
lightweight lint; higher for (b), a real static-analysis tool. Neither
is scoped or started — this entry exists purely so the blind spot is
written down rather than living only in this session's own memory.

---

#### 7. Cost-Aware Planner Needs Recalibration Once Real Traffic Accumulates

**Issue:** `resolve_execution_cost_estimate()` (`api/router.py`) —
a pre-execution cost estimate for `dynamic_query_loop`, warning on an
expensive-looking question before running anything — was calibrated
against real `query_cost_log` rows (`scripts/query_cost_log_
calibration.sql`), not guesses, per the explicit ask that built it. But
the table held only **13 rows** at calibration time: this week's own
testing, not a week of organic production traffic. Most individual
primitives had only 1-2 rows where they fired at all —
`enrichment_shortcut_fired` and `scratchpad_rejection_fired`'s
"fired=true" groups turned out to be the exact same two invocations,
not independent evidence. Two of the five calibrated deltas
(`dimension_resolver_matched`, `ambiguous_dimension_term_flagged`) came
back showing LOWER cost when fired than when not, which is plausible
(proactive resolution avoiding a reactive correction pass later) but
just as likely n=2/n=5 noise — kept as computed rather than flipped to
match intuition, since a "corrected" model would be calibrated to
priors, not data.

**Status:** SHIPPED, WORKING, LOW CONFIDENCE BY DESIGN. Every estimate
this function returns carries an explicit `confidence: "low (n=13...)"`
label naming the real sample size — it is not silently presented as
precise. Validated against the one real, individually-identified case
from the calibration pull (`query_cost_log` id=13, the EMEA/Enterprise/
Jake question — 2 iterations, 35452 tokens actually measured) to
same-order-of-magnitude, not a tight tolerance the data doesn't
support: the estimate came back at 1 iteration / ~24,948 tokens, in the
right neighborhood but not precise.

**Work:** Re-run `scripts/query_cost_log_calibration.sql` (or extend it)
once meaningfully more traffic has accumulated — a few dozen rows per
primitive at minimum — and update `api/router.py`'s
`_COST_BASE_ITERATIONS` / `_COST_BASE_TOKENS` / `_COST_DELTAS`
constants directly from the new numbers, the same way they were built
this time. No automated recalibration pipeline exists; this is a
manual, occasional pass. Worth specifically re-checking the two
counter-intuitive negative deltas once there's enough data to tell
signal from noise.

**Complexity:** Low — the recalibration procedure itself is just
re-running the same SQL and updating four named constants. The
blocker is purely accumulated traffic volume, not investigative or
implementation complexity.

**Documentation:** `api/router.py`'s `resolve_execution_cost_estimate()`
own module-level comment (exact deltas and full caveat);
`tests/test_execution_cost_estimate.py`; `scripts/query_cost_log_
calibration.sql`.

---

#### 8. `eval_handler_descriptions.py` Has Been Failing on 5 Undocumented Handler-Adjacent Functions Since At Least 2026-09-06 — ✅ FIXED

**Issue:** `scripts/eval_handler_descriptions.py` (run as part of `TEST
0` in `.github/workflows/gate-tests.yml`) asserts every function it
finds in `api.handlers`'s namespace has a matching entry in
`HANDLER_DESCRIPTIONS`. A live CI run surfaced it failing with:

```
AssertionError: Missing descriptions for 5 handlers:
{'compute_cycle_time', 'load_scope_config', 'canonical_stage',
 'is_deal_in_analytics_scope', 'compute_at_risk_deals'}
```

Confirmed via `git blame` that all five names trace back to commit
`b75a3c1`, dated 2026-09-06 — five days before this failure was ever
seen. Previously invisible because the `ClientOptions` import-crash
(High Priority #4) blocked `TEST 0` before it ever reached this check.

**Status:** FIXED. Investigated what `HANDLER_DESCRIPTIONS` is actually
FOR before writing anything — it's not just documentation, it's the
routing classifier's own menu: `build_intent_prompt()` (`api/router.py`)
lists every key in it as a pickable "handler" in the classifier's
prompt, and the dispatcher calls whatever comes back as
`getattr(handlers, handler_name)(params, sb)`. Read all 5 functions'
actual code before deciding anything (none had been read before, per
the explicit ask): all five are genuine utility/helper functions with
signatures completely incompatible with the `(params, sb)` handler
convention — `canonical_stage(stage_id: str)` (a `field_semantics`
helper, imported like the already-excluded `stage_bucket`/`stage_label`),
`load_scope_config(config=None)` and `is_deal_in_analytics_scope(
stage_at_date, pipeline_id, ...)` (shared analytics-scoping helpers
from `scripts/analytics/point_in_time.py`), and `compute_cycle_time(sb,
since_date=None, until_date=None)` / `compute_at_risk_deals(sb,
deal_ids=None, use_stage_aware=True, time_window=None)` (canonical
computation helpers defined in `api/handlers.py` itself, called BY
several already-documented handlers, e.g. `query_cycle_time` calls
`compute_cycle_time()`).

Writing real `HANDLER_DESCRIPTIONS` entries for any of these — the
literal ask — would have been an actual, dangerous regression: it
would let the classifier route a live user question to one of them and
crash immediately on the argument mismatch, the exact opposite of the
docs-completeness goal. Fixed instead by adding all 5 to
`eval_handler_descriptions.py`'s own `KNOWN_NON_HANDLERS` exclusion
set, extending the identical, already-established pattern for the
`field_semantics` helpers (`stage_bucket`, `stage_label`, `is_won`,
`is_lost`, `is_open`) already excluded there for the same reason, each
with a one-line comment naming what it actually is and who calls it.
`eval_handler_descriptions.py` now passes locally with zero missing
entries (35 handlers, 35 descriptions).

**Verified further than requested:** running `TEST 0`'s full sequence
of eval scripts locally (not just `eval_handler_descriptions.py` in
isolation) surfaced that fixing this gap unblocks progress into SEVERAL
MORE pre-existing, unrelated failures further down that same script
sequence — see new Low Priority #9. `TEST 0` is still not fully green;
this fix closes exactly the one check it targeted and no more.

**Documentation:** `scripts/eval_handler_descriptions.py`'s own
`KNOWN_NON_HANDLERS` comments; this entry.

---

#### 9. `TEST 0`'s Eval-Script Sequence Has Several More Pre-Existing Failures Beyond the Handler-Descriptions Gap — ✅ FIXED (all 4 items closed)

**Issue:** Fixing Low Priority #8 let `TEST 0`'s `set -e` sequence of
~28 `scripts/eval_*.py` calls progress past `eval_handler_descriptions.py`
for the first time — and immediately hit more failures further down
the same list, none related to tonight's work or to #8's fix. Found by
running the entire `TEST 0` step's script sequence locally (matching
`.github/workflows/gate-tests.yml` line for line), not just the one
script being fixed. Each confirmed pre-existing via `git blame` —
`scripts/eval_handlers_no_raise.py`, `api/router.py`'s `_honest_miss()`
(via `eval_bestseller_incident.py`), and `scripts/eval_fallback_message.py`
/`scripts/eval_requirements_complete.py` all trace to commit `b75a3c1`,
2026-09-06, same as #8 — genuinely pre-existing, not a regression:

1. **`eval_handlers_no_raise.py` → `query_rep_pipeline` raises
   `NameError: name 'tw' is not defined`** (`api/handlers.py:2463`,
   `"period": tw["label"] if tw else "all active"` — `tw` is never
   assigned in that function; likely meant to reference a differently-
   named local variable, or a leftover from a refactor).
2. **`eval_bestseller_incident.py` → `_honest_miss()` raises
   `TypeError: '>' not supported between instances of 'dict' and
   'int'`** (`api/router.py:124`, `if entity_count > 0:`) — the eval
   calls `_honest_miss("query_deal_health", {"deals": [], "summary":
   "x"})`, passing a dict where the function's own signature declares
   `entity_count: int`. Unclear yet whether the eval itself is stale
   (calling with the wrong shape) or a real caller elsewhere in the
   app passes a dict too — needs checking real call sites, not just
   the eval, before fixing either side.
3. **`eval_fallback_message.py`'s own mock is stale**: it stubs
   `get_schema_context` as `lambda sb, tables_with_descriptions=None:
   ""`, missing the `lightweight` keyword the real function
   (`api/schema_context.py`) now accepts and `_dynamic_query_loop_core`
   now always passes — `TypeError: <lambda>() got an unexpected
   keyword argument 'lightweight'`. This one is almost certainly the
   eval's own fixture going stale after a real signature change, not
   an application bug.
4. **`eval_requirements_complete.py` → `slack_sdk` imported
   (`scripts/run_calibration_via_slack.py`) but not declared** in
   `requirements.txt` or the eval's own alias map. A real, narrow gap
   in dependency declaration — the import would only fail at runtime
   if that specific script actually executes somewhere `slack_sdk`
   isn't otherwise pulled in as a transitive dependency.
5. **Two more failures in this local run were sandbox artifacts, not
   real bugs** — `eval_evaluator_json_salvage.py` and
   `eval_score_pinning.py` both failed with `ModuleNotFoundError: No
   module named 'anthropic'` purely because this sandbox's ambient
   Python environment doesn't have it installed (confirmed via `pip
   show anthropic`); CI's own `pip install -r requirements.txt`
   includes `anthropic>=0.40.0`, so these two are expected to run fine
   in the real workflow and don't need any code change.

**Status:** ✅ ALL 4 FIXED, each as its own standalone commit, each
verified locally AND against a live CI re-run before moving to the
next:

1. **`query_rep_pipeline` `NameError`** — fixed by hardcoding
   `"period": "all active"`, matching the function's own docstring
   ("CURRENT STATE — never filters by close_date... no time scope");
   `tw` was dead, copy-pasted logic from a sibling time-windowed
   handler, never adapted. This was a genuine LIVE PRODUCTION BUG —
   every real call to this handler crashed, independent of CI.
2. **`_honest_miss()` `TypeError`** — fixing just the eval's type
   mismatch (a dict where `entity_count: int` was expected) surfaced a
   SECOND, independent, previously-invisible gap once actually run:
   `_honest_miss()`'s real message never stated facts about what came
   back, despite its sibling `_result_summary()` being docstring'd as
   "for the honest-miss message" and already computing the exact
   phrase the eval expected — but only ever wired into an internal log
   line, never the user-facing message. Fixed as a deliberate
   USER-FACING BEHAVIOR CHANGE: `_honest_miss()` now takes
   `tool_results` and threads `_result_summary()`'s output into both
   of its messages, so the log and what the user sees can no longer
   diverge. New test: `tests/test_honest_miss_includes_facts.py`.
3. **`eval_fallback_message.py`'s stale mock** — added the missing
   `lightweight=False` param to its `get_schema_context` stub. Purely
   a test-file change, no production code touched.
4. **`slack_sdk` dependency gap** — investigated before assuming this
   was dead code to delete: `scripts/run_calibration_via_slack.py` is
   real, wired into a real GitHub Actions workflow
   (`.github/workflows/run-calibration.yml`) with a real
   `SLACK_BOT_TOKEN` secret, deliberately using a direct Slack client
   (not the Zapier flow production Q&A uses) so it can observe the
   agent's actual reply landing in a Slack thread. `slack_sdk` was
   never in `requirements.txt` at any point — added `slack_sdk>=3.27.0`,
   verified in a genuinely fresh virtualenv install.

**Verified live in CI, not just locally**, across 4 separate re-runs of
`gate-tests.yml` on `claude/dazzling-brown-rxeaje` (runs #61-#64) — each
re-run progressed exactly one bug further than the last, confirming
each fix in turn and ruling out anything hiding behind it, until
**`TEST 0` itself came back fully green (run #64)**: 35/35 handler
descriptions, no `NameError`, no stale mocks, `slack_sdk` resolved, and
`_honest_miss()`'s new behavior all passing for real. This closes out
Low Priority #9 completely.

**Documentation:** `scripts/eval_handlers_no_raise.py`,
`scripts/eval_bestseller_incident.py`, `scripts/eval_fallback_message.py`,
`scripts/eval_requirements_complete.py`'s own passing output;
`tests/test_honest_miss_includes_facts.py`; this entry.

---

#### 10. `TEST 0b` (Forecast Correctness) Fails on Renewal Denominator Scoping — Real Metric-Logic Bug, First Reached Only Now That `TEST 0` No Longer Blocks It

**Issue:** With Low Priority #9 fully closed, `TEST 0` no longer blocks
the rest of `gate-tests.yml` for the first time all night — and the
very next step, `TEST 0b` (`scripts/eval_forecast_correctness.py`),
immediately failed on a test that has never once been reached before
tonight:

```
❌ FAILED: test_numerator_and_denominator_share_scope
   renewal denom should be its own, got {'rate_count': None,
   'closed_won_count': 1, 'week3_scoped_denominator': 0,
   'reason': 'denominator 0 < min_evidence 30'}
RESULTS: 11 passed, 1 failed
```

The test's own intent (per its docstring): "Both sides apply the same
pipeline+stage scope from the shared rule, and conversion is computed
per pipeline... default and renewal are separate." The renewal
pipeline's denominator is coming back as 0 (triggering a
below-min-evidence null) instead of its own real, independently-scoped
count — meaning the renewal-pipeline win-rate/conversion metric is
either silently nulling out when it shouldn't, or the scoping logic
that's supposed to keep default and renewal pipelines separate isn't
actually separating them correctly.

Confirmed pre-existing via `git blame`: both the test and the
`eval_forecast_correctness.py` module itself trace to commit `b75a3c1`
(2026-09-06) — same original commit as every item in #8 and #9, but
this is a genuinely separate, independent script/step (`TEST 0b`, not
part of `TEST 0`'s eval sequence at all) that was simply never reached
by any CI run until tonight's fixes removed everything blocking it.
Not caused by, or related to, anything touched tonight.

**Why this is NOT another quick same-night fix:** every item in #8 and
#9 was either a stale test fixture, a dead/unreferenced code path, or a
narrow dependency-declaration gap — safe to reason about and fix in
isolation late at night. This is different: it's REAL forecast/metric
business logic (how the renewal pipeline's conversion-rate denominator
gets scoped and whether it's being kept separate from the default
pipeline as designed). Getting this wrong in either direction (a
false-negative null suppressing a real number, or a scoping bug
quietly blending two pipelines that are supposed to stay apart) has
actual reporting/forecasting consequences if this ships. This deserves
a real, unhurried investigation into the scoping rule itself — reading
`eval_forecast_correctness.py`'s full test setup, the actual scoping
function it's testing, and forming a real hypothesis for why the
renewal population is coming back empty — not a late-night guess.

**Status:** ✅ FIXED. Investigated per Jeff's explicit decision: renewal
deals should NOT have a week-3 conversion rate at all (they don't move
through a qualification funnel — the concept doesn't apply, not "we
don't know the number"). Root cause: `_in_quarter_won_by_pipeline()`
(the numerator) counted a renewal win with no pipeline exclusion at
all, while the denominator already excluded the renewal pipeline via
the shared `is_deal_in_analytics_scope()` rule — the two sides were
never symmetric despite the code's own comment claiming they were.
Fixed by applying the same pipeline exclusion to the numerator (an
optional `excluded_pipelines` param, defaulting to the shared config).
Renewal now doesn't appear as a row in `by_pipeline` at all — absence,
not a 0-with-a-real-numerator or an explicit null, so "renewal
converts at 0%" (a value fact) can never be confused with "renewal
doesn't have this metric" (a scope fact). Test updated to assert this
correct behavior; verified passing for the right reason both locally
and in live CI (run #65).

**Documentation:** `scripts/analytics/forecast_analyses.py`'s updated
inline comment above `query_week3_conversion`; the updated
`test_numerator_and_denominator_share_scope`; this entry.

---

#### 11. `deals_snapshot` Has No `new_arr`/`expansion_arr` Columns — ✅ FIXED (migration 064)

**Issue:** Investigating the null-coalescing findings from #10's
verification chain (see the eval_reconstruction.py ratchet items below)
surfaced that `compute_forecast.py`'s week-3 average-deal-size fallback
reads `deal_value` from `deals_snapshot` because that's *all* it can
read — the table has never carried the two raw Incremental-ARR
components (`new_arr`/`expansion_arr`) that the `deals` table has had
since migration `007_add_reporting_fields.sql`. Checked every migration
touching `deals_snapshot` (`005`, `017`, `037`, `038`, `039`, `045`,
`060`, `062`) — its full column set is `deal_id, snapshot_date,
pipeline_id, stage_id, stage_order, deal_value, close_date, owner_email,
deal_status, snapshot_source, forecast_category, fiscal_quarter,
week_of_quarter, renewal_revenue, region, segment`. `renewal_revenue`
was added later (migration 045) specifically for GRR/NRR; the two
incremental components never were.

This matters because `config/client.yaml`'s own comment documents a
real, verified HubSpot hazard: HubSpot's own combined "Incremental ARR"
calculated field nulls out when *either* New ARR or Expansion ARR is
individually blank, even when the other is a real known value — this
codebase already avoids that hazard everywhere it CAN, by summing the
two raw components directly instead of trusting the combined field
(verified against 1,523 deals, zero disagreements). `deals_snapshot`
is the one place that can't, because the raw components were never
carried into the snapshot at all.

**Current stopgap (shipped tonight):** `compute_forecast.py`'s week-3
average-deal-size calculation null-propagates the existing `deal_value`
field instead — excludes unknown-value deals from both the sum and the
average's denominator, counts them, never zero-fills — matching
`compute_waterfall.py`'s already-established treatment of this exact
table/column. This is honest ("we can't recompute this, and we don't
fully trust a value that might reflect the HubSpot hazard") but not a
true fix — a deal_value that already avoided the hazard at write time
would be handled correctly, but a deal_value that inherited it upstream
would still silently understate.

**Fix shipped:**
1. **Migration `064_add_arr_components_to_snapshot.sql`** — adds
   `new_arr`/`expansion_arr` (`NUMERIC`, nullable) to `deals_snapshot`,
   with `data_dictionary` registration in the SAME migration (per the
   region/segment registration-gap lesson — migration 060 added
   region/segment without registering them, and the gap wasn't caught
   until migration 062, after it had already caused a real budget-
   exhaustion incident; this migration doesn't repeat that mistake).
   Point-in-time correct, not backfilled: per the exact lesson already
   learned from region/segment (`backfill_snapshot_enrichment.py`
   backfilled historical rows with CURRENT values, an acknowledged
   imperfect approximation) — existing historical rows get NULL and
   stay NULL. A deal's current ARR components don't reflect what was
   true at a past snapshot date; an honest unknown beats a wrong number.
2. **`scripts/analytics/snapshot_deals.py`** updated to read and write
   both columns going forward, starting from the next snapshot run.
   `renewal_revenue` is explicitly untouched — confirmed via
   `migration 045`'s own documented rationale that its NULL state is
   deliberate (already investigated, `deal_value` already includes
   renewal ARR via `compute_deal_value()`, do not backfill) — not a
   bug to fix alongside this one, even though it surfaced in the same
   investigation.
3. **`compute_forecast.py`'s Site 2** now recomputes Incremental ARR
   directly from `new_arr`/`expansion_arr` when either is present on a
   `deals_snapshot` row — mirroring Site 1 and avoiding the same
   HubSpot NULL-out hazard. Per-deal, not per-snapshot: a row where
   both components are genuinely NULL (a pre-migration/legacy row, or a
   deal with truly no known ARR components either way) falls back to
   that deal's own `deal_value`, still null-propagated (never zero-
   filled) if even that is missing.

**Verified:** two new eval scripts give this real, end-to-end
regression coverage for the first time —
`scripts/eval_compute_forecast_arr_recompute.py` (5 tests, runs
`compute_forecast.main()` against mocked Supabase data covering
recompute-from-components, both-blank exclusion, legacy-row fallback,
and genuinely-unknown exclusion) and
`scripts/eval_snapshot_deals_arr_fields.py` (3 tests, runs
`snapshot_deals.main()`, confirms `new_arr`/`expansion_arr` land on the
written row, confirms `renewal_revenue` is absent from every row and
from the file's source entirely). Notably, `compute_forecast.py` had
**zero** automated test coverage anywhere in this repo before tonight —
`eval_forecast_correctness.py`/`test_forecast_analyses.py` test a
different module (`forecast_analyses.py`) despite the similar name;
Sites 1 and 2's earlier fixes this same night were verified only by
direct logic simulation and `eval_reconstruction.py`'s null-coalescing
ratchet (which confirms the forbidden pattern is gone, not that the
new logic is correct end-to-end). These two new files close that gap.
`tests/test_data_dictionary_registration.py` confirms the migration's
dictionary entries satisfy the forward-looking registration gate.

**Documentation:** `scripts/migrations/064_add_arr_components_to_snapshot.sql`;
`scripts/analytics/compute_forecast.py` and `snapshot_deals.py`'s
updated inline comments; the two new eval scripts; this entry.

---

#### 12. Dimension-Verification Warning Observed to Dead-End Without Forcing a Retry — ✅ ROOT-CAUSED AND FIXED

**Issue:** While live-testing the historical new-vs-expansion ARR
questions (unrelated to the #11 schema fix itself — surfaced
incidentally during that testing, not caused by it), a
`⚠️ Verification failed: Question asked about New Business (pipeline)
but query never filtered for it. Retrieved data may be unfiltered.
Required query: filter_table with filters [...]` warning appeared and
the loop stopped there instead of forcing the retry this message is
supposed to trigger.

**Root cause, confirmed via exact-string match (not inference):**
`format_verification_error()` (`api/dimension_verification.py`) is
called from exactly ONE site in `api/router.py` — confirmed by
grepping for actual function *calls*, not just the two places that
import it — and that site is the finalization path inside
`_finalize_from_data()`, whose own log line said "Cannot retry (budget
exhausted). Returning diagnostic error." as if reaching this gate
always meant the loop's iteration/token budget was exhausted. It
doesn't: `_finalize_from_data()` is invoked from 10 different
`reason_tag`s across the loop (`no_progress`,
`scratchpad_prose_rejected`, `duplicate_tool_call`,
`id_scoped_enrichment_lookup`, `no_new_data`,
`aggregation_mismatch_unresolved`, `false_partial_claim_unresolved`,
`unknown_tool:*`, `dimension_retry_succeeded`, and
`iterations_exhausted`) — and only `iterations_exhausted` genuinely
correlates to the budget actually running out. Every other reason_tag
is an early, unrelated stop (a malformed response twice in a row, a
repeated tool call, an enrichment shortcut, etc.) that can fire with
plenty of iteration/token budget still available. The finalization
path's own dimension-verification gate assumed the "budget exhausted"
case unconditionally and shipped a bare diagnostic warning with no
follow-up regardless of which reason actually got it there — the exact
dead-end observed live.

**Fix (`api/router.py`, the finalization-path dimension-verification
gate inside `_finalize_from_data()`):** `verify_dimension_coverage()`'s
`required_query` is fully deterministic — an exact `filter_table` call
with `table`/`filters` already computed, nothing left for a model to
decide — so instead of giving up unconditionally, the gate now forces
that call directly (the same "force one deterministic corrective
fetch" pattern already used earlier in this same function for the
missing-snapshot-anchor case and the diff company-name backfill),
appends the result to `accumulated_data`, and runs one more finalize
resynthesis. If that resynthesis now verifies cleanly, a real,
corrected, `answered: True` answer ships. If the forced fetch itself
fails, or the resynthesis still doesn't verify, the loop gives up
**honestly and completely** — never a bare warning: the response
states both the original diagnostic AND, explicitly, that an automatic
retry was attempted and still could not produce a verified answer.
`cost_state["primitives_fired"]["dimension_verify_forced_fetch_fired"]`
tracks the mechanism firing, following the existing
`forced_anchor_fetch_fired`/`diff_company_name_backfill_fired`
convention (a mechanism marker, not a `FAILURE_MODE_PRIMITIVES`
detection primitive, since either outcome already changes what the
user sees by construction).

**Which of the 5 (or a 6th) path was the actual cause:** the
documented no-retry finalization path (site 2 of the original 5) —
confirmed definitively via the exact-string match, not the 4 "should
retry" sites and not a 6th unwired path. But the path's own
"budget exhausted" framing was wrong for most of the reason_tags that
actually reach it; the real bug was that assumption, not a missing
call site.

**Verified:** `tests/test_dimension_verify_finalize_retry.py`
reproduces the exact reported scenario as a fixture — a question
mentioning "New Business", an initial `filter_table` call against
`waterfall_weekly` with the exact `pipeline_id`/`week_ending` filters
from the live incident but no pipeline filter, driven into the
finalization path via `reason_tag="no_progress"` (two malformed
responses in a row — a real, non-budget-exhaustion reason) — proving
two things: (1) when the forced corrective fetch succeeds, a real
corrected answer ships (`answered: True`, the bare warning text is
never present in the final answer); (2) when the forced fetch itself
fails, the final message is honest and complete (states both
"Verification failed" and that an automatic retry was attempted and
still failed) rather than a bare dead-end warning. Full test suite
(33 files) passes.

**Documentation:** `api/router.py`'s finalization-path dimension-
verification gate (inline comment cites this entry); new
`tests/test_dimension_verify_finalize_retry.py`; this entry.

---

#### 13. Migration 064 Shipped in Code but Never Auto-Applied to the Live Database — Broke `weekly-snapshot.yml` Until Caught — ✅ FIXED, PROCESS GAP LOGGED

**Issue:** Migration `064_add_arr_components_to_snapshot.sql` (Low
Priority #11) was written, committed, and pushed — and the dependent
code (`snapshot_deals.py` writing the two new columns,
`compute_forecast.py`'s Site 2 reading them) shipped in the SAME
commit. But this repo's migrations do NOT auto-apply on push — they
require `scripts/setup_supabase.py` to be run with real credentials,
or the SQL pasted directly into Supabase's SQL Editor. Nothing ran
either, so the live database never actually got the new columns while
the code that depends on them was already live.

**Consequence:** manually triggering `weekly-snapshot.yml` to verify
the fix (as explicitly requested) surfaced the gap in the worst way —
the real production job failed:

```
postgrest.exceptions.APIError: {'message': "Could not find the
'expansion_arr' column of 'deals_snapshot' in the schema cache", ...}
Qualified deals for snapshot: 443 / 1,890
```

Because `snapshot_deals.py` includes both new columns in every upsert
batch unconditionally, Postgres rejected the entire batch — meaning
this run wrote **zero** snapshot rows for the day, not just rows
missing the two new fields. This would have recurred on the real
Monday 02:00 UTC scheduled run had it not been caught first. Audited
every other workflow that reads/writes these columns
(`weekly-analytics.yml`, `recompute-forecast.yml`) — neither had
actually run during the vulnerable window (last runs 2026-09-08 and
2026-08-11 respectively, before this code shipped), so nothing else
was actually broken, though both would have hit the identical error
had they fired first.

**Resolved:** migration 064 applied directly via the Supabase SQL
Editor and confirmed. Re-triggered `weekly-snapshot.yml` — succeeded,
443 rows written, `new_arr` populated on 373/443 and `expansion_arr`
on 368/443, with real captured values (e.g. a $200,000 Expansion ARR
on a live renewal deal, distinct from that deal's $322,062.50 total
`deal_value`) confirming the recompute genuinely works end-to-end in
production, not just against mocks.

**The real, standing lesson — not a one-off:** nothing in tonight's
workflow included a "confirm this migration is live before shipping
code that depends on it" checkpoint. The offline data-dictionary gate
(`TEST 0e`) only validates that a migration FILE would register its
columns correctly if run — it says nothing about whether the migration
has actually been applied to the real database. `TEST 1b` (the live
coverage check) would have caught this, but it's still blocked on the
missing `SUPABASE_DB_URL` secret (see the top-level "Last Updated"
history for that thread), so it provided no safety net here.

**Standing rule going forward:** any migration a commit's code depends
on must be confirmed applied to production BEFORE that commit's
dependent code ships — not after, and not assumed. Committing the
migration file and the dependent code together is fine; shipping
without confirming the migration actually ran against the live
database is the gap that caused this. Worth writing this into whatever
this repo's deploy/release checklist is (none currently exists as a
single document — `scripts/migrations/README.md` documents how to
create a migration, not a pre-flight check before shipping dependent
code).

**Documentation:** `scripts/check_snapshot_arr_fields.py` (the real
verification this incident produced); `.github/workflows/weekly-snapshot.yml`'s
`Verify snapshot coverage` step (previously a no-op echo, now runs
that script for real); this entry.

---

#### 14. Fictional `pipeline` Dimension Let Verification Falsely "Pass" a Silently-Dropped Filter — ✅ FIXED

**Issue:** Found while confirming the Low Priority #12 fix against a
real Slack question ("How has our new business ARR changed week over
week for the last 3 weeks"). The answer that shipped was headed "New
business pipeline ARR... (Sales Pipeline only)" — the client confirmed
"Sales Pipeline" is a single HubSpot pipeline object that holds New
Business AND Expansion deals together, so an answer scoped only to
that pipeline object is NOT the same as one scoped to New Business
specifically, even though it looked confident and detailed (real
dollar figures, real segment/region breakdowns) and carried no warning
at all.

**Root cause, confirmed via code + migration history, not inference:**
`api/dimension_verification.py`'s `load_known_dimensions()` has
hardcoded, since the primitive was written (2026-09-09):
`known_dims['pipeline'] = ['New Business', 'Renewal', 'Upsell',
'Cross-Sell']` — assuming a literal `pipeline` column holds these
values. Checked every migration that ever touched `deals`,
`deals_snapshot`, and `waterfall_weekly` (`006`, `007`, `011`, `016`,
`037`, `038`, `039`, `045`, `060`, `061`, `062`, `064`,
`add_region_segment_to_waterfall.sql`, `update_waterfall_constraint.sql`)
— **no column named `pipeline` has ever existed** (only `pipeline_id`,
the HubSpot pipeline *object* — a different concept). Confirmed further
via `scripts/discover_properties.py`'s own comment: "currency and
deal_type don't exist in Supabase deals table - removed." The one place
this repo actually derives deal type
(`verify_segment_scope_and_deal_type.py`) does it from
`deals.renewal_revenue` being null/0 (New Business) vs >0 (Expansion) —
a 2-way split that doesn't even match the 4 fictional values, and can't
be expressed as the single `['eq', col, value]` filter this whole gate
is built around (it needs "IS NULL OR = 0", not an equality match).

**Why this shipped a confident wrong answer instead of an error:**
`api/tools.py`'s `filter_table()` silently **drops** any filter naming
a column that isn't registered as queryable for that table
(`_validate_filters()`) — it never errors. So whenever the router (or
the Low Priority #12 fix's forced-retry mechanism) tried to "correct" a
query by adding `['eq', 'pipeline', 'New Business']`, that filter was
silently discarded before ever reaching Postgres, and the exact same
unfiltered (all deal types mixed) data came back. But
`check_dimension_filtered()` only ever checked `queries_run` — what was
*requested* — never what actually executed, so it saw the filter in its
own request log and reported "verified," even though nothing was
actually filtered. This bug **predates** tonight's Low Priority #12
fix and would have caused this same silent mis-scoping at any of the
original 5 dimension-verification call sites, any time a
pipeline/deal-type mention triggered the check. The #12 fix does change
the visible symptom for the finalization path specifically: previously
it would at least surface an honest "⚠️ Verification failed" warning
(since it couldn't retry); after #12, it "successfully" retries into
this false-positive pass and ships a confidently wrong-scoped answer
with no warning at all — worse for trust, even though #12 was correctly
built to the "never dead-end silently" spec it was given.

**Fix, two parts (`api/dimension_verification.py`):**
1. **Removed `pipeline` from `known_dimensions` entirely** rather than
   trying to patch it to a real column — it can never be correctly
   verified via this gate's eq-filter mechanism even in principle,
   given the real data model (see root cause above). A real fix needs
   either a materialized deal-type column (backed by `renewal_revenue`
   at ETL time, so it can finally be `eq`-filtered) or a content-based
   check (verify returned rows' `renewal_revenue` values actually match
   the claimed deal type) — a real schema/design decision, not a
   same-night patch. Documented in `load_known_dimensions()`'s
   docstring as an explicit, deliberate gap so nobody re-adds it without
   fixing the underlying data model first.
2. **General structural safeguard, for every dimension, not just this
   one:** `check_dimension_filtered()` now accepts an optional `sb`
   (threaded through from all 7 real call sites in `api/router.py`,
   which previously called `verify_dimension_coverage()` with no `sb`
   at all) and, when given, cross-checks a claimed filter's column
   against the same data_dictionary-backed valid-column set
   `filter_table()` itself validates against (`api.tools._VALID_COLUMNS`)
   before trusting it. A filter naming a column `filter_table()` would
   silently drop can never again count as satisfying verification, for
   any current or future dimension — closing the general mechanism that
   let this specific bug happen, not just this one instance of it.
   Degrades gracefully (falls back to the original queries_run-only
   check) if `sb` is `None` or column metadata can't be loaded, so
   existing offline callers (`test_verification_forced_retry.py`,
   `test_budget_exhaustion_improvements.py`) keep working unchanged.

**Verified:** `tests/test_dimension_verify_finalize_retry.py` — its two
original Low Priority #12 tests were ported from the now-removed
`pipeline`/"New Business" dimension to the real `region`/"EMEA"
dimension (still exercising the exact same forced-fetch retry
mechanism), plus three new tests: `pipeline` confirmed absent from
`known_dimensions`; a filter naming a column NOT registered as
queryable never falsely satisfies verification even though `queries_run`
claims it was applied; a filter on an actually-registered column still
verifies normally (safeguard doesn't break the common case). Full
suite (33 files) passes, plus both standalone root-level scripts using
the old 3-argument `verify_dimension_coverage()` signature still pass
unchanged (backward-compatible `sb=None` default).

**Documentation:** `api/dimension_verification.py` (docstrings on
`load_known_dimensions()`, `check_dimension_filtered()`,
`verify_dimension_coverage()`); `DIMENSION_VERIFICATION_IMPLEMENTATION.md`
(superseded-note added at top); `tests/test_dimension_verify_finalize_retry.py`;
this entry.

---

#### 15. Add a Materialized `deal_type` Column — SCOPED, NOT STARTED (deliberate follow-up)

**Issue:** Low Priority #14 removed the fictional `pipeline` dimension
rather than patch it, because no real column backs "New Business" vs.
"Renewal" vs. "Upsell" vs. "Cross-Sell" anywhere in this schema. That
was the honest fix for tonight (never falsely verify something that
can't actually be checked), but it leaves "New Business ARR"-type
questions in a real gap: the dynamic loop can no longer even attempt
to verify a deal-type filter, so such a question is either answered
without that guarantee, or (per #14's structural safeguard) never
falsely reported as verified — never a **safely, deterministically
filterable** answer the way an EMEA or Mid-Market question already is.

**Proposed fix (NOT started, explicitly deferred):** add a real,
materialized `deal_type` column — most likely on `deals` (and
propagated to `deals_snapshot` at snapshot time, the same pattern
migration 064 used for `new_arr`/`expansion_arr`) — populated at ETL
time so it becomes a normal, `eq`-filterable dimension like `region`/
`segment`, closing the gap #14 could only honestly document.

**Mandatory prerequisite — confirm with Jeff before writing anything:**
the only real signal currently in this codebase
(`verify_segment_scope_and_deal_type.py`) classifies deals as just
"New Business" (renewal_revenue null/0) vs. "Expansion" (renewal_revenue
> 0) — a 2-way split. The dimension this whole investigation started
from assumed 4 categories (New Business / Renewal / Upsell /
Cross-Sell). Before writing a migration or ETL logic, confirm with Jeff:
1. Is the real business distinction 2-way (New Business vs. Expansion)
   or genuinely 4-way? If 4-way, what HubSpot property (or combination)
   actually distinguishes Renewal from Upsell from Cross-Sell — none of
   the three collapses to a single existing column today.
2. Is `renewal_revenue` null/0 vs. >0 actually the right determining
   signal for "New Business" specifically, or is there a more direct
   HubSpot deal-type/lifecycle-stage property that should be the
   source of truth instead (the same kind of clarification the
   Incremental ARR formula needed earlier tonight before migration 064
   was written — don't assume, ask)?
3. Whether this should live on `deals` only, or also get backfilled/
   snapshotted onto `deals_snapshot` — and if snapshotted, whether it's
   point-in-time-correct to backfill historical rows (a deal's deal
   type is unlikely to change after creation, unlike region/segment/
   ARR components, so backfilling this one may not carry the same
   point-in-time hazard already documented for those — but confirm
   rather than assume).

**Standing lesson to apply once the logic is confirmed (Low Priority
#13):** register the new column in `data_dictionary` in the SAME
migration that adds it — not a follow-up migration — and confirm the
migration is actually applied to the live database (SQL Editor or
`setup_supabase.py`) BEFORE shipping any code that depends on it, per
#13's standing rule. Once the column exists and is registered, restore
a `pipeline`/deal-type entry to `dimension_verification.py`'s
`known_dimensions` pointing at the real column — closing the loop #14
opened.

**Complexity:** Low once the business logic is confirmed (a migration
+ ETL column derivation + data_dictionary registration, following the
064 pattern almost exactly); the actual work is confirming the right
determining logic first, not the implementation.

**Documentation:** none yet — scoped here per explicit instruction to
treat this as a separate, deliberate follow-up, not same-night work.

---

#### 16. Real Deal-Type Dimension Resolution (New Business / Expansion / Upsell / Renewal) Using Existing Data — ✅ FIXED

**Issue:** Low Priority #14 correctly stopped `dimension_verification.py`
from falsely "verifying" a fictional `pipeline` dimension, but that left
"New Business ARR"-type questions with no code-level backstop at all —
either answered without any filter guarantee, or (per #14's safeguard)
never falsely marked verified. Explicitly requested as a same-night fix
(unlike #15's materialized-column follow-up): wire a REAL deal-type
mapping into `resolve_dimension_filter()` — the same PROACTIVE
resolution pattern already proven for region/segment/roster terms
(api/dimension_resolver.py) — using data that already exists, no
migration needed.

**Mapping implemented** (`api/dimension_resolver.py`):
- "New Business" / "New" → `deals.new_arr > 0`
- "Expansion" / "Upsell" → `deals.expansion_arr > 0`
- "Renewal" → `deals.pipeline_id = <config/client.yaml's configured
  renewal_pipeline_ids[0]>` (866608541 for this client — read from
  config, not a second hardcoded literal)

`new_arr`/`expansion_arr` have existed on `deals` since migration 007;
`pipeline_id` since the base schema — confirmed real, queryable, no
migration required, unlike #15's proposal.

**Deliberately NOT the same definition as
`api/field_semantics.py`'s `is_renewal_base()`/`is_incremental_pipeline()`**
(GRR/NRR-specific: renewal base additionally requires
`renewal_revenue > 0`, and "pipeline"/incremental ARR excludes pure
renewal base). This maps the plain-English TERM a question uses to
what it most naturally means for an ad-hoc question — two different,
deliberately separate definitions for two different purposes, not an
inconsistency. Documented inline where both live so a future reader
doesn't mistake this for a contradiction.

**Non-mutual-exclusivity, handled explicitly:** a deal can independently
match Renewal AND Expansion at once (a renewal that also carries
expansion ARR). `format_dimension_resolution_note()` now appends an
explicit "query each condition separately and report the UNION, not
the intersection" directive whenever 2+ deal-type terms are resolved
together — the opposite of how region+segment combine (an "EMEA
Enterprise" question DOES mean the intersection), so this needed to be
said explicitly rather than left to the model's existing AND-pattern
default.

**Honest historical gap, handled explicitly:** `deals_snapshot.new_arr`/
`expansion_arr` only exist from migration 064's rollout (2026-09-11)
forward (Low Priority #11/#13); `deals` itself has always had them. A
second directive fires specifically for new_arr/expansion_arr-backed
terms (not Renewal, which has no such gap) stating this cutoff
explicitly and instructing the model to say so honestly for a
pre-cutoff `deals_snapshot` point-in-time question rather than reading
a missing value as zero/absent — same honest-gap pattern as every
other "can't answer this precisely" case in this codebase, never
silently wrong.

**Scope boundary, explicit:** proactive resolution only
(`resolve_dimension_filter()`/`scan_question_for_known_dimension_terms()`),
matching exactly what was asked ("same pattern already proven for
EMEA/Enterprise/rep names" — those are proactive-only too).
`dimension_verification.py`'s REACTIVE backstop was deliberately NOT
extended to cover these terms: its `required_query`-building logic is
hardcoded to `eq`-only, single-column-equals-value semantics
(`required_filters.append(['eq', dim_name, value])`), which doesn't
fit "New Business" (needs `gt` on a *different* column, not an `eq` on
a column named after the dimension). Extending that would be a real,
separate refactor, not in scope here.

**Verified:** `tests/test_deal_type_dimension_resolver.py` (14 tests) —
11 unit-level (each alias resolves to the exact correct filter; "new"
alone is denylisted from the opportunistic scan but "New Business" the
phrase still fires; case/hyphen insensitivity; the union note fires
only for 2+ deal-type terms; the historical-gap note fires only for
new_arr/expansion_arr terms, never for Renewal alone; a plain
region/segment question is unaffected by either new note) plus 3
end-to-end tests driving the real `dynamic_query_loop`, one per example
question from the ask: "what's our current New Business pipeline"
(directive reaches the model, correct `new_arr.gt.0` filter_table call,
real answer ships), "what's our win rate on Expansion deals" (same,
`expansion_arr.gt.0`), and "show me Renewal+Expansion deals" (both
terms resolve with the union directive present, the two categories are
queried as SEPARATE `filter_table` calls — asserted never ANDed
together into one — and the final answer covers both). Full suite (36
files) passes; both standalone root-level scripts using the pre-#14
`verify_dimension_coverage()` signature still pass unchanged.

**Documentation:** `api/dimension_resolver.py` (module docstring,
`_deal_type_candidates()`, `_load_renewal_pipeline_id()`,
`format_dimension_resolution_note()`); `tests/test_deal_type_dimension_resolver.py`;
this entry. Low Priority #15 (the materialized `deal_type` column)
remains open and unaffected — this fix closes the *filterability* gap
using existing data today; #15 is still worth doing later if a
genuinely 4-way (not 2-way) breakdown, or point-in-time historical
deal-type filtering on `deals_snapshot`, ever becomes necessary.

---

#### 17. `query_pipeline()`'s `pipeline_filter` Silently Never Worked in Either Direction — ✅ FIXED

**Issue:** A live Slack question, "what's our current New Business
pipeline," shipped a confident, fully-formatted answer titled "Current
New Business Pipeline (Incremental ARR)" that included 11 deals in
Upcoming Renewal / Renewal Engaged stages — with no caveat at all. This
is the exact failure mode the primitive-visibility work this session
built to catch: a scoped answer confidently including data outside its
claimed scope.

**Which handler answered — confirmed structurally, not guessed:** the
response's shape (Pipeline by Stage / Pipeline by Owner / Top Deals by
Size / Data Hygiene Flags, with the exact phrasing "Current Pipeline
(Incremental ARR)" and "hygiene issues") is unique to `query_pipeline()`'s
own structured return value and its embedded `_synthesis_note` —
no `dynamic_query_loop` synthesis produces this shape. This means Low
Priority #16's new deal-type resolver (built earlier tonight)
**could not have been involved**: `resolve_dimension_filter()`/
`scan_question_for_known_dimension_terms()` only ever run inside
`_dynamic_query_loop_core`, and dedicated handlers like `query_pipeline()`
are dispatched via a completely separate intent-classification path
that never reaches them. This was the pre-existing "OLDER handler"
branch of the investigation, unrelated to tonight's earlier fixes.

**Root cause, confirmed via git blame + the literal comparison logic:**
`query_pipeline()` has its own `pipeline_filter` param ("new_business" /
"renewal") with in-memory exclusion logic, unchanged since the
handler's first commit (`b75a3c1`, 2026-09-06):
```python
if pipeline_filter == "new_business" and "renewal" in pipeline_id.lower():
    continue
if pipeline_filter == "renewal" and "renewal" not in pipeline_id.lower():
    continue
```
`pipeline_id` is always the raw numeric HubSpot pipeline id —
`"default"` or the renewal pipeline's id, `"866608541"` for this client
(the same value `field_semantics.py`'s `is_incremental_pipeline()`,
called two lines above in this same function, already compares
correctly via exact equality). Neither value has ever contained the
literal substring `"renewal"`, so this check could never match either
real value: `pipeline_filter="new_business"` silently excluded
**nothing** (every deal, renewal-pipeline included, passed straight
through — the exact reported symptom, since those 11 deals correctly
carry real `expansion_arr` and so correctly count toward the *general*
"Incremental ARR Pipeline" metric, which is what leaked through
unfiltered), and `pipeline_filter="renewal"` silently excluded
**everything** (always returned zero deals, the opposite failure, in
the same code, undiscovered until now because nobody had asked a
"renewal pipeline" question against this exact handler and noticed the
empty result).

A contributing visibility gap made this hard to confirm from logs
alone: the handler's own `[QUERY_PIPELINE_FILTER]` defensive log line
(added earlier this session, TEST 0t's audit) only logged the
DB-level `base_filters` — `stage_filter`/`pipeline_filter` are applied
IN-MEMORY further down and were never logged at all, so there was no
way to tell from logs whether `pipeline_filter="new_business"` was
even set for a given request.

**Fix (`api/handlers.py`):**
1. Replaced the substring check with an exact-value comparison against
   `field_semantics._RENEWAL_PIPELINE_ID` — the SAME constant
   `is_incremental_pipeline()` already trusts in this exact function,
   rather than a third, differently-broken copy of the renewal-pipeline
   concept.
2. Extended the existing `[QUERY_PIPELINE_FILTER]` log line to also log
   `stage_filter`/`pipeline_filter`, closing the exact gap that made
   this bug hard to confirm from logs during this investigation.

**Verified:** `tests/test_query_pipeline_pipeline_filter_bug.py` (4
tests) — confirms the real renewal pipeline id never contains the
substring "renewal" (the root-cause proof itself); the unfiltered case
is unchanged (both a New Business deal and a renewal-pipeline deal
with real expansion ARR correctly count toward the general Incremental
ARR pipeline); `pipeline_filter="new_business"` now correctly excludes
the renewal-pipeline deal (previously included it — the live
incident); `pipeline_filter="renewal"` now correctly returns the
renewal-pipeline deal instead of zero (the previously-undiscovered
opposite-direction failure). Confirmed the fix actually catches the
regression by re-running the new test against the pre-fix code via
`git stash` — it fails with the exact reported symptom, then passes
again once restored. Full suite (37 files) passes, including the
pre-existing `tests/test_handler_filter_logging.py` and
`tests/test_owner_email_canonicalization.py` (both still pass
unchanged, confirming the log-line and owner-email-resolution paths
this fix touches weren't disturbed).

**Documentation:** `api/handlers.py` (`query_pipeline()`'s pipeline-
filtering block and its defensive log line, both with inline comments
citing this entry); `tests/test_query_pipeline_pipeline_filter_bug.py`;
this entry.

---

## 📝 Notes

### Patterns Established

**Data Hygiene Rules:**
All follow same discipline: **filter at data layer, not silently in metrics**
- `is_valid_cycle_deal()` - excludes negative cycle times
- `is_fresh_pipeline_deal()` - excludes stale deals (>180 days)
- `is_incremental_pipeline()` - distinguishes pipeline from renewal base
- `is_test_deal()` - excludes test/demo data ✅

**Data Dictionary Registration:**
Schema changes for query handlers require data_dictionary registration:
1. Add column to database schema
2. Populate with data
3. Register in `data_dictionary` with `is_queryable=True`

Without step 3, LLM query builder cannot see the column exists.

**Detection Primitives — see `PRIMITIVE_CHECKLIST.md`:**
Any new "detects a correctness problem" check in `dynamic_query_loop`
(aggregation totals, scratchpad narration, snapshot-date labeling,
dimension ambiguity, and any future one) must satisfy two things
before it's done, enforced by `tests/test_primitive_contract.py`:
1. Its failure writes to a queryable field (an outcome bucket or a
   distinct `reason_tag` in `query_cost_log`) — never only a log line
   or `primitives_fired`'s JSONB.
2. Its failure changes what the user sees when unresolved — a caveat
   or an honest give-up — never silent shipping of a plausible-looking
   wrong answer. Same "exists but not applied" gap pattern as the
   Related Issues below: `verify_aggregation_completeness()` correctly
   detected a bad total twice, live, and shipped it wrong both times
   because the retry told the model to "recheck" instead of handing it
   the already-computed correct value — found and fixed 2026-09-11,
   then two more primitives (`verify_snapshot_date_labeling`, the
   ambiguous-dimension-term flag) found with the exact same gap in the
   same retroactive audit.

### Related Issues

**Same "exists but not applied" gap pattern:**
- property_history implementation (existed, not used)
- coaching config (existed, not used)
- is_test_deal() (existed, NOW WIRED - commit fd2c29e)

**Lesson:** When implementing new functions/configs, immediately wire them into the handlers that should use them. Don't let them sit as "tested-but-unused" code.

---

## 🔄 Process

**To add new work:**
1. Document the issue (what/why/impact)
2. Design the fix (what changes needed)
3. Estimate complexity
4. Add to appropriate priority section
5. Create detailed .md file if needed (like TEST_DATA_HYGIENE_RULE.md, REGION_WATERFALL_GAP.md)

**When starting work:**
1. Move item to "In Progress" section
2. Add date started
3. Create task tracking if multi-step

**When completing work:**
1. Move to "Recently Completed" section
2. Add completion date
3. List commits
4. Note any documentation created
5. After 30 days, archive to separate COMPLETED_WORK.md file

---

## 📊 Summary

**Total Open Items:** 9
- High Priority: 4 (⚠️ URGENT: committed DB password needs rotation,
  snapshot ETL phantom exits, query_pipeline_movement zero-row mystery
  for an SDR — mitigated but not root-caused, and a follow-up
  canonicalization gap in 5 other dedicated handlers — logging shipped,
  fix still pending)
- Low Priority: 5 (zero-day cycle times, forecast bugs, rep-name-to-email
  matching, snapshot ETL date.today() day-boundary stamp, dead
  synthesis_aggregation_fix.py needs deleting or marking historical)

**Recently Completed:** 6
- Budget exhaustion on snapshot-diff questions (2026-09-11) - **FIXED & CI-GATED** (data-dictionary registration gap eliminated a round-trip; ID-scoped enrichment shortcut generalized; new data-dictionary-coverage gate added, same shape as the date-resolution gate)
- Date resolution single-source-of-truth audit (2026-09-10) - **FIXED & CI-GATED** (4 instances of the same bug class, one structural gate)
- Synthesis aggregation gap (2026-09-09) - **TESTED & VERIFIED** (core bug fixed; ⚠️ its own "-$120K/last 2 weeks" test window has since been found wrong — see caveat, needs re-verification)
- aggregate_results empty data bug (2026-09-09) - **IMPLEMENTED & VERIFIED** (Sept 6 impact: LOW)
- Waterfall region + segment segmentation (2026-09-08) - **PRODUCTION VERIFIED**
- Test data hygiene (2026-09-08)

**Major Milestones:**
- Date resolution fixed structurally, not case-by-case: resolve_time_window() is now the only place "today"/relative time phrases become dates anywhere in api/, with a CI gate (tests/test_date_resolution_single_source.py) that fails the build on a new parallel implementation. Confirmed the 952/954 waterfall backfill reconciliation is unaffected (it never resolves "today" at all).
- Synthesis aggregation gap fixed: Eliminated week/segment anchoring and false "partial" claims. Test results show complete data reporting with no dropped segments or activities.
- Region-segmented waterfall production-verified with 972 historical rows across 56 weeks (Aug 2025 → Sep 2026), enabling accurate EMEA/APAC/LATAM/NAM pipeline reporting by company size segment.
- aggregate_results 66.7% failure rate fixed with three-layer validation (prompt + tool + router), verified no real user harm (Sept 6 answer accurate despite internal failure).
