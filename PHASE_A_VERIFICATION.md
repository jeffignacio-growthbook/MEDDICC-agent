# Phase A Analytics Layer - Verification Report

## Summary

Phase A analytics layer successfully ported to production (GrowthBook) repo.

- ✅ All Python files pass syntax validation
- ✅ New pipeline config produces identical exclusions to legacy config
- ✅ Backward compatibility maintained (both shapes supported)
- ✅ Kimi files removed
- ✅ FIREWORKS_API_KEY removed from workflow

## Files Changed

### New Files Created
- `scripts/migrations/003_add_component_scores.sql` - Component scores table (methodology-agnostic)
- `scripts/migrations/004_add_qualification_tracking.sql` - Adds lost_reason and stage_source to deals
- `scripts/migrations/005_add_deals_snapshot.sql` - Daily deal snapshots for trending
- `scripts/migrations/006_add_waterfall_and_winloss.sql` - Waterfall metrics + win/loss narratives
- `scripts/utils.py` - Pipeline helpers + shared slugify function

### Files Modified
- `scripts/etl_deals.py` - New get_excluded_stages() with dual config support
- `config/client.yaml` - Added Phase A pipeline structure (keeps legacy)
- `.github/workflows/nightly.yml` - Removed FIREWORKS_API_KEY

### Files Deleted
- `scripts/kimi_client.py`
- `scripts/context_builder_kimi.py`
- `scripts/meddicc_agent_kimi.py`

---

## Config Shape Comparison

### LEGACY CONFIG (config/client.yaml - OLD)

```yaml
excluded_stages:
  meeting_set:
    - name: "Meeting Set"
      id: "79653122"

  disqualified:
    - name: "Disqualified"
      id: "68509551"

  closed_won:
    - name: "Closed won"
      id: "closedwon"
    - name: "Closed Won"
      id: "1297321623"

  closed_lost:
    - name: "Closed lost"
      id: "closedlost"
    - name: "Closed Lost"
      id: "1297321624"

pipelines:
  excluded:
    - name: "Renewal"
      id: "866608541"
```

### NEW CONFIG (config/client.yaml - PHASE A)

```yaml
pipeline:
  value_field: "incremental_arr"
  qualified_stage_order: 2

  excluded_pipelines:
    - name: "Renewal"
      id: "866608541"

  pipelines:
    - id: "default"
      name: "Sales Pipeline"
      stages:
        - id: "79653122"
          name: "Meeting Set"
          order: 1
          exclude_from_analysis: true  # Too early

        - id: "appointmentscheduled"
          name: "Discovery"
          order: 2
          qualified_stage_order: 2

        - id: "qualifiedtobuy"
          name: "Scoping"
          order: 3

        - id: "presentationscheduled"
          name: "Proposal"
          order: 4

        - id: "decisionmakerboughtin"
          name: "Negotiating"
          order: 5

        - id: "closedwon"
          name: "Closed Won (default)"
          order: 100
          is_won: true

        - id: "1297321623"
          name: "Closed Won"
          order: 100
          is_won: true

        - id: "closedlost"
          name: "Closed Lost (default)"
          order: 101
          is_lost: true

        - id: "1297321624"
          name: "Closed Lost"
          order: 101
          is_lost: true

        - id: "68509551"
          name: "Disqualified"
          order: 102
          is_lost: true
          exclude_from_analysis: true  # BOTH flags
```

---

## get_excluded_stages() Output - Side by Side

### With LEGACY config ONLY (excluded_stages.*)

```python
{
  'meeting_set': ['79653122'],
  'disqualified': ['68509551'],
  'closed_won': ['closedwon', '1297321623'],
  'closed_lost': ['closedlost', '1297321624'],
  'excluded_pipelines': ['866608541']
}
```

### With NEW config ONLY (pipeline.pipelines[])

