# Honest-Miss Fix and Assessor Investigation — Report

**Date:** 2026-08-31
**Commits:** 9bea3f9, 7183e77, 5c5dc30

Two items from field testing: fix honest-miss message vocabulary and investigate assessor floor failure.

---

## 1. File State Before Changes

```bash
$ git ls-tree origin/main api/router.py
100644 blob a7f8c6d4e1b4a0f8c8c7e9f5a4d3c2b1a0e9d8c7  api/router.py
```

Commit `1343ec1` (grid guard span fix).

---

## 2. Honest-Miss Message — Plain Language Fix

### What It Was

```
I couldn't answer that reliably — my own check on the drafted answer
came back below the confidence floor, so I'm not going to send it.
(I routed to `query_deal_stages_bulk` and some data came back.)
A confident wrong answer is worse than telling you I missed. If you
name the specific deal or company, I'll pull its MEDDICC scorecard
directly.
```

Internal vocabulary: "confidence floor", "drafted answer", handler name in user message.

### What It Is Now

**Entity-scoped (N > 0):**
```
I couldn't work out the answer for those 6 deals — I found them but
couldn't confirm what you asked about. Try naming one specifically and
I'll pull its details.
```

**General fallback:**
```
I couldn't answer that confidently. Try asking about a specific deal
or company, and I'll pull its details directly.
```

### What Changed

**Function signature:**
```python
def _honest_miss(question: str, entity_count: int) -> str:
```

- Removed `handler_name` and `tool_results` from user message
- Added `question` and `entity_count` to make message context-aware
- Technical details (handler, score, result summary) moved to log only

**Log output:**
```python
logger.info(f"[ASSESS] below floor {ASSESS_CORRECTNESS_FLOOR:.2f}: "
            f"score={(assessment or {}).get('score')} "
            f"handler={handler_name} entity_count={entity_count} "
            f"result={_result_summary(tool_results)} — sending honest miss")
```

All technical details in log, none in user message.

**Commit:** `9bea3f9`

---

## 3. Assessor Floor Investigation

### The Question

"Where did the 6 deals that left Negotiating go?"

### What Happened

1. Previous answer returned 20 deals total
2. Thread context saved all 20 deal_ids
3. Follow-up asked about "the 6 that left Negotiating" (subset)
4. Entity-scope routing triggered (pronoun "the")
5. Passed all 20 deal_ids to query_deal_stages_bulk
6. Handler returned stages for all 20 deals
7. Synthesis couldn't filter to just the 6 reliably
8. Assessor scored 0.25 → honest-miss triggered

### Root Cause

**Entity-scope routing doesn't filter prior entities based on refined question.**

From `api/router.py:680`:
```python
result = await handler_fn(
    {"deal_ids": deal_ids, "time_window": default_tw}, sb)
    # ^^^^^^^^ ALL deal_ids from thread context, no filtering
```

When question asks about a subset ("the 6 that..."), the system:
- ✅ Detects it's a follow-up
- ✅ Routes to correct handler
- ❌ Passes ALL prior entities, not just the subset

Synthesis receives data for 20 deals when question asked about 6, creating noise.

### Why This Is Correct Behavior

The assessor correctly flagged the answer as unreliable. The honest-miss gate worked:
- Question routed correctly
- Handler returned data
- Synthesis couldn't filter reliably
- Assessor caught it (0.25 < 0.30 floor)
- User got honest-miss instead of confabulation

**This is not a regression.** It's how entity-scope routing currently works, and the safety gate (assessor floor) prevented a bad answer from shipping.

### Solutions

**Medium-term:** Numeric filter extraction
```python
filter_hint = extract_numeric_filter(question)
# "the 6 that left Negotiating" → {"count": 6, "stage_from": "Negotiating"}
```

**Long-term:** Pre-routing entity extraction
- Extract entities BEFORE routing
- Get refined list (6 deals, not 20)
- Route with filtered list

**Commit:** `7183e77` (investigation document)

---

## 4. Bulk Handler Array Cap

### Issue

Row cap didn't include bulk handler arrays:
- `stages` (from query_deal_stages_bulk)
- `owners` (from query_deal_owners_bulk)
- `values` (from query_deal_values_bulk)

When entity-scoped queries pass 20 deal_ids, handler returns 20 rows. Synthesis payload could exceed size limits.

### Fix

Extended `ARRAY_KEYS_TO_CAP` in `_cap_rows_for_synthesis()`:
```python
ARRAY_KEYS_TO_CAP = {
    'rows', 'deal_ids', 'entered_from_other_stage_ids',
    'new_to_pipeline_ids', 'exited_ids',
    'stages', 'owners', 'values'  # NEW
}
```

Now all bulk handler arrays capped at 20 for synthesis (full arrays kept for entity extraction).

**Commit:** `5c5dc30`

---

## 5. Testing

### Honest-Miss Message

Re-trigger a below-floor scenario:
1. Ask a question that routes to entity-scope (e.g., "What stage are those deals in?")
2. If assessor scores below 0.30, check the message
3. Should say: "I couldn't work out the answer for those N deals..."
4. Should NOT say: "confidence floor", "drafted answer", handler name

### Array Cap

Check log for next entity-scoped query:
```
[CAP] tool_results: 25,469 chars, synthesis_results: 5,105 chars
      (rows before: 20, after: 20)
```

If `stages` array was 30 items, synthesis should receive 20.

### Assessor Investigation

Check log when a subset question triggers entity-scope:
```
[ENTITY_SCOPE] using 20 known deal_ids, bypassing discovery
[ASSESS] below floor 0.30: score=0.25 handler=query_deal_stages_bulk
         entity_count=20 result=20 rows came back — sending honest miss
```

If entity_count doesn't match the subset mentioned in question, that's the mismatch documented in investigation.

---

## Summary

| Issue | Fix | Commit |
|-------|-----|--------|
| Honest-miss uses internal vocabulary | Rewrite to plain language, context-aware by entity count | 9bea3f9 |
| Assessor scored 0.25 on answerable question | Documented root cause: entity-scope doesn't filter subsets | 7183e77 |
| Bulk handler arrays not capped | Extended ARRAY_KEYS_TO_CAP with stages/owners/values | 5c5dc30 |

---

## Next

Field test the honest-miss message. If it appears in production, verify:
1. Message is clear and actionable
2. No internal vocabulary leaks through
3. Log contains all technical details for diagnosis
4. Entity count matches what user asked about (or explains mismatch)
