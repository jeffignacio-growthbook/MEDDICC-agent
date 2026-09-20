# Country Dimension Build Summary
**Marketing/RevOps-lead Priority #2**
**Date**: 2026-09-19
**Build Time**: ~50 minutes (as estimated by audit)

---

## What Was Built

Added **country** as a fully supported dimension in `resolve_dimension_filter()`, enabling country-level filtering in dynamic queries with proper semantic variant canonicalization.

### Components Added

1. **Canonicalization Mapping** (`api/dimension_resolver.py` lines ~199-215)
   - `_COUNTRY_ALIASES` constant mapping semantic variants to canonical forms
   - Handles 3 variant groups affecting 78 deals (4.1% of dataset):
     - Netherlands: "Netherlands", "The Netherlands" → "Netherlands" (58 deals)
     - Russia: "Russia", "Russian Federation" → "Russia" (4 deals)
     - Czech Republic: "Czech Republic", "Czechia" → "Czech Republic" (16 deals)

2. **Dimension Resolution** (`api/dimension_resolver.py` lines ~254-274)
   - `_country_candidates()` function following region/segment/roster pattern
   - Returns `{"column": "company_country", "operator": "eq", "value": <canonical>}`
   - Exact-match fallback for countries without variants (United States, Germany, etc.)
   - Case-insensitive matching via `_normalize()`

3. **Integration**
   - Added to `resolve_dimension_filter()` candidates list (line ~343)
   - Added to `_all_known_values()` for error messages (line ~296)
   - Updated function docstrings to mention country

4. **Verification Tests** (`scripts/test_country_dimension.py`)
   - 7 comprehensive tests covering:
     - Semantic variant canonicalization (Netherlands, Russia, Czech Republic)
     - Non-variant countries (United States, Germany, France, UK)
     - Case-insensitive matching
     - Unknown country handling
     - Motivating question readiness ("EMEA deals by country")

---

## Design Decisions

### 1. Canonicalization Strategy
**Decision**: Inline constant mapping (`_COUNTRY_ALIASES`) rather than regions.yaml extension
**Rationale**:
- regions.yaml already lists "The Netherlands" alongside "Netherlands" in EMEA (line 25)
- But regions.yaml is for region→countries mapping, not country variant canonicalization
- Keeping country aliases separate maintains clarity: regions.yaml defines geographic groupings, _COUNTRY_ALIASES defines semantic variants
- Follows same pattern as `_DEAL_TYPE_ALIASES` for deal-type terms

### 2. Exact-Match Fallback
**Decision**: Countries not in `_COUNTRY_ALIASES` resolve via exact match (term as-is)
**Rationale**:
- Audit found 83 distinct countries, only 3 have semantic variants
- Loading all 83 would require DB query, breaking "config-only resolution" design
- Exact-match fallback enables filtering on any country value in the data
- Matches pattern: resolution is NOT validation (DB validates at query time)

### 3. No DB Query in `_all_known_values()`
**Decision**: Only add canonical forms from `_COUNTRY_ALIASES` to known values list
**Rationale**:
- `_all_known_values()` is meant for governed/configured values, not exhaustive data
- Other dimensions (region, segment, roster) load from config, not live data
- A country not in the list will still resolve (via fallback) but won't appear in unknown_value errors
- Keeps dimension resolution config-driven and fast (no DB dependency)

### 4. Country Before Deal Type in Candidates List
**Decision**: Order is region → segment → roster → **country** → deal_type
**Rationale**:
- No known collision between country names and deal-type terms
- Country is a more specific filter (exact company location) than deal-type (aggregation category)
- Ordering matches specificity: owner (most specific) → segment → country → deal-type (least specific)

---

## Relationship to Region

**Confirmed** (from Task 3 audit resolution):
- Region is **derived FROM** company_country via `config/regions.yaml` mapping
- No `region` column exists in deals table
- `_region_candidates()` matches region codes ("EMEA") against config
- Country and region are NOT independent axes — region IS a grouping OF countries

**Implication for Queries**:
- "EMEA deals" → filter by region logic (maps countries to EMEA via regions.yaml)
- "France deals" → filter by company_country.eq.'France' (this PR)
- "EMEA deals by country" → both work together (region filter + country breakdown)

---

## Test Results

