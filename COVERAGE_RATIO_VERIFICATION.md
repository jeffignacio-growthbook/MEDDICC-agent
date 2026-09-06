# Coverage Ratio Verification — Sep 6, 2026

## Initial Problem

query_pipeline was querying for:
```sql
level = 'company' AND metric = 'total_arr'
```

**Result:** No rows found → coverage_ratio would be None

**Would have shown (if data existed):** 18.6x coverage against $1M target

## Verification Findings

### 1. Wrong Query Target

**Actual data structure:**
- 6 rep-level targets: `metric="incremental_arr"`, sum to **$1.55M**
- 1 team-level target: `metric="incremental_arr"`, value = **$1.55M**
- No company-level targets exist

**Correct query:**
```sql
level = 'team' AND metric = 'incremental_arr'
```

### 2. Correct Coverage Calculation

```
Pipeline: $18,565,953 (306 deals, all active incremental ARR)
Target: $1,550,000 (Q3 FY2027 team incremental_arr target)
Coverage: 12.0x
```

### 3. Is 12x Plausible?

**Typical healthy pipeline coverage: 3-5x**

**Why 12x is high but CORRECT:**

Pipeline is **timeless by design** (per Jeff's confirmed definition):
- Includes ALL active incremental deals
- No close_date filtering
- Spans Q3, Q4, Q1+, etc.

Target is **quarterly scoped**:
- $1.55M for Q3 FY2027 only
- Does not include future quarters

**Verification of top deals:**
```
Tubi: $500K → closes 2027-07-26 (Q4)
Anthropic: $500K → closes 2026-12-12 (Q3)
Ingka Ikea: $500K → closes 2027-01-29 (Q4)
Comcast: $350K → closes 2027-01-01 (Q4)
...many more closing in future quarters
```

**This is not an error** - it's the correct behavior for a timeless pipeline design.

## What Was Fixed

1. **Query corrected:**
   - Changed from `level="company"` to `level="team"`
   - Changed from `metric="total_arr"` to `metric="incremental_arr"`

2. **Coverage caveat added:**
   - When coverage > 10x, add explicit caveat
   - "Coverage is high because pipeline includes ALL active deals regardless of close date"
   - "For deals closing THIS quarter specifically, filter by close_date"

3. **Synthesis instruction updated:**
   - "If coverage_caveat is present, ALWAYS include it immediately after stating coverage ratio"
   - Never present high coverage without context

## Expected Response

```
Current Pipeline (Incremental ARR): $18.6M across 306 deals

Coverage: 12.0x quarterly target ($1.55M)
Note: Coverage is high because pipeline includes ALL active deals regardless
of close date (timeless design). Many deals close in future quarters. For
deals closing THIS quarter specifically, filter by close_date.

[Stage breakdown, top deals]

Data quality: 126 deals in pipeline have $0 incremental ARR recorded.

Want to see deals closing this quarter, or upcoming renewals?
```

## Cross-Checks

✅ Target matches q005 team attainment target ($1.55M)
✅ Pipeline value verified against 306 actual deals ($18.6M)
✅ Top deals are legitimate enterprise accounts
✅ Coverage caveat prevents misleading stakeholder presentation

## Conclusion

12.0x coverage is **accurate and correctly contextualized**. This is a legitimate finding about the timeless pipeline design, not an error to fix.
