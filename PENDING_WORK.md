# Pending Work

**Last Updated:** 2026-09-08 (updated after waterfall segmentation completion)
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

## 📋 Backlog

### High Priority

#### 1. Waterfall net_change Formula Bug
**Issue:** `compute_waterfall_segmented.py` incorrectly includes `moved_forward_value` and `moved_backward_value` in net_change calculation

**Impact:** High - affects data integrity across all 56 weeks of waterfall data
- Stage movements double-counted, causing reconciliation mismatches
- `beginning_value + net_change ≠ ending_value`
- Example: Aug 28 EMEA/Enterprise shows $97K mismatch
- Synthesis may report "growth" when deals just re-ordered stages

**Evidence:**
- Aug 28 EMEA/Enterprise: Beginning $2.2M, Ending $2.2M, but net_change +$97K
- Zero ARR changes between snapshots, yet moved_forward $142K - moved_backward $45K = $97K
- Reconciliation: Expected ending $2.3M, actual $2.2M (mismatch = net_change)

**Root cause:** Stage movements represent deals re-ordering within pipeline, not entering/leaving
- Deal moving stage 3→4 is counted in BOTH beginning (at stage 3) and ending (at stage 4)
- Adding moved_forward to net_change double-counts it

**Correct formula:**
```python
net_change = new_pipeline + newly_qualified - won - lost
# NOT including moved_forward/backward
```

**Work required:**
1. Fix formula in `compute_waterfall_segmented.py` (lines 494-501)
2. Fix formula in `compute_waterfall.py` (if still used)
3. Recompute all historical data (56 weeks)
4. Verify zero reconciliation mismatches after recompute

**Complexity:** Low effort, high impact

**Documentation:** WATERFALL_NET_CHANGE_BUG.md

**Discovered:** 2026-09-08 via live Slack test + user scrutiny ("Don't accept 'likely an ARR update' - trace the actual deals")

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
- High Priority: 1 (waterfall net_change formula bug - data integrity)
- Low Priority: 2 (zero-day cycle times, forecast bugs)

**Recently Completed:** 2
- Waterfall region + segment segmentation (2026-09-08) - **PRODUCTION VERIFIED**
- Test data hygiene (2026-09-08)

**Major Milestone:** Region-segmented waterfall production-verified with 972 historical rows across 56 weeks (Aug 2025 → Sep 2026), enabling accurate EMEA/APAC/LATAM/NAM pipeline reporting by company size segment. Workflow confirmed calling segmented script, historical gap closed, synthesis honesty rule deployed (pending production trigger test).
