# Targets Unified: Config Source, Table Query Target

**Issue:** `query_rep_attainment` handler failed with "partial" result because targets existed in `config/targets.yaml` but not `rep_targets` table.

**Root Cause:** Two sources of truth with no sync mechanism. Same pattern that led to `renewal_revenue` being in three places and diverging.

## Decision: Table as Query Target, Config as Source

Following the pattern from `seed_personas_from_config.py`:

1. **config/targets.yaml** = Source of truth (edited by humans)
2. **rep_targets table** = Query target (efficient joins for handlers)
3. **scripts/seed_targets.py** = Sync mechanism (run after config edits)

This gives:
- **Handlers:** Efficient joins (`deals.owner_email = rep_targets.entity_email`)
- **Semantic context:** Direct load from config for agent knowledge
- **One source:** Config is edited, table is derived

## What Changed

### 1. Created scripts/seed_targets.py

Loads `config/targets.yaml` and upserts to `rep_targets` table:

```bash
$ python scripts/seed_targets.py

Period: FY2027_Q3
  Team total: $1,550,000
  Basis: incremental_arr

  ✓ jake.heier@growthbook.io: $300,000
  ✓ christian.liebenow@growthbook.io: $250,000
  ✓ james.shannon@growthbook.io: $300,000
  ✓ scott.keller@growthbook.io: $300,000
  ✓ dan.wathne@growthbook.io: $250,000
  ✓ marcel.geldner@growthbook.io: $150,000 (ramp)
  ✓ AE Team total: $1,550,000

  Non-quota roles (no target rows):
    - cary.rakin@growthbook.io
    - andy.marshall@growthbook.io

SUCCESS: Seeded 7 target rows
```

**Key details:**
- 6 individual rep targets + 1 team total
- Non-quota AMs explicitly excluded (no table rows)
- metric = "incremental_arr" (matches target basis)
- Upserts on conflict, safe to re-run

### 2. Fixed api/handlers.py metric check

```python
# Before (looking for wrong metric):
if t.get("metric") == "arr_won":  # or appropriate metric name

# After (matches config basis):
if t.get("metric") == "incremental_arr":  # new_arr + expansion_arr
```

The handler was checking for `"arr_won"` but config stores `"incremental_arr"` as the basis. This mismatch would have caused the handler to ignore valid targets even after seeding.

### 3. Updated config/field_semantics.yaml

```yaml
# ============================================================================
# SALES TARGETS AND ATTAINMENT
# ============================================================================
# Source of truth: config/targets.yaml (edited by humans)
# Query target: rep_targets table (seeded from config via scripts/seed_targets.py)
#
# The table is derived from config. After editing targets.yaml, run:
#   python scripts/seed_targets.py
```

Documents the relationship to prevent future divergence.

## Verification

Targets are now queryable from both sources:

**From table (handlers use this):**
```sql
SELECT entity_email, target_value, metric
FROM rep_targets
WHERE period = 'FY2027_Q3' AND level = 'rep';
```

**From config (semantic context uses this):**
```python
from utils import build_semantic_context
context = build_semantic_context()
# Includes targets section with rep breakdown
```

## Test Questions (from WAVE_0_TARGETS.md)

Now that targets are seeded, these should work:

1. **"How is Christian tracking?"**
   - Should show attainment against $250,000 target
   - Handler can join `deals.owner_email = rep_targets.entity_email`

2. **"How is Cary doing?"**
   - Should describe contribution without inventing quota
   - No row in rep_targets for cary.rakin@growthbook.io (by design)
   - Handler sees empty target, knows it's non-quota AM

3. **"What do you forecast for the quarter?"**
   - Already working (saw "$1.91M against $1.55M")
   - Gap framing from semantic context (config)

4. **"Do we have enough pipeline?"**
   - Should calculate required vs $1.55M target
   - Coverage meaningful when derived from target

## Workflow for Future Edits

When targets change:

1. Edit `config/targets.yaml` (source of truth)
2. Run `python scripts/seed_targets.py` (sync to table)
3. Commit both files
4. Deploy

Config and table stay in sync. No manual SQL required.

## Commits

- 744e3e4: Add Wave 0: Sales Targets and Gap to Plan (config only)
- a61f224: Unify targets: config as source, table as query target (sync mechanism)

The foundation is complete. Handlers can query efficiently, semantic context provides framing, and config remains the single editable source.
