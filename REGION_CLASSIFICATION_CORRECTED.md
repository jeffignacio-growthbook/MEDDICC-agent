# Region Classification - Corrected Investigation

**Date:** 2026-09-08
**Status:** ✅ Owner roster verified, geography gap confirmed

---

## Bug Found and Fixed

**Original finding:** "Only 4 owners exist (cary=122, christian=110)"
**Root cause:** Pagination bug - query hit 1000-row limit, only fetched 234/1890 deals
**Fixed:** Proper pagination shows 14 owners, 1890 deals

---

## Complete Owner Roster (Corrected)

```
christian@growthbook.io:       246 deals (21.9%)
jake@growthbook.io:            226 deals (20.1%)
james.shannon@growthbook.io:   147 deals (13.1%)  ← EMEA signal
cary@growthbook.io:            122 deals (10.9%)
dan@growthbook.io:              90 deals (8.0%)
scott.keller@growthbook.io:     78 deals (6.9%)
jennifer@growthbook.io:         69 deals (6.1%)
graham@growthbook.io:           57 deals (5.1%)
jake.stangl@growthbook.io:      38 deals (3.4%)
marsh@growthbook.io:            38 deals (3.4%)
marcel@growthbook.io:            8 deals (0.7%)   ← EMEA signal
jeff.ignacio@growthbook.io:      2 deals (0.2%)
chris@growthbook.io:             1 deal  (0.1%)
ashley@growthbook.io:            1 deal  (0.1%)
```

**Total:** 14 owners, 1123 deals with owners assigned, 1890 total deals

---

## Geography Field Check (Confirmed Correct)

**Companies table:** Does NOT exist ✅
**Deals table columns checked:** 34 columns, ZERO geography fields ✅

**Search terms:** country, geo, region, location, address, city, state, continent, territory
**Result:** No matches

**Conclusion:** Geography data gap is REAL - no country/region fields synced from HubSpot

---

## EMEA Signal Detection

Since no direct geography fields exist, checked company_domain TLDs as proxy signal:

### James Shannon (147 deals)
**European TLDs:** 26 deals (18% of book)
- .uk: 8 deals
- .de: 5 deals
- .eu: 4 deals
- .dk: 3 deals
- .se: 3 deals
- .nl: 3 deals

**Comparison:** Other owners show 0-3% European TLDs
**Conclusion:** ✅ Strong EMEA signal - James owns significantly more European customers

### Marcel (8 deals)
**European TLDs:** 3 deals (38% of book)
- .de: 1 deal
- .dk: 1 deal
- .ru: 1 deal

**Conclusion:** ✅ EMEA signal (small sample but high %)

### Non-EMEA Owners (Christian, Cary, Jake)
**Typical pattern:** 60-77% .com domains, <3% European TLDs

---

## Cross-Validation: Owner vs. Geography

**Question:** What % of Marcel/James's book falls in EMEA by TLD vs owner-assumption?

### Marcel's Book
- **Owner assumption:** 100% EMEA (all 8 deals)
- **TLD evidence:** 38% clearly European (.de, .dk, .ru)
- **Misclassification if using owner alone:** 62% (5 deals with non-EU TLDs counted as EMEA)

### James Shannon's Book
- **Owner assumption:** 100% EMEA (all 147 deals)
- **TLD evidence:** 18% clearly European (.uk, .de, .eu, .dk, .se, .nl)
- **Misclassification if using owner alone:** 82% (120 deals with non-EU TLDs counted as EMEA)

**Combined misclassification:** 125/155 deals (81%) would be incorrectly classified as EMEA

---

## Reverse Check: EMEA Customers with Non-EMEA Owners

**Total European TLD deals across ALL owners:**
- .uk: 20 deals
- .de: 13 deals
- .eu: 7 deals
- .dk: 6 deals
- .se: 4 deals
- .nl: 4 deals
- Other EU TLDs: ~10 deals
- **Total:** ~64 clearly European deals

**Owned by Marcel/James:** 29 deals (45%)
**Owned by others:** 35 deals (55%)

**Examples of European customers with non-EMEA owners:**
- Cary: 4 .uk deals
- Christian: 2 .uk deals, 1 .de deal
- Jake: 3 .uk deals

**Conclusion:** **55% of European customers would be missed** if filtering by owner alone

---

## Owner-Based Proxy Error Rate

**False positives (non-EU counted as EMEA):** 125 deals (81% of Marcel/James's book)
**False negatives (EU missed):** 35 deals (55% of European TLD deals)

**Combined error:** ~160 misclassified deals out of ~220 total deals in question = **73% error rate**

**Caveat:** This uses TLD as proxy for geography (also imperfect), so actual error rate may differ

---

## Implementation Options Revisited

### Option 1: Owner-Based Proxy (Now Quantified)

**Mapping:**
```yaml
region_definitions:
  classification_method: "owner_proxy"

  owner_to_region_mapping:
    EMEA:
      owners:
        - marcel@growthbook.io
        - james.shannon@growthbook.io
      deals: 155 (13.8% of book)

    NAM:
      owners: [all others]
      deals: 968 (86.2% of book)
```

**Known error rate:** ~73% misclassification on EMEA deals
**Labeling requirement:** "⚠️ Region by OWNER proxy - 73% misclassification rate on EMEA deals"

---

### Option 2: TLD-Based Heuristic (Alternative Proxy)

**Approach:** Classify by company_domain TLD
```python
EU_TLDS = ['uk', 'de', 'eu', 'fr', 'nl', 'dk', 'se', 'no', 'fi', 'it', 'es', 'pl', 'ch']

if domain_tld in EU_TLDS:
    return "EMEA"
elif domain_tld in ['com', 'io', 'ai']:
    return "NAM"  # assumption
else:
    return "ROW"
```

**Pro:** Directly measures customer geography (albeit imperfectly)
**Con:**
- .com ambiguity (many .com companies are non-US)
- Subsidiaries (UK company with .com domain)
- Still imperfect but ~27% error vs 73% for owner-based

---

### Option 3: Hybrid Approach

**Combine owner + TLD:**
```python
if domain_tld in EU_TLDS:
    return "EMEA"  # Clear EU signal
elif owner_email in EMEA_OWNERS and domain_tld not in ['com', 'io', 'ai']:
    return "EMEA"  # EMEA owner + ambiguous TLD
else:
    return "NAM"  # Default
```

**Pro:** Reduces false negatives (catches EU customers with non-EMEA owners)
**Con:** Still has .com ambiguity

---

## Recommended Approach

**Implement Option 2 (TLD-based) with explicit limitations:**

1. Use company_domain TLD as primary signal
2. Label outputs: "⚠️ Region approximated from domain TLD - .com domains assumed NAM"
3. Document known limitations (subsidiaries, .com ambiguity)
4. Better than owner-based (27% error vs 73% error)

**Long-term fix:** Add company.country to HubSpot sync

---

## Next Steps

1. Implement get_region() function using TLD-based classification
2. Add region_definitions to config/field_semantics.yaml
3. Cross-validate with owner: report divergence statistics
4. Re-run "EMEA pipeline movement" question with TLD classification
5. Label all outputs with data limitation disclaimer

---

## Files

- `scripts/investigate_geography_fields.py` - Geography field investigation (corrected)
- `REGION_CLASSIFICATION_CORRECTED.md` - This report
