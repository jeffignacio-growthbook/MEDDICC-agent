# Pending Work

**Last Updated:** 2026-09-23 (#33 placement fallback, YAML latency, #36 deals-ETL failures resolved; Supabase deals staleness mitigated 24h → ~4h; incremental deal sync and LOW test_question.py flag open)
**Purpose:** Single tracking mechanism for all documented-but-not-implemented work

---

## 🟡 Open Items

### 🟠 MEDIUM: Incremental deal sync to cut Supabase `deals` staleness below ~4h (found 2026-09-23)
**Status:** OPEN. This is the real fix; the 4-hour cron below is a stopgap.
Scope it carefully, on its own; don't rush it.

**Why:** only `etl_deals.py --mode analytics` writes Supabase `deals`, so its
schedule sets the worst-case staleness of every deal field against HubSpot
(see "Supabase deals up to 24h stale" under Recently Completed).

**Plan:** an hourly (or more frequent) job that fetches only the deals
modified since a stored checkpoint and upserts them. The full design, from
the 2026-09-23 audit, covers the checkpoint table, a 30-min overlap,
`hs_object_id` keyset paging, deletion handling and a ~12h full
reconciliation.

**Correction (2026-09-23 audit):** an earlier version of this entry said
`HubSpotDealsClient.get_deals_modified_since()` "already exists and is
unused" and "requests the same property list as
`get_all_deals_including_closed()`". **Both were wrong:**
- **It isn't unused, it's dead.** Its one caller, the delta check in
  `scripts/run_nightly.py` (~line 649), passes `counter.get('last_run_date')`.
  Since 2026-08-10 (`6cfd6a67`, per-run counter files) the rollup counter
  has no `last_run_date` key, so the argument is always `''` and the branch
  never runs. Even when it did run, it only printed a count and never wrote
  anything.
- **It requests only 8 properties:** `dealname`, `dealstage`, `pipeline`,
  `closedate`, `amount`, `incremental_arr`, `hubspot_owner_id`,
  `hs_lastmodifieddate`. It has no `new_revenue`, `expansion_revenue`,
  `prior_arr`, `renewal_revenue`, `sao`, forecast category or `bdr_owner`.
- **It would fail if it ran.** Its documented input format (ISO without a
  timezone, e.g. `'2026-08-01T02:00:00'`) returns **HTTP 400** from
  deals/search (probe run 35899912562). The caller catches the error and
  prints a warning.

**Don't reuse it as-is.** The sync needs a new fetch: the full property
list, epoch-millisecond filter values, and keyset paging on `hs_object_id`.

**⚠️ Boundary safety is the whole risk.** A "since last successful run"
watermark is exactly the kind of mechanism behind this session's
transcript-ETL cutoff bug, where a boundary condition silently dropped
records. A deal whose edit lands late for a window already processed must
never be silently skipped. Build in, and test with real boundary cases:
- Only advance the watermark after a fully successful run. Store it
  durably, not in memory. Any failed or partial run leaves it where it was.
- Advance to the max `hs_lastmodifieddate` actually received, never to the
  wall clock. Overlap each window by a safety margin (e.g. re-read the last
  15-30 min), and rely on idempotent upserts to absorb the duplicates.
- Test edits exactly at the boundary, edits whose `hs_lastmodifieddate`
  arrives late, clock skew, and a run that fails halfway. The search cap of
  10,000 results per query needs a paging strategy for a large backlog
  (e.g. split by date range).
- Keep the full every-4h analytics run as a reconciliation backstop, and
  have the incremental job report how many deals it fetched vs upserted,
  like the #36 RUN SUMMARY.

### 🟢 LOW: `scripts/test_question.py` prints "Answered: False" for every direct dynamic_query answer (found 2026-09-23)
**Status:** OPEN. Cosmetic, but it reads as a failure.

**What:** `route_question()`'s direct `dynamic_query` return
(`api/router.py` ~line 5838: `{"answer", "needs_ack", "tool_results",
"handler_name": "dynamic_query"}`) drops the loop's `answered` flag, so
`test_question.py:107` (`result.get('answered', False)`) prints
`Answered: False` even for a complete, correct answer. Seen on the
2026-09-23 live verification of Ryan's question.

**Fix plan:** pass `"answered": dynamic_result.get("answered")` through
in that return (and the two sibling dynamic returns that also drop it),
so the flag reflects the loop's real outcome.

---

## ✅ Recently Completed

### MEDIUM: Ghost deal deleted in HubSpot, still active in Supabase for six weeks (found and fixed 2026-09-23)
**Status:** ✅ FIXED 2026-09-23 (migrations 067 + 068, applied to production).

**What:** Inditex **29591984407** ("Inditex - 2025 renewal (should
expand)", renewal pipeline, stage Upcoming Renewal) was deleted in HubSpot
at 2026-08-11 23:26:35Z. HubSpot confirms it: the deal is in
`GET /crm/v3/objects/deals?archived=true`, and a normal GET returns 404.
deals/search never returns archived deals, so no ETL ever learned about
the deletion. Its `deals` row (last written 2026-08-11 20:03Z) stayed
`deal_status='active'`, and every weekly snapshot kept re-adding it. That's
because `snapshot_deals.py` reads every `deals` row and filters by stage,
not status.

**Impact (counts, not dollars):** every value field was $0 or null, so no
dollar total moved anywhere.
- **Snapshots:** 12 `deals_snapshot` rows dated after the deletion
  (2026-08-17 .. 09-21) showed it as an open renewal, so renewal-pipeline
  counts from snapshots for those dates were 1 too high.
- **Forecast:** `forecast_weekly` counts open deals by close-date quarter,
  and its close date was 2025-07-11, so only that past quarter's renewal
  row had +1 open deal (at $0).
- **Unaffected:** the waterfall and pipeline-generation "created" counts
  (it was created in 2024), and `query_upcoming_renewals` for any forward
  window.
- **Slack answers that cited it:**
  - 2026-09-02 18:44 UTC ("$0 renewal, past due");
  - 2026-09-06 04:47 and 16:22 UTC ("the 1 active deal missing an owner",
    recommending someone assign an owner to a deleted deal);
  - 2026-08-28 06:56 UTC, possibly: it lists "Inditex — $0 (TBD) | Jul 11
    (Cary)", but the ghost had no owner, so this may be another deal.

**Fix:**
- **067** adds a `deleted_deals` tombstone table. A status flag on `deals`
  wouldn't work: consumers filter status in different ways
  (`neq won`/`neq lost`, no filter at all in the snapshot writer, and
  model-written dynamic queries), so a 'deleted' flag would slip through.
  Moving the row out makes `deals` mean "exists in HubSpot" for every
  consumer.
- **068**, in one transaction, writes the tombstone (the full deal row plus
  the 12 post-deletion snapshot rows), then deletes those rows. The 54
  pre-deletion snapshots stay, because they're correct history.

**Result:**
- `deals` went from 1,957 to **1,956**, which equals HubSpot's own search
  total.
- `deals_snapshot` went from 28,684 to 28,672.
- The snapshot diff now shows the deal leaving in the week it was actually
  deleted.

**Still open:**
- Deletion handling in the incremental sync (below) finds future cases
  automatically.
- Historical diffs that join pre-deletion snapshots to `deals` for company
  names will show no name for this deal. The name is kept in
  `deleted_deals.deal_row`.

### HIGH: ETL failure alerts could never fire (found and fixed 2026-09-23)
**Status:** ✅ FIXED 2026-09-23.

**What:** `scripts/alert_etl_failure.py` counts failures in Supabase
`etl_failures` and alerts at the 2nd one. It has three gaps:
- **No credentials.** The Daily Deal and Daily Calls ETL alert steps passed
  only `ZAPIER_ALERT_URL`, not the Supabase credentials the counter needs.
- **Silent fallback.** On that error `record_failure()` returned 1 ("first
  failure"), below threshold, so no alert was ever sent. The code's own
  comment said "alert anyway". `etl_failures` had **0 rows, ever**.
- **No alert at all.** The Daily Analytics ETL (every 4h since #37, and the
  only writer of Supabase `deals`) had no alert step.

**Fix:**
- An unknown failure count now alerts (fail open).
- The db imports are lazy, so an import error degrades to "alert anyway"
  instead of crashing the alert step.
- All three workflows' alert steps get `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`,
  step-scoped, so the Daily Deal ETL step still has no Supabase access.
- The analytics workflow gets the alert step, with `--job etl-deals-analytics`.
- Test: `tests/test_etl_failure_alert.py` checks the alert logic and pins
  all three workflows' alert wiring, with planted pre-fix controls.

**Not live-tested:** a real Zapier send. That posts to the channel, so it
needs sign-off first.

**Known quirk, left as is:** despite the name, the "consecutive" count is
the number of failures in the last 3 days, not reset by a success. That
errs toward alerting.

### MEDIUM: Supabase `deals` up to 24h stale vs HubSpot (found 2026-09-23; mitigated to ~4h)
**Status:** ✅ MITIGATED 2026-09-23. `daily-analytics-etl.yml` cron changed
from `0 4 * * *` to `0 */4 * * *`. The real fix, an incremental sync, is
open above.

**Finding:** Ryan's "pipeline added in the last two weeks" answer said
**$2,776,296 / net $1,798,796** at 04:59 UTC. At 16:13 the same question
said **$2,726,296 / net $1,748,796**. Same 24 added and 10 exited deals,
exactly $50,000 lower. HubSpot's property history reconciles it to the
dollar with two edits made the evening before, both by HubSpot user
84883357:
- **Twitch** (61032303431): `new_revenue` $150,000 → $250,000 at 2026-09-22 19:19Z.
- **Engine / Gen™** (64576827032): $200,000 → $50,000 at 20:05Z.

So (150k + 200k) − (250k + 50k) = +$50,000.

HubSpot already held the new values at 04:59: the 24 deals summed to
$2,726,295.68 then, the same as now. **The 04:59 answer was wrong when it
was given.** Supabase still had the values from the 2026-09-22 09:05
analytics run until the 2026-09-23 09:07 run replaced them.

**Cause:** `etl_deals.py --mode analytics` is the only job that writes
Supabase `deals`. The Daily Deal ETL (active mode) runs without
`SUPABASE_URL`, and all 57 runs log `⏭️ SUPABASE_URL not set — skipping
Supabase write`, so it only writes `memory/deals/index.json`. With one
writer running once a day (cron 04:00, actual starts ~09:05 because of
GitHub schedule delay), the **whole row** was up to ~24h behind HubSpot.

**Correction of the record:** my first explanation said active mode
refreshed `arr_usd` at 02:40 but not `new_arr`/`expansion_arr`, leaving
fields in one row of different ages for ~6.5h a day. That was **wrong**:
active mode never writes Supabase at all. The ETL does gate those four
fields to analytics mode, but that doesn't matter while active mode has no
Supabase access. The planned "make active mode write ARR" fix would
therefore have changed nothing and was dropped.

**Cost of every 4h:** $0 in Actions minutes, since this is a public repo on
standard runners (6 × 8-12 min ≈ 48-72 runner-min/day). HubSpot load is
~60 requests per run, and Supabase load is ~3.9k small requests per run.

**Caveat:** GitHub delays scheduled runs, and the old 04:00 cron actually
started ~09:05, so "~4h" is nominal. Real gaps can be longer, which is one
more reason for the incremental sync.

### HIGH: Deals ETL swallowed HubSpot failures and exited 0 (found and fixed 2026-09-23)
**Status:** ✅ FIXED 2026-09-23.

**What:** `scripts/hubspot_deals.py` made bare `requests` calls, with no
retry and no 429 handling. Every failure path in `scripts/etl_deals.py`
printed a message and returned, so the process exited 0 and the Actions run
showed green, with the "Alert on failure" step skipped.

**It already fired three times.** Daily Deal ETL runs #18 (2026-08-15), #40
(2026-09-06) and #41 (2026-09-07) each logged `❌ Failed to fetch deals: 429
Client Error: Too Many Requests for url:
https://api.hubapi.com/crm/v3/objects/deals/search`. Each fetched 0 deals,
committed nothing, and left `memory/deals/index.json` a day stale. All 57
runs were checked; the 3 analytics runs were clean.

**Two latent corruptions in the same code (not seen in logs):**
- A company-association or company batch that failed wrote
  `company_id=None`, `segment='Unknown'` and `segment_reason='no_company'`
  over good values.
- An owner-fetch failure would have written `owner_email=''` over every deal.

**Fix:**
- `scripts/http_retry.py` holds the one retry mechanism, extracted from
  `transcript_store.fetch_utterances` (#28). That function now calls it
  too, and its behaviour is unchanged: `eval_transcript_store` 48/48 and
  `eval_etl_supabase_persist` ALL PASS, before and after.
- `HubSpotDealsClient._request` makes 5 attempts:
  - 429 honours Retry-After, else waits 15/30/60/120s;
  - 5xx and network errors wait 2/4/8/16s;
  - other 4xx responses fail at once.
- `etl_deals.main()` returns an exit code, and the entry point is
  `sys.exit(main())`. The policy is explicit in the code:
  - **fatal, exit 1, nothing written:** client or owner fetch, deal fetch,
    CSV load, creating the Supabase writer;
  - **partial, exit 1, good data written:** a batch or upserts still failing
    after retries. The affected deals keep their stored company fields in
    Supabase and in the index.
- A RUN SUMMARY prints fetched, processed, preserved, upserted/failed and
  retries taken.
- Test: `tests/test_deal_etl_failure_handling.py`, with planted-bug controls.

### MEDIUM: Config YAML re-parsed hundreds of times per dynamic question (found and fixed 2026-09-23)
**Status:** ✅ FIXED 2026-09-23.

**Cause:** `api/dimension_resolver.py:_load_yaml()` opened and re-parsed
its file on every call, with no caching. Every per-term helper
(`_load_regions`, `_load_segment_names`, `_load_roster`,
`_load_renewal_pipeline_id`) calls it, and `_all_known_values()` calls
all of them. A term that resolves costs 1 regions.yaml + 2 client.yaml
parses. An unknown term costs 3 + 6, because the unknown_value path in
`resolve_dimension_filter()` calls `_all_known_values()` twice. Both
`scan_question_for_*` functions try every word and word-pair, and most
of those are unknown, so parse count grew with question length. The
scan docstring's claim that "resolving a term is an in-memory config
lookup" was false. Slow since the scans shipped (2026-09-11, ba350116);
2026-09-16's 6dc0f01e added the second `_all_known_values()` call (for a
log line), doubling the cost of every unknown term. No other module reads config per term; the other
config reads (handlers, time_resolver, db, plausibility, ...) happen
once per request.

**Fix:** `_parse_yaml_once()` (`functools.lru_cache`) parses each file
once per process. `_load_yaml()` returns a deep copy, so a caller that
mutates its result can't corrupt the cache. This deliberately differs
from the original "path plus mtime" plan. Nothing writes these files
at runtime; they change only through a deploy, and each Railway deploy
starts a fresh `uvicorn api.main:app` process, so there is no
stale-config risk in production. Locally, editing a config YAML now
needs a server restart (`--reload` only watches .py files).

**Measured (offline, same container, before = origin/main 1c88b505):**

| | Before | After |
|---|---|---|
| Both scans, 151 questions (every distinct `query_cost_log` question + 24-question battery + `tests/regression_questions.txt`) | 1015.6s total; median 5.7s, p95 15.0s, max 56.3s | 8.7s total; median 48ms, p95 130ms, max 473ms |
| YAML parses in those scans | 40,895 (max 2,322 per question) | 2 (one per file, whole process) |
| Ryan's "added in the last two weeks" question, scans only | 16.3s | 134ms |
| Same question, full offline `dynamic_query_loop` (canary_harness, 3 runs) | 16.5 / 16.1 / 15.9s; 635 parses | 0.39 / 0.27 / 0.27s; 5 parses (all once per request) |

**No behavior change:** the resolution output (known and ambiguous
terms) for all 151 questions is byte-identical before and after. 34
questions have at least one known term and 4 have an ambiguous one.

**Regression test:** `tests/test_dimension_resolver_config_cache.py`,
wired into `pr-offline-tests.yml`, checks four things:
- at most one parse per file across 6 dimension-heavy questions;
- the cached read equals a fresh parse;
- 12 terms, covering every outcome type, resolve identically cached and
  uncached;
- mutating a returned config doesn't reach the cache.

Planted-bug controls: restoring the old reader is caught (1,408
client.yaml / 706 regions.yaml parses), and so is dropping the deep copy.

### HIGH: Aggregation placement-corruption fallback had never worked (found and fixed 2026-09-23)
**Status:** ✅ FIXED 2026-09-23 (PR #33). Broken from the moment it was introduced (2026-09-15, 8bae539)
until this fix; it never once blocked a corrupted answer.

**What:** in `_finalize_from_data`'s aggregation retry (`api/router.py`,
~line 4211 at 5f58fcf), when `verify_total_placement()` detects
placement corruption in the resynthesized answer, the code is meant to
"force honest fallback instead of shipping corrupted data":
```python
return _diagnostic_answer(
    tail, "aggregation_placement_corruption"
)
```
`tail` is not defined in that scope. `_diagnostic_answer(tail, reason_tag)`
(~line 3556) takes it as a parameter, but this call site never binds it
(pyflakes: `undefined name 'tail'`). The `NameError` is raised inside a
`try:` whose `except Exception` only logs `[AGGREGATION_VERIFY]
resynthesis retry raised: ...`, and then execution falls through to ship
the retry's answer anyway.

**Impact:** this safety net has provided zero protection since it was
written. Every detected placement corruption on the finalize path ships
the corrupted answer, and it looks like a caught exception rather than
the detection it actually was. There's a second defect on the same line:
even with `tail` bound, `_diagnostic_answer()` returns a string, but the
caller must return `{"answer", "tool_results", "answered"}`. So the fix
should route through `_give_up(...)` (or build the dict) and not just
define `tail`.

**Fix plan:** replace the call with `return _give_up("aggregation_placement_corruption",
"<business-language tail>")`. Then add a test that drives a
placement-corrupted resynthesis through `_finalize_from_data` and asserts
the diagnostic ships with `answered=False`, not the corrupted text.
Negative control: re-introduce the undefined name and require the test
to fail.

**Resolution (2026-09-23):**
- **Confirmed live:** the detector fired correctly ("finalize retry placement
  corruption: Corrected value … appears 2 times"). Then `NameError: name 'tail'
  is not defined` was raised in `_finalize_from_data`, logged only as
  "[AGGREGATION_VERIFY] resynthesis retry raised: …", and the corrupted
  answer shipped with `answered=True`.
- **Never worked:** introduced in 8bae539 (2026-09-15, "Rebuild aggregation
  placement fix at primitive level") with `tail` already undefined, and
  undefined in every later version of router.py.
- **Fix:** the gate now sets `primitives_fired.aggregation_placement_corruption`
  and returns `_give_up("aggregation_placement_corruption", ...)`. That's the
  proper `{"answer", "tool_results", "answered": False}` dict, and it keeps
  diff_result and records a queryable reason_tag.
- **Test:** `tests/test_finalize_placement_corruption_fallback.py` replays the
  2026-09-14 EMEA incident through the real loop. Its planted-bug control
  compiles router.py with the old call restored and reproduces the silent
  ship. The existing placement tests only unit-tested the detector and were
  in no workflow.
- **Impact check against production data** (query_cost_log, 456 rows from
  2026-09-11 to 09-23, cross-referenced with conversation_threads):
  - 11 questions had placement corruption detected by the main loop, and all
    11 shipped an answer (0 fell back). None of them has a Slack thread:
    they were test/verification runs, 10 of them on 09-17/18 when no Slack
    threads were saved at all.
  - About 48 other mismatch events ended on a finalize path, where this gate
    lives but left no flag before the fix. Only 2 of those reached Slack
    (#449 Mid-Market win rate, #453 Ryan's pipeline question on 09-23 03:04
    UTC). Re-running verify_total_placement on both delivered texts gives
    placement_ok=True, so the broken fallback was not hit for either.
  - #453 did ship a wrong answer ("Total new deals added to pipeline:
    1,408"), but that came from the week_of_quarter value-column inference
    bug fixed in #29, not from this gap.
  - The definitive record would be Railway's logs for the string "name 'tail'
    is not defined"; this session has no access to them.
- **Second finding, fixed in the same PR:** `aggregation_placement_corruption`
  was set by both placement gates but never registered in
  `FAILURE_MODE_PRIMITIVES`. It had no default in `_new_cost_state` and no
  outcome bucket, so a blocked corruption read as generic `other_fallback`
  and a shipped one as `answered_after_resynthesis`. It's now registered,
  defaulted to False, and a blocked corruption gets its own
  `blocked_placement_corruption` outcome (asserted by the incident-route
  test).
- **Historical signature:** replaying the incident against the pre-fix
  code logs outcome=`answered_after_resynthesis` with
  reason_tag=`aggregation_placement_corruption`. Three production rows match
  that signature exactly (query_cost_log ids 52, 73, 86; 2026-09-17/18,
  "How has [new business] pipeline moved in the last 2 weeks?"). The logs
  can't tell whether their finalize retry was corrupted (the gap) or
  correct, since both log identically. None of the three has a Slack thread
  in conversation_threads.

### CRITICAL: Database Schema Mismatch — "pain" vs "identified_pain" (2026-09-21)
**Status:** ✅ FIXED (commit 44cb20c) - Proper architecture: separate Supabase/HubSpot key mappings

**Timeline:**
1. **Aug 12** (be16c07c): HubSpot properties created with "identified_pain" key
2. **Aug 23** (17aaecfb): Progressive Scoring introduced with "pain" key (matching DB schema)
3. **Sept 21** (a90e7c8): Bug #1 fix globally renamed "pain" → "identified_pain" (caused cascading failure)
4. **Sept 21** (44cb20c): **THIS FIX** - Reverted to "pain" internally, added HubSpot translation layer

**The Crisis (Sept 21, Post-Bug #1 Fix):**
Bug #1 fix (commit a90e7c8) changed call_scorer.py to use "identified_pain" globally, which cascaded into **100% failure rate**:
- ALL 179 deals failed with: `column call_scores.identified_pain_score does not exist`
- Progressive mode completely broken (0% analysis success rate)
- rollup_deal_scores.py could not read ANY existing call_scores rows
- More severe than original Bug #1 (which only affected 54.7% of deals)

**Root Cause:**
1. Database schema (migrations/043) defines column: `pain_score`
2. 1,469 existing call_scores rows use `pain_score`
3. Bug #1 fix globally renamed "pain" → "identified_pain" in COMPONENTS
4. rollup_deal_scores.py generates column list from COMPONENT_KEYS: `[f"{k}_score" for k in cs.COMPONENT_KEYS]`
5. SQL SELECT tried to read "identified_pain_score" column (doesn't exist in schema)

**The Proper Fix (commit 44cb20c):**
1. **Reverted call_scorer.py** COMPONENTS to use "pain" (matches DB schema: `pain_score`)
2. **Added HUBSPOT_KEY_MAPPING** in hubspot_deals.py to translate "pain" → "identified_pain" ONLY when writing to HubSpot properties
3. **Updated all files** to use "pain" internally (Supabase-facing):
   - context_builder.py: meddicc_state keys
   - run_nightly.py: meddicc_state initialization
   - meddicc_agent.py: example test data
   - test_setup.py, test_component_scores.py: test fixtures

**Design Principle Established:**
**Never use one global key for both Supabase and HubSpot.** The two systems have genuinely different naming conventions that don't need to match. Maintain TWO separate mappings:
- **Supabase/internal:** "pain" (matches `call_scores.pain_score` column)
- **HubSpot properties:** "identified_pain" (matches `meddicc_identified_pain_score`)
- **Translation layer:** `write_component_scores()` applies `HUBSPOT_KEY_MAPPING` at write time

**Why This Architecture is Correct:**
- Supabase schema is fixed (1,469 existing rows, migration-based)
- HubSpot properties are fixed (created Aug 12, can't easily rename)
- Systems genuinely have different conventions — forcing one name breaks the other
- Translation layer is explicit, localized, and easy to maintain

**Verification Still Needed:**
Live test run must confirm BOTH paths work simultaneously:
1. Supabase read: `load_deal_call_scores()` succeeds (no schema error)
2. HubSpot write: `write_component_scores()` succeeds (no 400 error)

**Files Changed:**
- scripts/call_scorer.py - Reverted COMPONENTS to "pain"
- scripts/hubspot_deals.py - Added HUBSPOT_KEY_MAPPING translation
- scripts/context_builder.py - "identified_pain" → "pain"
- scripts/run_nightly.py - "identified_pain" → "pain"
- scripts/meddicc_agent.py - "identified_pain" → "pain"
- scripts/test_setup.py - "identified_pain" → "pain"
- scripts/test_component_scores.py - "identified_pain" → "pain"

**Lesson:** Low-priority naming inconsistencies can escalate to critical failures when "fixed" with global renames without considering schema dependencies. Proper fix required understanding that the two systems legitimately differ and need explicit translation, not unification.

---

### Intent Classifier max_tokens Truncation (2026-09-18)
**Status:** ✅ FIXED - Systemic routing failure resolved

**The Bug:**
Intent classifier's max_tokens=300 was truncating JSON responses mid-output, causing ALL handler routing to fail with 0.50 confidence → unanswerable classification since August 18, 2026 (1 month).

**Evidence:**
- LLM correctly returned: `{"handler": "query_pipeline_movement", "scope": "full_scope", "params": {...}}`
- But response hit max_tokens at ~500 tokens, ending mid-JSON: `"score": null` (missing closing braces)
- _extract_json() failed on malformed JSON → returned None/partial data
- Code defaulted to handler="unanswerable", confidence=0.50 (below 0.80 threshold)
- Routed to dynamic_query instead of dedicated handlers

**Impact:**
- Pre-existing since commit fa2b61bb (2026-08-18) - "Add unified LLMClient adapter"
- Affected ALL handlers requiring full param enumeration in classifier response
- Handlers may have been unreachable via natural questions for entire 1-month period
- User questions silently fell back to dynamic_query, never exercising handler-specific fixes

**Root Cause:**
The LLM prompt requires listing ALL possible params (40+ fields) even when null, generating ~500 tokens. max_tokens=300 was insufficient, introduced during the LLMClient refactor without testing against full param schema.

**Fix (2026-09-18, commit 036ead2):**
1. Increased max_tokens from 300 → 600 for complete JSON response
2. Upgraded classifier from Haiku 4.5 → Sonnet 4.5 for better reasoning (secondary benefit)
3. Fixed circular routing: query_pipeline now redirects to query_pipeline_movement (not query_waterfall)

**Verification:**
- All 10 Phase 1b test questions now route at 0.95-0.98 confidence (vs 0.50 before)
- query_pipeline_movement: 5/5 questions reach handler ✅
- query_stale_deals: 5/5 questions reach handler ✅

**Follow-up Needed:**
This likely affected OTHER handlers beyond Phase 1b's two. Any handler expecting full param schema may have been unreachable. Recommend:
- Audit query_cost_log for questions that routed to dynamic_query but should have matched dedicated handlers
- Check handler usage stats pre/post fix to quantify impact
- Consider: should max_tokens be configurable per classifier prompt complexity?

**Files Changed:**
- `api/router.py` - max_tokens 300→600
- `scripts/llm_client.py` - classifier default Haiku→Sonnet (also in config/client.yaml)

**Related Commits:**
- 036ead2: FIX #5 (actual root cause): Increase intent classifier max_tokens from 300 to 600
- 944283d: FIX #5 (systemic routing failure): Upgrade intent classifier from Haiku to Sonnet 4.5
- dc0c522: Fix query_stale_deals default stale_days handling (explicit None crash)

---

### query_definition Handler - Completely Non-Functional Since Creation (2026-09-18)
**Status:** ✅ FIXED - Discovered as side effect of query_waterfall audit

**The Bug:**
query_definition handler was completely non-functional from creation (commit df8048d, Sept 1, 2026) through Sept 18, 2026 — **17 days of total breakage**. Every keyword match against an empty question string always evaluated False, so the handler could never successfully answer ANY question, regardless of what was asked.

**Discovery:**
Found accidentally as a side effect of auditing query_waterfall's separate, unrelated schema gap — NOT through any direct test of query_definition itself. The handler was routing correctly (classifier selected it at high confidence), but execution was silently broken.

**Root Cause:**
Same missing `params["question"]` router injection that broke query_waterfall's report_shape detection. Both handlers read `params.get("question", "")` for keyword matching, but the router never populated it.

**Evidence:**
```python
# Line 5268 in api/handlers.py (query_definition)
question = params.get("question", "").lower()  # Always got ""

# Line 5289: All keyword checks
if "at risk" in question or "at-risk" in question:  # "at risk" in "" → False
if "qualified" in question:                         # "qualified" in "" → False
if "renewal" in question:                           # "renewal" in "" → False
# ... etc, ALL checks always False
```

**Impact:**
- User asks: "What does at-risk mean to you?"
- Handler receives: `question = ""`
- ALL keyword checks fail
- Result: Empty or minimal response, NO definitions matched

**Timeline:**
- **Sept 1, 2026** (commit df8048d): query_definition added, immediately broken
- **Sept 18, 2026** (commit e8e3d65): Fixed via router injection of `params["question"]`
- **Duration:** 17 days of complete non-functionality

**Fix:**
Same commit (e8e3d65) that fixed query_waterfall also fixed query_definition — router now injects `params["question"] = question` before calling any handler.

**Pattern Recognition - SECOND Handler Found Silently Broken:**
This is the SECOND time this session a handler has been found completely or partially unreachable/non-functional for an extended period, discovered only by accident while working on something else:

1. **First:** max_tokens truncation (1 month) - ALL handlers potentially unreachable, found during Phase 1b routing tests
2. **Second:** query_definition (17 days) - completely non-functional, found during query_waterfall audit

**Recommendation:**
Consider whether this justifies a **periodic, deliberate health-check pass across ALL handlers** — not just the ones currently being refactored — to catch any other silently-dead handlers before they're found by accident a third time. Neither of these failures would have been caught by typical "does it return a response" smoke testing; both required looking at the actual execution logic to spot.

**Files Changed:**
- `api/router.py` - Same fix as query_waterfall (inject params["question"])

**Related Commits:**
- e8e3d65: Fix HIGH: Inject raw question text into params for handler use (fixed both handlers)
- df8048d: Add query_definition handler (introduced the bug)

---

### Handler Routing Ambiguities - Acceptable Overlaps (2026-09-18)
**Status:** ✅ DOCUMENTED - Not fixing, monitoring for user dissatisfaction

**Context:**
During Phase 1b routing health check, found 2 semantic overlaps where natural phrasings route to plausible alternate handlers rather than the "expected" one. These are NOT routing failures (all questions route at 0.95 confidence, above 0.80 threshold), but semantically adjacent handlers competing for ambiguous phrasing.

**Acceptable Overlaps:**

1. **query_deals_at_risk vs query_coaching_priorities**
   - Question: "what deals need attention"
   - Routes to: `query_coaching_priorities` (0.95 confidence)
   - Expected: `query_deals_at_risk`
   - Rationale: Coaching priorities explicitly includes "deals needing attention" — semantically defensible

2. **query_deals_at_risk vs query_deal_health**
   - Question: "show me weak deals"
   - Routes to: `query_deal_health` (0.95 confidence)
   - Expected: `query_deals_at_risk`
   - Rationale: Deal health handles MEDDICC health filters for weak scores — semantically defensible

**Why Not Fixing:**
- Both alternates are genuinely related handlers that could reasonably answer the question
- Routing confidence is strong (0.95), not degraded
- No evidence yet of user dissatisfaction with these routings
- Strengthening one handler's description risks introducing NEW ambiguities elsewhere

**Resolution Criteria:**
Revisit if real usage shows users explicitly reject these answers or rephrase questions to get different handlers. Until then, treat as acceptable semantic overlap in a 40+ handler system.

**Related Fix (Same Session):**
Fixed a REAL routing gap (query_win_loss vs query_waterfall) where "win loss breakdown" was routing to waterfall — that one warranted immediate fix because waterfall returns flow metrics (counts) not win/loss analysis (narratives). See commit [pending].

**Files:**
- This entry in PENDING_WORK.md
- Related routing tests in `/tmp/test_waterfall_*.log`, `/tmp/test_at_risk_*.log`

---

### Schema-Dictionary Drift Check (2026-09-15)
**Status:** ✅ COMPLETE - Fourth structural gate deployed

**The Bug Pattern:**
When manual DB migrations add columns (e.g., `ALTER TABLE deals ADD COLUMN xyz`) but forget to register them in `data_dictionary`, those columns become INVISIBLE to the dynamic query system — the exact pattern that hid `region`/`segment` and `new_arr`/`expansion_arr`/`renewal_revenue` from queries for days.

**What Makes This Gate Different:**
Unlike the first three gates (date-math, primitive-contract, handler-param-completeness) which run per-PR, this gate runs on a SCHEDULE (weekly) because schema drift comes from manual DB migrations, not code commits. A per-PR gate would never catch it.

**Completed Work:**
- [x] `scripts/check_schema_dictionary_drift.py` - Queries information_schema.columns vs data_dictionary for 19 queryable tables
- [x] Two drift categories:
  - Category (a) HIGH: Columns in real schema but missing from data_dictionary (makes data invisible)
  - Category (b) LOWER: Columns in data_dictionary but not in real schema (stale registration)
- [x] `.github/workflows/schema-drift-check.yml` - Weekly scheduled check (Mondays 9 AM UTC)
- [x] Fails loudly on category (a) drift with actionable error message
- [x] Tested against current production state (found 62 gaps, as expected for newly-added tables)
- [x] Verified trap springs: Added test column to `deals`, confirmed detection, reverted

**How It Works:**
1. Queries `information_schema.columns` for all columns in QUERYABLE_TABLES
2. Queries `data_dictionary WHERE is_queryable=TRUE` for registered columns
3. Compares and reports both missing (category a) and stale (category b) columns
4. Checks `config/data_dictionary_exclusions.yaml` for intentional omissions
5. Exits 1 on category (a) drift, triggering workflow failure

**Protected Tables (19 total):**
deals, deals_snapshot, calls, analyses, objections, feature_gaps, win_loss_narratives, competitive_signals, pipeline_signals, deal_risks, waterfall_weekly, forecast_weekly, pipeline_generation_weekly, rep_performance, rep_targets, sdr_metrics, sdr_users, user_personas, arr_by_customer

**The Four Structural Gates:**
1. **Date-math gate** (tests/test_date_resolution.py) - Per-PR, prevents `date.today()` calls
2. **Primitive-contract gate** (tests/test_primitive_contract.py) - Per-PR, ensures detection primitives act on findings
3. **Handler-param-completeness gate** (tests/test_handler_schema_completeness.py) - Per-PR, prevents handlers reading params not in classifier schema
4. **Schema-dictionary drift gate** (scripts/check_schema_dictionary_drift.py) - SCHEDULED (weekly), prevents unregistered columns

**Commits:**
- [script + workflow created, not yet committed in this session]

**Files:**
- `scripts/check_schema_dictionary_drift.py` - Drift detection script
- `.github/workflows/schema-drift-check.yml` - Weekly scheduled workflow
- This entry in PENDING_WORK.md

---

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

#### 1. 62 Unregistered Columns - 4 Tables Completely Invisible to dynamic_query
**Status:** ✅ COMPLETE (2026-09-15) - All 62 gaps closed

**Original Issue:** The schema-dictionary drift check (4th structural gate, deployed 2026-09-15) found 62 columns in real Postgres schema that are missing from `data_dictionary` with `is_queryable=TRUE`. This was LIVE invisible data — the exact bug pattern (region/segment, new_arr/expansion_arr) the investigation has been chasing.

**Original Severity: LATENT RISK, not actively broken**
- Dedicated handlers worked fine (they use explicit column lists via `select_all()`)
- But if the classifier misrouted a question to `dynamic_query`, those queries would fail
- Risk depended on classifier routing accuracy

**Breakdown:**
- **4 fully-unregistered tables** (0 columns in data_dictionary):
  - `sdr_metrics`: 20 columns missing (calls_made, connected_calls, emails_sent, etc.)
  - `user_personas`: 15 columns missing (name, email, persona, role, slack_user_id, etc.)
  - `sdr_users`: 8 columns missing (user_email, user_name, tool, tool_user_id, etc.)
  - `arr_by_customer`: 4 columns missing (company_name, total_arr, won_deal_count, most_recent_close)
  - **Subtotal: 47 columns across 4 tables**

- **5 partially-unregistered tables** (some columns missing):
  - `deals_snapshot`: 4 columns missing (renewal_revenue, fiscal_quarter, forecast_category, week_of_quarter)
  - `calls`: 5 columns missing (competitors_mentioned, duration_minutes, formatted_summary, has_feature_gap, has_objection)
  - `forecast_weekly`: 3 columns missing (historical_conversion_high/mid/low)
  - `waterfall_weekly`: 2 columns missing (newly_arr_bearing_count, newly_arr_bearing_value)
  - `analyses`: 1 column missing (stage_at_analysis)
  - **Subtotal: 15 columns across 5 tables**

**Handler Coverage (protects against immediate failure):**
- `query_arr` → queries `arr_by_customer` directly with explicit columns ✓
- `query_sdr_metrics`, `query_sdr_leaderboard`, `query_sdr_pipeline_sourced` → query `sdr_metrics`/`sdr_users` directly ✓
- `user_personas` → no dedicated query handler, used internally for persona lookups ⚠️

**Failure Modes:**
1. **If routing works correctly** → Dedicated handlers see their columns → safe
2. **If classifier routes to dynamic_query** → Schema context shows 0 columns for these 4 tables → silent wrong answer or "I don't have that data" when data actually exists
3. **If a question needs a join across these tables** → dynamic_query can't construct it → fails

**Resolution (2026-09-15):**

Closed all 62 gaps via table-by-table triage (NOT bulk backfill):

*REGISTERED (39 queryable columns):*
- analyses (1): stage_at_analysis
- arr_by_customer (4): company_name, total_arr, won_deal_count, most_recent_close
- calls (5): competitors_mentioned, duration_minutes, formatted_summary, has_feature_gap, has_objection
- deals_snapshot (4): fiscal_quarter, forecast_category, renewal_revenue, week_of_quarter
- forecast_weekly (3): historical_conversion_high/mid/low
- waterfall_weekly (2): newly_arr_bearing_count/value
- sdr_metrics (17): all activity metrics (calls_made, emails_sent, connect_rate, etc.)
- sdr_users (3): tool, user_email, user_name

*EXCLUDED (23 internal columns):*
- sdr_metrics (3): id, tool_user_id, etl_run_at - housekeeping
- sdr_users (5): id, internal_user_id, tool_user_id, first_seen, last_seen - housekeeping
- user_personas (15): ALL columns - bot configuration, not queryable sales data

*Decision rationale:* Each column triaged individually per handler-param pattern from earlier tonight - queryable business data → registered, internal IDs/ETL timestamps → excluded.

*Verification:*
✓ scripts/check_schema_dictionary_drift.py reports 0 category-(a) gaps
✓ All 275 columns across 19 tables registered or explicitly excluded
✓ Test suite passes (269 tests)

**Routing Audit Results (2026-09-15): ✅ LATENT RISK CONFIRMED, NO ACTIVE HARM**

Audited query_cost_log, fallback_log, and conversation_threads for last 30 days:

*Findings:*
1. **Zero instances of silent wrong answers** due to missing schema registration
2. **Zero instances of dynamic_query successfully querying the 4 invisible tables**
   - Confirmed via fallback_log queries_run: no queries reference sdr_metrics/sdr_users/user_personas/arr_by_customer
3. **SDR/call quality questions DO attempt dynamic_query first** (found in query_cost_log)
   - Example: "How's Scott's call quality been this month?" (ID 7, 2026-09-11 13:21:27)
   - Example: "How many meetings has Jake Stangl's SDR pipeline generated this quarter" (ID 10, 2026-09-11 13:28:33)
4. **When dynamic_query fails (exception), system falls back to dedicated handlers**
   - Both example questions got honest answers via fallback: "No call quality scores on record", "Zero deals attributed"
5. **All real user questions got correct answers** — the fallback mechanism worked

*Conclusion:*
- **"Latent risk" assessment is accurate** — the gap exists but hasn't caused harm
- Routing does fail (questions hit dynamic_query first), but fallback prevents damage
- No urgency to fix immediately, but should address to eliminate the failed dynamic_query attempts and reliance on fallback

*Evidence:*
- query_cost_log: 2 SDR-related exceptions (both fell back successfully)
- conversation_threads: Both questions delivered with honest answers
- fallback_log: No queries ever reached the 4 invisible tables
- 20+ SDR/ARR/metrics questions in last 30 days, all answered correctly

**Classifier Routing Follow-up:**

Fixing schema registration does NOT fix the routing pattern. The classifier uses `HANDLER_DESCRIPTIONS` and confidence thresholds to decide routing, NOT data_dictionary. Evidence shows SDR/call quality questions routed to dynamic_query first (then fell back to dedicated handlers after exceptions).

Key question: Will the exception-then-fallback pattern continue even with full schema coverage? Or will dynamic_query now successfully query these tables directly (potentially with partial/wrong results if the classifier confidence was independently too low)?

**Logged as separate follow-up:** See High Priority #6 below - "SDR/ARR Question Routing: Confidence vs. Handler Matching"

**Commits:**
- 783a6bf: Register 39 queryable columns, exclude 23 internal columns
- ebffc47: Fix test suite for expanded schema drift coverage

**Related:** This gap is exactly why the schema-dictionary drift check (4th gate) was built — would have caught region/segment and new_arr/expansion_arr immediately instead of days later.

---

#### 2. Snapshot ETL Phantom Exits Bug
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

#### 3. query_pipeline_movement Zero-Row Mystery (Jake Stangl incident) — MITIGATED, NOT ROOT-CAUSED, DEPRIORITIZED

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

#### 4. Dedicated Handlers: Owner-Email Canonicalization Gap (audit follow-up)

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

#### 5. Why Does GitHub Actions' Hosted Runner Fail to Import `ClientOptions` from `supabase`?

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

#### 6. SDR/ARR Question Routing: Does Schema Fix Affect Classifier Behavior?

**Issue:** After registering the 62 missing columns (High Priority #1), will SDR/ARR questions still route to dynamic_query first (with exceptions), or will routing behavior change?

**Background:**
- Routing audit confirmed SDR/call quality questions DO attempt dynamic_query first
- dynamic_query then fails with exception (tables were invisible)
- System falls back to dedicated handlers (query_sdr_metrics, query_call_quality, etc.)
- Handlers answer correctly

**The Question:**
Does fixing `data_dictionary` registration affect classifier routing decisions?

**Investigation Findings (2026-09-15):**

*Classifier routing mechanism:*
- Uses `HANDLER_DESCRIPTIONS` (api/router.py) to match questions to handlers
- Applies confidence thresholds (confidence < 0.80 → falls through to dynamic_query)
- Does NOT consult data_dictionary for routing decisions

*Conclusion:*
**NO** - registering columns does NOT change routing. Classifier will continue routing based on confidence scores, independent of schema coverage.

**Implications:**

Two possible outcomes post-fix:
1. **If confidence remains low (<0.80):** Questions still route to dynamic_query first
   - Previously: dynamic_query exception → fallback to dedicated handler
   - Now: dynamic_query might succeed with partial schema → risk of wrong answers?
   - OR: dynamic_query still routes internally to correct handler via schema context

2. **If confidence was never the issue:** Questions might route differently for other reasons
   - Need to verify actual classification scores for these questions
   - Check if handler descriptions match question phrasing well enough

**Recommended Next Steps:**
1. Monitor query_cost_log after schema fix deployed to production
2. Check if SDR/ARR questions still appear (routing to dynamic_query) or disappear (routing directly to handlers)
3. If they still appear: Check outcome - success or exception?
4. If success with wrong answers: Investigate classifier confidence scores and handler description matching

**Status:** ANALYSIS COMPLETE, MONITORING RECOMMENDED

**Priority:** Low urgency - current exception-then-fallback pattern is working, no production harm. This is about eliminating the exception pattern, not fixing a broken system.

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

#### 18. `get_week_of_quarter()` Duplicated — Two Independent Implementations, No Shared Source of Truth

**Issue:** The same "which week (1-13) of the fiscal quarter is this
date" formula exists twice, written independently:
- `scripts/analytics/snapshot_deals.py::get_week_of_quarter(snapshot_date, quarter_start)`
  — used by the live/prospective nightly snapshot writer.
- `scripts/analytics/backfill_snapshots.py::BackfillEngine.week_of_quarter(snapshot_date)`
  — used by the historical reconstruction path, resolves `quarter_start`
  internally via `get_fiscal_quarter()`.

Both compute `((snapshot_date - quarter_start).days // 7) + 1`, capped
to 13, and currently agree. Neither imports from the other.

**Found during:** forecast-trustworthiness primitive design (CRO
Priority #1, NORTH_STAR.md). The primitive needs "what week of the
CURRENT quarter is it today" at call time and was pointed at the live
writer's version (`snapshot_deals.py`) rather than adding a third copy.

**Why it matters:** this is the same failure shape as other duplicated-
formula bugs found earlier this session (e.g. the two independently-
coalesced `pipeline_filter` checks in Low Priority #17, and the
point-in-time reconstruction work's explicit ratchet test
`test_no_duplicate_reconstruction_implementations` guarding against
exactly this in `point_in_time.py`) — two copies of one formula don't
drift until someone fixes a boundary case (leap week, fiscal-year-start
edge, off-by-one) in one and not the other, and nothing would catch it.

**Status:** NOT BROKEN (both currently agree, confirmed identical
output shape). Not urgent — logged so it has a paper trail before it
silently drifts, per the pattern already seen elsewhere tonight.

**Work:** Consolidate to one shared function (e.g. move to
`point_in_time.py` alongside the other shared population/value
reconstruction logic, or a small dedicated fiscal-week module), with
both `snapshot_deals.py` and `backfill_snapshots.py` importing it. Add
a ratchet test analogous to `test_no_duplicate_reconstruction_implementations`
if consolidated.

**Complexity:** Low effort, no urgency.

**Addendum (found during Step A of `assess_forecast_trust()` implementation):**
the same underlying pattern extends one level up — "quarter label/date
-> quarter boundaries" also has multiple independent implementations,
not just "date -> week number":
- `scripts/utils.py::get_fiscal_quarter(as_of=None, config=None)` —
  the canonical date-in, `(q_start, q_end, label)`-out function.
- `scripts/deal_risk_assessor.py::get_at_risk_deals()` — resolves an
  explicit `fiscal_quarter` label back to boundaries via its own
  regex (`FY(\d{4})\s+Q([1-4])`) plus manual calendar math, because it
  only ever receives a label, never a date.
- `scripts/analytics/forecast_analyses.py::_quarter_window_iso(sb, quarter)`
  — resolves a label back to boundaries a third way: looks up any
  existing `deals_snapshot` row for that quarter, takes its
  `snapshot_date`, and calls `get_fiscal_quarter()` on that date.

Three call sites, three different strategies for label->boundaries,
none sharing a source of truth for that direction (only the date->label
direction is canonical, via `get_fiscal_quarter()`). `assess_forecast_trust()`
sidesteps this entirely by always starting from a date (`as_of`) and
calling `get_fiscal_quarter()` directly — it does not add a fourth
implementation. Not fixing the pre-existing two (`get_at_risk_deals`'s
regex, `_quarter_window_iso`'s snapshot-lookup) as part of this build —
out of scope for a primitive that doesn't need label->boundaries at
all — but logging it here since it's the same class of risk as the
entry above, one level up the same call chain.

---

#### 19. `api/tools.py::assess_deal_risk()` — Documented `deal_ids` Parameter Is Always Ignored

**Issue:** The `dynamic_query_loop`-facing async wrapper
`api/tools.py::assess_deal_risk(sb, deal_ids=None, fiscal_quarter=None)`
documents `deal_ids` as "Optional list of deal IDs to assess (for
entity-scoped queries). If None, queries all late-stage/COMMIT deals in
target quarter" — but the implementation never reads it:

```python
async def assess_deal_risk(sb, deal_ids=None, fiscal_quarter=None):
    ...
    raw_result = get_at_risk_deals(sb, fiscal_quarter=fiscal_quarter)
    ...
```

`get_at_risk_deals()` always runs its own late-stage-OR-COMMIT query
regardless of what (if anything) was passed as `deal_ids`. Anyone
calling this tool with specific `deal_ids` today — e.g. an
entity-scoped question like "assess risk for these 3 deals" — silently
gets the full current-fiscal-quarter cohort back instead, with no
error or warning that the scoping was dropped.

**Different pattern from #18/#18-addendum:** those are duplicated
formulas that currently agree; this is a documented-but-dead parameter
— a caller relying on the docstring gets silently wrong scope, not
just a risk of future drift.

**Found during:** `assess_forecast_trust()` implementation (Step A),
while confirming `scripts/deal_risk_assessor.py::assess_deal_risk()`
(the lower-level, general-purpose function this wrapper calls into)
was the right thing to compose against directly, rather than through
this wrapper.

**Status:** NOT BROKEN for the wrapper's actual current callers (none
found passing `deal_ids` in this audit), but the parameter is
unconditionally a no-op today. Not fixed as part of this build — out
of scope, `assess_forecast_trust()` doesn't call this wrapper at all.

**Work:** Either wire `deal_ids` through to a scoped query in
`get_at_risk_deals()` (or a new parameter path), or remove the
parameter from the signature/docstring until it's implemented, so the
documented contract matches what the function actually does.

**Complexity:** Low effort, no urgency.

---

#### 20. `api/handlers.py::query_coverage()` — Confirmed Broken, Produces 8,000%+ Nonsense

**Issue:** `query_coverage()` fetches ALL qualified pipeline as a single
unscoped total (`total_pipeline`), then divides that SAME total against
EACH individual target row (team-level and every per-rep row alike)
from `rep_targets`:

```python
coverage_rows.append({
    ...
    "target":   tv,
    "pipeline": total_pipeline,   # same unscoped total for every row
    "coverage": round(total_pipeline/max(tv,1)*100, 1),
})
```

A rep with a $250k individual target gets `coverage` computed against
the WHOLE team's qualified pipeline (millions), not their own book —
producing coverage percentages in the thousands, confirmed live during
the 2026-09-19 pipeline-coverage audit (NORTH_STAR.md CRO Priority #2).

**Found during:** the pre-build audit for
`scripts/pipeline_coverage.py::assess_pipeline_coverage()` — confirmed
live via `scripts/audit_pipeline_coverage.py` before concluding
pipeline-coverage was a genuine reasoning-layer gap rather than an
already-solved question.

**Status:** NOT fixed. Out of scope for the `assess_pipeline_coverage()`
build — that primitive is a new, correctly-scoped composition
(`api/handlers.py::query_pipeline_coverage`, intent-routed ahead of
`query_coverage` for coverage questions), not a patch to this handler.
`query_coverage`'s intent-map entry now flags it as legacy/broken so the
router prefers `query_pipeline_coverage`, but the handler itself is
unchanged and still produces this output if reached directly (e.g. via
the dynamic-query-loop fallback).

**Work:** Either fix `query_coverage()` to scope `pipeline` per-target
(team total vs. company-wide qualified pipeline; per-rep target vs. that
rep's own qualified pipeline, via `owner_email`), or remove/deprecate it
now that `query_pipeline_coverage` exists as the correct, tested
replacement.

**Complexity:** Low-medium (the fix is a per-row scoping change, not a
new algorithm) — no urgency now that the router steers questions to the
correct handler.

---

#### 21. `rep_targets` — Two Live Period-Label Formats for the Same Quarter (`FY2027_Q3` vs `Q3_FY2027`)

**Issue:** Confirmed live during the same 2026-09-19 pipeline-coverage
audit: the `rep_targets` table has 11 total rows for the current
quarter, split across TWO different label formats — 7 rows under
`FY2027_Q3` (from `scripts/seed_targets.py`'s own convention:
`quarter_key.replace('fy','FY').replace('_q','_Q').upper()`, 6 reps + 1
team-total row) and 4 rows under `Q3_FY2027` (source unconfirmed —
plausibly an older seeding pass or a manual Slack `set target` write
using a different convention). `current_quarter_label()`
(`api/time_resolver.py`) itself produces `FY2027_Q3` (its own docstring
example of `'Q3_FY2027'` is stale/wrong — `get_fiscal_quarter()`'s real
label format is `"FYyyyy Qn"`, underscored), so every handler that
queries `rep_targets` by `current_quarter_label()`
(`query_pipeline()`, `query_coverage()`, the new
`query_pipeline_coverage()`) correctly finds the 7 `FY2027_Q3` rows —
but the 4 `Q3_FY2027` rows are silently invisible to all of them. Same
class of finding as an earlier-session incident (TEST 0r, "FY2027 Q2"
vs "Q3_FY2027" quarter-label-convention risk).

**Found during:** the `rep_targets`-population confirmation step for
`assess_pipeline_coverage()`'s Step A (`scripts/audit_rep_targets_all_periods.py`).

**Status:** NOT fixed — does not currently produce wrong output (the
canonical format is the one every handler queries), but is dead/orphaned
data sitting under the wrong key, and a latent trap for any future code
that queries `rep_targets` without going through
`current_quarter_label()`.

**Work:** Identify the source of the 4 `Q3_FY2027` rows (check
`set_target` handler's own period-formatting logic against
`seed_targets.py`'s), reconcile or delete the orphaned rows, and — if
`set_target` is the source — fix it to use the same canonical format
`current_quarter_label()`/`seed_targets.py` already agree on.

**Complexity:** Low effort (a data cleanup + one formatting fix), no
urgency — not currently causing wrong output, but should not be left to
silently accumulate more orphaned rows each quarter.

---

#### 22. Country Canonicalization Mapping Duplicated — Two Independent Sources of Truth

**Issue:** The same country semantic-variant mapping (Netherlands/The
Netherlands, Russia/Russian Federation, Czech Republic/Czechia) exists
twice, written independently:
- `api/dimension_resolver.py::_COUNTRY_ALIASES` — used by the FILTER
  path in `resolve_dimension_filter()` when a question mentions a
  country (e.g., "show me Netherlands deals").
- `api/tools.py::_COUNTRY_CANONICALIZATION` — used by the GROUP BY path
  in `aggregate_results()` when grouping deals by company_country (e.g.,
  "show me EMEA deals by country").

Both currently contain identical mappings:
```python
# dimension_resolver.py
"netherlands": "Netherlands",
"the netherlands": "Netherlands",
"russia": "Russia",
"russian federation": "Russia",
"czech republic": "Czech Republic",
"czechia": "Czech Republic",

# tools.py (same values)
"the netherlands": "Netherlands",
"netherlands": "Netherlands",
"russian federation": "Russia",
"russia": "Russia",
"czechia": "Czech Republic",
"czech republic": "Czech Republic",
```

Neither imports from the other.

**Found during:** Country dimension implementation (Marketing Priority
#2, 2026-09-19). Initial implementation only handled FILTER path;
follow-up testing confirmed GROUP BY path needed separate
canonicalization. Both were fixed in the same session (commits 47e0963,
3a1b38a), but as two separate constants to meet immediate need.

**Why it matters:** Same failure shape as other duplicated-mapping bugs
found earlier (#18/#18-addendum: `get_week_of_quarter()` duplication).
Two copies of one mapping don't drift until a fourth country variant
needs adding (e.g., "Korea" vs "South Korea" vs "Republic of Korea") —
someone updates one constant and not the other, and queries would
canonicalize inconsistently between filtering and aggregation paths.

**Status:** NOT BROKEN (both currently agree, confirmed identical
mappings). Not urgent — logged so it has a paper trail before it
silently drifts, per the pattern already seen elsewhere.

**Work:** Consolidate to one shared constant (e.g., move to a new
`api/country_canonicalization.py` module or add to
`api/dimension_resolver.py` and import from `api/tools.py`), with both
FILTER and GROUP BY paths importing from the same source. Worth doing
proactively if a fourth country variant ever needs adding, so it only
has to be added once.

**Complexity:** Low effort, no urgency — only becomes urgent if/when a
new country variant is discovered in the data.

---

#### 23. AMER vs NAM Region Naming — RESOLVED (was misdiagnosed as a data-hygiene gap)

**Found during:** Territory comparison audit (CRO Priority #6,
2026-09-19). Test question "How does EMEA compare to AMER this
quarter?" returned zero AMER deals (0 active, 0 won, 0 lost), while
EMEA returned 47 active deals — a clear asymmetry. The query log showed
AMER was correctly resolved and filtered for, but the data contained no
matching region values.

**Confirmed directly by Jeff (2026-09-20):** this was NOT a data
hygiene gap. "NAM" is GrowthBook's actual, correct region terminology
— not a typo, not a legacy value, not one of several inconsistent
variants in the data. The test question itself used the wrong term
("AMER" instead of "NAM"); the data was never broken.

**Fix shipped:** Even though the underlying data was never wrong, a
real user asking a live question might still reasonably say "AMER"
colloquially. `api/dimension_resolver.py`'s `_region_candidates()` now
resolves "AMER" as an alias to the canonical "NAM" region_code, via a
new `_REGION_ALIASES` map — the same alias-map pattern
`_country_candidates()` already uses for country variants (Netherlands
vs The Netherlands, Russia vs Russian Federation). Verified locally
before the fix: `resolve_dimension_filter("NAM")` already resolved
correctly (`region.eq.NAM`); `resolve_dimension_filter("AMER")`
returned `unknown_value`. After the fix, both resolve to the same
canonical `region.eq.NAM` filter, in both the direct-lookup path and
the proactive whole-question scan
(`scan_question_for_known_dimension_terms()`, which calls
`resolve_dimension_filter()` per candidate term, so no separate wiring
was needed there). Three regression tests added to
`tests/test_dimension_resolver.py`
(`test_nam_resolves_correctly`, `test_amer_resolves_as_a_colloquial_
alias_for_nam`, `test_amer_is_surfaced_by_the_proactive_scan_too`);
the alias's own load-bearing-ness was verified by actually emptying
`_REGION_ALIASES` and confirming the AMER test fails before restoring
it clean. No `deals.region` data changes were made or needed — this
was a resolver-side vocabulary fix only.

---

#### 24. `win_loss_narratives.key_factors` — "100% Populated" Is Misleading, LLM Fills Absence-of-Data as a Factor

**Issue:** `scripts/analytics/generate_win_loss.py`'s prompt asks the
model for "key_factors: list of 3-5 short factor strings" for every
closed deal, whether or not there's any real signal to report. When the
underlying data is empty (no `lost_reason`, no call transcripts, no
MEDDICC history), the model does not return an empty list — it fills
the field with commentary ABOUT the absence, e.g. "Rep provided no loss
reason" (10x across 58 lost narratives), "No call activity documented"
(8x), "No call transcripts recorded" (7x), "Poor deal hygiene" (3x).

**Found during:** CRO Priority #5 audit (win/loss pattern reasoning,
2026-09-20). `key_factors` reads as 58/58 (100%) non-empty across all
lost-outcome narratives — which looks like excellent coverage until the
actual strings are inspected. Of 290 total key_factors mentions
sampled, the top 10 most common strings are ALL variations of "there
was nothing to report here," not real loss drivers (competitor,
pricing, timing, champion loss, etc.).

**Why it matters:** This is the same class of danger as a confidently-
wrong number, just in a text field. Any future code (or any future
`dynamic_query` reasoning pass) that checks `if key_factors:` or counts
non-empty rows as "signal available" will systematically overcount —
the field's fill rate looks like 100% coverage of REAL pattern data
when it is actually ~100% coverage of "the LLM said something," a
meaningful fraction of which is itself a report of missing data. A
naive competitor-frequency or factor-frequency aggregation built
directly on this field, without first filtering out the "no data"-
flavored strings, would produce a pattern-reasoning primitive whose top
finding is "we have no data" dressed up as a substantive factor.

**Status:** NOT FIXED. Confirmed live, not hypothetical — this is the
actual content of the actual table today, not a worst-case guess.

**Work:** Either (a) change `generate_win_loss.py`'s prompt to return an
empty `key_factors` list (or a single explicit `"insufficient_data"`
sentinel) when there's no real signal, instead of narrating the
absence, or (b) if the field is ever read for pattern reasoning, filter
out absence-of-data phrasing (e.g. a denylist of "no reason"/"no call"/
"no data"/"not provided" substrings) before treating a non-empty
`key_factors` as real signal. (a) is the more durable fix since it
closes the gap at the source instead of requiring every future
consumer to remember the filter.

**Complexity:** Low effort for (a) — a one-line prompt change plus a
backfill decision for the 58 existing rows. Not urgent on its own
(nothing reads `key_factors` for aggregation today), but load-bearing
BEFORE any pattern-reasoning primitive is built on top of it.

---

#### 25. `generate_win_loss.py` Double-Encodes `key_factors` — Stored as a JSON String, Not a Native jsonb Array

**Issue:** `scripts/analytics/generate_win_loss.py` writes
`'key_factors': json.dumps(parsed.get('key_factors', []))` into
`win_loss_narratives.key_factors`, a `jsonb` column. Passing an
already-`json.dumps()`'d Python string into a jsonb column write
double-encodes it: Postgres stores a JSON STRING whose contents happen
to look like a JSON array (`"[\"a\", \"b\"]"`), not a real JSON array
value.

**Found during:** CRO Priority #5 audit (win/loss pattern reasoning,
2026-09-20), while checking whether `key_factors` was safe to iterate
directly for frequency counting. Confirmed live: all 58 lost-outcome
`win_loss_narratives` rows return `key_factors` as a Python `str`
requiring an explicit `json.loads()` to recover the actual list, not a
native Python `list` as a correctly-stored jsonb array would.

**Why it matters:** Any code written against `key_factors` assuming
supabase-py hands back a Python list directly (as it does for a
correctly-stored jsonb array elsewhere in this codebase) will either
crash (iterating a string instead of a list produces one character at
a time) or silently misbehave. Real but minor — nothing currently reads
this field, so it hasn't caused a live incident, but it's a landmine
for whoever builds the first thing that does.

**Status:** NOT FIXED. Confirmed via live data, not a guess.

**Work:** Change `generate_win_loss.py` to write
`parsed.get('key_factors', [])` directly (the native list), not
`json.dumps(...)` of it — the supabase client / PostgREST layer handles
jsonb serialization on its own. A backfill (`UPDATE ... SET
key_factors = key_factors::text::jsonb` or a small Python pass calling
`json.loads()` on each existing row) would fix the 58 rows already
written this way.

**Complexity:** Low effort — one-line fix in the writer, small backfill
for existing rows. Not blocking anything today.

---

#### 26. `query_win_loss`'s Routing to `dynamic_query` Is Intentional, Not a Confidence-Floor Miss — Docstring Is Stale

**Issue:** Live-testing "why are we losing deals," "what's causing our
losses," and "which competitor do we lose to most" (CRO Priority #5
audit, 2026-09-20) showed all three routed through `dynamic_query`,
never through `query_win_loss` as a standalone dedicated handler —
apparently contradicting `api/router.py`'s own `INTENT_MAP` description
of `query_win_loss`, which explicitly lists these exact phrasings
("why are we losing," "what's causing deals to close lost") as its
territory.

**Investigated (not assumed):** the production log for all three test
runs shows `[UNIFIED_ROUTING] query_win_loss → dynamic loop (classifier
confidence=0.95, bypassed)` — confidence 0.95, nowhere near the 0.80
routing floor. This is **not** a confidence-threshold miss, the same
bug class fixed multiple times earlier this session. It's `api/
router.py`'s own explicit, already-shipped "Phase 2: Unified routing
for migrated handlers" logic (line ~5275): `query_pipeline_movement`,
`query_pipeline`, `query_stale_deals`, `query_waterfall`,
`query_rep_pipeline`, `query_win_loss`, and `query_deals_at_risk` are
ALL deliberately routed to `dynamic_query` regardless of classifier
confidence, because each is registered as a callable TOOL for the
dynamic loop (`_call_handler_as_tool`, line ~4634) rather than run
directly — this is the same migration already logged and closed in
this file's own "✅ Phase 2 Handler 5/6 (query_win_loss) — Migrated, 3
real bugs found" section.

**Why it matters:** Nothing is broken — `query_win_loss`'s raw-list
logic still runs, just as one tool inside `dynamic_query`'s reasoning
loop rather than as the sole handler, which is why the live answers
showed genuine ad hoc computation (ARR breakdowns, MEDDICC averages,
$0-value ghost-deal detection) rather than a bare dump. The only real
issue is `INTENT_MAP`'s description text for `query_win_loss` (and the
other 6 migrated handlers) still reads as if the classifier's chosen
handler is what actually executes — a future reader could reasonably
assume there's live branching here when the routing for these 7
handlers is now unconditional.

**Status:** NOT A BUG. No fix pass needed on the routing itself.

**Work:** Optional, cosmetic only: update `INTENT_MAP`'s entries for
the 7 unified-routing handlers to note that they always execute via
`dynamic_query` as a tool, not as a standalone handler, so a future
reader of `router.py` doesn't have to trace the Phase-2 migration logic
to learn that.

**Complexity:** Trivial (comment/docstring text only) if done at all —
no functional change.

---

#### 27. `deals_snapshot` Daily Cadence Blocked by Evidence-Counting Dedup Gap — `query_commit_ml_calibration_by_week` and `query_stage_close_rate`

**Issue:** Two primitives built tonight (`forecast_trust.py`'s
`query_commit_ml_calibration_by_week()` and `pipeline_coverage.py`'s
`query_stage_close_rate()`) count `deals_snapshot` **rows** matching a
`(fiscal_quarter, week_of_quarter)` pair without deduplicating by
`deal_id`. Both gate their output on `classified >= min_evidence_count`
(default 30) before trusting a win-rate computation. This design is
correct under the current weekly snapshot cadence — each deal
contributes ≤1 row per week, so row count ≈ distinct deal count — but
would break if `deals_snapshot` moves to daily cadence: a deal that
doesn't change stage/category for a week would contribute ~7 identical
rows to that week's bucket, inflating `n_tagged`/`classified` counts
~7x while the real number of distinct deals stays the same.

**Why it matters:** The evidence floor would trip roughly 7x too early,
silently letting a genuinely thin week (e.g., 5 real deals) pass as if
it had 35 — defeating the exact protection `min_evidence_count` exists
for. The win-rate point estimate itself would likely stay close to
correct (numerator and denominator inflate together), but the
statistical significance gate would be systematically wrong.

**Found during:** Daily analytics ETL audit (2026-09-21). Both
primitives (`query_commit_ml_calibration_by_week` and
`query_stage_close_rate`) explicitly document the row-counting
assumption in their docstrings: *"deal-week observations, not deduped
to unique deals"*. This was a deliberate design choice under weekly
cadence, not an oversight.

**Status:** NOT BROKEN today — `deals_snapshot` is still written weekly
via `weekly-analytics.yml`, so the current row-counting logic is
correct. This is a **hard prerequisite blocking any future move of
`deals_snapshot` to daily cadence**. The audit explicitly defers moving
snapshot writes to daily (Step 2 only moves the base `deals` table
upsert to daily, snapshot stays weekly).

**Work:** If/when `deals_snapshot` moves to daily cadence:
1. **Add deduplication by `deal_id`** to both
   `query_commit_ml_calibration_by_week()` and
   `query_stage_close_rate()` — either via a DISTINCT clause in the SQL
   query or by counting unique `deal_id` values per week in Python
2. **OR select one row per deal per week** — e.g., `MAX(snapshot_date)`
   per `(deal_id, fiscal_quarter, week_of_quarter)` group, so each deal
   contributes exactly one row per week regardless of how many daily
   snapshots exist
3. Update docstrings to reflect the new dedup logic

**Complexity:** Low effort (one DISTINCT clause or GROUP BY per query,
~10-15 lines total), but **blocking** — do not move
`snapshot_deals.py` to daily cadence without fixing this first. Logged
here so nobody makes that change later without reading this
prerequisite.

---

#### 28. Hardcoded Fireflies API Key in `fireflies_client.py` — Live Secret Exposure

**Issue:** `scripts/fireflies_client.py` line 24 contained a hardcoded Fireflies API key as a fallback default: `"5313ce93-256a-4bd7-840e-864941fa3e81"`. This is a live credential committed to source control.

**Security impact:**
- Same severity class as the earlier database password exposure (item at top of this file)
- Anyone with read access to this repo (or its git history) can retrieve and use this API key
- Fireflies API access includes read/write permissions to all meeting transcripts

**Found during:** Transcript gap investigation (2026-09-22), while verifying terminal empty call classification logic.

**Status:** **FIXED** (2026-09-22) — Hardcoded key removed, replaced with explicit ValueError if environment variables not set. However:
1. **The API key has NOT been rotated** — it was exposed in git history; treat as compromised
2. **Still present in git history** — commit history contains the key; anyone can retrieve it

**Work required:**
1. **Rotate the Fireflies API key immediately** (closes live exposure)
2. Update `FIREFLIES_API_KEY` / `GROWTHBOOK_FIREFLIES_API_KEY` in all environments (.env, GitHub Secrets, etc.)
3. Optional: git history scrubbing (BFG Repo-Cleaner) or accept as dead credential after rotation

**Complexity:** Low effort for rotation; history scrubbing is optional if key is rotated.

---

#### 29. Apollo Phone-Dialer Calls Have No `formatted_summary` — Richer Data Exists But Isn't Fetched

**Issue:** Apollo phone-dialer calls (source=`apollo`, identified by short duration and lack of meeting URL) are fetched via the `get_conversation()` endpoint, which returns only transcript fragments. Apollo's dedicated phone-call analytics API provides richer structured data:
- Call outcome (connected, voicemail, no-answer, busy)
- Call direction (inbound vs outbound)
- Call disposition/notes
- Linked contact/account metadata

The current implementation treats phone calls identically to meeting recordings, resulting in:
- No `formatted_summary` (stored as None)
- No outcome/disposition tracking
- Missed opportunity to distinguish connected calls from voicemails

**Impact:**
- Rep coaching features (talk time, question rate) still work (transcript fragments sufficient)
- But higher-level activity metrics (connect rate, call outcomes by rep) are unavailable
- Current workaround: infer call type from duration (short = likely phone, long = likely meeting), but not definitive

**Found during:** Transcript gap investigation (2026-09-22), while analyzing Apollo call completeness.

**Status:** **NOT BROKEN** — current behavior is working-as-designed for available data. This is a **feature unlock** opportunity, not a bug.

**Work required:**
1. Identify Apollo phone calls (heuristic: duration < X minutes, no meeting URL, or dedicated API flag)
2. Route phone calls to Apollo's phone-analytics API instead of `get_conversation()`
3. Transform phone-call structured data into `formatted_summary` equivalent (e.g., "Outbound call, connected, 3m 24s, disposition: interested")
4. Optionally: add `call_outcome` / `call_disposition` columns to `calls` table for queryability

**Complexity:** Medium — requires Apollo phone-analytics API integration (not currently wired) + routing logic to distinguish phone from meeting calls.

**Priority:** Low — transcript gap fixed; this is a quality-of-life enhancement for deeper phone-call analysis, not blocking any current feature.

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

---

## 🏗️ Future Architectural Initiatives

*These are deliberate, multi-day refactoring efforts, not immediate tasks. Do NOT start without explicit go-ahead.*

### Handler-Primitive Convergence (Scoped, Not Started)

**Status:** Documented for future scoping (3-5 day effort)  
**Document:** `docs/HANDLER_PRIMITIVE_CONVERGENCE.md`  
**Identified:** 2026-09-14 (during pipeline_filter gap investigation)

**Problem:**
Dedicated handlers (query_pipeline, query_waterfall, etc.) contain hand-written logic that duplicates what governed primitives and field_semantics.py already do correctly. This creates divergence risk - any fix must be applied in both places, and "verified in CI" doesn't mean "working in production" if the upstream path (classifier) doesn't execute.

**Tonight's incident that exposed this:**
- Handler code had correct pipeline_id filtering logic (commit 44827e9, Sep 12)
- Tests passed because they called handler directly with pipeline_filter set
- Production failed because classifier schema didn't define pipeline_filter
- Result: Filtering code never executed, 11 renewal deals shipped under "New Business Pipeline"

**Three-part solution:**
1. **Audit and refactor existing handlers** - Eliminate duplicated business logic (pipeline classification, stage bucketing, date resolution, dimension filtering, aggregation). Each handler should be < 100 lines calling shared primitives.

2. **Primitives-first policy for new clients** - Build primitives before handlers. Dedicated handlers are thin wrappers only, never independent business logic.

3. **Reduce handler logic overall** - Long-term goal: handlers < 50 lines, 90%+ business rules in primitives/field_semantics.

**Why this is NOT tonight's task:**
- Touches 9+ handlers, 100s of lines each
- Requires extensive regression testing (20+ live Slack questions must give same answers)
- Estimated 3-5 days, not 3-5 hours
- Current priority: Fix tonight's fire (pipeline_filter gap) first

**Acceptance criteria (when executed):**
- Every dedicated handler < 100 lines (ideally < 50)
- No duplicated business logic between handlers and primitives
- Regression suite: 20+ Slack questions answered identically before/after
- audit_handler_param_gaps.py shows zero real gaps

**Do NOT start without explicit approval.** This is architectural hygiene - user-facing behavior should be identical before/after.


---

## Phase 2 Migration Finding: query_stale_deals Over-Scoping Bug (2026-09-18)

**Discovery Context**: Handler 2/6 baseline testing during unified routing migration

**Issue**: The OLD direct-handler path was applying an implicit current-quarter 
time_window filter to `query_stale_deals` queries, even when the user's question 
("what deals are stale") didn't mention any time scope.

**Behavior Comparison**:
- OLD path: 30 deals / $390K (filtered to close_date in Q3 FY2027: 2026-08-01 to 2026-10-31)
- NEW path: 64 deals / $987K (no time filter - all stale deals regardless of close date)

**Root Cause**: The classifier in the OLD path was proactively extracting a 
current-quarter time_window for stale deals queries, creating an implicit filter 
that has no semantic connection to what "stale" actually means.

**Correctness Analysis**: "Stale" is a duration-based measure of deal inactivity 
(deals with no stage movement for N days or past their close date). This concept 
does NOT logically depend on WHEN a deal is scheduled to close. A deal closing 
next quarter that has been inactive since June is genuinely stale RIGHT NOW, and 
filtering it out because its close_date falls outside "this quarter" discards 
real signal for no principled reason.

**Resolution**: The NEW path's behavior (all stale deals, no implicit time filter) 
is CORRECT. The OLD path had a pre-existing product-correctness bug that happened 
to surface during this baseline comparison. Users who want stale deals scoped to a 
specific window (e.g., "stale deals closing this quarter") should explicitly 
mention the time scope in their question, exactly as time_window's schema supports.

**Baseline Updated**: query_stale_deals now uses 64 deals / $987,194.02 as the 
correct baseline.

**Status**: Documented. No code fix needed - the migration corrected the behavior.


## ✅ Handler 4 (query_rep_pipeline) Migration - Synthesis Bug FIXED

**Date**: 2026-09-19
**Status**: ✅ FIXED - NEW path now shows complete datasets correctly

**Finding**: NEW path synthesis was incorrectly filtering results to Q3-focused subset (16-25 deals) instead of showing all 94 active deals, violating handler's documented intent.

**Root Cause**:
- Handler returned all 94 deals correctly (17,677 chars JSON)
- _aggregate_and_sample recognized structured results without "rows" key ✅
- BUT: Tool result was truncated to 3000 chars before being shown to LLM (line 4876)
- Truncation cut off after ~15 deals, so LLM synthesized based on incomplete data
- Result: Varied between runs (16-25 deals, $3.86M-$4.6M) instead of all 94 / $7.5M

**Fix (2026-09-19)**:
1. Detect structured results with "summary" field containing "total_deals" (line 4877)
2. For complete datasets, skip [:3000] truncation and pass full JSON to LLM
3. Add explicit instruction: "⚠️ COMPLETE DATASET: This result contains ALL X deals"
4. Row-based results still use existing 3000-char truncation (already aggregated/sampled)

   **⚠️ CORRECTION (2026-09-23): item 4 was false.** Row-based results
   were NOT already aggregated/sampled when they reached the model. The
   serializer was handed the RAW tool result and cut it to 3000 chars
   mid-row. The aggregate `_aggregate_and_sample()` had computed over
   every row was stored in `accumulated_data[step_N]` and never shown to
   the model. The canary test (`tests/test_canary_no_silent_drop.py`)
   measured it on a 60-row filter_table result: the model saw 13 rows,
   no `aggregates`, no `row_count`. So any dynamic question over 20 rows
   was answered from a partial raw slice. After a CODE-ENFORCED
   completeness retry it was worse: the message was still built from
   the incomplete first call. FIXED: `_serialize_tool_result_for_synthesis()`
   now sends the stored aggregated view (summary keys first, whole sample
   rows trimmed only if over `LOOP_STEP_VIEW_CHARS` (8000), never a character
   cut while rows remain). The same applies at the three forced-fetch
   message sites in `_finalize_from_data`, and `_aggregate_and_sample()`
   now passes through every key it doesn't compute. Guarded by
   `test_fix_aggregate_view_reaches_synthesis_is_guarded` and
   `test_fix_aggregate_passthrough_is_guarded`.

**Verification**:
- Baseline test: "show me Christian's pipeline"
- NEW path: "94 total active deals, $7.5M total ARR" ✅ CORRECT
- Matches OLD path and direct handler test
- Consistent across multiple runs

**Files Changed**:
- `api/router.py` lines 1775-1788: _aggregate_and_sample handles structured results
- `api/router.py` lines 4875-4894: Conditional truncation for complete datasets

**Impact**:
Users now get complete, accurate pipeline views matching handler's "never filters by close_date" design intent.


## ✅ SYSTEMIC FINDING: Synthesis-truncation bug is pipeline-wide, not Handler-4-specific (2026-09-19) — FIXED

**Status update (2026-09-19, same day): fixed at the source.** The
narrow, shape-specific detection condition described below has been
replaced with a structural one in `api/router.py`:
`tool_name in api.evaluator.STRUCTURED_HANDLERS` (the same registry
`evaluate_result()` already uses to know a handler's return isn't raw
"rows" to sample — hoisted from a function-local dict to a module-level
constant in `api/evaluator.py` so `router.py` can share it). Extracted
into one shared helper, `_serialize_tool_result_for_synthesis()`, used
at **both** truncation sites — the main loop body, and a **second,
independently-broken, unconditional `[:3000]` site inside
`_append_tool_result_message()`** (found during this fix, not part of
the original report below) used by three early-return synthesis
shortcuts (`query_pipeline_movement` fast-path, `dimension_retry_
succeeded`, `id_scoped_enrichment_lookup`) — the original Handler 4 fix
never touched this second site, so a structured handler reaching
synthesis through one of those shortcuts was still silently truncated
even after that fix shipped.

This automatically covers `query_waterfall` too (already registered in
`STRUCTURED_HANDLERS` as `["pipeline_summary", "waterfall"]`), even
though no baseline fixture exists to empirically confirm its real
payload size — see `test_query_waterfall_is_covered_by_the_same_
structural_fix` below.

**Verification:** `tests/test_synthesis_truncation_fix.py` drives the
real `dynamic_query_loop` end-to-end (scripted LLM responses; only the
handler functions are stubbed, returning the EXACT captured production
baseline data from `tests/fixtures/query_pipeline_baseline.json` and
`query_stale_deals_baseline.json` — not synthetic data) and confirms:
the full 7,654-char/313-deal `query_pipeline` payload and the full
14,207-char/64-deal `query_stale_deals` payload both now reach the
synthesis call intact (including a real company name from each — "UPS"
/ "Opera" — that sits past the old 3000-char cutoff); a negative control
proves the `STRUCTURED_HANDLERS` check specifically (not the test
harness) is what makes the data visible; `query_waterfall` is covered
via a synthetic payload shaped like its real, uncapped return value; and
a genuinely unstructured raw-row result (`filter_table`) is confirmed
**still** truncated, proving the fix didn't disable truncation
universally. Wired into `.github/workflows/gate-tests.yml` as TEST 0z.

**Not independently confirmable in this environment:** an actual live
LLM producing correct synthesized English from this data — no
`ANTHROPIC_API_KEY` / live Supabase credentials are available here. The
test instead proves the exact thing that was broken (the content handed
to the model), which is the full extent verifiable without live
credentials. A live re-ask of "show me our pipeline" / "what deals are
stale" in Slack is the remaining confirmation step, same as any other
fix from this session that needed live access (see High Priority #2 and
similar entries above).

**Existing baseline-capture scripts left unchanged, deliberately:**
`capture_query_pipeline_baseline.py` / `capture_query_stale_deals_
baseline.py` call handlers directly, bypassing `api/router.py`'s
synthesis step entirely — they verify handler output, never what the
LLM receives, which is why they never caught this bug class in 4
handler migrations. Rather than rewire them to also drive a live LLM +
Supabase (slow, non-deterministic, and costly on every CI run, for a
check that doesn't need either), the fix is verified by a separate,
deterministic synthesis-level test using the same captured baseline
JSON. If a future change needs the baseline scripts themselves to
exercise the full router path, that's a bigger, separate lift (real
LLM + live DB in CI) and should be scoped on its own, not bundled into
this fix.

**Original report follows, preserved for context:**

**Discovered while auditing the 3 previously-migrated handlers (query_pipeline,
query_stale_deals, query_waterfall) after the Handler 4 fix above, before
proceeding to Handler 5.** This is logged separately from the Handler 4 entry
because it is not a query_rep_pipeline bug — it is a property of the shared
synthesis step in `api/router.py` (~line 4877) that every handler and every
future handler passes through.

### The mechanism

Before a tool result reaches the LLM for synthesis, `api/router.py` checks:

```python
is_complete_structured = ("summary" in result and "total_deals" in result.get("summary", {}))
```

If this is False, the result is silently hard-truncated with `json.dumps(result, default=str)[:3000]`
before the LLM ever sees it — mid-list, mid-object, wherever 3000 chars lands.
The LLM then synthesizes an answer from whatever fragment survived, with no
signal to itself or the user that the data was cut.

This condition only matches a payload with a **top-level `summary` key that
itself contains a `total_deals` key** — the exact shape `query_rep_pipeline`
happens to return. It is not a general "is this a complete structured
dataset" check; it is a check for one handler's specific return shape.

### Exposure of the 3 previously-migrated handlers, checked directly against real captured output

| Handler | Has `summary.total_deals` shape? | Realistic-question payload size | Exposed? |
|---|---|---|---|
| `query_pipeline` | **No** — `total_deals` is top-level, no `summary` key at all | 6,856–7,654 chars across all 5 baseline test cases (`tests/fixtures/query_pipeline_baseline.json`) | **Yes — every captured test case exceeds 3000 chars** |
| `query_stale_deals` | **No** — `stale_count`/`total_stale_pipeline` are top-level, no `summary` key | Default/unscoped question ("what deals are stale"): **14,207 chars** (`tests/fixtures/query_stale_deals_baseline.json`, 3 of 6 test cases at this size). Single-owner-scoped questions: 1,891 chars (safe) | **Yes for the realistic default question — nearly 5x the truncation threshold.** Only owner-narrowed questions happen to stay under 3000 by coincidence of a smaller deal list, not by design |
| `query_waterfall` | **No** — top-level keys are `pipeline_summary`, `waterfall`, `period`, `report_shape`, `cache_payload`; `pipeline_summary` is a different key than `summary` and the condition checks the literal string `"summary"` | Not empirically captured — **no baseline fixture exists for this handler** (no `capture_query_waterfall_baseline.py`, unlike the other two). Structural estimate: `cache_payload.deals` is an uncapped `select_all()` over all deals closing in the time window (no `[:20]` or similar limit anywhere in the handler), stacked on top of `pipeline_summary.by_stage`, `needs_attention` lists, and the `waterfall` weekly rows — almost certainly exceeds 3000 chars for any non-trivial time window, consistent with `query_pipeline`'s capped 20-deal list alone already costing ~7000 chars | **Structurally confirmed to bypass the fix's detection condition; size not empirically measured — measuring it requires a live DB capture, which the environment used for this audit does not have credentials for** |

**Conclusion: all 3 previously-migrated handlers are structurally guaranteed to
bypass the fix's detection condition** (none has a `summary.total_deals`
shape), and at least 2 of 3 (`query_pipeline`, `query_stale_deals`) are
empirically confirmed, from their own captured baseline data, to produce
payloads well over the 3000-char cutoff for realistic, unscoped questions —
meaning they hit the *exact* same silent-truncation-before-synthesis bug
Handler 4 had, right now, in production, independent of and prior to any
Handler 5 work.

### Why the existing "Step C" baselines did not catch this

`tests/fixtures/capture_query_pipeline_baseline.py` and
`capture_query_stale_deals_baseline.py` both call the handler function
**directly** (`await query_pipeline({}, sb)`, `await query_stale_deals({}, sb)`),
bypassing `api/router.py` entirely. Their `critical_fields_to_verify` lists
(`total_deals`, `by_stage`, `by_owner`, `stale_count`, `total_stale_pipeline`,
deal-list lengths) are all fields of the **raw handler return value**. These
baselines never invoke the synthesis step and never capture or compare any
LLM-synthesized text at all — this is stronger than "only spot-checked that
the answer looked reasonable": there is no synthesized-answer check present
in these fixtures whatsoever. `query_waterfall` has no baseline fixture of
either kind.

The Handler 4 bug itself was only caught because it happened to be tested
live through the full Slack → router → synthesis path ("show me Christian's
pipeline" → "94 total active deals" — no equivalent fixture file exists for
`query_rep_pipeline` either). Nothing currently in the automated test suite
exercises the truncation-then-synthesis step at all — a repo-wide grep for
the fix's own marker strings (`is_complete_structured`, `COMPLETE DATASET`,
`[:3000]`) returns zero matches under `tests/`.

### Why structured verification ("Step D", `verify_structured_aggregations()`) does not protect against this

`verify_structured_aggregations()` runs **inside each handler, before
`return`** — it checks the handler's own internal aggregation math (e.g. that
`by_stage`/`pipeline_summary.total_open_arr` sums match a recomputation from
raw rows). By the time its result reaches `api/router.py`'s truncation step,
verification has already passed and returned. It has no visibility into, and
provides no protection against, what happens to that already-verified object
on its way to the LLM. A handler can pass `verify_structured_aggregations()`
with a perfectly correct return value and still have the user see a wrong
answer, because the corruption happens strictly after verification, in a
step verification never touches. This is true of `query_pipeline` and
`query_waterfall` today (both call `verify_structured_aggregations()` at
return) and was true of `query_rep_pipeline` before its fix.

### Forward-looking implication

**Any current or future handler** — migrated to unified routing or not —
that returns a payload without the specific `summary.total_deals` shape, and
whose realistic-question payload exceeds 3000 chars, is exposed to this same
silent truncation, regardless of how well-tested its internal aggregation
logic is. This includes Handler 5 and Handler 6 (not yet migrated) and any
handler built after this point. Passing `verify_structured_aggregations()`
and having a fixture-based baseline in the current style are both
insufficient to catch it, because neither exercises the synthesis step.

**[Superseded by the "FIXED" status update at the top of this entry —
left here for history.] Not fixed in this pass** — this was a report,
per explicit instruction at the time, to establish full exposure before
Handler 5 proceeded or Handler 4 was considered closed. Two directions
were visible during this audit but not evaluated for tradeoffs or
implemented then:
1. Generalize the detection condition to something structural (e.g. "does
   this result contain a count/total field anywhere, regardless of nesting"
   or "is this a `dict`, not a `rows` list, at all" — the latter matches the
   comment already in the code: "Row-based results are already
   sampled/aggregated" implies the *intent* was "any non-row-based
   structured result," not "only this one handler's shape"). **Done** —
   implemented as option 1's spirit, via `STRUCTURED_HANDLERS` membership
   rather than a `dict`-vs-`rows` shape check (a cleaner structural signal
   already single-sourced elsewhere, per Jeff's direction).
2. Add a baseline-capture mode that runs the full router/synthesis path (not
   just the bare handler call) and asserts the synthesized text's stated
   count/total against the verified raw data, for every migrated handler —
   closing the exact gap that let the Handler 4 bug through 3 handler
   migrations before anyone was testing that path at all. **Done**, via a
   separate dedicated test (`tests/test_synthesis_truncation_fix.py`)
   rather than rewiring the existing baseline-capture scripts themselves —
   see the "Existing baseline-capture scripts left unchanged" note above
   for why.


## ✅ Phase 2 Handler 5/6 (query_win_loss) — Migrated, 3 real bugs found

**Date**: 2026-09-19. Steps A/B/C/D done; live-verified via GitHub
Actions (Agent environment secrets) since this environment has no local
credentials — see the two runs linked below.

**STEP A (parameter completeness):** No gaps. `time_window` is the
generic schema field, pre-resolved by `_call_handler_as_tool()` before
any registered handler runs; `deal_ids` is injected by the same generic
entity-scope/pronoun-resolution/explicit-ID mechanism every handler
(migrated or not) already relies on.

**STEP B (registration):** Added to the `tool_fn` dict, the dynamic
loop's tool-description section, and the classifier bypass list.

**STEP D (structured verification):** `query_win_loss` had no
`verify_structured_aggregations()` call at all — added one, verifying
`win_count`/`loss_count` against the actual won/lost split, tested with
a planted discrepancy (`tests/test_query_win_loss_migration.py`).

**STEP C (baseline + live verification):** capture script added
(`tests/fixtures/capture_query_win_loss_baseline.py`). Two live GitHub
Actions runs against the `Agent` environment's real Supabase/HubSpot/
Anthropic secrets:
- Run 1 ([35442311297](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35442311297)) — **failed** on the baseline capture step, surfacing real bug #3 below.
- Run 2 ([35442557240](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35442557240)) — **succeeded** after the fix. Baseline: current quarter = 7 wins / 80 losses ($322K win ARR, 142,742-char full payload); last 90 days = 39 wins / 199 losses. Live rendered answers for two independent phrasings ("why are we losing", "give me a win loss summary for this quarter") both correctly stated **7 wins ($322K ARR) vs. 80 losses**, with real deal names (Comcast $350K, Fanatics Live $250K, ASN Bank lost to Adobe Target, etc.) and an honest data-quality caveat — no truncation, no hallucination, consistent across both phrasings.

**Three real bugs found and fixed during this audit** (not
hypothetical — this handler surfaced independent bugs the same way
every other handler touched this session has):

1. **`STRUCTURED_HANDLERS["query_win_loss"]` only checked `"losses"`.**
   A genuine wins-only quarter (real wins, zero losses — a *good*
   outcome) would return `losses=[]` and get misclassified as `"empty"`
   by `evaluate_result()`, discarding a real answer. Fixed to check
   `"wins"` OR `"losses"` (`api/evaluator.py`).

2. **`query_waterfall` and `query_rep_pipeline`'s verification-failure
   branches read `verification_result['details']`**, but the real
   return key on failure is `'discrepancies'` (confirmed against
   `api/structured_verification.py`'s own docstring and its two other
   call sites, `query_pipeline`/`query_stale_deals`, which already use
   the correct key). A genuine verification failure in either handler
   would have raised `KeyError` instead of the intended, clear
   `ValueError` message — copied into `query_win_loss`'s own first
   draft during this migration, caught and fixed in all three places.

3. **`_resolve_tw()` — shared by 14 handlers — didn't resolve a
   truthy-but-unresolved raw `time_window` spec**, only a missing one
   (`if tw: return tw` returned a raw `{"period": ..., "n": ...}` dict
   verbatim). Never fired in production (every real path pre-resolves
   `time_window` before calling any handler) but broke the function's
   own documented "answerable... under test" guarantee, and is exactly
   what crashed the live Step C baseline-capture run above with
   `KeyError: 'start'`. Fixed to resolve anything not already carrying
   both `"start"` and `"end"`, benefiting all 14 call sites.

**Also notable, not a bug:** `query_win_loss`'s full current-quarter
payload is 142,742 chars — by far the largest of the 5 migrated
handlers (query_stale_deals' was 14,207). Now safely un-truncated per
the `STRUCTURED_HANDLERS` fix above, and the live run confirms the LLM
handles it correctly, but this is a real cost/latency data point:
`narratives` (free-text weekly AI narratives) is the likely dominant
contributor. Worth a future look at whether `query_win_loss` needs its
own internal capping/summarization for cost, independent of the
truncation-correctness question this session was about — not urgent,
not a correctness bug, just flagged so it isn't rediscovered as a
surprise later.

**Status: Handler 5/6 complete, live-verified, ready for Handler 6
(query_deals_at_risk).**


## ✅ Phase 2 Handler 6/6 (query_deals_at_risk) — Migrated, final handler in the set

**Date**: 2026-09-19. Steps A/B/C/D done, live-verified via GitHub
Actions — this is the last of the 6 Phase-2 handlers (plus the Phase 1
query_pipeline_movement pilot), so all 7 unified-routing handlers are
now migrated and live-verified.

**STEP A:** No gaps — `deal_ids` and `time_window` both reach the
handler via the same generic mechanisms every other handler relies on.

**STEP B:** Registered in `tool_fn`, tool description, classifier
bypass list. **Real bug found and fixed BEFORE any live run** (Step
A/B review alone, not live testing): `STRUCTURED_HANDLERS` had no entry
for `query_deals_at_risk` at all, and a naive `["deals_at_risk"]`-only
entry would have reproduced `query_win_loss`'s exact wins-only mistake
— the genuinely-empty "no deals at risk" case has an empty
`deals_at_risk` list but a complete, human-readable `message`
explaining why. Registered as `["deals_at_risk", "message"]` so that
case classifies `"good"` instead of `"empty"` (which would have wasted
a dynamic-query fallback on a question the handler already answered).

**STEP D:** `query_deals_at_risk` had no `verify_structured_
aggregations()` call — added one verifying `total_at_risk` against the
real count *before* the top-10 display slice, tested with a planted
discrepancy.

**STEP C (baseline + live verification):** capture script added
(`tests/fixtures/capture_query_deals_at_risk_baseline.py`), including a
raw-unresolved `time_window` case specifically re-testing the
`_resolve_tw()` fix from Handler 5's audit against this handler too —
**confirmed it protects this handler as well** (no crash; baseline:
current scope = 63 at-risk deals, raw last-30-days spec = 52, both
succeeded). Live GitHub Actions run
([35443858332](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35443858332)):
"which deals are at risk" correctly routed to `query_deals_at_risk`
(`[HANDLER] query_deals_at_risk → good`, confirming the STRUCTURED_
HANDLERS fix classifies correctly) and answered **"63 deals flagged at
risk"** — exact match to the baseline capture's 63 — with real company
names (UPS $300K, ClickHouse $200K, etc.), real risk flags, and a
genuine pattern observation (Discovery-stage deals lacking Pain/
Champion scores, likely call-coverage gaps).

**Honest note on the second live phrasing:** "which deals have champion
gaps this quarter" did **not** route to `query_deals_at_risk` — the
classifier picked `query_deal_health` (confidence 0.95) instead, a
different, pre-existing, unmigrated handler. Confirmed this is **not a
regression from this migration**: `query_deal_health` isn't in the
unified-routing bypass list, was never touched by this work, and the
ambiguity is a genuine natural-language one between two legitimate
handlers with overlapping claims on "champion gaps" phrasing — exactly
the kind of classifier routing ambiguity `docs/UNIFIED_ROUTING_
ARCHITECTURE.md` names as a demonstrated bug class motivating the whole
migration, just not one this session chased down (out of scope: neither
handler was wrong to want that phrasing, and `query_deal_health` isn't
part of the Phase 2 migration set). So Handler 6 has ONE exact-match
live confirmation, not two — reported honestly rather than treating the
second run as a second success.

**No new `STRUCTURED_HANDLERS`/`['details']`-class bugs found in this
handler beyond the one listed above** — the `_resolve_tw()` and
`verification_result['details']` bugs were both shared-code issues
already fixed during Handler 5's audit and confirmed (via the raw-spec
baseline test case above) to already protect this handler too.

**Status: Phase 2 migration COMPLETE.** All 7 unified-routing handlers
(`query_pipeline_movement`, `query_pipeline`, `query_stale_deals`,
`query_waterfall`, `query_rep_pipeline`, `query_win_loss`, `query_deals_
at_risk`) are migrated, registered in `STRUCTURED_HANDLERS` (so none of
them can hit the synthesis-truncation bug class), have structured
verification wired, and have at least one live-verified exact-match
rendered answer. Remaining follow-ups from this whole audit, not
blocking: (1) `query_win_loss`'s 142K-char payload as a future cost/
latency look; (2) the `query_deal_health` / `query_deals_at_risk`
phrasing ambiguity noted above, if it's ever worth disambiguating
further; (3) the deferred `docs/UNIFIED_ROUTING_ARCHITECTURE.md` Phase 2
follow-through items (removing `HANDLER_DESCRIPTIONS` entries for
migrated handlers, removing now-dead redirect logic) — cosmetic/cleanup,
not correctness, left for a deliberate separate pass.


## 📊 EVIDENCE AUDIT: What primitive to build next (2026-09-19, report only — nothing built)

**Purpose:** replace the roadmap's guess-based ordering with real
frequency data from `query_cost_log` (every `dynamic_query_loop`
invocation, full history — 166 rows) and `learning_log` (assessor
correctness signals, full history — 517 rows). Script:
`scripts/audit_dynamic_query_failure_shapes.py`, run live via
[`audit-dynamic-query-failure-shapes.yml`](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35444671737)
(one-off, read-only).

**Population:** 82 of 166 query_cost_log rows (49.4%) were not a clean
answer — 37 failed outright (exception/other_fallback), 17 shipped
caveated, 28 needed a resynthesis. From learning_log: 105 floor
rejections, 10 `should_be_dynamic` flags, 402 ordinary dedicated-handler
mistakes (excluded from shape analysis — those are bugs in an existing
handler, not evidence for a new primitive). 197 rows total went into
shape classification (a live Haiku call per batch, role=evaluator).

**Methodology note, disclosed rather than hidden:** batching the Haiku
classification calls (40 questions/call) let the model coin a fresh
label per batch instead of reusing one — the raw output had 35 near-
duplicate labels (`pipeline movement tracking`, `pipeline trend`,
`pipeline velocity`, `pipeline trend analysis`, ... all the same
underlying need). The counts below are **consolidated by hand from the
actual example questions in each raw label** — a more reliable ground
truth than trusting the model to self-merge — not the raw per-batch
output. Full raw output is in the workflow run's log if anyone wants to
re-check the consolidation.

**A second, code-verified correction, not a guess:** once a handler is
added to the classifier bypass tuple (all 7 unified-routing handlers,
6 of them migrated THIS session), it can never again produce a
`floor_rejection` learning_log row — that check only runs for handlers
still on the classifier path, and bypassed handlers are redirected to
`dynamic_query` *before* the floor check ever executes. So any
`floor_rejection` evidence whose shape maps to an already-migrated
handler is now structurally impossible to recur, confirmed by reading
`route_question()`'s own code order, not inferred from timestamps
(which weren't captured in this pass). Resynthesis/caveat/exception/
`should_be_dynamic` evidence is NOT covered by this correction — those
are dynamic_query's own synthesis behavior or a dedicated handler's
substantive wrongness, neither of which the routing migration touches.

### Consolidated shape frequency (raw → adjusted after removing migration-fixed floor_rejections)

| Shape | Raw count | Migration-fixed portion | Adjusted (still open) | % of adjusted total |
|---|---|---|---|---|
| Pipeline movement / trend over time | 100 | 66 (floor_rejection, now-migrated `query_pipeline_movement`/`query_waterfall`) | **34** | 34.7% |
| Pipeline current state / snapshot | ~29 | 4 | **25** | 25.5% |
| Risk/likelihood judgment | 18 | 0 (not a migrated-handler concept) | **18** | 18.4% |
| Stale deals | 18 | 10 (`query_stale_deals`, migrated) | **8** | 8.2% |
| Rep coaching / activity metrics | 6 | 0 | **6** | 6.1% |
| Data hygiene / corrections | ~5–6 | 0 | **~5** | 5.1% |
| Pipeline segmentation (geo/market) | 3 | 0 | **3** | 3.1% |
| Why did we win/lose | 4 | 3 (`query_win_loss`, migrated) | **1** | 1.0% |
| Competitive positioning | 1 | 0 | **1** | 1.0% |
| Forecast trustworthiness | 1 | 0 | **1** | 1.0% |
| Objection patterns | 1 | 0 | **1** | 1.0% |
| Sales cycle velocity | 1 | 0 | **1** | 1.0% |
| *(meta/noise — bot complaints, acknowledgments, "run that query" — excluded)* | ~8 | — | — | — |

**Two honest caveats on the numbers, not swept under the rug:**

1. **Risk/likelihood judgment's 18 is one person retrying one exact
   question** ("please look at all hubspot deals in the 'negotiating'
   or 'awaiting signature' stages and assess them based on likelihood
   to close vs risk") repeatedly, not 18 distinct asks. As a *distinct-
   question* count it's ~1; as a *this kept failing and someone kept
   trying anyway* signal it's real and matches this session's own
   earlier `assess_deal_risk()`/`deal_risk_assessor.py` scoping work
   directly — a live, previously-uncounted confirmation that the demand
   for it is real, not hypothetical.
2. **The "adjusted" pipeline-movement/snapshot numbers (34, 25) are a
   floor, not a ceiling** — some of their remaining resynthesis/caveat
   rows may *also* already be fixed by this session's synthesis-
   truncation fix (a `caveated:answered_with_unverified_aggregation`
   result on a large pipeline payload is exactly this bug's signature),
   but confirming that needs each row's `primitives_fired`/timestamp
   cross-referenced against the truncation-fix commit, which this pass
   didn't do. So 34 and 25 are conservative upper bounds on what's
   still genuinely open there, not confirmed floors.

### Reading the ranking

**Risk/likelihood judgment is the strongest *qualified* signal for a
new primitive**: fully unaffected by tonight's routing/truncation
fixes, matches a primitive already designed (not from scratch) in this
session's earlier `assess_deal_risk()` scoping and the pulled-in
`scripts/deal_risk_assessor.py`, and the repeated-retry pattern is
itself evidence of real, unresolved frustration — just don't read "18"
as "18 different people asked this."

**Pipeline movement/snapshot's raw dominance (65% of all evidence
combined) is real but mostly not a call for a NEW primitive** — the
handlers already exist (`query_pipeline_movement`, `query_pipeline`,
`query_waterfall`, `query_rep_pipeline`); the bulk of the evidence is
either a routing-confidence problem this session's own migration
structurally closed tonight, or (plausibly, unconfirmed) the synthesis-
truncation bug this session also already fixed. Worth a live spot-check
of a few of the remaining "adjusted" rows before assuming they're still
open, not worth a new primitive.

**Everything else (rep coaching, data hygiene, pipeline segmentation,
win/loss, competitive positioning, forecast trustworthiness, objection
patterns, sales cycle velocity) is real but low-volume** — none has
enough distinct occurrences in the available history to outrank risk/
likelihood judgment on frequency alone. Objection patterns and
competitive positioning both already appear as named gaps elsewhere
(objection vault extraction is on the "Pending features" list at the
top of this file); this audit doesn't newly discover them, it just adds
a real (if thin: n=1 each) frequency data point to what was previously
a pure guess.

**No primitive was designed or built in this pass — report only, per
explicit instruction.**

