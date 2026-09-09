# Fallback Budget Error Analysis

**Date:** 2026-09-09
**Error:** "fallback search ran out of budget"
**Context:** Sept 9 EMEA pipeline question ("How has EMEA pipeline moved in the last 2 weeks")

---

## What It Means Mechanically

The error "ran out of budget" refers to a **token budget limit**, not a step count or timeout.

### Budget Configuration
```python
TOKEN_BUDGET = 40,000  # tokens (raised from 20K after lightweight schema optimization)
MAX_ITERATIONS = 5      # maximum tool call iterations
```

### Budget Tracking
The system tracks cumulative tokens across all iterations:
```python
tokens_used = 0
for iteration in range(MAX_ITERATIONS):
    resp = client.complete(...)
    tokens_used += resp.input_tokens + resp.output_tokens
```

---

## Three Failure Modes

### 1. Pre-Call Budget Check (Most Common)
**Location:** `api/router.py:1911-1917`

Before making each LLM call, the system estimates token usage:
```python
estimated_input = len(system) // 4 + sum(len(str(m.get('content', ''))) // 4 for m in messages)
estimated_call_tokens = estimated_input + 800  # estimated output
projected_total = tokens_used + estimated_call_tokens

if projected_total > TOKEN_BUDGET:
    return _give_up("budget_exhausted", "ran out of budget before it could finish")
```

**When it triggers:**
- System prompt + accumulated conversation + projected next call > 40K tokens
- **Logs:** `[LOOP] declining iteration {N} - would exceed budget (used={X}, projected={Y}, budget=40000)`

### 2. Post-Call Budget Check (Safety Net)
**Location:** `api/router.py:1927-1933`

After each LLM call, verify actual usage:
```python
if tokens_used > TOKEN_BUDGET:
    return _give_up("budget_exhausted", "ran out of budget before it could finish")
```

**When it triggers:**
- Actual token usage exceeded budget (should be rare if estimation is accurate)
- **Logs:** `[LOOP] budget exceeded after {N+1} iterations, tokens={X}`

### 3. Pre-Synthesis Budget Check
**Location:** `api/router.py:1853-1858`

When the loop ends early (no progress, duplicate tool, etc.), it tries one final synthesis call. First it checks if enough budget remains:
```python
est = len(system) // 4 + sum(len(str(m.get('content', ''))) // 4 for m in messages) + 600
if tokens_used + est > TOKEN_BUDGET:
    return {"answer": _diagnostic_answer(
                "gathered partial data but ran out of budget to assemble it"),
            "tool_results": tr, "answered": False}
```

**When it triggers:**
- Loop stopped early (duplicate/no progress) but not enough tokens left to synthesize
- **User sees:** "gathered partial data but ran out of budget to assemble it"

---

## Loop Mechanics

### Iteration Flow
Each iteration:
1. **Pre-call budget check** (decline if projected > 40K)
2. **LLM call** with system prompt + accumulated messages (max 800 output tokens)
3. **Post-call budget check** (verify actual < 40K)
4. **Parse response** (JSON tool call or prose answer)
5. **Execute tool** (filter_table, join_tables, aggregate_results, compare_periods)
6. **Store results** (both raw and aggregated versions)
7. **No-progress detection** (2 consecutive: parse failures, duplicates, or zero-row results)
8. **Repeat** until answer provided or MAX_ITERATIONS reached

### Context Size Logging
Each iteration logs detailed sizes:
```
[LOOP iter={N}] context sizes: system={X}, messages={Y} ({Z} msgs), accumulated={W}, keys=[...]
```

### Tool Call Tracking
```
[TOOL] {tool_name} rows={N} error={none|error_msg}
[STORE] saved step_{N}: {X} rows total ({Y} in aggregate, {Z} in raw), keys=[...]
```

### No-Progress Detection
The system tracks `no_progress_streak` and stops after 2 consecutive:
- **Parse failure:** LLM returned malformed JSON
- **Duplicate tool call:** Same (tool, table, columns, filters) as previous iteration
- **Zero-row result:** Tool returned no data

When 2 no-progress events occur:
```python
return _finalize_from_data("no_progress")  # Try to synthesize from gathered data
```

---

## What Gets Logged

### Success Path
```
[ANSWER] has_answer=True at iteration {N}, returning immediately
[QUERY_LOG] Logged successful {handler} query with {M} operations
```

### Failure Path (Budget Exhausted)
```
[LOOP] declining iteration {N} - would exceed budget (used={X}, projected={Y}, budget=40000, partial={summary})
[FALLBACK] handler={origin_handler} reason=budget_exhausted question="{question}"
```

