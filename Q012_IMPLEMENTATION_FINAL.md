# Q012 Implementation: At-Risk Deal Identification

## Status: ✅ READY FOR IMPLEMENTATION

**Date:** 2026-09-07

**Signal Configuration:** Signal 2 (derived) + Signal 3 (hand-picked 14-day fallback)

**Verification Type:** PARTIALLY DERIVED, PARTIALLY HAND-PICKED

---

## Executive Summary

Q012 (at-risk deal identification) is ready for implementation using **Signal 2 (time-in-stage)** only. Signal 1 (stakeholder count) and Signal 3 (activity recency gap) are explicitly deferred with documented rationale. The modified-AND logic adapts to single-signal operation: flag deals exceeding their segment-specific time-in-stage threshold.

**Implementation approach:** Segment-first methodology with stage × segment thresholds derived from historical won deal distributions. No manual threshold selection - all values data-driven.

---

## Signal Configuration

### Signal 1: Stakeholder Count (DEFERRED)

**Status:** ❌ Deferred

**Reason:** Required fields not available in current data schema.

**Fields needed:**
- Engagement count per contact
- Contact-to-deal associations
- Contact roles/influence levels

**Current data:** deals table has no contact association fields.

**Implication:** Cannot derive or implement stakeholder-based signals without CRM schema expansion.

**Re-evaluation criteria:** When contact-to-deal associations are added to data model.

---

### Signal 2: Time-in-Stage (IMPLEMENTED)

**Status:** ✅ Ready for implementation

**Definition:** Flag deals where time in current stage exceeds segment-specific 75th percentile of historical won deals in that stage.

**Data source:** dealstage property history (100% coverage, 2,009 changes across 737 deals)

**Derivation status:** Thresholds derived from historical data per stage × segment cell.

**Methodology:** Within-segment percentile (NOT global). Enterprise deals naturally sit longer than SMB - thresholds must reflect segment-specific pacing.

**Thresholds:** TO BE DERIVED - need to run derivation script using dealstage property history.

**Fallback logic:**
1. Use stage × segment threshold if available
2. Fall back to stage-only threshold if segment insufficient
3. Fall back to global 75th percentile if stage insufficient
4. No flagging if global sample <20 deals

---

### Signal 3: Activity Recency Gap (IMPLEMENTED - HAND-PICKED FALLBACK)

**Status:** ✅ Implemented (14-day global threshold)

**Derivation:** ❌ HAND-PICKED, NOT DERIVED

**Threshold:** 14 days without notes_last_updated activity

**EXPLICIT DOCUMENTATION REQUIRED:**

This is a **simple operational default**, NOT an empirically derived threshold. The earlier investigation found this data source doesn't support rigorous threshold derivation:

**Why not derived:**
- **Coverage:** Only 46% (116/253 clean deals have activity data)
- **Sample sizes:** Only 3/9 cells viable (below 50% threshold)
- **Direction:** 2/3 derivable cells showed incorrect or no won/lost separation
- **Discovery × SMB inversion:** Won median 49d vs Lost P25 2d (hypothesis preserved)

**14 days confirmed against Jeff's operational intuition** for GrowthBook's actual sales cadence (10-14 day range felt right; 14 selected as the specific value). This provides domain knowledge validation—a stronger footing than a purely arbitrary pick, though still not empirically derived from GrowthBook's own won/lost separation data.

**Limitations:**

1. **Not segment-specific:** Single global 14-day cutoff
   - Will likely **OVER-FLAG** fast-moving SMB deals (where 14 days may be normal pace)
   - Will likely **UNDER-FLAG** slower Enterprise deals (where 14 days is trivial, 30+ days might be concerning)
   - Same imbalance identified as a risk when Signal 2 used global proxy before segment-specific derivation

2. **Not stage-specific:** 14 days applies equally to Discovery, Scoping, and Proposal
   - Different stages may have different natural engagement rhythms
   - Insufficient data to derive stage-specific thresholds

3. **Coverage gap persists:** 33-36% of deals have ZERO activity history
   - Not just "no activity in 14 days" — literally never logged any notes_last_updated changes
   - For these deals, Signal 3 cannot fire either way
   - Route to `no_signal_at_risk` / `no_signal_healthy` split
   - Evaluated on Signal 2 alone with manual-review flag
   - **A 14-day threshold doesn't change the fact that some deals have no data to check**

