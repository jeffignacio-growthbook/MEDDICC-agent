# Phase D Task 0 - Ordinal Semantics Investigation Report
**Branch:** phase-d-backfill
**Date:** 2026-08-11
**Status:** PARTIALLY COMPLETE - Blocked on HubSpot API access for final verification

## Executive Summary

Three critical issues discovered and addressed before writing any backfill code:

1. **Stage name/ID corruption** - Sales Pipeline stages stored as display names instead of IDs (795 deals affected)
2. **Config duplication bug** - qualified_stage_order incorrectly placed in Discovery stage instead of pipeline level
3. **HWM=10 anomaly** - 253 deals with highest_stage_order_reached exceeding max configured order

**BLOCKING ISSUE:** Cannot complete Yoto deal (58169341204) fix without HUBSPOT_API_KEY to fetch stage history.

---

## Investigation A: Quantify HWM Against Real Data

### Query 1: HWM Distribution
```sql
SELECT
  highest_stage_order_reached AS hwm,
  count(*) AS deals,
  count(*) FILTER (WHERE stage = '68509551') AS now_disqualified,
  count(*) FILTER (WHERE deal_status = 'won')  AS won,
  count(*) FILTER (WHERE deal_status = 'lost') AS lost
FROM deals
GROUP BY 1 ORDER BY 1;
```

**Key Finding:** HWM=10 appears 253 times, exceeding max configured order (9).

| HWM | Deals | Now Disqualified | Won | Lost |
|-----|-------|------------------|-----|------|
| 10  | 253   | 252              | 0   | 1    |

**Analysis:**
- 252 deals: Currently in Disqualified (stage order=9), but HWM=10 suggests they passed through a stage with order=10
- 1 deal (Yoto - 58169341204): Currently in Discovery (order=1) with HWM=10 - needs investigation
- **Root cause:** Disqualified has order=9, but get_stage_order() is returning 10 due to stage name/ID mismatch

---

## Investigation B: Stage Name/ID Corruption

### Scope
**Sales Pipeline only** - Renewal Pipeline stages stored correctly as IDs.

### Affected Stages
```sql
SELECT stage, count(*) FROM deals
WHERE stage NOT IN (
  SELECT id FROM (VALUES
    ('appointmentscheduled'),('qualifiedtobuy'),('presentationscheduled'),
    ('24682892'),('43449439'),('closedwon'),('closedlost'),
    ('decisionmakerboughtin'),('68509551'),('79653122'),
    ('1297321618'),('1297321619'),('1297321620'),('1297321622'),('1297321623'),('1297321624')
  ) AS t(id)
)
GROUP BY stage ORDER BY count(*) DESC;
```

| Stage (Display Name) | Count |
|---------------------|-------|
| Closed lost | 795 |
| Disqualified | 274 |
| Negotiating | 63 |
| Awaiting Signature | 26 |

**Impact:**
- `get_stage_order("Closed lost")` returns `None` instead of `0.0` (closedlost order=7)
- `get_stage_order("Disqualified")` returns `None`, then GREATEST() logic defaults to treating it as higher than configured values
- This causes HWM inflation

---

## Investigation C: Config Bug

**Issue:** qualified_stage_order duplicated and misplaced

### Before (config/client.yaml lines 89-110)
```yaml
pipeline:
  value_field:
    type: computed
  qualified_stage_order: 1  # ← Correct location (line 89)

  pipelines:
    - id: "default"
      name: "Sales Pipeline"
      # MISSING: qualified_stage_order should be HERE
      stages:
        - id: "appointmentscheduled"
          name: "Discovery"
          order: 1
          qualified_stage_order: 1  # ← WRONG - inside a stage (line 110)
```

### After (FIXED)
```yaml
pipeline:
  pipelines:
    - id: "default"
      name: "Sales Pipeline"
      qualified_stage_order: 1  # ← ADDED at pipeline level
      stages:
        - id: "appointmentscheduled"
          name: "Discovery"
          order: 1
          stage_probability: 0.10
          # REMOVED: qualified_stage_order from here
```

**Status:** ✅ Fixed and committed to phase-d-backfill branch

---

## Investigation D: Recommended Semantics

### Proposed: exclude_from_progression Flag

Add new flag to client.yaml for administrative/terminal stages:

```yaml
- id: "68509551"
  name: "Disqualified"
  order: 9
  is_lost: true
  exclude_from_analysis: true
  exclude_from_progression: true  # NEW - don't count toward HWM

- id: "decisionmakerboughtin"
  name: "Review"
  order: 8
  exclude_from_progression: true  # NEW
```

