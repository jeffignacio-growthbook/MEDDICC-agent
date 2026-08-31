# Named Entity Sets — Verification Guide

**Commit:** 39d57c1

Implemented named entity sets for precise narrowing follow-ups.

---

## What Was Built

### 1. Extract Named Sets (api/db.py)

**Function:** `_extract_named_sets(tool_results)`

Scans pipeline movement `by_stage` arrays for ID groupings:

```python
by_stage = [
  {
    "stage": "Negotiating",
    "exited_ids": [1, 2, 3, 4, 5, 6],
    "entered_from_other_stage_ids": [7, 8],
    "new_to_pipeline_ids": []
  }
]

# Extracts to:
named_sets = {
  "exited_Negotiating": [1, 2, 3, 4, 5, 6],
  "entered_from_other_stage_Negotiating": [7, 8]
}
```

**Names from handler data, not question parsing.** The handler already knows what these groups mean.

---

### 2. Resolve Via Classifier (api/router.py)

**Function:** `resolve_named_set(question, named_sets, client)`

Uses LLM to match question to a named set:

```python
# Question: "Where did the 6 that left Negotiating go?"
# Available: {"exited_Negotiating": [1,2,3,4,5,6], ...}
# Returns: ([1,2,3,4,5,6], "exited_Negotiating")
```

**Not keyword matching.** The classifier handles variations:
- "left Negotiating" → exited_Negotiating
- "dropped out of Negotiating" → exited_Negotiating
- "the ones that exited" → exited_Negotiating

**Falls back to all deal_ids** if no match:
- "Which of those are enterprise?" → NONE (not a named set)
- Returns None → uses all prior deal_ids

---

### 3. Confirm in Answer

**Added to tool_results:**
```python
result["_resolved_set"] = "exited_Negotiating"
result["_resolved_count"] = 6
```

**Synthesis prompt instructs:**
> If _resolved_set is present, ALWAYS confirm which set you're answering about in the opening line.
> Format: "Of the 6 that left Negotiating: 4 closed won, 1 lost, 1 moved to Scoping."

**Why:** Confirms understanding of which subset. Failure mode is silently answering about the wrong group.

---

## Testing in Slack

### Test 1: Basic Named Set Resolution

**Setup:** Ask a question that triggers pipeline movement with exits.

1. **First question:**
   ```
   How has pipeline moved this week?
   ```

2. **Check log for named sets:**
   ```
   [NAMED_SET] exited_Negotiating: 6 deals
   [NAMED_SET] entered_from_other_stage_Discovery: 3 deals
   [ENTITY_EXTRACT] named sets: ['exited_Negotiating', 'entered_from_other_stage_Discovery', ...]
   ```

3. **Follow-up question:**
   ```
   Where did the 6 that left Negotiating go?
   ```

4. **Check log for resolution:**
   ```
   [NAMED_SET] resolved 'exited_Negotiating': 6 of 20 deals
   [ENTITY_SCOPE] query_deal_stages_bulk (quality=good)
   ```

5. **Check answer confirms:**
   ```
   Of the 6 that left Negotiating: 4 closed won, 1 closed lost, 1 moved to Scoping.
   ```

**Expected:** Handler receives 6 IDs (not 20), answer confirms the subset.

---

### Test 2: Phrasing Variations

After asking about pipeline movement:

**Different phrasings for the same set:**
- "Where did those 6 go?"
- "What about the ones that dropped out of Negotiating?"
- "Show me the deals that exited Negotiating"

**All should resolve to:** `exited_Negotiating`

**Check log shows:** Same resolution for all variations.

---

### Test 3: Non-Named Set Fallback

After asking about pipeline movement:

**Question that doesn't match a named set:**
```
Which of those deals are enterprise accounts?
```

**Check log:**
```
[NAMED_SET] no match (classifier returned: NONE)
[ENTITY_SCOPE] using 20 known deal_ids, bypassing discovery
```

**Expected:** Falls back to all 20 deal_ids, no _resolved_set in answer.

---

### Test 4: Multiple Named Sets

After asking about pipeline movement:

1. **Follow-up about exited deals:**
   ```
   Where did the deals that left Negotiating go?
   ```
   **Expect:** Resolves to `exited_Negotiating`

2. **Follow-up about entered deals:**
   ```
   What about the ones that entered Discovery?
   ```
   **Expect:** Resolves to `entered_from_other_stage_Discovery`

3. **Follow-up about new deals:**
   ```
   Show me the new deals in Qualification
   ```
   **Expect:** Resolves to `new_to_pipeline_Qualification`

**Each should confirm the specific set in the answer.**

---

### Test 5: Assessor Score Improvement

**Before named sets:** Question about "the 6 that left Negotiating" received all 20 deal_ids, assessor scored 0.25 (below floor).

**After named sets:**

1. Ask about pipeline movement
2. Follow up: "Where did the 6 that left Negotiating go?"
3. Check log:
   ```
   [ASSESS] score=0.85 issue=none
   ```

**Expected:** Score > 0.70 (above floor), no honest-miss message.

---

## Verification Checklist

- [ ] Named sets extracted from by_stage arrays
- [ ] Named sets stored in entity_context
- [ ] Classifier resolves "left Negotiating" to exited_Negotiating
- [ ] Handler receives 6 IDs, not 20
- [ ] Answer confirms: "Of the 6 that left Negotiating..."
- [ ] Phrasing variations ("dropped out") resolve correctly
- [ ] Non-named-set questions fall back to all deal_ids
- [ ] Assessor score improves (> 0.70, no floor trigger)

---

## Log Markers to Watch

**Named set extraction:**
```
[NAMED_SET] exited_Negotiating: 6 deals
[ENTITY_EXTRACT] named sets: ['exited_Negotiating', ...]
```

**Named set resolution:**
```
[NAMED_SET] resolved 'exited_Negotiating': 6 of 20 deals
```

**No match (fallback):**
```
[NAMED_SET] no match (classifier returned: NONE)
```

**Handler receives resolved IDs:**
```
[ENTITY_SCOPE] query_deal_stages_bulk (quality=good)
# Check next line shows 6 rows returned, not 20
```

---

## Example Flow

**Q1:** "How has pipeline moved this week?"

**Log:**
```
[HANDLER] query_pipeline_movement
[NAMED_SET] exited_Negotiating: 6 deals
[NAMED_SET] entered_from_other_stage_Discovery: 3 deals
[ENTITY_EXTRACT] named sets: ['exited_Negotiating', 'entered_from_other_stage_Discovery']
[ENTITY_EXTRACT] legacy shape: 20 deal_ids, 20 company_names
```

**A1:** "Pipeline movement from Aug 24 → Aug 31: 6 deals left Negotiating, 3 entered Discovery, ..."

---

**Q2:** "Where did the 6 that left Negotiating go?"

**Log:**
```
[ENTITY_SCOPE] using 20 known deal_ids, bypassing discovery
[NAMED_SET] resolved 'exited_Negotiating': 6 of 20 deals
[ENTITY_SCOPE] query_deal_stages_bulk (quality=good)
[ASSESS] score=0.85 issue=none
```

**A2:** "Of the 6 that left Negotiating: 4 closed won (Acme, Globex, Stark, Wayne), 1 closed lost (LexCorp), and 1 moved back to Scoping (Oscorp)."

---

## Next Steps

1. Deploy to Railway (restart API service to pick up changes)
2. Run Test 1 in Slack
3. Verify log shows named set extraction and resolution
4. Verify answer confirms the subset
5. Run Test 5 to confirm assessor improvement

If all tests pass, named sets close the gap for narrowing follow-ups.
