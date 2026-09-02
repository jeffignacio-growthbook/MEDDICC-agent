# Wave 1 Findings — Date-Filtered (Current State)

**Date filter applied**: 2026-08-31 (separates historical from current issues)

**Critical finding**: Most issues are historical. Routing fixes already deployed solved the major problems.

---

## Current State (After 2026-08-31)

### Learning Log: 16 entries (was 312 total)

| Issue Type | Count | Retry Success | Status |
|------------|-------|---------------|--------|
| data_gap | 12 (75%) | 10 (83%) | Ongoing — most recover on retry |
| UNKNOWN | 3 (19%) | 3 (100%) | Logging issue only |
| should_be_dynamic | 1 (6%) | 0 (0%) | Single occurrence |
| **wrong_handler** | **0 (0%)** | **N/A** | **SOLVED** |

**wrong_handler went from 11 entries (0% retry success) to ZERO.** The routing fixes already deployed closed that problem.

### Unanswered Queries: 2 entries (was 39 total)

| Reason | Count | Top Questions |
|--------|-------|---------------|
| fallback_exhausted | 1 | "historical win rates by stage" |
| no_data | 1 | "customers due to renew in Q3/Q4" |

17 "ambiguous" queries from before 2026-08-31 are gone. Disambiguation prompts already working.

---

## Historical Issues (Before 2026-08-31) — 296 entries

### Already Fixed

**wrong_handler (11 entries, 0% retry success)**:
- All 11 entries before 2026-08-31
- 9 of 11 routed to `query_rubric` incorrectly
- **Current count: 0** — routing descriptions fixed

**ambiguous (17 unanswered queries)**:
- "Pipeline this quarter" → now disambiguates
- All historical, none current

**should_be_dynamic (7 entries)**:
- Down to 1 current entry
- Confidence threshold calibration working

### Still Occurring (but recovering)

**data_gap (222 total, 12 current)**:
- 78% historical retry success
- 83% current retry success (improving)
- Most gaps don't block answers, just make them incomplete
- Audit per-handler to determine which are semantic vs data quality

---

## Ranked Current Work (Based on Date-Filtered Evidence)

### Priority 1: "At Risk" Definition ⚠️ BLOCKED

**Evidence**: 7x most-asked unanswered question (historical)

**Status**: BLOCKED on Ryan's definition

**Issue**: "At risk" is Ryan's term. We have a handler but no semantic fact defining what it checks. Cannot finalize without his definition.

**See**: `FOR_RYAN_TWO_QUESTIONS.md`

### Priority 2: Data Gap Audit (12 current entries, 83% retry success)

**Current top handlers**:
- Need to check which handlers are producing data_gap entries now
- Pull sample questions from current entries only
- Categorize: semantic fact vs data quality vs acceptable limitation

**Action**:
```sql
SELECT handler_used, COUNT(*),
       COUNT(*) FILTER (WHERE retry_succeeded) AS recovered
FROM learning_log
WHERE logged_at >= '2026-08-31' AND issue_type = 'data_gap'
GROUP BY 1 ORDER BY 2 DESC;
```

### Priority 3: Renewal Pipeline Query (1 unanswered)

**Question**: "Get a list of all customers due to renew in Q3 and then Q4"

**Type**: Missing handler (if renewal data exists in HubSpot)

**Check**: Does renewal pipeline data exist?
```sql
SELECT COUNT(*), SUM(renewal_revenue), SUM(deal_value)
FROM deals
WHERE pipeline_id = '866608541'  -- renewal pipeline
  AND deal_status = 'active';
```

If yes → create `query_upcoming_renewals` handler (2 hours)
If no → out of scope, document limitation

### Priority 4: Historical Win Rates by Stage (1 unanswered)

**Question**: "Would you be able to calculate historical win rates by stage?"

**Type**: Analysis query (possibly dynamic loop candidate)

**Check**: Can this be answered with existing data?
```sql
SELECT stage,
       COUNT(*) FILTER (WHERE deal_status = 'won') AS won,
       COUNT(*) FILTER (WHERE deal_status IN ('won','lost')) AS total,
       ROUND(100.0 * won / NULLIF(total, 0), 1) AS win_rate_pct
FROM deals
GROUP BY 1;
```

If yes → add to waterfall analysis or create dedicated handler
If no → explain what data is missing

---

## What Changed (Historical → Current)

| Issue | Historical | Current | Status |
|-------|-----------|---------|--------|
| wrong_handler | 11 (0% retry) | 0 | ✅ SOLVED |
| ambiguous queries | 17 | 0 | ✅ SOLVED |
| should_be_dynamic | 7 | 1 | ✅ Mostly solved |
| data_gap | 210 | 12 | 🔄 Ongoing (83% recover) |
| Total learning_log | 296 | 16 | ✅ 95% reduction |
| Total unanswered | 37 | 2 | ✅ 95% reduction |

---

## Key Insights

### 1. Routing fixes worked

Zero current wrong_handler entries. The confidence floor (0.80) and handler description updates solved the routing problem.

### 2. Most issues were one-time

95% reduction in both learning_log entries and unanswered queries after routing fixes deployed.

### 3. Data gaps recover

83% of current data_gap entries succeed on retry. These are incomplete answers, not failures.

### 4. Volume ≠ priority

312 total learning_log entries looked overwhelming. Date-filtering shows only 16 current issues, and 12 of those recover on retry.

### 5. "At risk" remains top user need

7x historical unanswered, but the need is real — users are asking for this. Blocked on definition, not capability.

---

## Next Steps

1. **Get Ryan's definitions** (FOR_RYAN_TWO_QUESTIONS.md)
   - What does "at risk" mean?
   - Why do larger deals lose?

2. **Audit current data_gap entries** (12 entries)
   - Which handlers?
   - What questions?
   - Semantic fact vs data quality?

3. **Check renewal data availability**
   - Can we answer "upcoming renewals" questions?
   - If yes, create handler

4. **Historical win rate analysis**
   - Can we answer with existing data?
   - If yes, add to waterfall or create dedicated handler

5. **Monitor trend**
   - Track learning_log by week
   - Confirm improvements hold
   - New issues surface quickly (not buried in historical noise)

---

## Recommendation

**Do not build new handlers yet.** Get Ryan's "at risk" definition first.

That's the #1 user need, and it sets the pattern for how semantic facts get defined going forward. If the first one is done right (definition → config → implementation → test), future semantic facts follow the same process.

Data gap audit comes second. 83% retry success suggests most are noise, but the 17% that don't recover might point to real semantic gaps.
