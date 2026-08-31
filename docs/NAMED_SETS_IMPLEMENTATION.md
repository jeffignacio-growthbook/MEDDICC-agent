# Named Entity Sets — Implementation Plan

**Problem:** Entity-scope routing passes ALL prior deal_ids, even when question narrows to a subset ("the 6 that left Negotiating"). Creates noise, causes assessor failures.

**Solution:** Store subsets with their meaning, so narrowing follow-ups resolve to the correct IDs.

---

## What We Already Have

Pipeline movement returns named ID arrays in `by_stage`:

```json
{
  "by_stage": [
    {
      "stage": "Negotiating",
      "exited": 6,
      "exited_ids": [123, 456, 789, 101, 102, 103],
      "entered_from_other_stage": 2,
      "entered_from_other_stage_ids": [104, 105],
      "new_to_pipeline": 0,
      "new_to_pipeline_ids": []
    },
    ...
  ]
}
```

These are the **named sets** we need. The 6 deals that left Negotiating are already identified.

---

## Implementation

### 1. Extract Named Sets (api/db.py)

Extend `extract_entity_context()` to detect named ID arrays:

```python
def extract_entity_context(tool_results: dict, sb=None) -> dict:
    # ... existing extraction ...

    # NEW: Extract named sets from by_stage arrays
    named_sets = {}
    by_stage = tool_results.get("by_stage", [])

    for stage_entry in by_stage:
        stage_name = stage_entry.get("stage", "")

        # Extract each named ID array
        for key in ["exited_ids", "entered_from_other_stage_ids", "new_to_pipeline_ids"]:
            ids = stage_entry.get(key, [])
            if ids:
                # Store with semantic key: "exited_Negotiating", "entered_Discovery"
                action = key.replace("_ids", "")  # "exited", "entered_from_other_stage", etc.
                set_name = f"{action}_{stage_name}"
                named_sets[set_name] = ids

    # Return extended entity context
    return {
        "deal_ids": [...],  # all IDs, as before
        "company_names": [...],
        "named_sets": named_sets  # NEW
    }
```

**Example output:**
```json
{
  "deal_ids": [101, 102, 103, 104, ..., 120],  // all 20
  "company_names": ["Acme Corp", ...],
  "named_sets": {
    "exited_Negotiating": [101, 102, 103, 104, 105, 106],  // the 6
    "entered_Discovery": [107, 108],
    "new_to_pipeline_Qualification": [109, 110]
  }
}
```

### 2. Resolve Named Sets (api/router.py)

When routing entity-scoped questions, check if question refers to a named set:

```python
async def route_entity_scoped_question(question: str, prior_entities: dict, sb, client):
    deal_ids = prior_entities.get("deal_ids", [])
    named_sets = prior_entities.get("named_sets", {})

    # NEW: Check if question refers to a named set
    resolved_ids = resolve_named_set(question, named_sets) or deal_ids

    if resolved_ids != deal_ids:
        logger.info(f"[ENTITY_SCOPE] resolved named set: {len(resolved_ids)} of {len(deal_ids)} deals")

    # Execute handler with resolved IDs (6, not 20)
    result = await handler_fn(
        {"deal_ids": resolved_ids, "time_window": default_tw}, sb)

    return (result, handler_name)
```

### 3. Named Set Resolver

Simple keyword matching to detect named set references:

```python
def resolve_named_set(question: str, named_sets: dict) -> list | None:
    """
    Detect if question refers to a named set.

    Examples:
    - "the 6 that left Negotiating" → named_sets["exited_Negotiating"]
    - "the ones that entered Discovery" → named_sets["entered_Discovery"]
    - "the new deals in Qualification" → named_sets["new_to_pipeline_Qualification"]
    """
    q_lower = question.lower()

    # Pattern: "left/exited <stage>"
    if any(word in q_lower for word in ["left", "exited", "departed"]):
        for set_name, ids in named_sets.items():
            if set_name.startswith("exited_"):
                stage_name = set_name.replace("exited_", "").lower()
                if stage_name in q_lower:
                    return ids

    # Pattern: "entered/moved to <stage>"
    if any(word in q_lower for word in ["entered", "moved to", "went to"]):
        for set_name, ids in named_sets.items():
            if set_name.startswith("entered_from_other_stage_"):
                stage_name = set_name.replace("entered_from_other_stage_", "").lower()
                if stage_name in q_lower:
                    return ids

    # Pattern: "new deals" or "new to pipeline"
    if any(phrase in q_lower for phrase in ["new deal", "new to pipeline", "just created"]):
        for set_name, ids in named_sets.items():
            if set_name.startswith("new_to_pipeline_"):
                return ids

    return None  # No named set matched, use all deal_ids
```

