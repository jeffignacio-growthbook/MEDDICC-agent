# Signal 3 Threshold Update: 7 Days → 14 Days

**Date:** 2026-09-07

**Status:** ✅ COMPLETE

**Updated by:** Jeff's domain knowledge validation

---

## Summary

Updated Signal 3 (activity recency) threshold from **7 days** to **14 days** based on Jeff's operational intuition for GrowthBook's actual sales cadence. The 10-14 day range felt right for their deal engagement patterns; 14 days selected as the specific value.

This provides **domain knowledge validation**—a stronger footing than a purely arbitrary pick—though still not empirically derived from won/lost separation data.

---

## Files Updated

### 1. config/field_semantics.yaml

**Changes:**
- `threshold: 7` → `threshold: 14`
- Updated methodology note to reflect domain knowledge validation
- Updated all limitation descriptions (7 days → 14 days)
- Updated modified_AND_specification (7 days → 14 days)

**Location:** Lines 394-458

### 2. Q012_IMPLEMENTATION_FINAL.md

**Changes:**
- Signal configuration: "7-day fallback" → "14-day fallback"
- Updated threshold value throughout document (7 → 14)
- Updated rationale to include Jeff's domain knowledge validation
- Updated implementation code example (> 7 → > 14)
- Updated all limitation descriptions

**Key sections updated:** Lines 8, 66-114, 139-169

### 3. SIGNAL3_IMPLEMENTATION_HANDPICKED.md

**Changes:**
- Title: "7-Day" → "14-Day"
- Updated threshold throughout document (7 → 14)
- Expanded rationale section with domain knowledge validation details
- Updated all code examples (> 7 → > 14)
- Updated config examples and alert formatting
- Updated Key Takeaways to reflect domain validation

**Comprehensive update:** Multiple sections throughout file

---

## Threshold Comparison Analysis

### Active Deals (Current Pipeline)

**Finding:** ALL 444 active deals have NO activity data in property_history.

**Implication:** Signal 3 cannot evaluate ANY current active deals. This confirms the coverage gap documented in the deferral investigation:
- 33-36% of deals have zero activity history (not just "no recent activity")
- For these deals, Signal 3 routes to `no_signal_at_risk` / `no_signal_healthy` classification
- Evaluated on Signal 2 alone with manual-review flag

**Coverage:** 0.0% (0/444 deals)

### All Deals (Including Closed)

To validate the threshold change impact, analyzed all 1,000 deals in the system:

**Coverage:**
- With activity data: 632 deals (63.2%)
- No activity data: 368 deals (36.8%)

**Flagging comparison:**
- 7-day threshold: 629 deals flagged
- 14-day threshold: 622 deals flagged
- **Reduction: 7 deals (1.1% fewer flags)**

**Deals in 8-14 day range (sample):**
- Uzum: 10 days (won)
- JOE BROWNS LTD: 12 days (lost)
- LEAP: 12 days (lost)
- ASICS: 12 days (lost)

---

## Key Findings

### 1. Minimal Impact on Flagging Rate

The threshold change from 7 to 14 days results in only **1.1% fewer flags** (7 deals out of 629). This suggests:
- Most silent deals are silent for much longer than 7-14 days
- The 8-14 day range captures very few deals
- Threshold change won't dramatically alter alerting behavior

### 2. Coverage Gap Confirmed

100% of active deals (444/444) have no activity data, confirming the coverage limitation:
- Signal 3 cannot evaluate current pipeline deals
- Modified-AND logic handles this with `no_signal` classification
- Active deals evaluated on Signal 2 (time-in-stage) alone

### 3. Domain Knowledge Validation Strengthens Rationale

While still not empirically derived, the 14-day threshold now has:
- **Operational validation:** Confirmed against Jeff's sales cadence intuition
- **Business context:** Aligned with GrowthBook's actual engagement patterns
- **Stronger footing:** Better than arbitrary pick, though still pragmatic choice

---

## Rationale for 14 Days

### Why 14 Days Feels Right

**Jeff's validation:**
- 10-14 day range aligns with GrowthBook's typical sales cadence
- 14 days selected as specific value (2 weeks, 10 business days)
- Reflects actual deal engagement patterns

**Operational reasoning:**
- Balances sensitivity (catch real disengagement) with specificity (avoid false alarms)
- 7 days felt too aggressive (would flag normal pauses in engagement)
- 14 days provides reasonable buffer for deal-appropriate gaps

