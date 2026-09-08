# Signal 3 Deferral: Activity Recency Gap

## Status: ❌ DEFERRED

**Date:** 2026-09-07

**Reason:** Insufficient coverage and sample sizes. No consistent won/lost separation in derivable cells.

---

## Executive Summary

Signal 3 (activity recency gap) cannot be derived from current data. After comprehensive investigation including bulk cleanup exclusion, close_date precision fix, and deal-type scoping, only 3/9 stage × segment cells meet minimum sample size requirements (n≥5 per outcome). Of these 3 cells, only 1 shows the expected direction (lost deals silent longer than won deals). Coverage is 46% (116/253 clean deals with activity data), below the 50% threshold for reliable metric derivation.

**Key finding preserved for future investigation:** Discovery × SMB cell shows INVERTED pattern (won median 49 days vs lost P25 2 days), suggesting SMB deals may have different quiet-period dynamics than Enterprise/Mid-Market. Sample too thin (n=9 won, n=19 lost) to confirm - flagged as hypothesis for re-testing with more data.

---

## Investigation Trail

### Phase 1: Initial Approach - Pairwise Gap Frequency (FAILED)

**Original methodology:** Compute gaps between ALL consecutive activities (notes_last_updated changes) per deal, derive thresholds from won vs lost gap distributions.

**Failure mode discovered:** 40-67% of ALL gaps (both won and lost) were 0-day gaps due to multiple same-day activities. This created artificial noise that made threshold derivation impossible.

**Finding:** notes_last_updated updates EVERY time ANY activity occurs (note, call, email, meeting, task). Multiple activities on same calendar day create artificial 0-day gaps that dominate distributions.

**Sample data:**
- proposal × Mid-Market: 56.8% of won gaps = 0 days
- proposal × SMB: 74.5% of won gaps = 0 days
- discovery × Enterprise: 51.7% of lost gaps = 0 days

**Lesson learned:** Pairwise gap approach is unsuitable for high-frequency activity fields. Template-portable: avoid this methodology for any field that updates multiple times per day.

### Phase 2: Corrected Approach - Recency Metric (Single Last Gap)

**Revised methodology:** Compute ONE recency value per deal - gap between LAST activity and close date. Answers "how long was deal silent before outcome?"

**Rationale:** Eliminates within-day multiplicity issue by construction. No "multiple touches in one afternoon" problem when measuring only the final gap.

**Expected pattern:**
- Won deals: Small gaps (actively engaged right up to close)
- Lost deals: Large gaps (went silent before dying)

**Result:** Methodology correction successful, but revealed coverage and sample size issues.

### Phase 3: Bulk Cleanup Exclusion

**Issue discovered:** 750 deals identified as bulk cleanup contamination from Q016 investigation (blank lost_reason in specific months + pre-2023 legacy deals).

**Action:** Excluded 484 bulk cleanup deals from closed population (253 clean deals remaining).

**Impact:** Necessary data quality filter. Coverage dropped but cleaned population.

### Phase 4: Negative Gap Investigation

**Issue discovered:** 114/137 deals (83%) with activity data had negative gaps (close_date < last_activity).

**Root cause analysis:**

**Check 1: Lost_reason distribution**
- Found: 100% blank company-wide (0/1121 lost deals)
- Conclusion: NOT distinguishing evidence (universal data quality gap)
- HubSpot field "closed_lost_reason" (26.5% filled) is NOT synced to Supabase

**Check 2: Won deals overlap with other data quality issues**
- 76 won deals with negative gaps
- $0 new_arr: 85.5% (vs 86.8% for all won deals)
- Conclusion: No significant overlap - similar to general won population

**Check 3: Gap magnitude distribution**
- 65% have -1 to -2 day gaps (74/114 deals)
- 35% have larger gaps (weeks/months)
- Suggests mixed population: timestamp precision + real post-close activity

**Check 4: Timestamp precision verification**
- Examined exact timestamps for 10 sample deals with -1 to -2 day gaps
- **Mechanism confirmed:** close_date stored as **midnight timestamp (00:00:00)**, last_activity has full time-of-day precision
- 9/10 deals showed activity on SAME calendar day but later than midnight → negative gap

