# Phase 5 Architecture: Two Consumption Models and Proposal Lifecycle

## Overview

Phase 5 extends the field_semantics consolidation with a **proposal lifecycle** for data_dictionary, enabling the agent to suggest new field definitions without immediately affecting production queries. This maintains the critical **harness boundary** while enabling self-improvement.

---

## The Harness Boundary

The consolidation creates two distinct consumption paths:

### 1. Handler Harness (Compile-Time, Static)

**Files:**
- `api/handlers.py` - Individual handler functions
- `api/field_semantics.py` - Generated stage logic module
- `scripts/etl_deals.py` - ETL writes to Supabase
- `scripts/analytics/backfill_snapshots.py` - Historical backfill

**Data Source:**
- Consumes ONLY `api/field_semantics.py` (generated from `config/field_semantics.yaml`)
- NEVER reads `data_dictionary` table at runtime
- Changes require regeneration and deployment

**Why:**
- Client porting is a simple yaml swap (GrowthBook → template)
- No runtime field definition lookups
- Stage logic is compile-time constant
- Enables aggressive optimization and testing

**Enforcement:**
- `scripts/eval_field_semantics.py::test_harness_boundary_isolation()` (Phase 5d)
- Greps for `select_all(*, 'data_dictionary')` in harness files
- Build fails if boundary is violated

### 2. Dynamic Query Path (Runtime, Flexible)

**Files:**
- `api/router.py` - Intent classification and synthesis
- `api/tools.py` - Dynamic query tool
- `api/schema_context.py` - Schema description generator

**Data Source:**
- Reads `data_dictionary` table at runtime
- Filters to `proposal_status IN ('active', 'accepted')`
- Discovers tables/columns not explicitly programmed

**Why:**
- Handles ad-hoc questions about new fields
- No code deployment for new HubSpot properties
- Can query any Supabase table dynamically
- Enables exploration and discovery

**Tradeoff:**
- More tokens per query (schema discovery)
- Requires careful relevance filtering
- Can't be as optimized as handlers

---

## Proposal Lifecycle

### States

| Status | Meaning | Consumed By | Next State |
|--------|---------|-------------|------------|
| `draft` | Proposed but not reviewed | Nothing | `active`, `rejected` |
| `active` | Under review/testing | Dynamic path only | `accepted`, `rejected`, `superseded` |
| `accepted` | Production-ready | Both paths (after regeneration if affects_handlers=true) | `superseded` |
| `rejected` | Proposed but declined | Nothing | Terminal |
| `superseded` | Replaced by newer definition | Nothing | Terminal |

### Fields Added (Migration 027)

```sql
proposal_status       TEXT      -- 'draft' | 'active' | 'accepted' | 'rejected' | 'superseded'
proposed_at           TIMESTAMPTZ  -- When definition was proposed
proposed_by           TEXT      -- 'agent' | 'human' | 'backfill' | user email
reviewed_at           TIMESTAMPTZ  -- When reviewed (null if pending)
reviewed_by           TEXT      -- Who reviewed (null if pending)
review_notes          TEXT      -- Optional review feedback
superseded_by_id      BIGINT    -- Points to replacement definition
affects_handlers      BOOLEAN   -- True if handlers consume this field
```

### Workflow: Agent Proposes New Field

1. **Discovery:** Agent encounters unknown HubSpot property in call transcript
   - Example: `customer_technical_champion` mentioned but not in data_dictionary

2. **Proposal:** Agent inserts draft definition
   ```sql
   INSERT INTO data_dictionary (
     source, hubspot_name, supabase_table, supabase_column,
     data_type, description, proposal_status, proposed_by, affects_handlers
   ) VALUES (
     'hubspot',
     'customer_technical_champion',
     'deals',
     'technical_champion',
     'text',
     'Name of technical champion at customer org (key decision influencer)',
     'draft',
     'agent',
     false  -- Dynamic path only, doesn't need handler changes
   );
   ```

3. **Review:** Human reviews draft proposals
   - Approve → set `proposal_status = 'active'`
   - Reject → set `proposal_status = 'rejected'`, add `review_notes`
   - Modify → update description, set `active`

4. **Consumption:**
   - Dynamic query path immediately sees `active` proposals
   - Can answer questions about the new field
   - Handlers unaffected (no regeneration needed if `affects_handlers = false`)

5. **Promotion:**
   - After validation period, set `proposal_status = 'accepted'`
   - If `affects_handlers = true`, regenerate field_semantics and redeploy

6. **Supersession:**
   - If better definition discovered, create new row
   - Set old row: `proposal_status = 'superseded'`, `superseded_by_id = <new_row_id>`

### Query Patterns

**Dynamic path queries active proposals:**
```sql
SELECT * FROM data_dictionary
WHERE proposal_status IN ('active', 'accepted')
  AND is_queryable = true
ORDER BY supabase_table, supabase_column;
```

**Find pending reviews:**
```sql
SELECT * FROM data_dictionary
WHERE proposal_status = 'draft'
  AND proposed_by = 'agent'
ORDER BY proposed_at DESC;
```

**Track supersession chain:**
```sql
WITH RECURSIVE chain AS (
  SELECT * FROM data_dictionary WHERE id = <starting_id>
  UNION
  SELECT d.* FROM data_dictionary d
  JOIN chain c ON d.id = c.superseded_by_id
)
SELECT * FROM chain ORDER BY proposed_at;
```

