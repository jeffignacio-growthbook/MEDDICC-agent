# Pipeline Definition - Clarification Needed from Jeff

## Context

Wave 4 q011 fix revealed three classification edge cases requiring business definition decisions. Current implementation makes assumptions that need validation.

---

## Question 1: Renewal Deals WITH Expansion (8 deals / $2.6M)

**Situation:** Some renewal-stage deals have BOTH expansion_arr AND renewal_revenue populated.

**Example:** Anthropic renewal
- expansion_arr: $500,000 (upsell/expansion)
- renewal_revenue: $810,000 (base renewal)
- deal_value: $1,310,000 (total)

**Current behavior:** Entire $1.31M counts toward incremental pipeline ($20.6M total).

**Proposed interpretation:**
- **Dollar-level split, not deal-level bucketing**
- expansion_arr ($500K) → incremental pipeline
- renewal_revenue ($810K) → renewal ARR (reported separately)
- Same deal appears in BOTH reports (not double-counting - measuring different components)

**Alternative interpretations:**
- (B) Exclude renewal deals entirely from pipeline, even if they have expansion
- (C) Count entire deal_value toward one bucket or the other, not split

**Question for Jeff:**
**Should renewal deals with expansion be split at the DOLLAR level (expansion_arr → pipeline, renewal_revenue → renewal ARR), or classified at the DEAL level (entire deal in one bucket)?**

**8 deals affected:**
1. Anthropic: $500K expansion + $810K renewal = $1.31M
2. Dropbox: $100K expansion + $325K renewal = $425K
3. Square: $200K expansion + $122K renewal = $322K
4. Khan Academy: $40K expansion + $136K renewal = $176K
5. Mistral: $50K expansion + $85K renewal = $135K
6. Breeze Airways: $105K expansion + $23K renewal = $128K
7. Wellhub: $9K expansion + $55K renewal = $63K
8. Boylesports: $20K expansion + $38K renewal = $58K

**Impact on totals:**
- If DOLLAR-LEVEL SPLIT (proposed):
  - Incremental pipeline: $20.6M (includes $923K expansion from these 8 deals)
  - Renewal ARR: $6.2M (includes $1.7M renewal base from these 8 deals)
- If DEAL-LEVEL (entire deal to one bucket):
  - Depends on rule, but would shift $2.6M between buckets

---

## Question 2: Time Period Interpretation ("this quarter")

**Situation:** User asks "What is our pipeline this quarter?" but query_pipeline has NO time filtering.

**Current behavior:**
- Returns ALL 306 active incremental deals (no time scope)
- Response says "This Quarter's Pipeline" (implies time scope that doesn't exist)

**Proposed interpretation:**
- **Pipeline = timeless current state** (like asking "what's the current temperature?")
- Fix response to say: "Current Pipeline (Incremental ARR)" NOT "This Quarter's Pipeline"
- If user wants time-bound view ("what closes this quarter"), route to different handler

**Alternative interpretation:**
- Implement time filtering: deals with close_date in stated quarter
- But contradicts verified value: "regardless of close date"

**Question for Jeff:**
**Should "pipeline" be timeless current state (no close_date filtering), or should it filter to deals closing in the stated time period?**

**Impact:**
- If TIMELESS (proposed): Current behavior correct, just fix messaging
- If TIME-FILTERED: Significant change, would reduce from 306 to ~161 deals (Q3 closers only)

---

## Question 3: Uncategorized Deals (39 deals / $733K with NULL ARR)

**Situation:** 39 active deals have ALL ARR fields NULL or 0.

**Examples:**
- shiftkey: deal_value=$129,750, but expansion_arr=NULL, new_arr=NULL, renewal_revenue=NULL
- Legend: deal_value=$150,000, but all ARR fields NULL
- Many others: deal_value=$0, all ARR fields NULL

**Current behavior:** Excluded from pipeline totals (not incremental, not renewal).

**Proposed interpretation:**
- **Surface explicitly in response** (don't silently drop)
- Example: "Note: 39 deals ($733K) excluded - missing ARR classification"
- Similar to how current response flags "$0 ARR recorded" for specific reps

**Alternative interpretation:**
- (B) Silently exclude them (current)
- (C) Include their deal_value in totals (treat as incremental by default)

**Question for Jeff:**
**How should deals with missing ARR fields be reported? Explicitly surface as uncategorized, or silently exclude?**

**Impact:**
- If SURFACE (proposed): Response adds data quality callout
- If SILENT (current): User doesn't know 39 deals are excluded
- If INCLUDE: Inflates totals with potentially wrong data

---

## Recommended Next Steps

1. **Get Jeff's written confirmation** on all three definitions
2. **Document decisions** in config/field_semantics.yaml (single source of truth)
3. **Implement confirmed logic** in handlers and helpers
4. **Update q011 verified value** if definitions change totals
5. **Re-test in production** with correct business definitions

---

## Why This Matters

These definitional choices affect:
- What "pipeline" means in every report and dashboard
- Whether renewal deals with expansion count toward quota attainment
- How reps forecast their numbers
- Whether data quality gaps are visible or hidden

Getting them wrong means hours of debugging later (as evidenced by this entire Wave 4 q011 session).

**Waiting for Jeff's confirmation before proceeding with implementation.**