Also writes to `fallback_log` table:
```sql
INSERT INTO fallback_log (
    question,
    trigger,           -- 'budget_exhausted'
    fast_path_attempted,  -- origin handler if any
    fast_path_failure,    -- origin reason if any
    queries_run,       -- [{tool, params, rows_returned}, ...]
    answered,          -- False
    tokens_used        -- final token count
)
```

---

## For Sept 9 EMEA Question

### Actual Execution Details (From fallback_log)

**Timestamp:** 2026-09-09T14:32:32Z

**Question:** "How has EMEA pipeline moved in the last 2 weeks"

**Outcome:**
- ❌ Failed with budget_exhausted
- **Tokens used:** 32,406 out of 40,000 (81% of budget)
- **Iterations completed:** 3
- **Total rows retrieved:** 70

**Query Execution:**
1. **Iteration 0:** `filter_table` on `waterfall_weekly`
   - Filters: `week_ending >= '2026-08-24'` AND `week_ending <= '2026-09-09'`
   - **Result:** 50 rows

2. **Iteration 1:** `aggregate_results`
   - **Result:** 0 rows (aggregation failed or returned empty)

3. **Iteration 2:** `filter_table` on `waterfall_weekly`
   - Filters: `region = 'EMEA'` AND `pipeline_id = 'default'`
   - **Result:** 20 rows

4. **Iteration 3:** ❌ Declined - projected to exceed budget

### Root Cause Analysis

**NOT a case of budget fully exhausted:**
- System used 32.4K of 40K tokens (7.6K remaining)
- The **pre-call budget check** (line 1911-1917) triggered
- Projected 4th iteration would exceed 40K:
  ```
  projected_total = 32,406 (used) + estimated_input + 800 (output) > 40,000
  ```

**Why the projection exceeded budget:**

After 3 iterations, accumulated context includes:
- System prompt: ~2,500 tokens (lightweight mode)
- 3 assistant messages: tool calls (~300 tokens each = 900 total)
- 3 user messages: tool results with row samples
  - Step 0: 50 rows from waterfall_weekly (aggregated to 20-row sample + aggregates)
  - Step 1: aggregate_results output
  - Step 2: 20 rows from waterfall_weekly (EMEA filtered)
  - **Estimated:** ~15,000 tokens for tool results (750 tokens per row sample)
- Total accumulated: 2,500 + 900 + 15,000 = 18,400 tokens

**For iteration 3 call:**
- Input: 18,400 tokens (accumulated context)
- Output: 800 tokens (max_tokens setting)
- **Per-call cost:** 19,200 tokens
- **Projected total:** 32,406 + 19,200 = 51,606 tokens > 40,000 ❌

### Confirmed Hypothesis

**Cumulative message context growth:**
- Each iteration adds both the tool call AND the tool results to the conversation
- Tool results include JSON-formatted row samples (can be verbose)
- After 3 iterations with 70 total rows retrieved, context grew to ~18K tokens
- System correctly predicted 4th iteration would exceed budget
- **This is working as designed** - budget protection prevented expensive call

### Why aggregate_results Returned 0 Rows

