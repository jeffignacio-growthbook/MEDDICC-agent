# Assessor Floor Failure Investigation

**Date:** 2026-08-31
**Question:** "Where did the 6 deals that left Negotiating go?"
**Score:** 0.25 (below 0.30 floor)
**Handler:** query_deal_stages_bulk

---

## What Happened

### The Mismatch

1. **Previous answer:** Returned 20 deals total (various stages)
2. **Entity extraction:** Saved all 20 deal_ids to thread context
3. **Follow-up question:** Asked about "the 6 deals that left Negotiating"
4. **Entity-scope routing:** Detected pronoun "the" → bypassed discovery
5. **Handler execution:** query_deal_stages_bulk received ALL 20 deal_ids
6. **Result:** Returned stages for all 20 deals, not just the 6
7. **Synthesis:** Tried to answer about 6, but had data for 20
8. **Assessor:** Scored 0.25 — answer was likely bloated or confusing

### The Root Cause

**Entity-scope routing doesn't filter entities based on the refined question.**

When the user asks about "the 6 deals that left Negotiating" (a subset of the 20), the system:
- ✅ Correctly detects this is a follow-up (pronoun "the")
- ✅ Correctly routes to query_deal_stages_bulk (stage lookup)
- ❌ Passes ALL 20 deal_ids from thread context
- ❌ Doesn't filter to "only the 6 that left Negotiating"

From `api/router.py:680`:
```python
result = await handler_fn(
    {"deal_ids": deal_ids, "time_window": default_tw}, sb)
    # ^^^^^^^^ ALL deal_ids from thread context, no filtering
```

### Why This Scored Low

The handler returned stages for 20 deals when the question asked about 6. Possible failure modes:
1. Synthesis listed all 20 deals (14 irrelevant)
2. Synthesis tried to filter but couldn't determine which 6
3. Answer was vague or hedged due to ambiguity

The assessor correctly flagged this as unreliable (0.25 score). The honest-miss gate worked as intended.

---

## Answerable But Failed

The question WAS answerable:
- Previous answer contained the 6 deal IDs
- Their current stage is one lookup away
- Thread context carried the entity list

But the routing/filtering layer couldn't narrow from 20 → 6, creating noise.

---

## What the Log Should Show

To diagnose this fully, check the log for:

1. **Thread context size:**
   ```
   [ENTITY_SCOPE] using 20 known deal_ids, bypassing discovery
   ```

2. **Handler result:**
   ```
   [ENTITY_SCOPE] query_deal_stages_bulk (quality=good)
   ```
   Check tool_results payload: does it have 20 rows in `stages` array?

3. **Synthesis input:**
   ```
   [CAP] tool_results: 35,656 chars, synthesis_results: 7,884 chars (rows before: 20, after: 20)
   ```
   Row cap doesn't apply to `stages` array (not in ARRAY_KEYS_TO_CAP).

4. **Assessor reasoning:**
   ```
   [ASSESS] score=0.25 issue=<what> — sending honest miss
   ```
   The `issue` field should explain what the assessor flagged.

---

## Solutions

### Short-term (Current Behavior)

**Accept this as designed.** The honest-miss gate worked:
- Question routed correctly
- Handler returned data
- Synthesis couldn't filter reliably
- Assessor caught it
- User got honest-miss instead of confabulation

This is better than a confident wrong answer.

### Medium-term (Numeric Filter Extraction)

Extract numeric filters from questions and pass them to handlers:

```python
# In route_entity_scoped_question:
deal_ids = prior_entities["deal_ids"]
filter_hint = extract_numeric_filter(question)
# "the 6 that left Negotiating" → {"count": 6, "stage_from": "Negotiating"}

# Pass to handler:
result = await handler_fn({
    "deal_ids": deal_ids,
    "filter_hint": filter_hint,  # NEW
    "time_window": default_tw
}, sb)
```

Handler could pre-filter before querying, or synthesis could use the hint.

### Long-term (Pre-Routing Entity Extraction)

Run entity extraction BEFORE routing to get the refined list:
1. Classify question type
2. Extract entities (including numeric filters)
3. Route with refined entity list
4. Handler gets exactly the deals asked about

This inverts the current flow (route → query → extract).

---

## Testing

To verify this diagnosis, re-run the question and check:

1. How many deal_ids were in thread context?
2. How many rows did query_deal_stages_bulk return?
3. What did the synthesis say? (the drafted answer)
4. What was the assessor's `issue` field?

If log shows 20 deal_ids → 20 rows → bloated answer → assessor flagged it, then this diagnosis is correct.

---

## Status

**Honest-miss message:** Fixed (commit 9bea3f9) — now uses plain language, no internal vocabulary.

**Underlying filter issue:** Documented. Not a regression — this is how entity-scope routing currently works. The assessor correctly caught the failure.

If this pattern becomes common (subset questions scoring below floor), implement numeric filter extraction (medium-term solution).
