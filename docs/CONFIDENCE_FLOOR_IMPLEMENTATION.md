# Confidence Floor Implementation

**Commit:** ecf256d

Config-driven confidence floor gates precomputed handler dispatch. Below threshold, route to dynamic loop instead of low-confidence match.

---

## Configuration

**File:** `config/client.yaml`

```yaml
routing:
  confidence_floor: 0.80           # General threshold for data handlers
  confidence_floor_help: 0.85      # Higher bar for orientation handlers
```

**Env overrides:**
- `ROUTING_CONFIDENCE_FLOOR`
- `ROUTING_CONFIDENCE_FLOOR_HELP`

**Status:** PROVISIONAL — starting guesses, tune against real routing logs.

---

## Logic

**After intent classification:**

1. **query_help / acknowledgment:** Require confidence >= 0.85
   - Misroutes are total loss (help menu looks like answer but isn't)
   - Below 0.85 → route to dynamic_query

2. **Data handlers:** Require confidence >= 0.80
   - Below 0.80 → route to dynamic_query
   - Exceptions: unanswerable, set_target, dynamic_query (no floor)

3. **Logging:**
   ```
   [ROUTING] confidence 0.72 < 0.85 for query_help — routing to dynamic instead
   ```
   Names original handler for retune analysis.

---

## Why This Matters

**Before:** "What do you forecast for the quarter?"
- No query_forecast handler
- Classified as query_help at 0.72 (best available option)
- Dispatched to query_help immediately
- User got help menu instead of answer
- Dynamic loop (which could answer) never got the chance

**After:**
- 0.72 < 0.85 → floor fires
- Routes to dynamic_query instead
- Dynamic loop with semantic layer gets first chance
- Can answer from deals_snapshot + config (stage probabilities)

**Principle:** Precomputed handlers = optimization for common questions, not prerequisite for answering.

---

## Tuning Guidance

**If floor keeps rejecting same handler at 0.78:**
- Fix: Improve handler description (make it more distinctive)
- NOT: Lower threshold

**Example:**
```
[ROUTING] confidence 0.78 < 0.80 for query_pipeline_movement — routing to dynamic
[ROUTING] confidence 0.79 < 0.80 for query_pipeline_movement — routing to dynamic
[ROUTING] confidence 0.77 < 0.80 for query_pipeline_movement — routing to dynamic
```

→ query_pipeline_movement description is too vague, overlaps with other handlers.
→ Make it more specific about what it handles.

---

## Risk: Budget Exhaustion

**More dynamic loop traffic = more iterations = more budget use.**

Watch for questions that:
- Used to get fast handler answer at 0.75
- Now take 3 iterations in dynamic loop
- Hit budget exhaustion

**If this happens:**
- Fix: Improve handler description so classifier is confident when it should be
- NOT: Lower confidence floor

**Mitigation:** Dynamic loop has semantic layer now (fiscal calendar, pipeline meanings, vocabulary). Should resolve most questions in 1-2 iterations.

---

## Test Plan

**Question:** "What do you forecast for the quarter?"

**Expected log:**
```
[INTENT] handler=query_help confidence=0.72
[ROUTING] confidence 0.72 < 0.85 for query_help — routing to dynamic instead
[LOOP] iteration 1/5
... dynamic loop execution ...
[LOOP] answered after N iterations
```

**Verify:**
1. Floor fires and logs both confidence and threshold
2. Names original handler (query_help)
3. Dynamic loop reaches real answer (not budget exhaustion)
4. Count iterations (should be 1-2 with semantic layer)

**Success criteria:**
- Dynamic loop answers forecast question in 1-2 iterations
- Confirms handlers are optimization, not requirement

---

## Deployment

Railway will auto-deploy from latest commit (ecf256d).

After deploy:
1. Re-ask "What do you forecast for the quarter?"
2. Check Railway logs for [ROUTING] line
3. Check if dynamic loop answers
4. Count iterations
5. Report findings

---

## Long-term

If floor works well:
- Confidence >= 0.80 → fast precomputed handler
- Confidence < 0.80 → dynamic loop gets first chance
- Semantic layer enables dynamic to answer most questions

If specific handlers keep getting rejected at high confidence (0.78+):
- Improve their descriptions
- Make them more distinctive from overlapping handlers
- Check classification logs to see what questions trigger false matches

Threshold tuning should be rare. Description improvement should be common.
