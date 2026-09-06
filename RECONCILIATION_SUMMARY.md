# Pipeline Reconciliation Summary — Sep 6, 2026

## Problem 1: Math Discrepancy Resolved

### Prior Audit (scripts/audit_pipeline_classification.py)
```
Total: 444 deals
- Incremental ONLY: 298 deals
- Renewal ONLY: 99 deals
- BOTH: 8 deals
- NEITHER: 39 deals
Total incremental: 306 deals (298 + 8)
```

### First Dollar-Split Implementation (INCORRECT)
```
Total: 444 deals
- Incremental ONLY: 172 deals
- Renewal ONLY: 100 deals
- BOTH: 8 deals
- NEITHER: 164 deals
Total incremental: 180 deals (172 + 8)
```

**126-deal discrepancy** - deals moved from "incremental" to "neither"

### Root Cause

The audit used `is_incremental_pipeline()` which returns `True` for:
1. **ANY deal in new business pipeline** (regardless of ARR values)
2. Deals in renewal pipeline with expansion_arr > 0 OR new_arr > 0

The first dollar-split implementation filtered to `incremental_value > 0`, which **incorrectly excluded** 126 deals in the new business pipeline that have NO ARR recorded.

These 126 deals are DATA QUALITY GAPS - they're in the pipeline but have $0 incremental ARR.

### Correct Implementation (scripts/reconcile_pipeline_logic.py)

**DEAL COUNT:** 306 (using is_incremental_pipeline)
**DOLLAR TOTAL:** $18,565,953 (sum of expansion_arr + new_arr across those 306 deals)
**DATA QUALITY GAP:** 126 deals in pipeline with $0 incremental ARR

```
Total: 444 deals
- Incremental (with value): 180 deals → $18.6M
- Incremental (zero ARR): 126 deals → $0 (DATA QUALITY GAP)
- Renewal ONLY: 99 deals → separate reporting
- BOTH: 8 deals → split at dollar level
- NEITHER: 39 deals → uncategorized gap
```

### Reconciliation Proof

```
Incremental deals by audit: 306 (298 + 8)
Incremental deals by corrected logic: 306 (180 with value + 126 with $0)
✅ MATCHES

Dollar total: $18,565,953
- Includes 8 BOTH deals' expansion_arr only (not full deal_value)
- Excludes 126 zero-ARR deals from dollar sum
- Excludes renewal base ($5.3M from 108 deals)
✅ CORRECT
```

## Problem 2: Coverage Ratio / Proactive Framing Implemented

### What Was Missing

Jeff's explicit instruction from prior turn:
1. Pull current-quarter targets from rep_targets table
2. Compute coverage ratio (pipeline / target)
3. Proactively offer next-quarter and renewal views
4. Frame like a VP of RevOps, not a query tool

This was **completely dropped** in the first implementation.

### Now Implemented

**query_pipeline now:**
1. Pulls quarterly target from rep_targets (company-level, total_arr metric)
2. Computes coverage_ratio = total_pipeline / quarterly_target
3. Returns coverage_ratio, quarterly_target, current_quarter in payload
4. _synthesis_note instructs: "Lead with coverage ratio if available. Offer to show next-quarter pipeline or upcoming renewals."

**Example response structure:**
```
Current Pipeline (Incremental ARR): $18.6M across 306 deals
Coverage: 18.6x quarterly target ($1M)

[Stage breakdown, top deals]

Note: 126 deals in pipeline have $0 incremental ARR recorded.

Want to see Q4 pipeline or upcoming renewals?
```

## Final Verified Value (q011)

```yaml
total_arr: 18565953
deal_count: 306
zero_arr_deals: 126
uncategorized_deals: 39
note: "Deal count: 306 (using is_incremental_pipeline). Dollar total: $18.6M (sum of expansion_arr + new_arr per deal, dollar-level split). Data quality: 126 deals in pipeline with $0 incremental ARR recorded."
```

## Files Changed

1. **api/handlers.py** - query_pipeline corrected to use is_incremental_pipeline() for deal count, added coverage ratio, proactive framing
2. **config/canonical_questions.yaml** - q011 verified value updated to 306 deals (not 180)
3. **scripts/reconcile_pipeline_logic.py** - reconciliation script proving 306 = audit logic
4. **RECONCILIATION_SUMMARY.md** - this document

## Ready for Testing

Both issues resolved:
- ✅ Math reconciles with audit (306 deals, $18.6M)
- ✅ Coverage ratio and proactive framing implemented

Next: Deploy and test in Slack 5-10 times.
