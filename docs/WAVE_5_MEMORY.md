# Wave 5 — Memory (Complete)

**Built:** September 3-4, 2026
**Status:** Schema ready, integration pending

---

## What Was Built

Three specific memory mechanisms — not a summary of every conversation:

1. **Corrections become proposals** (5a) — Most important
2. **Answers given persist** (5b) — Enables reconciliation
3. **Failure resolution tracking** (5c) — Closes the loop

Design constraint: Memory is three specific things, not a general conversation archive.

## Files Created

```
scripts/migrations/052_add_memory_tables.sql     — Schema for all three parts
api/corrections.py                               — 5a: Correction detection & proposals
api/memory.py                                    — 5b: Answer persistence
api/failure_resolution.py                        — 5c: Failure tracking
docs/WAVE_5_MEMORY.md                           — This file
```

---

## 5a. Corrections Become Proposals (Most Important)

### The Problem

During debugging, four corrections died in threads:
- "renewals value on renewal_revenue"
- "reps forecast Incremental ARR only"
- "Review is a parking lot"
- "targets use HubSpot's email convention"

These should have become proposals with the conversation as evidence.

### The Solution

**Correction detection:** `corrections.py` detects when user says agent got something wrong using pattern matching:

```python
CORRECTION_PATTERNS = [
    r"(?:that'?s|this is)\s+(?:wrong|incorrect|not right)",
    r"(?:actually|no,?)\s+(?:it'?s|the)",
    r"(?:should be|is actually|really is)\s+\d",
    r"renewals?\s+(?:value|should|uses?)\s+on\s+\w+",
    # ... 15 total patterns
]
```

**General vs specific:** Agent asks whether correction is general (becomes proposal) or one-off:

```
"I see you're correcting something. Quick question: is this correction
general (applies to all future questions like this) or specific to this
one question?

• General → I'll create a proposal for review
• Specific → I'll just fix this answer"
```

**Proposal creation:** If general, extract facts and write to `proposals` table:

```python
{
    'entity_type': 'field_definition',
    'entity_key': 'query_renewals_field_value',
    'proposed_value': {'correction': 'Use renewal_revenue field'},
    'rationale': '**What was wrong:** Using new_arr for renewals\n
                  **Correct approach:** Use renewal_revenue field',
    'conversation_evidence': {
        'thread_ts': '...',
        'user_message': 'renewals value on renewal_revenue',
        'agent_response': '...',
        'correction': 'Use renewal_revenue field'
    },
    'affects_handlers': True
}
```

### Integration Points

**In router.py synthesis:**

```python
from corrections import (
    detect_correction,
    ask_correction_scope,
    extract_correction_facts,
    create_correction_proposal
)

# After handler returns answer
if detect_correction(user_message):
    # Ask if general or specific
    scope = ask_correction_scope(user_message)
    # (Store state, wait for user response)

# If user says "general":
if correction_scope == 'general':
    facts = extract_correction_facts(user_message, agent_prior_response)
    proposal = create_correction_proposal(facts, thread_ts, user_id, handler_name)
    sb.table('proposals').insert(proposal).execute()
    logger.info(f"[CORRECTION] Created proposal {proposal['entity_key']}")
```

### Proposal Review Workflow

1. Agent proposes, human disposes
2. Nothing auto-applies
3. Approval workflow (already exists from migration 036):
   - `status='proposed'` → Review
   - `status='approved'` → Apply change
   - `status='rejected'` → Ignore
   - `status='superseded'` → Newer proposal replaces

---

## 5b. Answers Given Persist

### The Problem

Thread history expires after 24 hours. The renewals number went:
- $733K (Sep 2 morning)
- $5.2M (Sep 2 afternoon)
- $1.59M (Sep 2 evening)

Nobody could reconstruct the sequence because thread expired.

### The Solution

**Schema:** `answers_given` table persists:

