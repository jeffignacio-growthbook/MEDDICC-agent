# Pending Work

**Last Updated:** 2026-09-10 (updated after date-resolution single-source-of-truth audit)
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

**Total Open Items:** 5
- High Priority: 1 (snapshot ETL phantom exits)
- Low Priority: 4 (zero-day cycle times, forecast bugs, rep-name-to-email
  matching, snapshot ETL date.today() day-boundary stamp)

**Recently Completed:** 5
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