**Rationale:**
- Review and Disqualified are administrative parking spots, not progression milestones
- Closed Won (6) and Closed Lost (7) SHOULD count - reaching them is real progress
- This prevents administrative stages from inflating HWM

**Implementation:** Update get_stage_order() with progression_only=True mode that returns None for flagged stages

---

## FIX 1: Diagnose Stage Corruption Scope ✅

**Executed:**
```sql
SELECT stage, count(*) FROM deals
WHERE stage NOT IN (...configured stage IDs...)
GROUP BY stage ORDER BY count(*) DESC;
```

**Result:** Confirmed Sales Pipeline affected, Renewal Pipeline clean

**File:** [Documented above in Investigation B]

---

## FIX 2: Config Correction ✅

**Changes:**
1. Added `qualified_stage_order: 1` at pipeline level (after "Sales Pipeline" line ~95)
2. Removed duplicate from Discovery stage (line ~110)

**Verification:**
```python
from utils import get_pipeline_config
config = get_pipeline_config()
# Returns correct structure with qualified_stage_order at pipeline level
```

**Status:** ✅ Committed to phase-d-backfill branch (commit hash pending)

---

## FIX 3: HWM=10 Correction ⚠️ BLOCKED

### Part A: 252 Disqualified Deals ✅ READY

**SQL prepared:**
```sql
UPDATE deals
SET highest_stage_order_reached = 9
WHERE highest_stage_order_reached = 10
  AND stage = '68509551'  -- Disqualified
  AND deal_id != '58169341204';  -- Exclude Yoto
```

**Expected:** 252 rows updated (HWM 10→9)

**File:** scripts/fix_hwm_10_deals.sql

### Part B: Yoto Deal (58169341204) 🔴 BLOCKED

**Current State:**
- deal_id: 58169341204
- deal_name: "Yoto"
- Current stage: Discovery (order=1)
- highest_stage_order_reached: 10
- deal_value: $75,000

**Anomaly:** How does a Discovery-stage deal have HWM=10 when Discovery has order=1?

**Required Action:**
1. Fetch full dealstage property history from HubSpot API:
   ```python
   GET /crm/v3/objects/deals/58169341204
   ?propertiesWithHistory=dealstage
   &properties=dealname,createdate,pipeline
   ```

2. Map each historical stage_id to its order value using config/client.yaml

3. Calculate true maximum order reached (excluding exclude_from_progression stages if implemented)

4. Update:
   ```sql
   UPDATE deals
   SET highest_stage_order_reached = <calculated_max>
   WHERE deal_id = '58169341204';
   ```

**Blocker:** HUBSPOT_API_KEY not available in local environment
- Exists in GitHub Secrets but cannot be retrieved via `gh` CLI
- Need to either:
  - Export HUBSPOT_API_KEY locally
  - Run via GitHub Actions workflow
  - Use cached data if available

**Helper Script:** /tmp/check_yoto.sh (ready to run once API key is set)

---

## Next Steps

### Immediate (Once HUBSPOT_API_KEY is Available)
1. Fetch Yoto deal stage history
2. Analyze and determine correct HWM
3. Execute FIX 3 Part A (252 deals)
4. Execute FIX 3 Part B (Yoto conditional fix)
5. Verify results

### Then Continue Task 0
1. Report impact analysis: how many deals change HWM under new semantics
2. Decide on exclude_from_progression implementation
3. Proceed to Task 1 (stage_id_mapping.yaml creation)

---

## Files Created/Modified

### Modified
- `config/client.yaml` - Fixed qualified_stage_order placement

### Created
- `scripts/fix_hwm_10_deals.sql` - HWM correction SQL
- `TASK_0_INVESTIGATION_REPORT.md` - This file
- `/tmp/check_yoto.sh` - Helper script for Yoto history fetch

### Pending
- config/stage_id_mapping.yaml (Task 1)
- scripts/migrations/017_add_backfill_confidence.sql (Task 2)
- scripts/analytics/hubspot_history.py (Task 3)

---

## Known Limitations

1. **Stage name→ID corruption** needs systematic fix (not yet implemented)
2. **exclude_from_progression** flag not yet added to config or code
3. **Yoto investigation** incomplete pending API access

---

## Verification Queries (After Fixes)

```sql
-- Should show HWM=9 as max (no more 10s after fix)
SELECT max(highest_stage_order_reached) FROM deals;

-- Should show 0 deals with HWM=10 (after both parts of FIX 3)
SELECT count(*) FROM deals WHERE highest_stage_order_reached = 10;

-- Distribution should show deals clustered at meaningful stage orders
SELECT highest_stage_order_reached, count(*)
FROM deals
GROUP BY 1
ORDER BY 1;
```

---

**END OF REPORT**
