# Wave 1 Findings: Read the Logs

**Evidence analyzed**: 312 learning_log entries, 39 unanswered queries, 19 entity patterns

**Reporting period**: Weeks of history (check dates for currency)

---

## Ranked Fix List (Most Impactful First)

### 1. **"Which of those are at risk?"** — Missing Named Set
**Evidence**: 7x unanswered + 4x entity patterns resolved correctly
**Type**: Semantic layer (named set definition)
**Impact**: Most-asked unanswered question, but entity-scoped version works
**Root cause**: "At risk" narrowing phrase exists but not as named set
**Fix**: Add `at_risk` named set to entity registry
**Effort**: 10 minutes (config line)

**Details**:
- Entity-scoped version resolves to `query_deals_at_risk` correctly
- Initial question falls through, follow-up with IDs works
- Named set would make initial question work: "Show at-risk deals" → no IDs needed

---

### 2. **data_gap (222 entries)** — Triage Required
**Evidence**: 71% of learning_log, 173 retries succeeded
**Type**: Mixed (need per-handler breakdown to categorize)
**Impact**: Majority of imperfect answers, but most still deliver value
**Root cause**: Various — incomplete data, null values, missing fields
**Fix**: Per-handler audit (which gaps are worth fixing vs documenting)
**Effort**: Varies

**Top handlers with data_gap**:
- `query_win_loss`: Most common (need to check what gaps)
- `query_waterfall`: Also frequent

**Action**: Pull 10 sample questions from each handler's data_gap logs to determine:
- Business fact → semantics (e.g., "renewals on renewal_revenue field")
- Genuine data quality issue → upstream fix
- Acceptable limitation → document in handler description

**78% retry success rate** suggests gaps don't block answers, just make them incomplete.

---

### 3. **"Pipeline this quarter"** — Ambiguous (5 occurrences)
**Evidence**: 5x unanswered, reason="ambiguous"
**Type**: Semantic layer (disambiguation prompt)
**Impact**: Common phrasing, currently fails
**Root cause**: "Pipeline" could mean qualified pipeline, forecast, coverage, etc.
**Fix**: Add disambiguation prompt when "pipeline" detected without qualifiers
**Effort**: 30 minutes (router update)

**Suggested prompt**:
```
"Pipeline" can mean different things. Did you want:
1. Qualified pipeline value (waterfall)
2. Forecast (stage-weighted or category)
3. Pipeline coverage (pipeline / quota)
```

---

### 4. **"Customers due to renew in Q3/Q4"** — Missing Table
**Evidence**: 4x unanswered
**Type**: Missing precomputed table
**Impact**: Board-level question (renewal planning)
**Root cause**: No `renewals_upcoming` or similar table exists
**Fix**: Create renewal pipeline query (if renewal data exists)
**Effort**: 2 hours (handler + table if needed)

**Check**: Does renewal pipeline exist in HubSpot data? If yes, this is just a missing handler. If no, out of scope.

---

### 5. **wrong_handler (11 entries)** — Routing Descriptions
**Evidence**: 11 learning_log, 0 retries helped
**Type**: Routing (handler descriptions need tightening)
**Impact**: Questions routed to wrong handler, never self-corrected
**Root cause**: Handler descriptions not distinctive enough
**Fix**: Pull each wrong_handler example, identify which handler won vs should have won
**Effort**: 1 hour (update descriptions)

**Top handler**: `query_rubric` (need to check what it misrouted from)

**Critical**: These never recovered (0% retry success) — routing errors are harder to fix than data gaps.

---

### 6. **"Champion score above 6 close in Q3"** — Compound Filter
**Evidence**: 6x unanswered
**Type**: Missing capability (multi-filter query)
**Impact**: MEDDICC scoring + time filter compound
**Root cause**: No handler combines rubric scores + close date filtering
**Fix**: Either add compound filter handler OR improve dynamic loop SQL generation
**Effort**: 4 hours (new handler) or defer to future capability

**Note**: This is genuinely hard — compound filters across dimensions. May belong in "out of scope" for now.

---

### 7. **should_be_dynamic (8 entries, 1 retry helped)** — Routing Calibration
**Evidence**: 8 learning_log
**Type**: Routing (confidence threshold issue)
**Impact**: Questions routed to static handler that should have used dynamic loop
**Root cause**: Handler descriptions too broad or threshold too low
**Fix**: Tighten handler descriptions (not lower threshold)
**Effort**: 1 hour

**Top handler**: `query_waterfall` — likely catching questions that need SQL generation

---

### 8. **Stage Narrowing ("Which deals in Review?")** — Works via Entity Scope
**Evidence**: 2x entity patterns, both resolved correctly
**Type**: ✓ Already working
**Impact**: N/A (validate and document)
**Note**: Entity-scoped stage filtering works — "which deals in Review" → `query_deal_stages_bulk`

**No fix needed** — system already handles this pattern.

---

