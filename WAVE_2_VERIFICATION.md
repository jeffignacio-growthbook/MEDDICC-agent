# Wave 2 Verification Report

**Commit:** 349f3c7
**Date:** 2026-09-01

---

## Files Modified

All files exist in origin/main (verified via git ls-tree):

```
api/db.py                                 blob 9c2fd3f
.github/workflows/weekly-analytics.yml    blob 66d00a6
config/field_semantics.yaml               blob 0c30839
```

---

## Bug 1: Entity Extraction Cap

### Before
```python
# api/db.py lines 165-166
entities[entity_type]["ids"] = entities[entity_type]["ids"][:20]
entities[entity_type]["labels"] = entities[entity_type]["labels"][:20]
```

**Behavior:** `extract_entity_context()` capped all entity IDs at 20 after deduplication.

**Evidence from logs:**
- `[SAVE_THREAD] saving entity_context: 20 deal_ids` on answer covering 168 deals
- `[SAVE_THREAD] saving entity_context: 20 deal_ids` on answer covering 253 deals
- Follow-up "Which of those are enterprise" against 44-deal renewal answer → only considered 20
- Expansion-ARR analysis reported $102.4K across 3 deals, having looked at 20 of 253

### After
```python
# api/db.py lines 165-166
# NO CAP HERE - entity extraction preserves full population for follow-ups
# Capping happens in synthesis via _cap_rows_for_synthesis() in router.py
```

**Behavior:** `extract_entity_context()` now returns ALL entity IDs found in handler output.

**Expected logs:** `[SAVE_THREAD] saving entity_context: N deal_ids` where N matches the actual population (168, 253, etc.), not always 20.

**Verification method:** Next answer covering >20 deals should log full count in `[SAVE_THREAD]` message.

---

## Bug 2: Snapshot Cron Schedule

### Before
```yaml
# .github/workflows/weekly-analytics.yml line 5
- cron: '0 3 * * 0'  # Sunday 3:00 AM UTC
```

**Behavior:** Ran Sunday 3am UTC

**Conflict:** weekly-snapshot.yml runs Monday 2am UTC (`'0 2 * * 1'`).
Method 2 backfill used Monday grid. Grid guard refused to mix Sunday + Monday snapshots.

**Impact:** FY2027 Q2 week-3 snapshot had 192 rows vs typical 475.
Quarter excluded from conversion rate analysis due to incomplete data.

### After
```yaml
# .github/workflows/weekly-analytics.yml line 5
- cron: '0 3 * * 1'  # Monday 3:00 AM UTC (matches weekly-snapshot.yml grid)
```

**Behavior:** Runs Monday 3am UTC, matching weekly-snapshot.yml Monday 2am grid.

**Impact:** Does not repair Q2 historical data, but prevents problem regenerating in future quarters.

---

## Semantic Gap 1: Precomputed Tables

### Added to field_semantics.yaml (lines 26-59)

Documentation for three precomputed tables:
- `forecast_weekly` — quarter forecast by stage probability and historical conversion
- `waterfall_weekly` — pipeline movement categorization for waterfall charts
- `pipeline_generation_weekly` — new pipeline generation metrics

**Key constraint (STALENESS GUARD):**
> A precomputed value is only valid if recent. If computed_at is stale relative to the question, STATE IT rather than silently serving an old number.

Example: "Last computed 21 days ago on 2026-08-10 — may not reflect recent changes."

**Purpose:** Prevent returning raw open pipeline ($16.1M) when asked for Q3 forecast ($7.6M).

---

## Semantic Gap 2: Field Display Names

### Added to field_semantics.yaml (lines 220-235)

```yaml
field_display_names:
  deal_value: "Incremental ARR"
  arr_usd: "Total ARR"
  new_arr: "New ARR"
  expansion_arr: "Expansion ARR"
  renewal_revenue: "Renewal ARR"
  close_date: "Expected Close Date"
  created_at: "Created Date"
  stage_probability: "Win Probability"
```

**Constraint:** Synthesis uses display names, never column names.

**Example problem prevented:**
- Before: "$7.95M deal_value in Discovery" (column name, unclear meaning)
- After: "$7.95M Incremental ARR in Discovery" (display name, clear meaning)

---

## Semantic Gap 3: Scope Vocabulary

### Added to field_semantics.yaml (lines 250-286)

Three distinct scopes defined:

1. **OPEN PIPELINE**
   - All active deals (deal_status = 'active')
   - Regardless of close date
   - Use case: "How much pipeline do we have overall?"

2. **QUARTER PIPELINE**
   - Deals with close_date inside a specific quarter
   - Example: FY2027 Q3 = Aug 1 - Oct 31, 2026
   - Use case: "What's in the Q3 pipeline?" "What do you forecast for Q3?"

3. **QUALIFIED PIPELINE**
   - At or above qualified_stage_order threshold
   - Excludes parking-lot stages (exclude_from_analysis: true)
   - Can combine with Quarter (qualified Q3 pipeline)
   - Use case: "How much qualified pipeline do we have?"

**Constraint:** Handler logic MUST state which scope it used.

**Example problem prevented:**
- "$16.1M open" vs "$7.6M Q3" — both correct, different questions
- Never say "$7.6M in Discovery" without clarifying "Discovery overall" vs "Discovery closing in Q3"

---

## Next Step: Test Forecast Query

**Question to test:** "What do you forecast for the quarter?"

**Expected behavior:**
1. ✅ Reads `forecast_weekly` table (precomputed)
2. ✅ Scopes to FY2027 Q3 (quarter pipeline, not open pipeline)
3. ✅ Says "Incremental ARR" (display name, not deal_value)
4. ✅ States staleness if `computed_at` is >7 days old

**Verification:** Run query via Slack agent, check logs for:
- `[HANDLER] forecast_weekly` (precomputed table access)
- `fiscal_quarter = 'FY2027 Q3'` (quarter scope)
- Answer text contains "Incremental ARR" not "deal_value"
- Staleness warning if computed_at is stale

---

## Summary

✅ Bug 1: Entity extraction no longer caps at 20 — full population preserved
✅ Bug 2: Snapshot cron moved to Monday — grid alignment fixed
✅ Semantic Gap 1: Precomputed tables documented with staleness guard
✅ Semantic Gap 2: Field display names mapped for synthesis
✅ Semantic Gap 3: Scope vocabulary disambiguates three pipeline populations

All fixes committed to main (349f3c7).

**Remaining:** Test forecast query to verify semantic gaps are enforced by handlers.
