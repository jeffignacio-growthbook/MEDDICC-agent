# Pending Work

**Last Updated:** 2026-09-08
**Purpose:** Single tracking mechanism for all documented-but-not-implemented work

---

## ✅ Recently Completed

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

#### 1. Region-Aware Waterfall Segmentation
**Issue:** waterfall_weekly lacks region column, so regional pipeline questions get partial answers (new deals only) presented as if complete.

**Impact:**
- Regional pipeline reporting (EMEA, APAC, LATAM, etc.) currently incomplete
- Executive dashboards need region-specific waterfall
- Questions like "How has EMEA pipeline moved" get narrower answers without clear flagging

**Work Required:**
1. **Schema:** Add region column to waterfall_weekly table
   ```sql
   ALTER TABLE waterfall_weekly ADD COLUMN region TEXT;
   CREATE INDEX idx_waterfall_weekly_region ON waterfall_weekly(region);
   ```

2. **Table Grain:** Change from `(week_ending, pipeline_id)` to `(week_ending, pipeline_id, region)`

3. **Computation:** Update `scripts/analytics/compute_waterfall.py`
   - Group by `(week_ending, pipeline_id, region)` instead of `(week_ending, pipeline_id)`
   - Handle UNKNOWN region explicitly (don't drop it)

4. **Data Dictionary:** Register waterfall_weekly.region as queryable
   ```python
   {
       'supabase_table': 'waterfall_weekly',
       'supabase_column': 'region',
       'enum_values': ['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN'],
       'is_queryable': True
   }
   ```

5. **Historical Backfill:** Run `compute_waterfall.py --backfill` to recompute all historical data with region segmentation

**Complexity:** Medium (schema change + historical backfill + computation logic update)

**Documentation:** REGION_WATERFALL_GAP.md

**Related:** REGION_DATA_DICTIONARY_FIX.md (region classification implementation), config/regions.yaml (region mappings)

---

### Medium Priority

#### 2. Synthesis Question Substitution Pattern
**Issue:** When LLM identifies it cannot fully answer the question and substitutes a narrower question, it doesn't flag this substitution to the user.

**Example:**
- User asks: "How has EMEA pipeline moved in the last 2 weeks"
- LLM reasoning: "waterfall table doesn't have EMEA segmentation, let me look at new deals instead"
- LLM answer: Shows "EMEA Pipeline Movement" header but only includes new deals created

User sees "EMEA Pipeline Movement" and assumes full pipeline movement (beginning/ending/won/lost), but it's actually only showing new deals created.

**Fix:**
Make synthesis step explicitly flag when it substitutes a narrower/different question:

```
⚠️ Note: waterfall_weekly isn't region-segmented yet, so this shows
new deal creation only, not full pipeline movement (beginning/ending/
won/lost/net change). For full EMEA pipeline movement, I'd need
region-aware waterfall data.
```

**Implementation Location:** `api/router.py` or wherever synthesis step formats final answers

**Pattern:** Same "explicit honesty about data gaps" pattern as:
- `no_signal_at_risk` (MEDDICC gaps surfaced explicitly)
- `UNKNOWN` region (missing geography surfaced explicitly)

**Documentation:** REGION_WATERFALL_GAP.md (section 2)

---

### Low Priority

#### 3. Zero-Day Cycle Time Deals
**Issue:** 4 deals with negative or zero cycle time (data quality artifacts)

**Impact:** Low (already filtered by `is_valid_cycle_deal()` in handlers, but exist in raw data)

**Work:** Investigate and clean up at source (HubSpot or ETL)

**Complexity:** Low effort

---

#### 4. Forecast Analysis Bugs (Status Unconfirmed)
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

**Total Open Items:** 4
- High Priority: 1 (waterfall region segmentation)
- Medium Priority: 1 (synthesis question substitution)
- Low Priority: 2 (zero-day cycle times, forecast bugs)

**Recently Completed:** 1 (test data hygiene)

**Next Recommended:** Waterfall region segmentation (highest impact, enables accurate regional reporting)
