# Parameter Gap Classification Report

## 7 Parameters Missing from Classifier Schema

### 1. **limit** (query_arr, query_team_leaderboard)
- **Usage**: `limit = params.get("limit", 20)` / `limit = params.get("limit", 10)`
- **Context**: Controls result count - "show me top 10", "top 20 customers"
- **Default**: 20 (arr), 10 (leaderboard)
- **Classification**: **(a) USER-FACING** ✅
- **Recommendation**: Add to classifier schema
- **Example extraction**: "show me top 5" → limit=5

---

### 2. **sort_by** (query_team_leaderboard)
- **Usage**: `sort_by = params.get("sort_by", "pipeline")`
- **Context**: Sort dimension for leaderboard
- **Default**: "pipeline"
- **Classification**: **(a) USER-FACING** ✅
- **Recommendation**: Add to classifier schema
- **Example extraction**: "sort by ARR" → sort_by="arr"

---

### 3. **focus** (query_coaching_priorities)
- **Usage**: `focus = params.get("focus", "all")`
- **Context**: What to focus coaching on
- **Default**: "all"
- **Classification**: **(a) USER-FACING** ✅
- **Recommendation**: Add to classifier schema
- **Example extraction**: "focus on discovery" → focus="discovery"

---

### 4. **score** (query_rubric)
- **Usage**: `score = params.get("score")`
- **Context**: Used with component to query specific rubric entry (component + score → band)
- **Default**: None (optional)
- **Classification**: **(a) USER-FACING** ✅
- **Recommendation**: Add to classifier schema
- **Example extraction**: "what's a 7 for champion?" → component="champion", score=7

---

### 5. **stale_days** (query_stale_deals)
- **Usage**: `stale_days = params.get("stale_days", 21)`
- **Context**: Threshold for "stale" definition
- **Default**: 21 days
- **Classification**: **(a) USER-FACING** ✅
- **Recommendation**: Add to classifier schema
- **Example extraction**: "deals stale > 30 days" → stale_days=30

---

### 6. **component_threshold** (query_deal_health)
- **Usage**: `component_threshold = params.get("component_threshold", 4)`
- **Context**: Minimum score threshold for component health check
- **Default**: 4 (hardcoded constant)
- **Classification**: **(b) INTERNAL/CONFIG** ❌
- **Reasoning**: This is a system-defined threshold, not something users specify in questions. Users don't say "check deals with component threshold of 4" - the system applies its own health criteria.
- **Recommendation**: Add to KNOWN_INTERNAL_PARAMS whitelist
- **Risk if exposed**: Classifier might hallucinate threshold values

---

### 7. **score_threshold** (query_deal_health)
- **Usage**: `score_threshold = params.get("score_threshold", 5)`
- **Context**: Overall MEDDICC score threshold for health filtering
- **Default**: 5 (hardcoded constant)
- **Classification**: **(b) INTERNAL/CONFIG** ❌
- **Reasoning**: Same as component_threshold - system-defined health criteria, not user-specified. The handler applies canonical "at risk" definitions.
- **Recommendation**: Add to KNOWN_INTERNAL_PARAMS whitelist
- **Risk if exposed**: Classifier might hallucinate "5" when user asks about different thresholds

---

### 8. **pipeline_id** (query_pipeline_movement)
- **Usage**: `pipeline_id = params.get("pipeline_id")`
- **Context**: CRM pipeline identifier
- **Default**: None
- **Classification**: **NEEDS INVESTIGATION** ⚠️
- **Question**: Do users say "pipeline 123" or "show me pipeline X", OR is this resolved from HubSpot/CRM context?
- **Recommendation**: Check if this is:
  - User-facing: Users reference pipelines by ID → add to schema
  - Internal: Resolved from CRM metadata/deal context → add to whitelist

---

## Summary

| Parameter | Classification | Action |
|-----------|----------------|--------|
| limit | USER-FACING | Add to schema |
| sort_by | USER-FACING | Add to schema |
| focus | USER-FACING | Add to schema |
| score | USER-FACING | Add to schema |
| stale_days | USER-FACING | Add to schema |
| component_threshold | INTERNAL/CONFIG | Whitelist |
| score_threshold | INTERNAL/CONFIG | Whitelist |
| pipeline_id | NEEDS INVESTIGATION | TBD |

**5 params to add to schema**
**2 params to whitelist**
**1 param needs investigation**