**Full investigation:** See `SIGNAL3_DEFERRAL_FINAL.md` for complete derivation attempt trail

**Future refinement flag:** ⚠️ REVISIT when data improves

Once more data accumulates or logging discipline improves, **REVISIT deriving a real threshold** per the original methodology (won vs lost recency separation, segment-specific) rather than leaving 14 days as a permanent placeholder.

**Re-evaluation criteria:**
- Coverage ≥50% of clean closed deals
- ≥50% of stage × segment cells with n≥5 per outcome
- Consistent won/lost separation across cells
- Discovery × SMB pattern clarified with larger sample

---

## Modified-AND Logic with 2 Signals

**Original design:** Flag deal if Signal 1 AND (Signal 2 OR Signal 3) both fire.

**Adapted for 2 signals (Signal 1 deferred):** Flag deal based on Signal 2 AND Signal 3 combination.

**Signal configuration:**
- Signal 1 (stakeholder count): ❌ Deferred (fields not available)
- Signal 2 (time-in-stage): ✅ Implemented (DERIVED, segment-specific)
- Signal 3 (activity gap): ✅ Implemented (HAND-PICKED, 7-day global)

**Classification Matrix:**

| Signal 2 | Signal 3 | Classification | Interpretation |
|----------|----------|----------------|----------------|
| Fires | Fires | **CRITICAL** | Stalled (long time) AND disengaged (no activity) |
| Fires | No fire | **WARN** | Long time but recent activity (may be actively working) |
| Fires | No data | **no_signal_at_risk** | Long time, cannot check activity (manual review) |
| No fire | Fires | **HEALTHY** | Recent activity, normal pacing |
| No fire | No fire | **HEALTHY** | Normal pacing, engaged |
| No fire | No data | **no_signal_healthy** | Normal pacing, cannot check activity (manual review) |

**Implementation:**
```python
def classify_deal_risk(deal):
    # Signal 2: Time-in-stage (DERIVED, segment-specific)
    stage_bucket = stage_bucket(deal.stage)
    segment = deal.segment
    time_in_stage_days = (current_date - deal.stage_entered_date).days
    signal_2_threshold = get_time_in_stage_threshold(stage_bucket, segment)
    signal_2_fires = time_in_stage_days > signal_2_threshold if signal_2_threshold else None

    # Signal 3: Activity recency (HAND-PICKED, 14-day global)
    last_activity_date = get_last_activity_date(deal.deal_id)

    if last_activity_date is None:
        signal_3_result = "no_data"
    else:
        days_since_activity = (current_date - last_activity_date).days
        signal_3_fires = days_since_activity > 14
        signal_3_result = "fires" if signal_3_fires else "no_fire"

    # Modified-AND classification
    if signal_2_fires and signal_3_result == "fires":
        return "critical"
    elif signal_2_fires and signal_3_result == "no_fire":
        return "warn"
    elif signal_2_fires and signal_3_result == "no_data":
        return "no_signal_at_risk"  # Manual review flag
    elif not signal_2_fires and signal_3_result == "no_data":
        return "no_signal_healthy"  # Manual review flag
    else:
        return "healthy"
```

**Coverage caveat:** 33-36% of deals have NO activity history at all (not in property_history). For these deals, Signal 3 cannot evaluate, and they receive `no_signal_*` classification with manual-review flag. Signal 2 still evaluates (stage timing independent of activity logging).

---

## Signal 2 Derivation Specification

### Data Source

**Field:** dealstage property history

**Coverage:** 100% (737/737 closed deals have dealstage history)

**Data structure:**
```
property_history table:
- deal_id
- property_name = 'dealstage'
- changed_at (timestamp)
- new_value (stage value)
```

### Methodology

**Population:** Historical won deals only (exclude lost deals)

**Exclusions:**
1. Bulk cleanup deals (750 deals from Q016 investigation)
2. Negative cycle time deals (create_date > close_date)