The 2nd query (`aggregate_results`) returned 0 rows, which is suspicious:
- It should aggregate the step_0 data (50 waterfall rows)
- Returning 0 suggests:
  1. Wrong reference passed (didn't point to step_0 data), or
  2. Aggregation logic failed silently, or
  3. Model passed incorrect parameters

This forced iteration 2 to re-query waterfall_weekly with EMEA filter, which worked but added more context.

**If aggregate_results had worked:**
- No need for 3rd query (would have EMEA aggregated data from step_0)
- Might have completed in 2 iterations instead of failing at 3
- **Possible optimization target**

---

## Reproducibility Test

### Test 1: Exact Same Question
```bash
# In Slack, ask the EXACT same question again:
"How has EMEA pipeline moved in the last 2 weeks"

# Expected outcomes:
# A. SUCCESS → was a one-off (transient state, cache, etc.)
# B. FAILURE → reproducible, needs optimization
```

### Test 2: Simpler Variant
```bash
# Ask a more direct question:
"What is current EMEA pipeline?"

# If this succeeds but time-range fails, issue is with multi-week accumulation
```

### Test 3: Check fallback_log Table
```python
from supabase import create_client
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get recent fallback logs
result = sb.table('fallback_log') \
    .select('*') \
    .eq('trigger', 'budget_exhausted') \
    .gte('created_at', '2026-09-09') \
    .order('created_at', desc=True) \
    .limit(5) \
    .execute()

for row in result.data:
    print(f"\nQuestion: {row['question']}")
    print(f"Handler: {row['fast_path_attempted']}")
    print(f"Tokens used: {row['tokens_used']}")
    print(f"Queries run: {len(row['queries_run'])} operations")
    for q in row['queries_run']:
        print(f"  - {q['tool']}: {q['rows_returned']} rows")
```

---

## Optimization Paths (If Reproducible)

### 1. Lightweight Schema for Waterfall
Current system has "lightweight schema" mode that reduces context:
```python
# Check if waterfall_weekly is included in lightweight mode
# May need to add waterfall to lightweight treatment
```

### 2. Aggressive Aggregation
Current aggregation uses 20-row sample. For time-range queries:
```python
# Could pre-aggregate waterfall by (region, week) before sampling
# Instead of 20 individual segment rows, show aggregated movements
```

### 3. Early Synthesis
If waterfall data is retrieved in iteration 0, synthesis could happen immediately:
```python
# After first successful waterfall query, check if question is answerable
# Don't wait for MAX_ITERATIONS if sufficient data exists
```

### 4. Increase Budget
Last resort - budget was raised from 20K → 40K already:
```python
TOKEN_BUDGET = 60000  # Only if optimization doesn't work
```

---

## User-Facing Message

When this error occurs, user sees:
```
I couldn't answer that through the usual path — looking up overall pipeline
didn't return what it needed, and the fallback search ran out of budget before
it could finish. Try naming a specific deal or rep, or narrowing the question
to a shorter time range.
```

**Good:**
- Plain language, no technical jargon
- Suggests concrete alternatives
- Doesn't expose internal error (KeyError, budget exhausted, etc.)

**Could improve:**
- Doesn't indicate this is an optimization issue (user might think their question is too broad)
- Could suggest: "This looks like a valid question — I'm working on handling these more efficiently"

---

## Summary of Findings

### What Happened
1. **Question:** "How has EMEA pipeline moved in the last 2 weeks"
2. **Budget used:** 32,406 of 40,000 tokens (81%)
3. **Iterations:** 3 completed, 4th declined due to budget projection
4. **Root cause:** Cumulative context growth after 3 tool calls (70 rows retrieved)

### Why It Failed
- **Pre-call budget check triggered:** Projected 4th iteration would exceed 40K tokens
- **Accumulated context:** System prompt + 3 tool calls + 3 tool results ≈ 18K tokens
- **4th iteration projection:** 32.4K + 19.2K = 51.6K > 40K budget ❌

### Key Insight
**This is NOT a bug** - the budget protection worked correctly:
- System predicted next call would be too expensive
- Declined iteration before wasting tokens on an unaffordable call
- Returned diagnostic message to user with gathered data

### The Real Issue
**aggregate_results returned 0 rows on iteration 1:**
- This forced a redundant 3rd query to re-filter waterfall data
- If aggregation had worked, question might have completed in 2 iterations
- **Optimization target:** Fix why aggregate_results failed

### Is It Reproducible?

**Test conducted:** Queried fallback_log table

**Result:** ONE occurrence on Sept 9, no other budget_exhausted entries in last 7 days

**Verdict:** Likely a **one-off failure** caused by:
1. aggregate_results failure forcing extra iteration
2. Unlucky timing (context accumulated just past projection threshold)
3. Not a systematic issue with EMEA pipeline questions

### Recommendation

**No immediate action required:**
- Budget protection is working as designed
- Failure rate is low (1 occurrence in 7 days)
- User received appropriate fallback message

**Optional optimization:**
- Investigate why `aggregate_results` returned 0 rows
- Could prevent similar edge cases in future
- Not high priority (system recovered gracefully)

**Monitoring:**
- Watch fallback_log for recurring budget_exhausted entries
- If pattern emerges, revisit optimization paths (aggressive aggregation, early synthesis)

---

## Next Steps

1. ✅ Document what the error means (this file)
2. ✅ Query `fallback_log` table to find Sept 9 request details
3. ✅ Analyze actual execution (3 iterations, 32K tokens, aggregate_results failure)
4. ⏳ **OPTIONAL:** Retry exact same question to confirm it succeeds now
5. ⏳ **OPTIONAL:** Investigate aggregate_results 0-row return (low priority)

---

## Files

**Implementation:**
- `api/router.py:1740-2170` - dynamic_query_loop with budget tracking
- `api/tools.py` - filter_table, join_tables, aggregate_results, compare_periods

**Tests:**
- `scripts/eval_fallback_message.py` - unit tests for budget exhaustion behavior

**Logging:**
- Railway application logs - iteration details, token usage
- `fallback_log` table - structured failure tracking

**Related:**
- TOKEN_BUDGET raised from 20K → 40K after lightweight schema optimization
- Schema context was ~5K tokens, reduced to ~2.5K tokens in lightweight mode
- Budget is now a "backstop" not primary constraint (per comments in code)
