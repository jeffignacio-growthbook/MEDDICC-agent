# Region-Aware Waterfall - Known Gap

**Date:** 2026-09-08
**Status:** 🚧 Documented, not yet implemented

---

## Problem

The Slack agent correctly answered "How has EMEA pipeline moved in the last 2 weeks" by substituting a narrower question (new deals created) without clearly flagging the substitution.

**What the LLM said in its reasoning:**
```
The waterfall table doesn't have EMEA-level segmentation (it's global),
so let me look at EMEA deals created or updated in the last 2 weeks to
show movement.
```

**What it should have said to the user:**
```
⚠️ Note: waterfall_weekly isn't region-segmented yet, so this shows
new deal creation only, not full pipeline movement (beginning/ending/won/
lost/net change) for EMEA specifically.
```

The LLM correctly identified the gap but **silently substituted** a different, narrower question without flagging that substitution in the user-facing answer.

---

## Two Fixes Needed

### 1. Add Region to waterfall_weekly (Schema + Computation)

**Current grain:** `(week_ending, pipeline_id)`
**Needed grain:** `(week_ending, pipeline_id, region)`

**Changes required:**

**A. Schema change:**
```sql
-- Add region column to waterfall_weekly
ALTER TABLE waterfall_weekly ADD COLUMN region TEXT;
CREATE INDEX idx_waterfall_weekly_region ON waterfall_weekly(region);

-- Update primary key / unique constraint to include region
-- Current: (week_ending, pipeline_id)
-- Needed: (week_ending, pipeline_id, region)
```

**B. Computation logic update:**

File: `scripts/analytics/compute_waterfall.py`

Current logic:
1. Groups deals_snapshot by `(week_ending, pipeline_id)`
2. Computes beginning/ending/won/lost/net_change per group

Needed logic:
1. Group deals_snapshot by `(week_ending, pipeline_id, region)`
2. Compute beginning/ending/won/lost/net_change per group
3. Handle UNKNOWN region explicitly (don't drop it)

**C. Data_dictionary registration:**
```python
{
    'supabase_table': 'waterfall_weekly',
    'supabase_column': 'region',
    'data_type': 'text',
    'description': 'Sales region for this waterfall row: NAM, EMEA, APAC, LATAM, ROW, or UNKNOWN. Enables region-specific pipeline movement analysis (beginning/ending/won/lost/net change by week).',
    'is_queryable': True,
    'enum_values': ['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN'],
    'source': 'computed'
}
```

**D. Historical backfill:**
```bash
python scripts/analytics/compute_waterfall.py --backfill
```

This will recompute all historical waterfall data with region segmentation.

---

### 2. Synthesis Should Flag Question Substitution

**Pattern:** When the LLM identifies it cannot fully answer the question asked and substitutes a narrower/different question, it should **explicitly flag that substitution** in the user-facing answer.

**Example (current behavior):**
```
User: "How has EMEA pipeline moved in the last 2 weeks"
LLM reasoning: "waterfall table doesn't have EMEA segmentation, let me look at new deals instead"
LLM answer: "📍 EMEA Pipeline Movement — Last 2 Weeks
             New Deals Created (7 deals)..."
```

User sees "EMEA Pipeline Movement" as the header and assumes it's showing full pipeline movement (beginning/ending/won/lost), but it's actually only showing new deals created.

**Improved behavior:**
```
User: "How has EMEA pipeline moved in the last 2 weeks"
LLM reasoning: "waterfall table doesn't have EMEA segmentation, let me look at new deals instead"
LLM answer: "📍 EMEA New Deal Activity — Last 2 Weeks

             ⚠️ Note: waterfall_weekly isn't region-segmented yet, so this
             shows new deal creation only, not full pipeline movement
             (beginning/ending/won/lost/net change). For full EMEA pipeline
             movement, I'd need region-aware waterfall data.

             New Deals Created (7 deals)..."
```

**Implementation location:**

File: `api/router.py` or wherever the synthesis step formats final answers.

Add a check:
- If the LLM's reasoning mentions it cannot answer the full question and is substituting a narrower one
- Extract that caveat and surface it prominently in the user-facing answer
- Don't let it be buried in reasoning logs - make it visible

This is the same "explicit honesty about data gaps" pattern already established with:
- `no_signal_at_risk` (MEDDICC gaps surfaced explicitly)
- `UNKNOWN` region (missing geography surfaced explicitly)

**Now apply it to question substitution:**
- If you can't answer the full question, say so explicitly
- Don't present a partial answer as if it's complete

---

## Test Data After Implementation

After adding region to waterfall_weekly, this query should work:

```sql
SELECT
    week_ending,
    region,
    beginning_value,
    ending_value,
    won_value,
    lost_value,
    net_change
FROM waterfall_weekly
WHERE region = 'EMEA'
  AND week_ending >= '2026-08-25'
  AND week_ending <= '2026-09-08'
  AND pipeline_id = 'default'
ORDER BY week_ending;
```

And the Slack agent should be able to answer:
> "How has EMEA pipeline moved in the last 2 weeks"

With:
```
📍 EMEA Pipeline Movement — Last 2 Weeks (Aug 25 – Sep 8)

Pipeline Waterfall:
• Beginning (Aug 25): $2.3M
• Ending (Sep 8): $2.4M
• New pipeline added: $240K
• Won: $80K
• Lost: $60K
• Net change: +$100K

New deals qualified: 7 deals ($110K)
```

Full, accurate pipeline movement for EMEA specifically - not just new deals created.

---

## Files to Change

1. **Schema:**
   - `scripts/migrations/060_add_region_to_waterfall.sql` (new migration)

2. **Computation:**
   - `scripts/analytics/compute_waterfall.py` (add region grouping)

3. **Data Dictionary:**
   - Direct insert or script to add waterfall_weekly.region row

4. **Synthesis:**
   - `api/router.py` or synthesis step to flag question substitution

5. **Documentation:**
   - This file documents the gap and fix approach

---

## Priority

**Medium-High**

This affects:
- Regional pipeline reporting (EMEA, APAC, LATAM, etc.)
- Executive dashboards that need region-specific waterfall
- Accurate pipeline movement analysis by geography

Without this, regional questions get **partial answers** (new deals only, not wins/losses/net change) presented as if they're complete.

The synthesis flagging is also important - prevents users from trusting partial answers as complete.

---

## Related

- `REGION_DATA_DICTIONARY_FIX.md` - Explains why deals.region was needed
- `DESIGN_LESSON_CORRECT_NUMBERS_VS_NARRATIVES.md` - Similar pattern of "present what you have, flag what you don't"
- `config/regions.yaml` - Region definitions used for classification
- `scripts/populate_region_column.py` - Example of adding region to existing table

---

## Summary

**Gap identified:** waterfall_weekly lacks region segmentation, so regional pipeline movement questions get partial answers (new deals only) without clear flagging.

**Fix 1:** Add region column to waterfall_weekly, update computation logic, backfill historical data.

**Fix 2:** Make synthesis step explicitly flag question substitution when it cannot fully answer what was asked.

Both follow the same "explicit honesty about data gaps" pattern already established elsewhere in the system.
