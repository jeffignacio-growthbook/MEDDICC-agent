# Pending Work

**Last Updated:** 2026-09-11 (added Low Priority #8 — confirming the URGENT safety fix worked via a live CI re-run surfaced a genuinely pre-existing, unrelated finding: `eval_handler_descriptions.py` has been failing on 5 undocumented handler-adjacent functions since `b75a3c1` (2026-09-06), invisible until now only because the `ClientOptions` crash blocked CI before it ever reached that check; not urgent, not caused by tonight's work, confirmed via `git blame`; 🚨 URGENT SAFETY FIX: a live CI run of `gate-tests.yml` failed twice, identically, with `ImportError: cannot import name 'ClientOptions' from 'supabase' (unknown location)` at `api/db.py`'s import — added earlier the same night for the Supabase retry-transport fix — killing every downstream test; since Railway's deploy process plausibly does a similarly fresh install, this risked crashing the live app on its next deploy. Fixed by moving the `ClientOptions` import inside `create_resilient_supabase_client()`'s own try block (`scripts/supabase_client.py`), lazy not top-level, so any import-time failure degrades to a plain client with no retry protection instead of crashing — see `tests/test_supabase_client_fallback.py` (forces the exact failure and confirms a working client still comes back) and new High Priority #4 for the not-yet-root-caused "why does GitHub's runner resolve this differently" investigation, explicitly not blocking on it; shipped `resolve_execution_cost_estimate()` (`api/router.py`) — a pre-execution cost estimate for `dynamic_query_loop`, calibrated against 13 real `query_cost_log` rows pulled via `scripts/query_cost_log_calibration.sql`, warning on an expensive-looking question before running anything; every estimate self-reports low confidence given the tiny calibration sample, tracked as Low Priority #7 for recalibration once more traffic accumulates; also fixed a `.github/workflows/gate-tests.yml` naming collision from an earlier round tonight — two unrelated CI steps were both labeled "TEST 1b"; closed the loop on High Priority #2's open question: confirmed the RemoteProtocolError/ConnectionTerminated connection bug is NOT the explanation for the original Jake Stangl incident — the incident's own captured evidence was a completed request/response, structurally incompatible with a connection that died mid-stream, and no code path exists where that error could silently become an empty result. Status unchanged (MITIGATED, NOT ROOT-CAUSED) and now explicitly deprioritized — not actively being chased, re-open only if it recurs; added Low Priority #6, a known unclosed blind spot in `PRIMITIVE_CHECKLIST.md`'s two structural scans — a resolver-style function that returns ambiguous/unknown with no log call at all on that path, like `resolve_dimension_filter`, is invisible to both the function-name scan and the bracketed-log-tag scan added the same night; closing it needs a bigger lift, either a logging convention or real control-flow static analysis, not scoped or started; fixed a 4th detection-primitive gap found the same night, same file: the zero-rows suspicion note in `dynamic_query_loop` detected a suspicious enumeration-question zero-row result and logged an advisory note, but never verified the model acted on it before shipping — added a compliance check + its own outcome bucket (`answered_with_unresolved_zero_row_suspicion`), registered in `FAILURE_MODE_PRIMITIVES`, see `PRIMITIVE_CHECKLIST.md`'s "Follow-up audit" section; also fixed an unrelated stale test found along the way — `tests/test_zero_rows_suspicion.py`'s 3rd test had been failing since 2026-09-06 checking the wrong location for missing-value prompt guidance that was deliberately relocated to `api/router.py`'s `DYNAMIC_SYSTEM_PROMPT`, not lost; also fixed the recurring Supabase `httpx.RemoteProtocolError: ConnectionTerminated` connection issue found via a live test session — a long-lived singleton client hitting a known httpx/HTTP2 gotcha, fixed with a retry-once transport, see `scripts/supabase_client.py`'s `_RetryOnDeadConnectionTransport`; added `PRIMITIVE_CHECKLIST.md` — a standing, CI-enforced contract every detection primitive must satisfy, retroactively applied to fix 3 primitives found log-only with the same "detect but never act" gap the original aggregation-verification incident had; added High Priority #3, a follow-up audit of every other dedicated handler for the same owner-email exact-match risk found in query_pipeline_movement — defensive logging shipped everywhere, deeper canonicalization fix still pending per-handler; added High Priority #2, a query_pipeline_movement zero-row bug for an SDR that is MITIGATED but NOT root-caused — two hypotheses hardened, two more ruled out, the actual trigger still unconfirmed; added Low Priority #5, a confirmed-inert `synthesis_aggregation_fix.py` at the repo root that should be deleted or marked historical; ⚠️ see High Priority #0, a committed DB credential needs rotation)
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

#### 8. `eval_handler_descriptions.py` Has Been Failing on 5 Undocumented Handler-Adjacent Functions Since At Least 2026-09-06

**Issue:** `scripts/eval_handler_descriptions.py` (run as part of `TEST
0` in `.github/workflows/gate-tests.yml`) asserts every function it
finds in `api.handlers`'s namespace has a matching entry in
`HANDLER_DESCRIPTIONS`. A live CI run surfaced it failing with:

```
AssertionError: Missing descriptions for 5 handlers:
{'compute_cycle_time', 'load_scope_config', 'canonical_stage',
 'is_deal_in_analytics_scope', 'compute_at_risk_deals'}
```

**Status:** NOT FIXED, not urgent, not related to tonight's work.
Confirmed via `git blame` that all five names trace back to commit
`b75a3c1`, dated 2026-09-06 — five days before this failure was ever
seen. This was previously invisible for an unrelated reason: the
`httpx.RemoteProtocolError`/`ClientOptions` import-crash fix (High
Priority #4) blocked `TEST 0` before it ever reached this specific
check — once that crash was fixed, the workflow finally progressed far
enough into `TEST 0`'s own sequence of eval scripts to run
`eval_handler_descriptions.py` for the first time in this session, and
it immediately failed. A real, if narrow, documentation gap has been
silently un-verified in CI for five days, not a regression from
anything done tonight.

**Work:** For each of the 5 names, either add a `HANDLER_DESCRIPTIONS`
entry (if it's genuinely handler-shaped and should be discoverable/
routable) or adjust `eval_handler_descriptions.py`'s own scan to
exclude it (if it's a helper/utility function that was never meant to
be a "handler" in the routing sense — `load_scope_config` and
`is_deal_in_analytics_scope` are imported from `point_in_time`, not
defined in `api/handlers.py` itself, which suggests the scan may be
too broad rather than these five being genuinely missing
documentation). Needs a quick look at what the scan actually enumerates
before deciding which fix applies to which name.

**Complexity:** Low — this is a bounded, 5-item list with a clear
repro (the CI failure output above); the only real work is deciding
per-name whether it needs a description or an exclusion, then making
that small change.

**Documentation:** none yet — first surfaced in this session via the
live CI run that also confirmed High Priority #4's fix.

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