---

## Example Flow

**Previous answer:** Pipeline movement showing 20 deals total, 6 exited Negotiating.

**Entity extraction saves:**
```json
{
  "deal_ids": [1, 2, 3, ..., 20],
  "named_sets": {
    "exited_Negotiating": [1, 2, 3, 4, 5, 6]
  }
}
```

**Follow-up question:** "Where did the 6 deals that left Negotiating go?"

**Routing:**
1. Detects pronoun "the" → entity-scope
2. Calls `resolve_named_set("Where did the 6 deals that left Negotiating go?", named_sets)`
3. Matches "left" + "Negotiating" → returns `[1, 2, 3, 4, 5, 6]`
4. Passes 6 IDs to `query_deal_stages_bulk`, not 20
5. Handler returns 6 rows
6. Synthesis has clean data
7. Assessor scores high
8. User gets answer

---

## Backward Compatibility

**Existing threads:** Old entity_context entries don't have `named_sets`. Code handles this:

```python
named_sets = prior_entities.get("named_sets", {})
resolved_ids = resolve_named_set(question, named_sets) or deal_ids
# Falls back to all deal_ids if no named_sets or no match
```

**New threads:** Automatically get named sets when pipeline movement runs.

---

## Testing

### Unit Test: Named Set Extraction

```python
def test_extract_named_sets_from_by_stage():
    tool_results = {
        "by_stage": [
            {
                "stage": "Negotiating",
                "exited_ids": [1, 2, 3, 4, 5, 6],
                "entered_from_other_stage_ids": [7, 8]
            }
        ]
    }

    entities = extract_entity_context(tool_results)

    assert "named_sets" in entities
    assert entities["named_sets"]["exited_Negotiating"] == [1, 2, 3, 4, 5, 6]
    assert entities["named_sets"]["entered_from_other_stage_Negotiating"] == [7, 8]
```

### Unit Test: Named Set Resolution

```python
def test_resolve_named_set_exited():
    named_sets = {"exited_Negotiating": [1, 2, 3, 4, 5, 6]}

    result = resolve_named_set("Where did the 6 that left Negotiating go?", named_sets)
    assert result == [1, 2, 3, 4, 5, 6]

    # Different phrasing
    result = resolve_named_set("What about the ones that exited Negotiating?", named_sets)
    assert result == [1, 2, 3, 4, 5, 6]
```

### Integration Test: End-to-End

1. Ask: "How has pipeline moved this week?"
2. Check entity_context has named_sets with exited_Negotiating
3. Ask: "Where did those 6 go?"
4. Verify handler receives 6 IDs, not 20
5. Verify answer is clean and assessor scores > 0.70

---

## File Changes

1. **api/db.py** — `extract_entity_context()`
   - Add named set extraction from by_stage arrays
   - Return `named_sets` in entity context

2. **api/router.py** — `route_entity_scoped_question()`
   - Add `resolve_named_set()` function
   - Call it before passing deal_ids to handler

3. **tests/** — Unit and integration tests

---

## Effort Estimate

- Extract named sets: ~30 lines in `extract_entity_context`
- Resolve named sets: ~40 lines for `resolve_named_set` function
- Integrate into routing: ~5 lines in `route_entity_scoped_question`
- Tests: ~50 lines

**Total:** ~125 lines, 1-2 hours to implement and test.

---

## Future Extensions

Once this works for pipeline movement, extend to other handlers:

- **Win/loss analysis:** `closed_won_ids`, `closed_lost_ids` by quarter
- **At-risk deals:** `slipping_ids`, `stalled_ids`, `no_activity_ids`
- **SDR metrics:** `missed_quota_user_ids`, `top_performer_ids`

Any handler that produces distinguishable groups can store them as named sets.

---

## Decision

Proceed with implementation? This closes the gap for narrowing follow-ups and makes entity-scope routing precise instead of noisy.
