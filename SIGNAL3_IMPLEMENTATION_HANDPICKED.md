# Signal 3 Implementation: 14-Day Hand-Picked Fallback

## Status: ✅ IMPLEMENTED (Operational Default)

**Date:** 2026-09-07

**Threshold:** 14 days without notes_last_updated activity

**Derivation:** ❌ HAND-PICKED, NOT DERIVED

**Verification Type:** Domain knowledge validated threshold chosen for pragmatic alerting, not empirically derived from GrowthBook's won/lost separation

---

## Executive Summary

Signal 3 (activity recency) is implemented as a **simple 14-day global threshold**: flag deals with no notes_last_updated activity in the last 14 days. This is an **operational default**, not a rigorously derived statistical boundary.

**Why hand-picked instead of derived:** Earlier comprehensive investigation (documented in `SIGNAL3_DEFERRAL_FINAL.md`) found the data source doesn't support empirical threshold derivation:
- Coverage only 46% (below 50% minimum)
- Sample sizes too thin (3/9 cells viable, below 50% threshold)
- No consistent won/lost separation (2/3 cells showed backwards direction)

**14 days is a reasonable operational cutoff** for "deal has gone quiet," confirmed against Jeff's operational intuition for GrowthBook's actual sales cadence (10-14 day range felt right; 14 selected as the specific value). This provides **domain knowledge validation**—a stronger footing than a purely arbitrary pick—but it is still NOT a number backed by GrowthBook's own historical won vs lost patterns. This is a pragmatic choice for immediate operational value, not a statistically validated threshold.

**This implementation is marked as TEMPORARY** - flagged for future refinement when more data accumulates or logging discipline improves.

---

## Explicit Limitations

### 1. Not Segment-Specific (Single Global Cutoff)

**Issue:** 14 days applies equally to Enterprise, Mid-Market, and SMB deals.

**Expected impact:**
- **OVER-FLAG** fast-moving SMB deals where 14 days may be normal engagement pace
- **UNDER-FLAG** slower Enterprise deals where 14 days is trivial (30+ days might be concerning)

**Comparison to Signal 2:** Signal 2 (time-in-stage) uses segment-specific thresholds derived from historical won deals. Signal 3 does NOT have this rigor - it's a single global cutoff because data didn't support segment-specific derivation.

**Same imbalance identified earlier:** When Signal 2 was using a global proxy (before segment-specific derivation), this was flagged as a risk. Signal 3 still has this issue because empirical derivation failed.

---

### 2. Not Stage-Specific

**Issue:** 14 days applies equally to Discovery, Scoping, and Proposal stages.

**Reality:** Different stages may have different natural engagement rhythms:
- Discovery: May involve long evaluation periods with sparse touchpoints
- Proposal: Typically higher-frequency engagement (negotiations, contract review)
- Scoping: Mixed cadence depending on technical complexity

**Why not stage-specific:** Insufficient data to derive stage-specific thresholds. The investigation found only 3/9 stage × segment cells had viable sample sizes.

---

### 3. Coverage Gap Persists (33-36% of Deals)

**Critical distinction:** This is NOT about "no activity in 7 days" - it's about deals with **ZERO activity history at all**.

**Population breakdown:**
- 54% of clean deals have notes_last_updated history in property_history
- 46% have NO history at all (never logged any activity)
- Of the 46% with no history:
  - 33-36% are deals with genuinely zero activity data
  - For these deals, Signal 3 **cannot fire either way**

**Impact on modified-AND logic:**

When a deal has NO activity data:
- Signal 3 result = `no_data` (cannot evaluate)
- Classification routes to `no_signal_at_risk` or `no_signal_healthy`
- Deal evaluated on Signal 2 alone
- Manual-review flag applied (coverage gap, not normal operation)

**A 7-day threshold doesn't solve this** - it's a fundamentally different issue (data completeness, not threshold calibration).

---

### 4. Won Deal Coverage Issue

**Finding from investigation:** 36% of won deals (21/58) have NO activity recorded.

**Interpretation:** Won deals should have engagement history through close (contract review, signature coordination, etc.). High "no activity" rate for won deals suggests:
- Field not consistently populated
- Activity logged in other systems (not notes_last_updated)
- Data quality gap in activity tracking

**Impact:** Even with perfect threshold, Signal 3 cannot flag 36% of won deals if they have no data. This limits signal effectiveness.

---

## Implementation Specification

### Data Source

**Field:** notes_last_updated property history

**Coverage:** 54% (137/253 clean closed deals have activity data)

**Update frequency:** Every activity (note, call, email, meeting, task logged in HubSpot)

**Timestamp precision:** Full date-time (not date-only)

### Threshold Logic

**Simple comparison:** Flag if `days_since_last_activity > 14`

