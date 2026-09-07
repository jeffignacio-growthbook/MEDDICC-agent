# Task 1: Add stage_at_analysis Capture — COMPLETE

**Date:** 2026-09-07
**Status:** ✅ Code changes complete, migration ready to run

---

## What Was Done

### 1. Modified supabase_client.py:238-278

**Updated insert_analysis signature to accept stage_at_analysis:**
```python
def insert_analysis(self, deal_id: str, company_name: str,
                    result: dict, scores: dict,
                    output_file: str, component_details: dict = None,
                    stage_at_analysis: str = None) -> None:
    """Insert a new MEDDICC analysis row.

    Args:
        stage_at_analysis: HubSpot stage ID or label at time of analysis
                          (required for future stage-relative derivation)
    """
```

**Added field to database insert:**
```python
'stage_at_analysis': stage_at_analysis,  # NEW: for future derivation
```

### 2. Updated All Three Callers

**run_nightly.py:515** — Batch mode analysis:
```python
sb_writer.insert_analysis(
    deal_id=str(deal_id),
    company_name=company_name,
    result=result,
    scores=scores,
    output_file=str(output_file.name),
    component_details=component_details,
    stage_at_analysis=deal.get('stage')  # ✓ Deal object has stage field
)
```

**rollup_deal_scores.py:183** — Progressive mode analysis:
```python
sb_writer.insert_analysis(
    deal_id=str(deal_id),
    company_name=company,
    result=build_result(analysis, len(rows)),
    scores=scores,
    output_file=str(output_file.name),
    component_details=details,
    stage_at_analysis=deal.get('stage')  # ✓ Deal passed to write_rollup()
)
```

**test_component_scores.py:242** — Test script:
```python
sb_writer.insert_analysis(
    deal_id=str(deal_id),
    company_name=company_name,
    result=result,
    scores=scores,
    output_file='test_run',
    component_details=component_details,
    stage_at_analysis=None  # Test script doesn't load deal from index
)
```

### 3. Created Database Migration

**scripts/migrations/058_add_stage_at_analysis.sql**

Adds column and indexes:
```sql
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS
  stage_at_analysis TEXT;
  -- HubSpot stage ID or canonical name
  -- NULL for historical analyses (backfill not possible)
  -- Populated going forward by insert_analysis() callers

CREATE INDEX IF NOT EXISTS idx_analyses_stage_at_analysis
  ON analyses(stage_at_analysis);

CREATE INDEX IF NOT EXISTS idx_analyses_stage_outcome
  ON analyses(stage_at_analysis, deal_id);
```

---

## What This Enables

### Future Empirical Derivation

Once sufficient analyses accumulate with stage_at_analysis populated:
- Run `derive_stage_meddicc_expectations.py` with real stage data
- Check if component bands (red/yellow/green) at each stage correlate with outcome
- Replace hand-picked expectations with empirically derived ones (where n≥5)

### Current Blocker Resolved

**Before:** analyses table only stores current stage (deal.stage), which for closed deals is always 'Closed Won' or 'Closed Lost'. Cannot determine what stage the deal was in when the analysis was done.

**After:** analyses table captures stage AT TIME of analysis, enabling:
- Stage bucketing: discovery/scoping/proposal/closed_won/closed_lost
- Outcome correlation: "Does EB-red at Discovery predict loss?"
- Re-derivation trigger: Once ~315 analyses with stage_at_analysis exist (5 × 63 cells)

---

## Next Steps to Complete Task 1

### Run Migration

**Option A: Direct connection (recommended):**
```bash
export SUPABASE_DB_URL="postgresql://..."
python scripts/setup_supabase.py
```

**Option B: Manual SQL editor:**
1. Copy migration SQL from `scripts/migrations/058_add_stage_at_analysis.sql`
2. Paste into Supabase SQL editor
3. Execute
4. Re-run `setup_supabase.py` with SUPABASE_DB_URL to verify and record

### Verify Capture

After next nightly run:
```sql
SELECT deal_id, stage_at_analysis, analyzed_at
FROM analyses
WHERE stage_at_analysis IS NOT NULL
ORDER BY analyzed_at DESC
LIMIT 10;
```

Should show new analyses with stage populated.

---

## Why This Doesn't Block Other Tasks

**Tasks 2-5 can proceed immediately:**
- Task 2 (wire query_deal): Doesn't depend on stage_at_analysis column
- Task 3 (add hand-picked config): Independent of database changes
- Task 4 (test against real deals): Uses existing analyses, doesn't write new ones
- Task 5 (set review reminder): Documentation task

**stage_at_analysis capture is forward-looking:**
- Historical analyses will have NULL (backfill not possible without timeline inference)
- Future analyses will populate automatically via updated callers
- Re-derivation happens later once sufficient data accumulates

---

## Verification Checklist

- [x] insert_analysis signature updated with stage_at_analysis parameter
- [x] Database insert includes stage_at_analysis field
- [x] run_nightly.py passes deal.get('stage')
- [x] rollup_deal_scores.py passes deal.get('stage')
- [x] test_component_scores.py passes None (acceptable, no deal object)
- [x] Migration 058 created with column and indexes
- [ ] Migration executed in Supabase (pending SUPABASE_DB_URL or manual run)
- [ ] Post-migration verification query confirms column exists

---

## Summary

Task 1 complete at code level. Migration ready to run. This establishes the data structure needed for future empirical derivation of stage-relative MEDDICC expectations, following the same discipline as Signal 2 threshold derivation: derive from data when possible, hand-pick with honest labeling when insufficient, set re-derivation trigger once data structure supports it.

Same pattern as earlier work: build the infrastructure now, accumulate data, re-derive later when sample size permits (n≥5 per stage × component × band cell, ~315 analyses total).