```sql
CREATE TABLE answers_given (
    id BIGSERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    figures_cited JSONB,          -- Extracted metrics
    handler_name TEXT NOT NULL,
    thread_ts TEXT,
    answered_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Figure extraction:** `memory.py` extracts key figures for reconciliation:

```python
{
    'renewal_value': 1590000,
    'deal_count': 127,
    'attainment_pct': 12.7,
    'grr_pct': 77
}
```

**Reconciliation:** When a number changes, show the sequence:

```python
from memory import reconcile_figure_change

explanation = reconcile_figure_change(
    sb,
    figure_name='renewal_value',
    old_value=733000,
    new_value=1590000,
    question='renewal pipeline'
)

# Returns:
# "This figure has changed 3 times:
#   1. 2026-09-02: $733,000 (via query_renewals)
#   2. 2026-09-02: $5,200,000 (via query_renewals)
#   3. 2026-09-02: $1,590,000 (via query_renewals)
#
# Check proposals table for corrections that explain the change."
```

### Integration Points

**In router.py after synthesis:**

```python
from memory import save_answer

# After successful answer
answer_id = save_answer(
    sb,
    question=user_message,
    answer=final_response,
    handler_name=handler_name,
    thread_ts=thread_ts,
    asked_by=user_id,
    tool_results=tool_results
)

logger.info(f"[MEMORY] Saved answer {answer_id}")
```

**For "you told me X last week" queries:**

```python
from memory import get_prior_answers

prior = get_prior_answers(sb, question_pattern="renewal pipeline", limit=5)
# Returns last 5 answers about renewal pipeline with dates and figures
```

---

## 5c. Failure Resolution Tracking

### The Problem

`fallback_log` captures trigger and fast_path_attempted. But when a failure gets fixed, there's no way to mark it resolved. The log grows but doesn't show what was actually fixed.

### The Solution

**Schema additions to fallback_log:**

```sql
ALTER TABLE fallback_log ADD COLUMN resolved BOOLEAN DEFAULT FALSE;
ALTER TABLE fallback_log ADD COLUMN resolved_at TIMESTAMPTZ;
ALTER TABLE fallback_log ADD COLUMN resolution_type TEXT;
    -- 'handler_added' | 'semantic_fact_added' | 'data_fixed'
    -- | 'question_clarified' | 'out_of_scope'
ALTER TABLE fallback_log ADD COLUMN resolution_notes TEXT;
```

**Mark failures resolved:**

```python
from failure_resolution import mark_failure_resolved

# After fixing email mismatch that blocked Christian's attainment
mark_failure_resolved(
    sb,
    failure_id=42,
    resolution_type='data_fixed',
    resolution_notes='Fixed email mismatch: christian@ vs christian.liebenow@ in rep_targets'
)
```

**Bulk resolve similar failures:**

```python
from failure_resolution import bulk_resolve_similar

# After adding quarter resolution to query_pipeline
count = bulk_resolve_similar(
    sb,
    question_pattern='pipeline this quarter',
    resolution_type='handler_added',
    resolution_notes='Added quarter resolution to query_pipeline handler'
)

# Returns: 5 similar failures marked resolved
```

**Resolution statistics:**

```python
from failure_resolution import get_resolution_stats

stats = get_resolution_stats(sb, days=30)
# {
#     'total_failures': 42,
#     'resolved_count': 28,
#     'resolution_rate': 0.67,
#     'by_resolution_type': {
#         'handler_added': 8,
#         'semantic_fact_added': 12,
#         'data_fixed': 6,
#         'question_clarified': 2
#     },
#     'unresolved_count': 14
# }
```

### Integration Points

**Manual resolution after fixes:**

When you fix an issue that caused fallback failures, mark them resolved:

```python
# scripts/resolve_failures.py
from failure_resolution import find_similar_unresolved_failures, mark_failure_resolved

# Find all unresolved renewals failures
failures = find_similar_unresolved_failures(
    sb,
    question='renewal pipeline',
    handler_attempted='query_renewals'
)