```python
def get_days_since_last_activity(deal_id):
    # Query property_history for most recent notes_last_updated change
    last_activity = sb.table('property_history').select(
        'changed_at'
    ).eq('deal_id', deal_id).eq(
        'property_name', 'notes_last_updated'
    ).order('changed_at', desc=True).limit(1).execute()

    if not last_activity.data:
        return None  # No activity data

    last_activity_date = parse_date(last_activity.data[0]['changed_at'])
    days_since = (current_date - last_activity_date).days

    return days_since

def signal_3_fires(deal_id):
    days_since = get_days_since_last_activity(deal_id)

    if days_since is None:
        return "no_data"  # Cannot evaluate

    return days_since > 14  # True if fires, False if doesn't
```

### Integration with Modified-AND Logic

Signal 3 result feeds into classification matrix:

| Signal 2 | Signal 3 | Classification |
|----------|----------|----------------|
| Fires | Fires | CRITICAL |
| Fires | No fire | WARN |
| Fires | No data | no_signal_at_risk |
| No fire | Fires | HEALTHY |
| No fire | No fire | HEALTHY |
| No fire | No data | no_signal_healthy |

**See:** `Q012_IMPLEMENTATION_FINAL.md` for full modified-AND specification

---

## Rationale for Hand-Picked Threshold

### Why 14 days?

**Operational reasoning:**
- Confirmed against Jeff's operational intuition for GrowthBook's actual sales cadence
- 10-14 day range felt right based on domain knowledge
- 14 selected as the specific value (2 weeks, 10 business days)
- Balances sensitivity (catch real disengagement) with specificity (avoid false alarms)

**Domain knowledge validation:**
- Jeff reviewed GrowthBook's typical sales engagement patterns
- 14 days aligns with their actual deal cadence
- Stronger footing than purely arbitrary pick
- Still NOT empirically derived from won/lost separation data

**NOT based on:**
- GrowthBook's historical won vs lost patterns (data didn't support derivation)
- Statistical separation between outcomes (no clean separation found)
- Segment-specific analysis (insufficient sample sizes)

**Comparison to other thresholds:**
- 7 days: Too aggressive (would flag normal pauses in engagement)
- 21 days: Too lenient (deal could be genuinely stalled for 3 weeks before flag)
- 14 days: Validated against actual sales cadence

**This is a starting point, not an optimized value.** Monitor false positive/negative rates and adjust if needed.

---

## Comparison to Signal 2 (Rigor Contrast)

### Signal 2: Time-in-Stage (DERIVED)

**Methodology:**
- P75 of historical won deal time-in-stage
- Segment-specific (Enterprise/Mid-Market/SMB)
- Stage-specific (Discovery/Scoping/Proposal)
- Minimum sample size n≥5 per cell
- Fallback hierarchy (segment → stage → global)

**Coverage:** 100% (all deals have dealstage history)

**Empirical backing:** Thresholds reflect actual won deal pacing patterns

**Confidence:** High (data-driven, validated sample sizes)

---

### Signal 3: Activity Recency (HAND-PICKED)

**Methodology:**
- Single global 7-day cutoff
- NOT segment-specific
- NOT stage-specific
- No minimum sample size (not derived from data)
- No fallback hierarchy (one threshold for all)

**Coverage:** 54% (only deals with activity history)

**Empirical backing:** None - chosen as operational default

**Confidence:** Low (pragmatic choice, not data-driven)

---

**This contrast is intentional and must be preserved in documentation.** Signal 2 is rigorous, Signal 3 is pragmatic. Both are useful, but they have different levels of validation.

---

## Monitoring and Calibration

### Pre-Launch Validation

**Before production deployment:**

1. **Flagging rate check:**
   - Apply 7-day threshold to active pipeline
   - What % of deals flagged?
   - Does it align with sales team's intuition of "quiet deals"?

2. **Segment balance check:**
   - Flag rate per segment (Enterprise/Mid-Market/SMB)
   - If SMB flag rate >2x Enterprise, threshold may be too aggressive for SMB

3. **Manual review:**
   - Sample 10-20 flagged deals
   - Do they feel "disengaged" to sales team?
   - Adjust threshold if systemic over/under-flagging

### Post-Launch Monitoring

**Monthly review (first 3 months):**

1. **False positive rate:**
   - How many flagged deals closed won quickly after flag?
   - Target: <40% false positive rate

2. **False negative rate:**
   - How many lost deals were never flagged by Signal 3?
   - Target: <60% false negative rate (accept that coverage gap limits effectiveness)

3. **Segment imbalance:**
   - Track flag rate per segment
   - If SMB consistently >2x Enterprise, consider segment-specific thresholds (manual)

4. **Threshold adjustment:**
   - If false positive rate >50%: increase to 10 days
   - If false negative rate >70%: decrease to 5 days
   - Document any changes in config/field_semantics.yaml

---

## Future Refinement Plan

### When to Re-Evaluate

**Trigger conditions for revisiting derivation:**

