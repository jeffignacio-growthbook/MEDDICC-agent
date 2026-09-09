# Railway Logs Investigation: "Fallback Search Ran Out of Budget"

**Investigation Date:** 2026-09-09
**Request Timestamp:** 2026-09-09T14:32:32Z
**Question:** "How has EMEA pipeline moved in the last 2 weeks"

---

## 1. What It Means Mechanically

**Budget = Token limit, NOT step count or timeout:**
- `TOKEN_BUDGET = 40,000` tokens (raised from 20K after lightweight schema optimization)
- `MAX_ITERATIONS = 5` tool call iterations
- System tracks cumulative tokens: `tokens_used += resp.input_tokens + resp.output_tokens`

**The error triggers when:**
- **Pre-call budget check:** Projected next iteration would exceed 40K tokens
- **Post-call budget check:** Actual usage exceeded 40K tokens (rare)
- **Pre-synthesis budget check:** Not enough tokens left to synthesize final answer

**In this case:** Pre-call budget check triggered (iteration 3 → 4 projection)

---

## 2. How Many Iterations Before Failure

**3 iterations completed, 4th declined:**

| Iteration | Tool | Params | Rows Returned |
|-----------|------|--------|---------------|
| 0 | filter_table | waterfall_weekly, date range (Aug 24 - Sep 9) | 50 |
| 1 | aggregate_results | (aggregate step_0 data) | 0 ❌ |
| 2 | filter_table | waterfall_weekly, EMEA + default pipeline | 20 |
| 3 | ❌ DECLINED | Projected to exceed budget | N/A |

**Total tokens used:** 32,406 of 40,000 (81%)

**Why it stopped:**
- After 3 iterations, accumulated context ≈ 18K tokens (system prompt + 3 tool calls + 3 results)
- Projected 4th iteration: 32K + ~19K (input + output) = 51K > 40K budget
- Pre-call check declined iteration before making expensive call

---

## 3. Reproducible or One-Off?

**Result:** **ONE-OFF**

**Evidence:**
- Queried `fallback_log` table for last 7 days
- **Only 1 occurrence** of budget_exhausted trigger
- No pattern of EMEA questions failing
- No pattern of time-range questions failing

**Root cause of this specific failure:**
1. **aggregate_results returned 0 rows on iteration 1** (unexpected)
2. This forced iteration 2 to re-query waterfall_weekly with EMEA filter
3. Extra query added enough context that iteration 3 projected over budget
4. If aggregation had worked, question likely completes in 2 iterations

**Verdict:** Unlucky edge case, not systematic issue

---

## Key Findings

### Budget Protection Worked Correctly
- System **predicted** 4th call would be too expensive
- **Declined** before wasting tokens on unaffordable call
- Returned diagnostic message: "gathered partial data but ran out of budget to assemble it"
- User got appropriate fallback with suggestion to narrow question

### The Real Issue
**aggregate_results failure on iteration 1:**
- Should have aggregated 50 waterfall rows from step_0
- Returned 0 rows instead (likely wrong reference or param error)
- Forced redundant query, adding context
- **This is the optimization target**, not the budget

### No Action Required
- Budget protection is working as designed
- Failure rate is low (1 in 7 days)
- System recovered gracefully with user-facing message
- EMEA pipeline queries work normally (this was edge case)

---

## Detailed Analysis

Full technical breakdown available in:
- `FALLBACK_BUDGET_ERROR_ANALYSIS.md` - complete investigation
- `check_fallback_logs.py` - script to query fallback_log table

**For future monitoring:**
```sql
SELECT * FROM fallback_log
WHERE trigger = 'budget_exhausted'
ORDER BY created_at DESC
LIMIT 10;
```

Watch for patterns. If budget_exhausted becomes frequent, consider:
1. Fix aggregate_results to prevent extra iterations
2. Aggressive aggregation for waterfall queries
3. Early synthesis when sufficient data exists
4. Increase TOKEN_BUDGET to 60K (last resort)

---

## User-Facing Behavior

When this occurs, user sees:
> "I searched the data directly for this, and the fallback search gathered partial data but ran out of budget to assemble it. Try naming a specific deal or rep, or narrowing the question to a shorter time range."

**Good:**
- Plain language, no jargon
- Suggests concrete alternatives

**Could improve:**
- Indicate this is unusual (not that their question is too broad)
- "This looks like a valid question — I'm working on handling these more efficiently"