**Calculation per deal:**
1. Sort dealstage changes chronologically
2. For each stage transition, compute time spent in previous stage
3. Exclude time in closed stages (closedwon, closedlost)
4. Group time-in-stage values by stage × segment

**Threshold derivation:**
- 75th percentile of time-in-stage distribution per stage × segment cell
- Minimum sample size: 5 won deals per cell
- Fallback hierarchy: segment → stage → global

### Expected Thresholds (To Be Derived)

**Stage × Segment cells to derive:**

| Stage | Segment | Expected Sample | Threshold Derivation |
|-------|---------|----------------|----------------------|
| discovery | Enterprise | ? won deals | P75 of time-in-discovery |
| discovery | Mid-Market | ? won deals | P75 of time-in-discovery |
| discovery | SMB | ? won deals | P75 of time-in-discovery |
| proposal | Enterprise | ? won deals | P75 of time-in-proposal |
| proposal | Mid-Market | ? won deals | P75 of time-in-proposal |
| proposal | SMB | ? won deals | P75 of time-in-proposal |
| scoping | Enterprise | ? won deals | P75 of time-in-scoping |
| scoping | Mid-Market | ? won deals | P75 of time-in-scoping |
| scoping | SMB | ? won deals | P75 of time-in-scoping |

**Note:** Actual sample sizes and thresholds to be computed by derivation script.

---

## Implementation Steps

### Step 1: Derive Signal 2 Thresholds

**Script to create:** `derive_signal2_time_in_stage.py`

**Inputs:**
- deals table (won deals only, after exclusions)
- property_history table (dealstage changes)

**Outputs:**
- Threshold per stage × segment cell
- Sample size per cell
- Fallback thresholds (stage-only, global)

**Validation:**
- Verify sample sizes ≥5 per cell
- Verify Enterprise thresholds > SMB thresholds (slower pace)
- Verify thresholds align with business intuition

### Step 2: Implement Threshold Lookup

**Function:** `get_time_in_stage_threshold(stage_bucket, segment)`

**Logic:**
```python
def get_time_in_stage_threshold(stage_bucket, segment):
    # Try stage × segment
    threshold = thresholds.get((stage_bucket, segment))
    if threshold and threshold['sample_size'] >= 5:
        return threshold['threshold_days']

    # Fall back to stage-only
    stage_threshold = stage_thresholds.get(stage_bucket)
    if stage_threshold and stage_threshold['sample_size'] >= 5:
        return stage_threshold['threshold_days']

    # Fall back to global
    if global_threshold and global_threshold['sample_size'] >= 20:
        return global_threshold['threshold_days']

    # No threshold available
    return None
```

### Step 3: Implement At-Risk Flagging

**Handler:** `identify_at_risk_deals()`

**Logic:**
```python
def identify_at_risk_deals():
    # Get active pipeline deals
    active_deals = get_active_deals()

    at_risk_deals = []

    for deal in active_deals:
        stage_bucket = stage_bucket(deal.stage)
        segment = deal.segment

        # Skip if in closed stage
        if stage_bucket in ['closed_won', 'closed_lost']:
            continue

        # Get stage entry date
        stage_entered_date = get_stage_entry_date(deal.deal_id, deal.stage)
        if not stage_entered_date:
            continue

        # Compute time in stage
        time_in_stage_days = (current_date - stage_entered_date).days

        # Get threshold
        threshold = get_time_in_stage_threshold(stage_bucket, segment)
        if not threshold:
            continue  # No threshold available, skip flagging

        # Check if at risk
        if time_in_stage_days > threshold:
            at_risk_deals.append({
                'deal_id': deal.deal_id,
                'company_name': deal.company_name,
                'stage': deal.stage,
                'segment': deal.segment,
                'time_in_stage_days': time_in_stage_days,
                'threshold_days': threshold,
                'days_over_threshold': time_in_stage_days - threshold
            })

    return at_risk_deals
```

### Step 4: Integration with Slack Agent

**Handler addition:** Add `identify_at_risk_deals()` to CRO Slack Agent handlers.

**Query patterns:**
- "Which deals are at risk?"
- "Show me stalled deals"
- "Deals that have been sitting too long"