1. **Coverage improves:** ≥50% of clean closed deals have activity data (currently 46%)

2. **Sample sizes increase:** ≥50% of stage × segment cells with n≥5 per outcome (currently 33%)

3. **Logging discipline improves:** Won deal "no activity" rate drops from 36% to <20%

4. **Discovery × SMB pattern clarified:** Larger sample confirms or refutes inversion hypothesis (currently n=9 won, n=19 lost)

### Re-Derivation Approach

**When conditions met, re-run original methodology:**

1. Compute recency distributions (last activity → outcome date) per stage × segment cell
2. Derive thresholds from won vs lost separation (lost P25 vs won median)
3. Validate expected direction (lost deals silent longer than won deals)
4. Replace 7-day global threshold with segment-specific derived thresholds
5. Update config/field_semantics.yaml: derivation = "DERIVED" (not "HAND_PICKED")

**Full original methodology:** Documented in `SIGNAL3_DEFERRAL_FINAL.md`

---

## Configuration Updates

### config/field_semantics.yaml

```yaml
at_risk_definition:
  verification_type: "partially_derived_partially_hand_picked"

  signals:
    signal_3_activity_recency:
      status: "implemented"
      derivation: "HAND_PICKED"
      threshold: 14  # days
      threshold_type: "global"
      future_refinement_flag: true
```

**Key fields:**
- `derivation: "HAND_PICKED"` - NOT "DERIVED"
- `threshold: 14` - Domain knowledge validated
- `future_refinement_flag: true` - Marked for re-evaluation

### config/signal3_threshold.json

```json
{
  "threshold_days": 14,
  "threshold_type": "global",
  "derivation": "hand_picked",
  "rationale": "Domain knowledge validated threshold chosen for pragmatic alerting. 14 days confirmed against Jeff's operational intuition for GrowthBook's actual sales cadence (10-14 day range felt right; 14 selected as specific value). NOT empirically derived from won/lost separation due to insufficient coverage (46%), sample sizes (3/9 cells), and backwards direction in derivable cells.",
  "last_updated": "2026-09-07",
  "future_refinement_flag": true,
  "re_evaluation_criteria": [
    "Coverage ≥50% of clean closed deals",
    "≥50% of cells with n≥5 per outcome",
    "Consistent won/lost separation across cells",
    "Discovery × SMB pattern clarified"
  ],
  "limitations": {
    "not_segment_specific": "Single 14-day cutoff applies to Enterprise, Mid-Market, and SMB. Will likely over-flag SMB and under-flag Enterprise.",
    "not_stage_specific": "14 days applies equally to Discovery, Scoping, and Proposal stages.",
    "coverage_gap": "33-36% of deals have zero activity history. Signal 3 cannot evaluate for these deals.",
    "won_deal_no_activity": "36% of won deals have no activity recorded (data quality gap)."
  }
}
```

---

## Alert Messaging

### Slack Alert Format

When Signal 3 fires (days_since_activity > 14):

```
⚠️ Deal Disengaged (Signal 3)

Deal: Acme Corp (deal_id: 12345)
Stage: Discovery (Enterprise)
Last activity: 20 days ago (2026-08-18)
Threshold: 14 days

Owner: john@company.com

Action: Review engagement status
```

**IMPORTANT:** Do NOT say "derived threshold" or "statistically validated threshold" in alerts. Keep language neutral ("threshold: 14 days") without implying rigor.

---

## Documentation References

**Full investigation trail:** `SIGNAL3_DEFERRAL_FINAL.md`
- Why derivation failed
- Coverage analysis
- Sample size issues
- Direction problems (backwards patterns)
- Discovery × SMB inversion hypothesis

**Q012 implementation:** `Q012_IMPLEMENTATION_FINAL.md`
- Modified-AND logic with 2 signals
- Classification matrix
- Integration with Signal 2

**Session summary:** `SESSION_SUMMARY_2026-09-07.md`
- Complete investigation journey
- Verification discipline applied
- Lessons learned

---

## Key Takeaways

1. **Honest labeling:** Signal 3 is HAND-PICKED, not derived. This is documented explicitly so it's not confused with Signal 2's rigor.

2. **Domain knowledge validation:** 14 days confirmed against Jeff's operational intuition for GrowthBook's sales cadence—stronger footing than arbitrary pick, though still not empirically derived.

3. **Pragmatic value:** Even without empirical backing, a 14-day threshold provides operational value for catching disengaged deals.

4. **Temporary solution:** Flagged for future refinement when data improves. Not intended as permanent.

5. **Coverage caveat preserved:** 33-36% of deals have no activity data. Modified-AND logic handles this with no_signal classification.

6. **Different confidence levels:** Signal 2 (high confidence, derived) + Signal 3 (medium confidence, domain-validated) = partially rigorous system. This is acceptable and documented.

---

**END OF SIGNAL 3 HAND-PICKED IMPLEMENTATION**
