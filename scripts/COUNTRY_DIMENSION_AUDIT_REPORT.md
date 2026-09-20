# Country-as-Dimension Audit Report
## Marketing/RevOps-lead Priority #2

**Date**: 2026-09-19
**Motivating Question**: Ryan/Lyndsie asked for country-level breakdown of EMEA opportunities and deal value.
**Current State**: Region (EMEA) already resolves via resolve_dimension_filter(). Country does not - only works via dynamic_query's generic filter_table().

---

## Task 1: Country Data Existence and Quality

### Data Coverage
- **Total deals**: 1,912
- **Null/blank countries**: 194 (10.1%)
- **Non-null deals**: 1,718 (89.9%)
- **Distinct non-null values**: 83 countries

### Top Countries by Deal Count
1. United States: 722 deals (37.8%)
2. United Kingdom: 147 deals (7.7%)
3. India: 81 deals (4.2%)
4. Germany: 71 deals (3.7%)
5. Canada: 54 deals (2.8%)
6. Australia: 40 deals (2.1%)
7. The Netherlands: 38 deals (2.0%)
8. Brazil: 33 deals (1.7%)
9. France: 30 deals (1.6%)
10. Sweden: 28 deals (1.5%)

### Data Quality Finding
**89.9% coverage is GOOD** - low null rate indicates this field is populated consistently across deals. Not a data-quality blocker.

---

## Task 2: Canonicalization Need Assessment

### ✅ Clean Areas
- **No case variants**: Data is case-consistent
- **No abbreviation variants**: No US/USA/United States duplicates
- **No whitespace issues**: No leading/trailing spaces or double spaces

### ❌ Semantic Variants Found

**CANONICALIZATION IS NEEDED**

Three semantic variant groups found:

1. **Netherlands** (58 deals total):
   - "Netherlands": 20 deals
   - "The Netherlands": 38 deals
   - *Impact*: 3.0% of all deals split across two names for same country

2. **Russia** (4 deals total):
   - "Russia": 3 deals
   - "Russian Federation": 1 deal

3. **Czech Republic** (16 deals total):
   - "Czech Republic": 12 deals
   - "Czechia": 4 deals

### Recommendation
Create country canonicalization mapping (config file or function) with ilike/fuzzy matching in resolve_dimension_filter(), similar to existing owner_email canonicalization pattern.

**Canonical mapping**:
```yaml
country_aliases:
  "Netherlands": ["Netherlands", "The Netherlands"]
  "Russia": ["Russia", "Russian Federation"]
  "Czech Republic": ["Czech Republic", "Czechia"]
```

---

## Task 3: Relationship to Region Dimension

### Finding: No Region Column in Deals Table
- **Checked**: `deals` table schema
- **Result**: NO region-related columns found
- **Discrepancy**: User stated "Region (EMEA) already resolves via resolve_dimension_filter()" but no region field exists in deals table

### Investigation Needed
How does region resolution currently work if there's no region column?
- Is region derived from country at query time?
- Is region a computed field elsewhere?
- Does resolve_dimension_filter() compute region from country?

### Composition Question (Pending Region Investigation)
Should country be:
- **Independent dimension**: Filter by country alone (e.g., "France deals")
- **Composed with region**: Filter by region AND country (e.g., "EMEA + France")
- **Both**: Support "EMEA" and "EMEA + France" as separate queries

**Cannot finalize until region relationship is confirmed.**

---

## Task 4: Historical Usage in Query Logs

### Query Cost Log (166 total queries)
- **Queries mentioning 'country'**: 1
- **Example**: "Show me the pipeline breakdown by country..."

### Learning Log (517 total entries)
- **Entries mentioning 'country'**: 1 (same question as above)

### Usage Assessment
**ONE-OFF REQUEST, NOT RECURRING PATTERN**

The only historical usage is the motivating EMEA country-breakdown question itself. No other country-related queries found in the full 166+517 entry history.

This is **NOT** confirmed as a recurring need from logs alone - it's a single request. Contrasts with forecast trustworthiness (ranked #1 by domain expertise but only 1 hit in logs) and deal risk (strong log evidence).

---

## Task 5: Gap Analysis - What Needs to be Built

