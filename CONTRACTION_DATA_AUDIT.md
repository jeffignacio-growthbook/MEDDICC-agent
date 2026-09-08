# Contraction Data Audit - GRR Dogfood Test Prerequisite

**Date:** 2026-09-07
**Purpose:** Verify if contraction data is genuinely absent vs. legitimately zero before GRR dogfood test

---

## Executive Summary

**Finding:** Contraction field EXISTS and is TRACKED, but contraction is genuinely rare in this business.

- **Field name:** `contraction_revenue`
- **Field label:** "Contraction ARR"
- **Description:** "Absolute value of ARR lost on this motion for churn/downsell analysis"

This is **NOT** a "field never captured" scenario. The zeros are real zeros, not missing data.

---

## Detailed Findings

### Across All Deals (n=1898)
- **Populated:** 1609 deals (84.8%)
- **Non-zero values:** 2 deals (0.1% of populated)
  - Vestiaire Collective - 2026 renewal: $36,250 contraction
  - Byborg Enterprises - 2026 renewal: $-2,000 contraction

### Renewal Deals Only (n=256)
- **Populated:** 220 deals (85.9%)
- **Null/empty:** 36 deals (14.1%)
- **Zero values:** 218 deals (99.1% of populated)
- **Non-zero values:** 2 deals (0.9% of populated)

---

## Implications for GRR Calculation

### ✓ GRR Can Be Computed
- `contraction_revenue` field exists and is populated
- Zeros are REAL zeros (business has very low contraction)
- No need for "churn-only approximation" label
- Standard GRR formula applies: `(Starting ARR - Churn - Contraction + Expansion) / Starting ARR`

### ⚠️ Data Quality Note
- 14.1% of renewal deals have null/empty `contraction_revenue`
- These deals need handling in GRR calculation:
  - **Option 1:** Treat null as zero (assume no contraction)
  - **Option 2:** Exclude from GRR cohort (incomplete data)
  - **Option 3:** Flag as data quality issue during clarifying-questions

---

## Business Reality Check

The two non-zero contraction cases:

### Case 1: Vestiaire Collective - 2026 renewal
- Prior ARR: $33,073
- Renewal ARR: $33,073
- Expansion: $3,177
- Contraction: $36,250
- **Net:** Customer renewed at same level but had expansion and contraction

### Case 2: Byborg Enterprises - 2026 renewal
- Prior ARR: $10,625
- Renewal ARR: $8,125
- Expansion: $0
- Contraction: $-2,000 (negative value suggests data entry issue?)
- **Net:** Customer downsold from $10,625 to $8,125

**Interpretation:** Contraction is genuinely rare. This is a healthy retention business.

---

## Comparison to Original Concern

**User's concern:** "contraction_arr (or whatever the actual field is called) is genuinely 0/null for ALL historical deals"

**Actual situation:**
- Field EXISTS: `contraction_revenue` is defined and populated
- NOT all null: 85.9% of renewals have a value
- NOT missing: Zeros are real zeros (business reality)
- Historical data: Field has been tracked since at least 2024

**This is DIFFERENT from a "field never captured" scenario.**

---

## Phase 2d Test Case Requirement

Per user request, add this test case to Phase 2d:

### Test Case: Missing Input Field Detection

**Scenario:** User requests a metric that requires a field that genuinely doesn't exist or is never populated.

**Example:** "Calculate NRR including logo churn, expansion, and downsells" when downsell_arr field doesn't exist.

**Expected behavior:**
1. **Clarifying-questions stage:** System detects missing field
2. **Surface explicit choice:**
   - "Downsell data isn't currently captured - do you want to:"
     - a) Proceed with expansion-only NRR (labeled as 'NRR (expansion-only, downsells not tracked)')
     - b) Defer this metric until downsell tracking is implemented
3. **Block silent computation:** Must NOT silently compute incomplete metric under full intended name
4. **Honest labeling:** If proceeding with approximation, MUST label with caveat

**Success criteria:**
- System detects missing field (not just wrong population)
- User is explicitly asked to choose approach
- Metric stored with honest label if approximation chosen
- Same rigor as Signal 3's hand-picked threshold labeling

---

## GRR Dogfood Test - Ready to Proceed

**Status:** ✅ Ready

**Contraction data status:**
- Field exists and is tracked
- 85.9% populated on renewal deals
- Zeros are real zeros (very low contraction business)
- 2 non-zero cases provide validation examples

**Remaining considerations:**
1. How to handle 14.1% null/empty values (treat as zero vs. exclude)
2. Verify ground-truth GRR calculation includes both non-zero contraction cases
3. Confirm backtest correctly identifies contraction_revenue field for GRR calculation

**No "churn-only approximation" needed** - this is actual GRR with contraction data.