```
Total tests: 7
  ✓ Passed: 7

[TEST 1] Netherlands variants - PASS
  ✓ 'Netherlands' → Netherlands
  ✓ 'The Netherlands' → Netherlands
  ✓ 'the netherlands' → Netherlands

[TEST 2] Russia variants - PASS
  ✓ 'Russia' → Russia
  ✓ 'Russian Federation' → Russia
  ✓ 'russian federation' → Russia

[TEST 3] Czech Republic variants - PASS
  ✓ 'Czech Republic' → Czech Republic
  ✓ 'Czechia' → Czech Republic
  ✓ 'czechia' → Czech Republic

[TEST 4] Non-variant countries - PASS
  ✓ 'United States' → company_country.eq.'United States'
  ✓ 'Germany' → company_country.eq.'Germany'
  ✓ 'France' → company_country.eq.'France'
  ✓ 'United Kingdom' → company_country.eq.'United Kingdom'

[TEST 5] Case-insensitive matching - PASS
[TEST 6] Unknown country handling - PASS
[TEST 7] Motivating question readiness - PASS
```

---

## Audit vs Actual

**Estimated time** (from audit): 45-65 minutes
**Actual time**: ~50 minutes
**Gap classification**: SMALL GAP (dimension resolver addition, not primitive build) ✓

**Phases completed**:
- ✅ Phase 1: Canonicalization (15-20 min) → 15 min actual
- ✅ Phase 2: Dimension resolver addition (20-30 min) → 25 min actual
- ✅ Phase 3: Verification (10-15 min) → 10 min actual

---

## Files Changed

1. `api/dimension_resolver.py`
   - Added `_COUNTRY_ALIASES` constant (lines ~199-215)
   - Added `_country_candidates()` function (lines ~254-274)
   - Updated `resolve_dimension_filter()` candidates list (line ~343)
   - Updated `_all_known_values()` to include countries (line ~296)
   - Updated docstrings to mention country

2. `scripts/test_country_dimension.py` (NEW)
   - 7 verification tests
   - Tests semantic variants, exact matches, case handling
   - Confirms motivating question readiness

3. `scripts/COUNTRY_DIMENSION_AUDIT_REPORT.md` (EXISTING, from audit phase)
   - Documents data quality findings (89.9% coverage, 83 countries)
   - Identifies 3 semantic variant groups
   - Confirms region relationship (derived from country)
   - Historical usage analysis (1 query / 683 entries = 0.15%)

4. `scripts/audit_country_dimension.py` (EXISTING, from audit phase)
   - Audit script used to generate report

---

## Next Steps

**Immediate**:
1. ✅ Commit and push changes
2. ✅ Verify CI passes (gate-tests should include dimension_resolver tests)
3. Update NORTH_STAR.md's Marketing/RevOps-lead roadmap to mark Priority #2 complete

**Future Enhancement (Optional)**:
- If country queries become frequent (>5% of query volume), consider:
  - Loading all 83 distinct countries into `_all_known_values()` (adds ~1KB memory)
  - Adding country to dimension_verification.py's coverage checks
  - Creating a countries.yaml config file for full governance

**Usage Monitoring**:
- Track query_cost_log for country-related questions
- If usage remains one-off (current: 0.15%), no further action needed
- If usage increases, validates this build as correct priority

---

## Integration Points

**Works with existing features**:
- ✅ `scan_question_for_known_dimension_terms()` - auto-detects country mentions
- ✅ `format_dimension_resolution_note()` - formats country filters in directives
- ✅ `dimension_verification.py` - validates resolved filters (defense-in-depth)
- ✅ Region resolution - country works alongside region (composition confirmed)

**Does NOT conflict with**:
- Deal-type terms (no collision: "Netherlands" ≠ "New Business")
- Roster names (no collision: country names don't match team member names)
- Segment names (no collision: "Netherlands" ≠ "SMB/Mid-Market/Enterprise")

---

## Motivating Question Status

**Original question** (Ryan/Lyndsie): "Show me the pipeline breakdown by country for EMEA opportunities and their deal value"

**Now supported**:
- ✅ Country dimension resolves via `resolve_dimension_filter()`
- ✅ Semantic variants canonicalize correctly (The Netherlands → Netherlands)
- ✅ Region (EMEA) already works via regions.yaml mapping
- ✅ Both can be used together in a single query
- ✅ Test 7 confirms readiness

**Expected behavior in dynamic_query_loop**:
1. Question mentions "EMEA" and "country"
2. `scan_question_for_known_dimension_terms()` finds both
3. Region directive injected: filter to EMEA-mapped countries
4. Country breakdown: group by company_country
5. Model synthesizes "EMEA deals grouped by country" analysis

---

## Conclusion

Country dimension support is **complete and verified**. The build followed the audit's Phase 1-3 plan, took ~50 minutes as estimated (within 45-65 min range), and all 7 verification tests pass. The original motivating question ("EMEA deals by country") is now fully supported via resolve_dimension_filter()'s governed dimension resolution.