**Examples:**
- Apify: activity at 11:43 AM, close at midnight → -11.7 hours (same day)
- Avaaz: activity at 11:22 PM, close at midnight → -23.4 hours (same day)
- ScreenPal: activity at 12:09 AM, close at midnight → -0.2 hours (9 minutes!)

**Finding:** close_date field stored as date-only (midnight timestamp) while activity timestamps carry full time-of-day precision. This creates negative gaps when activity occurs later the same calendar day.

**Data quality note:** This close_date storage format could affect ANY date-diff calculation comparing close_date against full-timestamp fields elsewhere in codebase. Worth documenting in data quality registry.

### Phase 5: Stage-Transition-Date Fix

**Solution implemented:** For deals with negative gaps, use date when deal entered closed stage (from dealstage property history) instead of close_date.

**Fix applied:** 114 negative gaps corrected using stage transition timestamps.

**Result:** Successfully eliminated negative gaps. All 114 deals now have valid recency metrics.

---

## Final Results

### Coverage Analysis

**4-way population split:**
| Population | Count | % of Total |
|------------|-------|------------|
| Won with activity | 37 | 64% of won |
| Won no activity | 21 | 36% of won |
| Lost with activity | 79 | 82% of lost |
| Lost no activity | 17 | 18% of lost |

**Total with activity:** 116/253 deals (46% coverage)

**Issue:** 36% of won deals have NO activity recorded. This is a significant data completeness gap - won deals should have engagement history through close.

**Coverage too low:** 46% < 50% minimum threshold for reliable metric derivation.

### Sample Size Analysis

**Cells with sufficient sample (n≥5 per outcome): 3/9 (33.3%)**

| Stage | Segment | Won | Lost | Status |
|-------|---------|-----|------|--------|
| discovery | Mid-Market | 9 | 10 | ✅ Sufficient |
| discovery | SMB | 9 | 19 | ✅ Sufficient |
| proposal | Mid-Market | 11 | 6 | ✅ Sufficient |
| discovery | Enterprise | 3 | 8 | ❌ Insufficient |
| proposal | Enterprise | 3 | 2 | ❌ Insufficient |
| proposal | SMB | 2 | 9 | ❌ Insufficient |
| scoping | Enterprise | 0 | 10 | ❌ Insufficient |
| scoping | Mid-Market | 0 | 8 | ❌ Insufficient |
| scoping | SMB | 0 | 7 | ❌ Insufficient |

**Issue:** Only 33% of cells viable. Insufficient for production use.

### Direction Analysis

**Expected pattern:** Lost P25 > Won Median (lost deals silent longer)

**Actual results:**

| Cell | Won Median | Lost P25 | Direction | Status |
|------|------------|----------|-----------|--------|
| discovery × Mid-Market | 0 days | 0 days | Tie (no separation) | ❌ |
| discovery × SMB | **49 days** | **2 days** | **INVERTED** | ⚠️ |
| proposal × Mid-Market | 0 days | 9.8 days | Correct | ✅ |

**Critical finding:** Only 1/3 cells shows expected direction.

### Discovery × SMB Inversion - Hypothesis for Future Investigation

**Observed pattern:** Won deals have LONGER silence (49 day median) than lost deals (2 day P25).

**Interpretation (HYPOTHESIS - not confirmed):**

SMB deals may have an inverted quiet-period pattern relative to Enterprise/Mid-Market segments:

**Possible mechanisms:**
1. **Won deals = low-touch self-evaluation:** SMB buyers may evaluate independently with minimal sales engagement, leading to long silent periods before decision/purchase. High-quality leads self-convert with less handholding.

2. **Lost deals = fast disengagement:** SMB prospects disengage quickly when not interested (2-day silence before churning out). Lower tolerance for prolonged sales cycles.

3. **Sales motion difference:** SMB deals may use different engagement patterns (product-led growth, self-serve trials, async communication) vs Enterprise's synchronized-meeting-heavy cadence.