for failure in failures:
    mark_failure_resolved(
        sb,
        failure['id'],
        'semantic_fact_added',
        'Updated renewals to use renewal_revenue field'
    )
```

---

## What This Enables

### Corrections (5a)
- User says "renewals value on renewal_revenue"
- Agent: "Is this general or specific?"
- User: "General"
- Agent creates proposal with conversation as evidence
- Human reviews and approves
- Config gets updated

**Before:** Correction died in thread
**After:** Correction captured as reviewable proposal

### Answers (5b)
- User asks "what's the renewal pipeline?"
- Gets answer: $1.59M
- Next week, asks "didn't you say $733K last time?"
- Agent shows sequence: $733K → $5.2M → $1.59M with dates
- Links to proposal explaining the change

**Before:** Thread expired, sequence lost
**After:** Full history preserved, changes explainable

### Failures (5c)
- 42 "which of those are at risk?" failures in unanswered_queries
- Fix thread context preservation
- Bulk-resolve all 42 with resolution_type='semantic_fact_added'
- Log now shows what was actually fixed

**Before:** Growing list of unresolved failures
**After:** Resolution tracking shows impact of fixes

---

## Deployment Checklist

### 1. Apply Migration

```bash
# Option A: Via psql (if SUPABASE_DB_URL is set)
psql $SUPABASE_DB_URL < scripts/migrations/052_add_memory_tables.sql

# Option B: Via Supabase SQL Editor
# Copy contents of 052_add_memory_tables.sql and paste into editor
```

### 2. Verify Tables

```sql
-- Check answers_given exists
SELECT COUNT(*) FROM answers_given;

-- Check fallback_log has new columns
SELECT resolved, resolution_type FROM fallback_log LIMIT 1;

-- Check proposals has conversation_evidence
SELECT conversation_evidence FROM proposals LIMIT 1;
```

### 3. Integrate into Router

Add to `api/router.py`:

```python
# Imports
from corrections import detect_correction, ask_correction_scope, create_correction_proposal
from memory import save_answer
from failure_resolution import mark_failure_resolved

# After synthesis (line ~450)
if detect_correction(user_message):
    # Handle correction flow

# After successful answer (line ~480)
save_answer(sb, user_message, final_response, handler_name, thread_ts, user_id, tool_results)
```

### 4. Test Each Part

**Test 5a (Corrections):**
```
User: "renewals value on renewal_revenue"
Agent: "Is this correction general or specific?"
User: "General"
Agent: "Created proposal for review"
```

**Test 5b (Answers):**
```
User: "what's the renewal pipeline?"
# Check answers_given has record with figures_cited
```

**Test 5c (Resolutions):**
```python
# Mark a failure resolved and verify
mark_failure_resolved(sb, 1, 'handler_added', 'Test resolution')
```

---

## Examples from Debugging Session

Four corrections that should have become proposals:

| Correction | Entity Type | Proposal Key | Affects Handlers |
|------------|-------------|--------------|------------------|
| "renewals value on renewal_revenue" | field_definition | query_renewals_field_value | Yes |
| "reps forecast Incremental ARR only" | calculation_methodology | query_rep_attainment_calc | Yes |
| "Review is a parking lot" | stage_semantics | query_pipeline_stage_def | No |
| "targets use HubSpot's email convention" | identity_convention | query_rep_attainment_identity | Yes |

All four captured in `corrections.py` as `EXAMPLE_CORRECTIONS`.

---

## Wave 5 Complete

Three specific memory mechanisms built:

✓ **5a. Corrections → Proposals** with conversation evidence
✓ **5b. Answers persist** beyond 24-hour thread expiry
✓ **5c. Failure resolution** closes the loop

Migration ready, integration points documented, examples from debugging session preserved.

Ready for Wave 6 (Monitoring) when migration is applied and integration is tested.