### Current State Check
**resolve_dimension_filter()** exists in `api/dimension_resolver.py`:
- **Currently supported**: region, segment, pipeline
- **Country support**: NO

### Gap Classification

**SMALL GAP** - Dimension resolver addition (30-60 minutes)

This is a **straightforward dimension resolver addition**, NOT a full primitive build:
- Follow existing pattern for region/segment in resolve_dimension_filter()
- Add canonicalization mapping for semantic variants (Netherlands, Russia, Czech Republic)
- Test with ilike matching similar to owner_email pattern
- Wire into existing handler infrastructure (no new aggregation/synthesis logic needed)

**NOT** a multi-hour primitive build like forecast_trust or pipeline_coverage - those compose multiple data sources with reasoning logic. This is just adding a filterable dimension to existing handlers.

---

## Build Scope Recommendation

### Phase 1: Canonicalization (Required First)
**Estimated time**: 15-20 minutes
1. Create country canonicalization mapping in config (or function)
2. Map semantic variants to canonical forms:
   - Netherlands: "The Netherlands" → "Netherlands"
   - Russia: "Russian Federation" → "Russia"
   - Czech Republic: "Czechia" → "Czech Republic"

### Phase 2: Dimension Resolver Addition
**Estimated time**: 20-30 minutes
1. Add country to resolve_dimension_filter() following region/segment pattern
2. Implement ilike matching with canonicalization
3. Test with planted variants (e.g., "the netherlands" should match "Netherlands")

### Phase 3: Verification
**Estimated time**: 10-15 minutes
1. Test with motivating question: "Show me EMEA deals by country"
2. Verify Netherlands/Russia/Czech variants resolve correctly
3. Confirm null handling (194 deals with no country)

**Total estimated time**: 45-65 minutes (NOT a multi-hour primitive build)

---

## Priority Assessment

### Arguments FOR Higher Priority
- **Data quality is good**: 89.9% coverage, not blocked by data issues
- **Clean data**: Only 3 semantic variants, rest is pristine
- **Fast addition**: 45-65 minute build, not multi-hour investment
- **Domain request**: Marketing/RevOps lead (Lyndsie) explicitly asked for this

### Arguments AGAINST Higher Priority
- **One-off usage**: Only 1 historical query across 683 total log entries (0.15%)
- **Not confirmed recurring**: Cannot prove this is a pattern vs. single request
- **No region composition clarity**: Unclear how country relates to EMEA resolution
- **Lower on roadmap**: Ranked #2 in Marketing list, below pipeline generation by source/channel

### Net Recommendation
**DEFER until region relationship is clarified**, THEN promote to higher priority if:
1. Region is indeed derived from country (confirms composition need)
2. OR another country-related question appears in logs (confirms recurring pattern)
3. OR Lyndsie/Ryan explicitly confirm this as recurring need (domain override)

The build itself is fast (< 1 hour), but **the priority evidence is weak** (single log hit, no confirmed recurrence). Compare to deal risk (CRO #3): dominant in real usage logs, strong domain + evidence agreement - clear build target. Country dimension: weak log evidence, fast build, awaiting clarity on region relationship and usage pattern.

---

## Open Questions for User

1. **Region resolution**: How does "Region (EMEA) already resolves via resolve_dimension_filter()" work if there's no region column in deals table? Is region computed from country?

2. **Composition intent**: Should "EMEA deals by country" filter to (all EMEA deals) THEN break down by country, or should each country be independent?

3. **Priority confirmation**: Given only 1 historical usage (0.15% of queries), should this still be prioritized over items with stronger log evidence?

4. **Build timing**: Fast build (< 1 hour) but weak usage signal. Build now or wait for recurrence confirmation?

---

## Appendix: Raw Data

### All 83 Distinct Country Values
(See audit script output for complete list)

### Semantic Variants Detail
- Netherlands (38 deals) + Netherlands (20 deals) = 58 deals (3.0% of total)
- Russia (3) + Russian Federation (1) = 4 deals (0.2%)
- Czech Republic (12) + Czechia (4) = 16 deals (0.8%)

**Combined impact**: 78 deals (4.1% of all deals) affected by semantic variants