**Response format:**
```
At-Risk Deals (Signal 2: Time-in-Stage)

Discovery stage:
• Acme Corp (Enterprise) - 120 days in stage (threshold: 90 days, +30 days over)
• Beta Inc (Mid-Market) - 65 days in stage (threshold: 45 days, +20 days over)

Proposal stage:
• Gamma Ltd (SMB) - 40 days in stage (threshold: 30 days, +10 days over)

Total: 3 deals flagged
```

---

## Monitoring and Alerting

### Daily Check

**Frequency:** Daily (2am UTC via GitHub Actions)

**Logic:**
1. Fetch active pipeline deals
2. Compute time-in-stage for each deal
3. Compare against thresholds
4. Flag deals exceeding threshold
5. Store results in Supabase `at_risk_deals` table

### Alert Triggers

**Slack notification when:**
1. Deal newly flagged as at-risk (crossed threshold since last check)
2. Deal remains at-risk for 7+ days (escalation alert)
3. At-risk deal count increases by >20% week-over-week (systemic issue)

**Notification format:**
```
⚠️ New At-Risk Deal Alert

Deal: Acme Corp (deal_id: 12345)
Stage: Discovery (Enterprise)
Time in stage: 120 days
Threshold: 90 days
Days over: +30 days

Owner: john@company.com
Last activity: 2026-09-01 (6 days ago)

Action: Review deal status and next steps
```

---

## Validation and Calibration

### Pre-Launch Validation

**Before production deployment:**

1. **Historical accuracy check:**
   - Apply thresholds to past closed deals
   - Measure: What % of lost deals would have been flagged?
   - Target: ≥50% of lost deals flagged (sensitivity)
   - Measure: What % of won deals would have been flagged?
   - Target: ≤30% of won deals flagged (specificity)

2. **Current pipeline scan:**
   - Apply thresholds to active pipeline
   - Review flagged deals with sales team
   - Confirm: Do flagged deals feel "at risk"?
   - Adjust thresholds if systemic over/under-flagging

3. **Threshold reasonableness:**
   - Compare against business intuition
   - Enterprise discovery: expect 60-90 days
   - SMB discovery: expect 20-40 days
   - Validate derived thresholds align with expectations

### Post-Launch Monitoring

**Monthly review (first 3 months):**
1. Track flagged deal outcomes (win/loss rate of at-risk deals)
2. Measure false positive rate (flagged deals that closed won quickly)
3. Measure false negative rate (lost deals that were never flagged)
4. Adjust thresholds based on outcomes

**Target accuracy:**
- Sensitivity (lost deals flagged): ≥60%
- Specificity (won deals not flagged): ≥70%
- Precision (flagged deals that lose): ≥40%

---

## Limitations and Caveats

### 1. Single-Signal Operation

**Limitation:** With only Signal 2 active, at-risk detection is less comprehensive than 3-signal design.

**Implication:** May miss at-risk deals that have normal time-in-stage but lack stakeholder engagement or activity.

**Mitigation:** Document clearly that this is phase 1. Expand to multi-signal when data availability improves.

### 2. Won-Deal-Only Calibration

**Limitation:** Thresholds derived from won deals (75th percentile). Does not use lost deal patterns.

**Implication:** Threshold represents "upper bound of normal won behavior" rather than "separation point between won and lost."

**Rationale:** Lost deals may have been stalled for various reasons (not just time). Won deal pacing is cleaner baseline.

**Mitigation:** Monitor false positive rate. If >40% of flagged deals close won, thresholds may be too aggressive.

### 3. Segment-Specific Thresholds

**Limitation:** Requires sufficient won deals per segment for reliable P75.

**Implication:** If segment has <5 won deals in a stage, threshold may be unreliable or fall back to broader aggregation.

**Mitigation:** Fallback hierarchy ensures graceful degradation (segment → stage → global).

### 4. Stage Entry Date Precision

**Limitation:** Depends on dealstage property history completeness.

**Implication:** If deal's stage history is incomplete, time-in-stage calculation may be inaccurate.

**Mitigation:** Use stage history from property_history table (100% coverage validated). Log warning if stage entry date missing.

---

## Future Enhancements

### Phase 2: Add Signal 3 (Activity Recency)

**When:** Coverage improves to ≥50% and sample sizes increase.