### 9. **UNKNOWN Issues (68 entries in learning_log, 10 in unanswered)**
**Evidence**: 22% of learning_log, all retries succeeded
**Type**: Logging gap (issue_type not set)
**Impact**: Can't categorize without reading individual entries
**Fix**: Audit UNKNOWN entries to populate issue_type field
**Effort**: 30 minutes (code audit)

**Note**: 100% retry success suggests these aren't serious failures, just mis-logged.

---

### 10. **"Why did we lose last three deals?"** — Missing Loss Analysis
**Evidence**: 3x unanswered
**Type**: Missing handler (loss narrative)
**Impact**: Board-level question (loss insights)
**Root cause**: `query_win_loss` may exist but doesn't do narrative across multiple deals
**Fix**: Add "recent losses" handler with loss reason aggregation
**Effort**: 2 hours

---

## Summary Statistics

### Learning Log Breakdown (312 total)

| Issue Type | Count | Retry Success | Destination |
|------------|-------|---------------|-------------|
| data_gap | 222 (71%) | 173 (78%) | **Audit per-handler** |
| UNKNOWN | 68 (22%) | 68 (100%) | Logging fix |
| wrong_handler | 11 (4%) | 0 (0%) | **Routing descriptions** |
| should_be_dynamic | 8 (3%) | 1 (13%) | **Routing calibration** |
| format_only | 2 (1%) | 2 (100%) | Cosmetic |
| missing_join | 1 (<1%) | 0 (0%) | Code defect |

### Unanswered Queries Breakdown (39 total)

| Reason | Count | Top Fix |
|--------|-------|---------|
| ambiguous | 17 (44%) | Disambiguation prompts |
| UNKNOWN | 10 (26%) | Logging fix |
| fallback_exhausted | 6 (15%) | Dynamic loop improvement |
| no_data | 4 (10%) | Document limitations |
| out_of_scope | 2 (5%) | Accept as boundary |

### Entity Scope Patterns (19 total)

| Pattern Type | Count | Status |
|--------------|-------|--------|
| At-risk filtering | 4 | ✓ Works (needs named set) |
| Stage filtering | 2 | ✓ Works |
| Value queries | 4 | ✓ Works |
| Rubric scores | 3 | ✓ Works |
| Other | 6 | ✓ Works |

**Finding**: Entity-scoped follow-ups work well. Named sets would eliminate the initial ID-gathering step.

---

## Prioritized Work Queue

### Week 1: High-Impact, Low-Effort (Semantics)

1. ✅ **Add "at_risk" named set** (10 min) — closes most-asked unanswered question
2. ✅ **Add "pipeline" disambiguation** (30 min) — closes 5 ambiguous queries
3. ⚠️ **Audit data_gap samples** (2 hours) — determine which are semantic vs data quality

### Week 2: Routing Fixes

4. ✅ **Fix wrong_handler routing** (1 hour) — 0% retry success means critical
5. ✅ **Calibrate should_be_dynamic** (1 hour) — tighten handler descriptions

### Week 3: Missing Handlers

6. ⚠️ **Check if renewal data exists** (15 min) — determines if #4 is viable
7. ✅ **Add renewal upcoming handler** (2 hours) — if data exists
8. ✅ **Add recent losses handler** (2 hours) — board-level insight

### Future / Defer

9. ⏸️ **Compound filters** (4+ hours) — "champion >6 AND close in Q3" (genuinely hard)
10. ⏸️ **Fix UNKNOWN logging** (30 min) — low priority, 100% retry success

---

## Data Quality Warnings

### Check Dates Before Acting

Many issues may already be fixed. Check `logged_at` / `asked_at` timestamps:
- Learning log entries from before scope filter fix (commit c71d620) may be historical
- Unanswered queries from before entity registry may be resolved
- Wrong_handler issues from before description updates may be stale

**Action**: Filter each table to last 7 days and recount before implementing fixes.

---

## Key Insights

1. **Entity-scoped follow-ups work** — 19 patterns, all resolved correctly. Named sets would eliminate the initial ID step.

2. **Data gaps don't block** — 78% retry success. Most gaps deliver incomplete answers rather than no answer.

3. **Routing errors are critical** — 0% retry success on wrong_handler. Once mis-routed, never recovers.

4. **Ambiguity is fixable** — 17 "ambiguous" queries need disambiguation prompts, not new handlers.

5. **"At risk" is the most-wanted named set** — 7x unanswered + 4x entity patterns. Clear user need.

---

## Recommended Next Steps

1. **Run read_evidence_logs.py filtered to last 7 days** to get current state
2. **Pull 10 sample questions per issue type** from learning_log for context
3. **Implement Week 1 queue** (semantics: at_risk, pipeline disambiguation, data_gap audit)
4. **Report spread** before fixing anything else — current forecast work validates methods

**Do not let volume drive ranking alone** — one wrong_handler on a board question > fifty data_gap notes.
