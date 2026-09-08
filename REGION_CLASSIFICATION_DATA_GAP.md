# Region Classification - Data Gap Report

**Date:** 2026-09-08
**Status:** ❌ NO GEOGRAPHY DATA AVAILABLE

---

## Investigation Results

### 1. Geography Field Check

**Companies table:** Does not exist
**Deals table:** Checked for geography fields

**Search terms:** country, geo, region, location, address, city, state

**Result:** ❌ **ZERO** geography-related fields found

**Available deal fields:**
```
arr_usd, backfill_confidence, close_date, company_domain, company_employee_count,
company_id, company_name, company_slug, create_date, created_at, days_to_close,
deal_id, deal_status, deal_value, expansion_arr, forecast_category,
highest_stage_order_reached, incremental_arr, last_analyzed, lost_reason, new_arr,
owner_email, pipeline, pipeline_id, prior_arr, qualified_date, renewal_revenue,
sao, sdr_owner_email, segment, segment_reason, stage, stage_source, updated_at
```

**Notable missing fields:**
- No `billing_country`
- No `company_country`
- No `hq_country`
- No `region`
- No geography data synced from HubSpot

---

## Data Gap Classification

**Tier:** Same as missing contacts table - genuine data gap, not implementation issue

**Impact:**
- Region-based pipeline queries CANNOT use real geography
- "EMEA pipeline" questions must use owner as proxy
- Misclassification risk: European customers with non-EMEA owners counted wrong

---

## Current Owner Distribution

```
cary@growthbook.io:       122 deals (52.1%)
christian@growthbook.io:  110 deals (47.0%)
ashley@growthbook.io:       1 deal  (0.4%)
chris@growthbook.io:        1 deal  (0.4%)
```

**Total deals:** 234 (with owner assigned)

---

## Implementation Options

### Option 1: Owner-Based Proxy (Recommended for Now)

**Approach:**
Define region classification in `config/field_semantics.yaml`:

```yaml
region_definitions:
  classification_method: "owner_proxy"
  data_gap_documented: true

  owner_to_region_mapping:
    EMEA:
      owners: ["marcel@growthbook.io", "james@growthbook.io"]  # Example - needs Jeff to confirm
      note: "Assumed EMEA based on owner assignment, not company geography"
    NAM:
      owners: ["cary@growthbook.io", "christian@growthbook.io"]  # Example - needs confirmation
      note: "Assumed NAM based on owner assignment"
    ROW:
      owners: []  # Catch-all for any other owners
      note: "Rest of world - all owners not explicitly mapped"
```

**Function signature:**
```python
def get_region(deal: dict, method: str = "owner_proxy") -> str:
    """
    Get region for a deal using owner-based proxy.

    ⚠️ WARNING: This uses OWNER as proxy, not actual company geography.
    Deals owned by non-EMEA reps with European customers are misclassified.

    Args:
        deal: Deal dict with owner_email
        method: "owner_proxy" (only available method)

    Returns:
        "NAM" | "EMEA" | "ROW"
    """
```

**Labeling requirement:**
Every region-based output MUST include disclaimer:
```
⚠️ Region classified by OWNER, not company geography
European customers with non-EMEA owners may be misclassified
```

---

### Option 2: Defer Until Geography Data Added

**Approach:**
- Document region classification as "Not Available - Data Gap"
- Return error on region-based queries: "Region classification requires geography data (not available)"
- Recommend adding to HubSpot sync as priority

**Pro:** Honest about limitation, prevents false confidence
**Con:** Blocks any region-based analysis

---

### Option 3: Infer from Company Name (Risky)

**Approach:**
- Parse company_name for geography hints (Ltd, GmbH, Inc, etc.)
- Use company_domain TLD (.uk, .de, .com) as signal

**Example:**
```python
# Risky heuristics
if ".uk" in domain or "Ltd" in name:
    return "EMEA"
elif ".de" in domain or "GmbH" in name:
    return "EMEA"
elif ".com" in domain:
    return "NAM"  # ??? Many .com companies are non-US
```

**Pro:** Some signal better than none
**Con:**
- High error rate (.com ambiguity, subsidiaries)
- False confidence - looks like real data but isn't
- **NOT RECOMMENDED**

---

## Recommended Fix

**Short-term:** Implement Option 1 (owner-based proxy) with explicit labeling

**Long-term:** Add geography field to HubSpot sync

**HubSpot properties to add:**
```
company.country          → deals.company_country
company.state            → deals.company_state
company.city             → deals.company_city
deal.billing_country     → deals.billing_country
```

**Priority:** Medium-High
- Blocks accurate region-based reporting
- Owner proxy has known misclassification risk
- Common sales ops requirement

---

## Questions for Jeff

1. **Owner-to-region mapping:** Which owners should map to which regions?
   - Current owners: cary@growthbook.io, christian@growthbook.io
   - Are either of these EMEA? Or is GrowthBook all NAM?

2. **Marcel/James reference:** These owners don't exist in the database. Were they:
   - Hypothetical example to illustrate the pattern?
   - Former owners no longer in system?
   - Different email addresses than expected?

3. **EMEA scope:** If implementing owner-based proxy, confirm EMEA definition:
   - Europe only? (UK, France, Germany, etc.)
   - Europe + Middle East + Africa? (full EMEA)
   - Matters for future geography field addition

4. **Implementation preference:**
   - Option 1 (owner proxy with labeling) - functional but imperfect?
   - Option 2 (defer until real data) - honest but blocks analysis?

---

## Original Question Impact

**Question:** "How has EMEA pipeline moved in the last 2 weeks"

**Without geography data:**
- Cannot identify EMEA by company location
- Must use owner proxy (if we know which owners are EMEA)
- Answer will be labeled as owner-based approximation

**With geography data:**
- Filter deals where company_country IN ('UK', 'Germany', 'France', ...)
- Accurate EMEA pipeline regardless of owner
- No misclassification risk

---

## Files Created

- `scripts/investigate_geography_fields.py` - Field investigation script
- `REGION_CLASSIFICATION_DATA_GAP.md` - This report

---

## Next Steps

**Blocked on Jeff's input:**
1. Confirm owner-to-region mapping for GrowthBook
2. Choose Option 1 (proxy) or Option 2 (defer)
3. If Option 1: Implement region classification with explicit labeling
4. If Option 1: Re-run EMEA pipeline question with owner-based classification