**Logic:** Combine Signal 2 AND Signal 3 with OR logic:
- Flag if (time-in-stage > threshold) OR (activity-gap > threshold)

**Benefit:** Catch deals that are moving through stages but lack engagement.

### Phase 3: Add Signal 1 (Stakeholder Count)

**When:** Contact-to-deal associations added to data model.

**Logic:** Full 3-signal modified-AND:
- Flag if (stakeholder-count < threshold) AND [(time-in-stage > threshold) OR (activity-gap > threshold)]

**Benefit:** Comprehensive at-risk detection across multiple dimensions.

### Phase 4: Machine Learning Enhancement

**When:** Sufficient labeled data (12+ months of outcomes with at-risk flags).

**Approach:**
- Train classification model: predict deal outcome (won/lost) from signals
- Use model confidence scores to rank at-risk deals by severity
- Threshold ML confidence instead of individual signals

**Benefit:** More accurate risk scoring, accounts for signal interactions.

---

## Configuration Files

### config/signals.yaml

```yaml
q012_at_risk_deals:
  enabled: true
  signal_configuration:
    signal_1_stakeholder_count:
      enabled: false
      reason: "Required fields not available"
      re_evaluation_criteria: "When contact-to-deal associations added"

    signal_2_time_in_stage:
      enabled: true
      data_source: "property_history.dealstage"
      coverage: "100%"
      threshold_methodology: "P75 of won deals per stage x segment"
      min_sample_size: 5
      fallback_hierarchy: ["stage_x_segment", "stage_only", "global"]

    signal_3_activity_gap:
      enabled: false
      reason: "Insufficient coverage (46%) and sample sizes (3/9 cells)"
      full_documentation: "SIGNAL3_DEFERRAL_FINAL.md"
      re_evaluation_criteria:
        - "Coverage ≥50% of clean closed deals"
        - "≥50% of cells with n≥5 per outcome"
        - "Consistent won/lost separation"

  logic: "single_signal"  # Modified-AND with 1 signal = direct evaluation

  thresholds_file: "config/signal2_time_in_stage_thresholds.json"

  monitoring:
    daily_check: true
    alert_on_new_at_risk: true
    alert_on_prolonged_at_risk_days: 7
    alert_on_count_increase_pct: 20
```

---

## Next Steps

1. **Create derivation script:** `derive_signal2_time_in_stage.py`
   - Input: deals table + property_history (dealstage changes)
   - Output: Thresholds per stage × segment cell
   - Validation: Sample sizes, threshold reasonableness

2. **Run threshold derivation:**
   - Execute script on historical won deals
   - Review derived thresholds with sales team
   - Confirm thresholds align with business intuition

3. **Implement at-risk handler:**
   - Add `identify_at_risk_deals()` to handlers.py
   - Integrate with Slack Agent query routing
   - Add unit tests

4. **Pre-launch validation:**
   - Historical accuracy check (sensitivity/specificity)
   - Current pipeline scan (sales team review)
   - Threshold calibration if needed

5. **Deploy to production:**
   - Enable daily monitoring (GitHub Actions)
   - Configure Slack alerts
   - Document in canonical_questions.yaml

6. **Post-launch monitoring:**
   - Track flagged deal outcomes (monthly for 3 months)
   - Measure accuracy metrics
   - Adjust thresholds based on outcomes

---

## Success Criteria

**Q012 is successfully implemented when:**

1. ✅ Signal 2 thresholds derived from historical data
2. ✅ At-risk handler integrated with Slack Agent
3. ✅ Daily monitoring and alerting operational
4. ✅ Pre-launch validation completed (sensitivity ≥50%, specificity ≥70%)
5. ✅ Documentation complete (runbook, API docs, user guide)
6. ✅ Sales team trained on at-risk deal workflow

**Long-term success metrics (3 months post-launch):**

- At-risk deals have higher loss rate than non-flagged deals (validates signal)
- Sales team takes action on ≥60% of flagged deals (validates utility)
- False positive rate <40% (validates threshold accuracy)
- User satisfaction: Sales leaders find alerts actionable and useful

---

**END OF Q012 IMPLEMENTATION SPECIFICATION**
