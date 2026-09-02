# "At Risk" — Pending Definition

## Status: BLOCKED on Ryan's Definition

**Evidence**: 7x most-asked unanswered question in Wave 1 analysis

**Problem**: "At risk" is Ryan's term and means something specific to him. We have a handler but no authoritative definition of what it should check.

**Blocker**: Cannot finalize implementation without knowing what "at risk" means.

---

## What Exists Now

### Handler (Placeholder Logic)

**File**: `api/handlers.py` → `query_deals_at_risk()`

**Current behavior**: Flags deals where any MEDDICC component required at the current stage is below threshold (stage-aware band checking).

**Problem**: This is placeholder logic, not a semantic fact. It might match what Ryan means, or it might not.

### Config (Pending)

**File**: `config/field_semantics.yaml` → `deal_states.at_risk`

**Current state**: Marked "PENDING DEFINITION FROM RYAN" with candidate criteria listed but not implemented.

---

## Why This Matters

This is the **first user-facing definition in the semantic layer**.

If the definition doesn't match what Ryan means by "at risk," every answer using it will be subtly wrong in a way nobody notices until it breaks trust.

Examples of wrong answers:
- User: "Show me at-risk deals"
- Bot: [Lists deals with MEDDICC gaps]
- Reality: Ryan considers "at risk" to mean "stalled for 30 days" (not MEDDICC scores)
- Result: Bot is answering a different question than asked

---

## Candidate Criteria (Unverified)

Common sales risk indicators:
1. No champion identified
2. Overall MEDDICC score below threshold (what threshold?)
3. No activity (calls/emails/meetings) in 30+ days
4. Stalled in current stage for X days
5. Close date slipped N times
6. Something else specific to how Ryan thinks about risk

Can be one condition or a combination. Can be stage-specific.

---

## Next Steps

### 1. Get Ryan's Definition

See `FOR_RYAN_TWO_QUESTIONS.md` — bundles this with deal-size bias finding.

Ask: "What makes a deal 'at risk' to you?"

His answer becomes the semantic fact in `field_semantics.yaml`.

### 2. Implement Definition

Once we have Ryan's answer:

**If activity-based** (no activity in X days):
```sql
ALTER TABLE deals ADD COLUMN last_activity_date DATE;
```
Update ETL to populate from HubSpot engagements.

**If slippage-based** (close date slipped N times):
```sql
ALTER TABLE deals ADD COLUMN close_date_slips INTEGER DEFAULT 0;
```
Track in property history.

**If MEDDICC threshold-based** (e.g., overall < 40):
No schema change needed, just update handler logic.

**If champion-based** (no champion identified):
Check `champion_score` or add explicit `has_champion` boolean.

### 3. Update Config

Add to `config/field_semantics.yaml`:
```yaml
deal_states:
  at_risk:
    label: "At Risk"
    description: >
      [Ryan's definition verbatim]
    criteria:
      - [Condition 1]
      - [Condition 2]
    implementation: query_deals_at_risk
    verified_by: Ryan
    verified_date: 2026-09-XX
```

### 4. Update Handler

Modify `api/handlers.py` → `query_deals_at_risk()` to implement Ryan's exact criteria.

### 5. Test

```
User: Show me at-risk deals
Bot: [Lists deals matching Ryan's definition]

User: Show me pipeline
Bot: [Lists all deals]
User: Which of those are at risk?
Bot: [Filters to at-risk subset]
```

---

## Why We Can't Guess

Initial implementation chose "overall MEDDICC score < 40" as the threshold. That was my number, not Ryan's.

"At risk" is his vocabulary from years of sales leadership. It might mean:
- "No champion and stalled" (compound condition)
- "In Review for 2+ weeks" (stage-specific timing)
- "Competitor mentioned and no POC scheduled" (competitive threat)
- Something else entirely

**We need his definition, not a best guess.**

---

## Timeline

- **Now**: Ask Ryan (bundled with deal-size bias)
- **Next**: Implement as semantic fact in config
- **Then**: Update handler to match definition
- **Finally**: Test with real questions

Until Ryan defines it, the handler returns placeholder results (stage-aware MEDDICC gaps).