---

## Handler Definition Proposals

### The affects_handlers Gate

Not all field definitions affect the handler harness. Only definitions consumed by handlers require regeneration.

**affects_handlers = false:**
- Field used only by dynamic query path
- Changes don't require regeneration
- Can go `draft → active → accepted` without deployment

**affects_handlers = true:**
- Field consumed by handlers (e.g., stage definitions, transition logic)
- Changes require regeneration of `api/field_semantics.py`
- Must update `config/field_semantics.yaml` → regenerate → redeploy

**Examples:**

| Field | affects_handlers | Why |
|-------|-----------------|-----|
| `customer_technical_champion` | false | Only queried dynamically, not used in handler logic |
| `closedwon` stage definition | **true** | Handlers use `is_won()` which depends on this |
| `pipeline_id` mapping | **true** | Handlers route by pipeline in `STAGE_COMPONENT_QUESTIONS` |
| `mrr_value` | false | Dynamic calculations, not hardcoded in handlers |

### Workflow: Agent Proposes Stage Change

1. **Proposal:** Agent notices template uses different stage IDs
   ```sql
   INSERT INTO data_dictionary (
     source, hubspot_name, supabase_column,
     data_type, description, proposal_status, proposed_by, affects_handlers
   ) VALUES (
     'hubspot',
     'technical_validation',
     'technical_validation',
     'enumeration',
     'Stage: Technical validation phase (discovery bucket)',
     'draft',
     'agent',
     true  -- Handlers need this for stage_bucket() logic
   );
   ```

2. **Review with Regeneration Check:**
   - Human reviews proposal
   - If approved, adds to `config/field_semantics.yaml`:
     ```yaml
     technical_validation:
       label: "Technical Validation"
       bucket: "discovery"
       transition: "discovery_to_scoping"
       aliases: ["987654321"]
     ```

3. **Regeneration:**
   ```bash
   python scripts/generate_field_semantics.py
   ```

4. **Testing:**
   ```bash
   python scripts/eval_field_semantics.py  # All drift tests must pass
   ```

5. **Deployment:**
   - Deploy updated `api/field_semantics.py`
   - Mark proposal: `proposal_status = 'accepted'`

---

## Relevance Surfacing (Optional, Deferred)

When a new field definition becomes `active`, the system should check if it affects existing handlers:

1. **Scan handlers:** Grep for references to related fields
2. **Surface relevance:** If handler mentions "champion" and new field is `technical_champion`, notify
3. **Propose integration:** Suggest adding field to handler's return structure

**Implementation deferred** (per user: "proposal lifecycle and relevance-surfacing parts of Phase 5 could defer").

---

## Migration Path

### Immediate (Completed in Phase 5):

1. ✅ **Isolation test** (`test_harness_boundary_isolation`) locks the boundary
2. ✅ **Migration 027** adds proposal lifecycle columns
3. ✅ **Documentation** explains two consumption models

### When Needed (Future):

4. **Backfill existing definitions:** Mark all as `accepted`, `backfill` source
5. **Agent proposal loop:** When agent encounters unknown field, insert `draft` row
6. **Review workflow:** UI or script for human review of `draft` proposals
7. **Relevance surfacing:** Scan handlers when new field becomes `active`

---

## Key Invariants

1. **Handlers NEVER read data_dictionary at runtime** (enforced by Phase 5d test)
2. **Dynamic path queries ONLY `active` or `accepted` proposals** (draft/rejected invisible)
3. **If `affects_handlers = true`, change requires regeneration** (no runtime stage logic)
4. **Client porting is a yaml swap** (GrowthBook → template changes only yaml, not code)

---

## Testing

### Drift Test Suite (scripts/eval_field_semantics.py)

All 8 tests must pass before deployment:

1. `test_generated_module_matches_yaml` - No hand-editing
2. `test_aliases_resolve_to_canonical` - Numeric IDs work
3. `test_stage_bucket_covers_all_stages` - No unknown buckets
4. `test_is_won_is_lost_mutually_exclusive` - Outcome logic consistent
5. `test_stage_transition_returns_correct_keys` - Transitions defined
6. `test_unknown_stages_handled_gracefully` - No crashes on bad data
7. `test_no_raw_stage_ids_outside_field_semantics` - No ID leaks
8. **`test_harness_boundary_isolation`** - **Phase 5d critical guard**

### Manual Verification

**Check proposal states:**
```sql
SELECT proposal_status, COUNT(*)
FROM data_dictionary
GROUP BY proposal_status;
```

**Find handler-affecting proposals:**
```sql
SELECT * FROM data_dictionary
WHERE affects_handlers = true
  AND proposal_status != 'accepted';
```

---

## Summary

Phase 5 establishes a **dual-consumption architecture**:

- **Handlers** consume static, compile-time definitions (harness boundary)
- **Dynamic path** consumes runtime definitions with proposal lifecycle
- **Isolation test** enforces the boundary (prevents future drift)
- **Proposal workflow** enables self-improvement without breaking production

This architecture makes client porting a **yaml swap** while maintaining the flexibility for agents to propose improvements to field definitions over time.