**Sample size caveat:** n=9 won, n=19 lost. Too thin to confirm pattern.

**Recommendation:** **DO NOT dismiss as noise.** Revisit with more data before assuming this generalizes or rejecting the hypothesis. If confirmed with larger sample:
- SMB segment may need INVERTED threshold logic (flag deals that are too "hot" rather than too "cold")
- Or may indicate SMB deals should use different signals entirely (product usage metrics rather than sales activity)
- Or may reflect genuine SMB buyer behavior that should inform sales strategy

**Action:** Flag for re-testing when more SMB deals with activity data are available. Current sample insufficient for production decision.

---

## Template-Portable Lessons

### 1. notes_last_updated Field Characteristics

**What it is:** HubSpot auto-updated field tracking timestamp of last note/activity.

**Coverage:** 86% of closed deals (validated via HubSpot API).

**Update frequency:** EVERY activity (note, call, email, meeting, task).

**Timestamp precision:** Full date-time (not date-only).

**Suitability for Signal 3:**
- ✅ High coverage (86%)
- ✅ Reflects genuine activity timing
- ❌ Too high-frequency for pairwise gap analysis (creates 0-day gap noise)
- ✅ Suitable for recency metric (single last gap)
- ❌ Insufficient coverage after exclusions (46% usable)

### 2. close_date Field Storage Format

**Discovered characteristic:** Stored as **date-only field with midnight timestamp (00:00:00)**, not full date-time.

**Impact:** Creates artificial negative gaps when compared against full-timestamp activity fields (if activity occurs later same calendar day, gap appears negative).

**Resolution:** Use stage transition timestamps from dealstage property history instead of close_date for timing-sensitive calculations.

**Template-portable note:** Check close_date storage format for each client. If date-only, use stage transitions for precise outcome timing.

### 3. 4-Way Population Split

**Methodology:**
- Won with activity
- Won no activity (sanity check - should be rare)
- Lost with activity
- Lost no activity (report separately)

**Purpose:** Separates data completeness issues from pattern analysis. High "no activity" rates indicate field population problems, not signal viability.

**Template-portable:** Use this split for ANY activity-based signal derivation to identify coverage gaps early.

### 4. Bulk Cleanup Detection

**Criteria used:**
- Lost deals with blank lost_reason in specific months (>10 per month threshold)
- Pre-2023 legacy deals (before pipeline scheme existed)
- Deal-level exclusion (not month-level)

**Result:** 750 deals excluded (67% of lost deals in full population).

**Template-portable:** Always check for bulk cleanup contamination before deriving thresholds. Use deal-level exclusion lists rather than date ranges.

### 5. Stage-Transition-Date Approach

**When to use:** When close_date has precision issues or timing mismatches.

**How:** Find first dealstage change to closed stage (closedwon or closedlost) from dealstage property history.

**Advantages:**
- More accurate than close_date (reflects actual stage entry)
- Avoids midnight-timestamp precision issues
- Consistent with field_semantics approach (use stage for won/lost determination)

**Template-portable:** Prefer stage transitions over close_date for timing-sensitive metrics.

---

## Deferral Rationale

**Signal 3 is deferred due to:**

1. **Insufficient coverage:** 46% < 50% minimum threshold
   - Only 116/253 clean deals have activity data
   - 36% of won deals have NO activity (data completeness issue)

2. **Insufficient sample sizes:** Only 3/9 cells viable (33%)
   - Below 50% cell coverage threshold for production use
   - Scoping stage completely unusable (0 won deals with activity)

3. **No consistent won/lost separation:** Only 1/3 derivable cells shows expected direction
   - 2/3 cells show incorrect or no pattern
   - Discovery × SMB shows INVERTED pattern (hypothesis flagged for re-testing)

4. **Data quality constraints:**
   - notes_last_updated field not consistently populated
   - close_date field stored as date-only (precision issues)
   - Bulk cleanup contamination affecting coverage

**Signal 3 is NOT VIABLE with current data source.**

---

## Alternative Approaches Considered

### Option 1: Use calls-only data
- **Coverage:** 23% (validated earlier)
- **Conclusion:** Insufficient coverage, worse than notes_last_updated