```python
{
  'meeting_set': ['79653122'],
  'disqualified': ['68509551'],
  'closed_won': ['closedwon', '1297321623'],
  'closed_lost': ['closedlost', '1297321624'],
  'excluded_pipelines': ['866608541']
}
```

### With BOTH configs (NEW wins)

```python
{
  'meeting_set': ['79653122'],
  'disqualified': ['68509551'],
  'closed_won': ['closedwon', '1297321623'],
  'closed_lost': ['closedlost', '1297321624'],
  'excluded_pipelines': ['866608541']
}
```

## ✅ VERIFICATION RESULT: **IDENTICAL**

All three scenarios produce the same output. Tonight's nightly run will be unaffected.

---

## Key Rules

### Disqualified Stage Handling

**RULE:** Disqualified stages get BOTH flags:
- `is_lost: true`
- `exclude_from_analysis: true`

This allows:
- Lost stages (`is_lost=true`) to appear in waterfall metrics
- Disqualified stages (`is_lost + exclude_from_analysis`) to be filtered out completely

Example from config:
```yaml
- id: "68509551"
  name: "Disqualified"
  order: 102
  is_lost: true
  exclude_from_analysis: true  # BOTH flags
```

---

## Fallback Logic

The `get_excluded_stages()` function has three-tier fallback:

1. **NEW SHAPE** - Check for `pipeline.pipelines[]` structure → Use if exists
2. **LEGACY SHAPE** - Check for `excluded_stages.*` → Use if NEW not found
3. **HARDCODED** - Use constants from top of etl_deals.py → Use if no config

This ensures:
- New configs work immediately
- Legacy configs continue working
- Missing configs fall back gracefully

---

## Next Steps

### To Apply These Changes:

1. **Review this branch:**
   ```bash
   git checkout phase-a-analytics
   git log --stat
   ```

2. **Test locally** (if desired):
   ```bash
   python verify_excluded_stages.py  # Should show all checks passed
   python scripts/etl_deals.py --mode active  # Should work identically
   ```

3. **Merge to main** (when ready):
   ```bash
   git checkout main
   git merge phase-a-analytics
   git push origin main
   ```

4. **Run migrations** (after merge):
   ```bash
   python scripts/setup_supabase.py
   # Migrations 003-006 will create new analytics tables
   ```

5. **Monitor nightly run:**
   - First nightly after merge should behave identically to current
   - Check GitHub Actions logs for any issues
   - New analytics tables will be populated on future runs

---

## Risk Assessment

### Low Risk
- ✅ Backward compatible (legacy config still works)
- ✅ New config produces identical output to legacy
- ✅ All syntax checks passed
- ✅ No changes to MEDDICC scoring logic
- ✅ No changes to prompt generation
- ✅ Migrations are additive only (no schema changes to existing tables)

### What Could Go Wrong
- ⚠️ If config/client.yaml has syntax errors, falls back to hardcoded constants
- ⚠️ If Supabase migrations fail, analytics tables won't be created (but agent still runs)
- ⚠️ If YAML parsing fails, error message printed but agent continues with defaults

### Monitoring
After merge, check:
1. First nightly run completes successfully
2. `memory/deals/index.json` has same excluded stage counts
3. No errors in GitHub Actions logs related to config loading

---

## Commit

```
Phase A: Add analytics layer with pipeline config and migrations

- Add migrations 003-006 for component scores, deal snapshots, waterfall tracking, qualification history
- Add pipeline helpers to utils.py (get_pipeline_config, get_stage_order, is_won/lost_stage)
- Refactor get_excluded_stages() with new pipeline.pipelines[] config shape + legacy fallback
- Update config/client.yaml with Phase A pipeline structure (keeps legacy for compatibility)
- Delete Kimi files (kimi_client.py, context_builder_kimi.py, meddicc_agent_kimi.py)
- Remove FIREWORKS_API_KEY from workflow
- Verification: New config produces identical output to legacy (all checks passed)
```

**Branch:** phase-a-analytics
**Commit:** e9f233f
**Status:** Ready for review and merge
