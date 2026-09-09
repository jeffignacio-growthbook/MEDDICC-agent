# Pending Work

**Last Updated:** 2026-09-09 (updated after synthesis aggregation fix completion)
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

**Total Open Items:** 3
- High Priority: 1 (snapshot ETL phantom exits)
- Low Priority: 2 (zero-day cycle times, forecast bugs)

**Recently Completed:** 4
- Synthesis aggregation gap (2026-09-09) - **TESTED & VERIFIED** (core bug fixed)
- aggregate_results empty data bug (2026-09-09) - **IMPLEMENTED & VERIFIED** (Sept 6 impact: LOW)
- Waterfall region + segment segmentation (2026-09-08) - **PRODUCTION VERIFIED**
- Test data hygiene (2026-09-08)

**Major Milestones:**
- Synthesis aggregation gap fixed: Eliminated week/segment anchoring and false "partial" claims. Test results show complete data reporting with no dropped segments or activities.
- Region-segmented waterfall production-verified with 972 historical rows across 56 weeks (Aug 2025 → Sep 2026), enabling accurate EMEA/APAC/LATAM/NAM pipeline reporting by company size segment.
- aggregate_results 66.7% failure rate fixed with three-layer validation (prompt + tool + router), verified no real user harm (Sept 6 answer accurate despite internal failure).