**Comparison to alternatives:**
- 7 days: Too aggressive for GrowthBook's cadence
- 21 days: Too lenient (3 weeks is genuinely concerning)
- 14 days: Validated against actual sales motion

---

## Still a Hand-Picked Threshold

**Important context preserved:**

Despite domain knowledge validation, Signal 3 threshold is still **HAND-PICKED, NOT DERIVED**:
- NOT based on GrowthBook's historical won vs lost patterns
- Data didn't support empirical threshold derivation (46% coverage, 3/9 cells viable)
- Full investigation documented in `SIGNAL3_DEFERRAL_FINAL.md`

**This is marked as TEMPORARY:**
- Flagged for future refinement when data improves
- Re-evaluation criteria documented in config/field_semantics.yaml
- Will revisit deriving real threshold when coverage ≥50% and sample sizes increase

---

## Production Impact

### Expected Behavior

**For current active deals (444 deals):**
- Signal 3 will return `no_data` for all deals
- Classification routes to `no_signal_at_risk` or `no_signal_healthy`
- Evaluated on Signal 2 (time-in-stage) alone
- Manual-review flag applied

**For future deals with activity data:**
- 14-day threshold will flag deals with >14 days since last activity
- Expect ~1% fewer flags compared to 7-day threshold
- Aligned with GrowthBook's validated sales cadence

### No Breaking Changes

**Backward compatibility:**
- Classification logic unchanged (modified-AND still applies)
- No code changes needed in handlers or API
- Configuration-driven threshold (easy to adjust)

---

## Monitoring Recommendations

### Post-Update Validation

**Track over next 3 months:**

1. **False positive rate:**
   - How many flagged deals close won quickly after flag?
   - Target: <40% false positive rate

2. **False negative rate:**
   - How many lost deals were never flagged by Signal 3?
   - Target: <60% false negative rate (accept coverage gap limits effectiveness)

3. **Coverage improvement:**
   - Monitor % of active deals with activity data
   - If coverage improves to ≥50%, revisit empirical derivation

4. **Threshold calibration:**
   - If false positive rate >50%: increase to 21 days
   - If false negative rate >70%: decrease to 10 days
   - Document any changes in config/field_semantics.yaml

---

## Next Steps

### Immediate (Complete)

✅ Update config/field_semantics.yaml
✅ Update Q012_IMPLEMENTATION_FINAL.md
✅ Update SIGNAL3_IMPLEMENTATION_HANDPICKED.md
✅ Run threshold comparison analysis
✅ Document findings in this summary

### Short-term (Deploy)

- Deploy updated configuration to production
- Verify Signal 3 evaluation logic uses new 14-day threshold
- Test modified-AND classification with sample deals
- Update Slack alert messaging if needed

### Long-term (Monitor)

- Track flagging outcomes over 3 months
- Monitor coverage improvements
- Re-evaluate empirical derivation when conditions met
- Adjust threshold if false positive/negative rates warrant

---

## Documentation Trail

**Investigation history:**
1. `SIGNAL3_DEFERRAL_FINAL.md` - Original derivation attempt and deferral rationale
2. `SIGNAL3_IMPLEMENTATION_HANDPICKED.md` - Hand-picked implementation specification (now updated to 14 days)
3. `Q012_IMPLEMENTATION_FINAL.md` - Full Q012 at-risk identification specification
4. `SESSION_SUMMARY_2026-09-07.md` - Original investigation session summary
5. **This document** - Threshold update from 7 to 14 days with validation

**Script created:**
- `scripts/compare_signal3_thresholds.py` - Reusable threshold comparison tool

---

## Key Takeaways

1. **Domain knowledge validation:** 14 days confirmed against Jeff's operational intuition—stronger footing than arbitrary pick

2. **Minimal flagging impact:** Only 1.1% fewer flags (7 deals) at 14 vs 7 days—most silent deals are silent much longer

3. **Coverage gap persists:** 100% of active deals have no activity data—Signal 3 cannot evaluate current pipeline

4. **Still hand-picked:** Despite validation, threshold is NOT empirically derived from won/lost separation

5. **Temporary solution:** Flagged for future refinement when data improves

6. **Configuration-driven:** Easy to adjust threshold if monitoring reveals need for calibration

---

**END OF THRESHOLD UPDATE DOCUMENTATION**