### Option 2: Day-rounding to eliminate 0-day gaps
- **Issue:** Doesn't address root cause (high-frequency updates)
- **Conclusion:** Abandoned in favor of recency metric correction

### Option 3: Minimum 1-day floor for gaps
- **Issue:** Arbitrary threshold, masks data characteristics
- **Conclusion:** Not pursued after recency metric correction

### Option 4: Stage-transition-date for all deals (not just negative gaps)
- **Issue:** Doesn't solve coverage problem (46% still too low)
- **Conclusion:** Applied for negative gap fix, but insufficient for full viability

---

## Re-evaluation Criteria

Signal 3 should be reconsidered when:

1. **Coverage improves:** ≥50% of clean closed deals have activity data
2. **Sample sizes increase:** ≥50% of stage × segment cells have n≥5 per outcome
3. **Discovery × SMB pattern clarified:** Larger sample confirms or refutes inversion hypothesis
4. **Alternative data source:** If calls data coverage improves (currently 23%) or new activity tracking field introduced

---

## Related Metrics

- **Q016 (Sales Cycle Time):** 52 days median, 22 deals, verified and in production
- **Signal 2 (Time-in-Stage):** Derivable per investigation, ready for Q012 implementation
- **Signal 1 (Stakeholder Count):** Deferred (field not available)

---

## Scripts Created

### Investigation Scripts
1. `validate_notes_last_updated_full.py` - Full coverage validation (737 deals)
2. `fetch_and_persist_property_history.py` - Property history persistence to Supabase
3. `derive_signal3_from_supabase.py` - Initial derivation with month-based bulk exclusion (FAILED)
4. `investigate_signal3_gaps.py` - Deep dive into 0-day gap issue
5. `get_bulk_cleanup_deal_ids.py` - Identify 750 bulk cleanup deals from Q016 criteria
6. `derive_signal3_deal_exclusion.py` - Corrected derivation with deal-level exclusion
7. `diagnose_gap_distributions.py` - Sample raw gap distributions
8. `export_raw_gap_distributions.py` - Full gap distribution export to CSV
9. `derive_signal3_recency.py` - Corrected methodology (recency not frequency)
10. `investigate_negative_gaps.py` - Root cause analysis of negative gaps
11. `diagnose_recency_exclusions.py` - Exclusion reason breakdown
12. `derive_signal3_stage_transition.py` - Final derivation with stage-transition-date fix

### Validation Scripts
13. `diagnose_gap_distributions.py` - Why Lost P25 = 0?
14. `investigate_negative_gaps.py` - Timestamp precision verification

**All scripts are template-portable** - reusable methodology for any client attempting Signal 3 derivation.

---

## Data Quality Findings

### 1. close_date Midnight Timestamp Issue

**Finding:** close_date stored as date-only field (midnight timestamp), not full date-time.

**Impact:** Creates negative gaps when compared against full-timestamp fields.

**Evidence:** 9/10 sample deals showed activity on SAME calendar day but later than midnight, creating -0.2 to -23.4 hour gaps.

**Resolution:** Use stage transition timestamps for precise timing.

**Registry note:** This affects ANY date-diff calculation using close_date. Consider using stage transitions for timing-sensitive metrics company-wide.

### 2. lost_reason Field Not Populated

**Finding:** 100% blank company-wide (0/1121 lost deals).

**HubSpot comparison:** HubSpot shows "Closed Lost Reason" field with 26.5% fill rate, but this field is NOT synced to Supabase.

**Impact:** Cannot use lost_reason as filter or distinguishing characteristic.

**Action:** Investigate sync configuration if lost_reason analytics needed.

### 3. notes_last_updated Coverage Gap

**Finding:** 86% coverage in full population, but only 46% usable coverage after bulk cleanup exclusion.

**Implication:** Bulk cleanup deals had MORE activity history than clean deals (likely touched during cleanup operations).

**Impact:** Clean cohort has lower activity data completeness than contaminated population.

---

**END OF DEFERRAL DOCUMENTATION**
