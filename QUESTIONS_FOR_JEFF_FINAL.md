# Questions for Jeff - Q012 and Q016 Final Verification
**Date:** September 6, 2026

---

## Q016: Sales Cycle Time Definition

### Actual Computed Results (September 6, 2026)

| Calculation | Population | Sample | Median | Date Fields | Filter |
|-------------|-----------|--------|--------|-------------|--------|
| **All-time (current data)** | Won only, all-time | 113 won deals | **116 days** | Full timestamp | days >= 0 |
| **Rolling 12-month (current)** | Won only, 12-month window | 72 won deals | **156.5 days** | Full timestamp | days >= 0 |
| **Rolling 6-month (current)** | Won only, 6-month window | 47 won deals | **158 days** | Full timestamp | days >= 0 |
| **Original (YAML - old data)** | Won only, 6-month window (Mar 5 - Sep 5) | 48 won deals | **159 days** | `create_date[:10]` (date only) | days >= 0 |

### Business Logic: Won-Only Is Almost Certainly Correct

Lost deals often stall for reasons unrelated to sales velocity (budget freeze, champion left, competitor won). Blending 1120 lost deals into "cycle time" answers a different question than **"how fast do we close when we win"**.

- **Won-only** measures successful sales velocity
- **Won+lost** measures time-to-resolution (including stalls), which is a distinct metric

**Recommendation:** Use won-only for cycle time metric.

---

### The Real Open Question: All-Time vs Rolling Window

**Current data shows:**
- **All-time:** 116 days median (113 won deals)
- **Rolling 12-month:** 156.5 days median (72 deals)
- **Rolling 6-month:** 158 days median (47 deals)

**Key insight:** Recent deals (6-month and 12-month windows) are taking ~40 days LONGER to close than the all-time average. This suggests sales cycle has lengthened in recent periods, which is a meaningful business signal.

**Why the 40-day difference matters:**

Sales motion and segment mix change over time. The fact that rolling windows show 156-158 days while all-time shows 116 days indicates either:
1. Recent deals are genuinely taking longer (longer qualification, more stakeholders, etc.)
2. Segment mix has shifted toward larger/slower deals
3. Historical data includes faster-closing deals that no longer represent current reality

**Trade-offs:**

| Approach | Pros | Cons |
|----------|------|------|
| **All-Time (116d)** | Largest sample (113 deals), most stable | Masks current lengthening trend |
| **Rolling 6-Month (158d)** | Reflects current conditions, surfaces trend | Smaller sample (47 deals), more volatile |
| **Rolling 12-Month (156.5d)** | Balance: current + stable, good sample size | Still shows current slower reality |

---

### Question for Jeff

**Should the canonical cycle time metric use:**

1. **All-time window** (116 days, 113 deals) - Larger sample, more stable, but masks recent lengthening
2. **Rolling 6-month window** (158 days, 47 deals) - Reflects current reality, smaller sample
3. **Rolling 12-month window** (156.5 days, 72 deals) - Balance of recency and sample size

**My recommendation:** Rolling 12-month window (156.5 days). Here's why:

1. **Reflects current reality:** Recent cycle times ARE genuinely longer (156-158d vs 116d all-time)
2. **Adequate sample size:** 72 deals is statistically sufficient (>20 threshold)
3. **Captures meaningful trend:** If cycle time is lengthening, leadership should know about it
4. **Actionable:** A 40-day lengthening trend is a business issue worth investigating

**The all-time number (116 days) is misleadingly low** - it blends historical faster deals that no longer represent current selling conditions. Using it would give false confidence about current sales velocity.

**Important caveat:** This recommendation assumes the lengthening trend is real. Worth investigating:

- **If sales motion is stable** (same segments, similar deal sizes, consistent team): The 40-day difference suggests process changes or market conditions shifted.
- **If there's been real change** (new segments, different average deal size, team growth/reorg): Rolling window captures current reality better despite smaller sample.

**Data-driven insight from actual numbers:** The 40-day lengthening (116d all-time → 156-158d rolling) is strong evidence that SOMETHING has changed. This isn't just noise - it's a consistent signal across both 6-month and 12-month windows. Whether it's segment mix, ICP shift, or market conditions, the rolling window metric correctly surfaces this change while all-time would hide it.

**Question to consider:** Has GrowthBook's GTM strategy, segment mix, or team structure changed materially in the past 6-12 months? The data suggests yes - worth investigating what's driving the longer cycles.

---

## Q012: At-Risk Deal Definition - Multi-Signal Implementation

### Jeff's 3-Signal Definition - Data Availability

| Signal | Description | Status | Details |
|--------|-------------|--------|---------|
| **1. Low Stakeholder Engagement** | Late-stage enterprise deals with < N contacts/stakeholders | ❌ **NOT COMPUTABLE** | `contacts` table does not exist - data gap |
| **2. Time-in-Stage Outlier** | Deal in current stage longer than 75th percentile for that stage | ⚠️ **PARTIALLY COMPUTABLE** | Can use `updated_at` as proxy (imprecise - changes on ANY update, not just stage changes) |
| **3. Engagement Dropoff** | No two-way engagement in past N days | ⚠️ **PARTIALLY COMPUTABLE** | `calls` table exists (296/444 deals = 67% coverage); `emails`/`notes` tables missing |

---

### Implementation Plan: 2-of-3 Signals Now, 1 Deferred

**Implement Now:**

**Signal 2: Time-in-Stage Outlier (Stage-Specific Top Quartile)**
- **Logic:** For each stage, calculate 75th percentile of time-in-stage from historical closed deals
- **Data Source:** `updated_at` field (proxy for stage change)
- **Limitation:** `updated_at` changes on ANY deal update, not just stage changes (imprecise)
- **Reference:** Ported from `/pandora-starter-kit/server/analysis/engagement-analysis.ts`:
  ```sql
  SELECT stage,
         PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY time_in_stage) AS p75_days
  FROM historical_closed_deals
  GROUP BY stage
  HAVING COUNT(*) >= 5  -- Minimum sample for valid percentile
  ```
- **Flag deals where:** `(now - updated_at) > p75_days` for that deal's current stage

**Signal 3: Engagement Dropoff (Last-Activity Date)**
- **Logic:** Flag deals with no two-way engagement in past N days
- **Data Source:** `calls` table (`MAX(call_date)` per deal)
- **Coverage:** 296 of 444 active deals (67%)
- **Flag deals where:** `(now - MAX(call_date)) > N days`
- **No-signal handling:** 148 deals with no call data flagged as `"no_signal"` (cannot assess)

**Defer (Data Gap):**

**Signal 1: Low Stakeholder Engagement**
- **Status:** Data gap - `contacts` table does not exist
- **Action:** Document in `config/field_semantics.yaml` as `"DEFERRED - awaiting contact tracking"`

---

### Critical Design Question: Signal Combination Logic

**Current recommendation:** Flag as at-risk if **ANY implemented signal fires** (OR logic)

```
at_risk = (signal_2_fires OR signal_3_fires)
```

**Trade-off:**

Given Signal 2 uses an imprecise proxy (`updated_at`) and Signal 3 only covers 67% of deals, **OR logic may produce false positives** (one noisy signal flags the deal).

**Alternative:** Require **BOTH signals to agree** (AND logic) for higher precision

```
at_risk = (signal_2_fires AND signal_3_fires)
```

Or a **weighted/scored approach**:
```
risk_score = (signal_2_weight × signal_2_fires) + (signal_3_weight × signal_3_fires)
at_risk = risk_score > threshold
```

---

### Question for Jeff

**Should at-risk classification require:**

1. **ANY one signal** (OR logic) - Higher recall, more false positives
2. **BOTH signals to agree** (AND logic) - Higher precision, may miss some at-risk deals
3. **Weighted score** (configurable) - Flexible, but requires tuning thresholds

**My recommendation:** Modified AND logic with special handling for no-signal deals (see below).

**Critical limitation of strict AND logic:** Under strict AND logic, the 148 deals with zero call data can **NEVER be flagged at-risk** (Signal 3 permanently unavailable = AND condition permanently fails), regardless of how long they've stalled.

**This may be backwards:** Deals with no logged activity at all are arguably **HIGHEST risk** (genuinely neglected), not exempt from checks.

**Proposed solution:**
- **Deals with both signals available:** Require BOTH to fire (AND logic) for higher precision
- **Deals with no Signal 3 data (no calls):** Evaluate on Signal 2 ALONE (time-in-stage outlier) + flag as `"no_signal - review manually"`
- **Logic:**
  ```python
  if has_call_data:
      at_risk = (signal_2_fires AND signal_3_fires)
  else:
      at_risk = signal_2_fires
      flag_for_manual_review = True  # No activity data = concerning
  ```

This prevents silently passing 33% of pipeline as "not at risk" just because activity data is missing.

---

### Example Classification Output (Modified AND Logic)

```python
at_risk_classification = {
    "critical": [
        # Deals where BOTH signals fire (full data available)
        {"deal_id": "123", "reason": "61 days in Discovery (p75=45d) + 38 days since last call"}
    ],
    "no_signal_at_risk": [
        # Deals flagged on Signal 2 ALONE (no call data available)
        {"deal_id": "456", "reason": "73 days in Discovery (p75=45d) - NO CALL DATA - review manually"}
    ],
    "no_signal_healthy": {
        # Deals with no call data but passing Signal 2 (time-in-stage OK)
        "count": 80,
        "note": "No call data but time-in-stage within normal range"
    },
    "healthy": {
        # Deals passing both signal checks (full data available)
        "count": 200
    }
}
```

**Key difference:** Deals with no activity data aren't silently marked "healthy" - they're evaluated on time-in-stage alone and flagged for manual review if stalled.

---

### Config Structure for field_semantics.yaml

```yaml
at_risk_definition:
  client: "GrowthBook"
  version: "1.0"

  # Signal combination logic
  classification_logic: "AND"  # Options: "AND", "OR", "WEIGHTED"

  # Implemented signals
  signals:
    time_in_stage_outlier:
      status: "IMPLEMENTED_PARTIAL"
      percentile_threshold: 0.75  # Top quartile
      min_sample_per_stage: 5
      data_source: "updated_at (proxy)"
      limitation: "Imprecise - changes on any update"

    engagement_dropoff:
      status: "IMPLEMENTED_PARTIAL"
      critical_days: 30
      warning_days: 21
      data_sources: ["calls"]
      missing_sources: ["emails", "notes"]
      coverage: "67% (296/444 deals)"

    low_stakeholder_engagement:
      status: "DATA_GAP"
      implementation: "DEFERRED - contacts table missing"
      required_data: ["contacts.deal_id", "contacts.engagement_level"]
```

---

### DO NOT Compare to Current 70-Deal Output

The current `compute_at_risk_deals()` returning 70 deals uses an OLD, incomplete definition (likely single MEDDICC threshold, not multi-signal approach).

**After implementing new definition:** Recompute and get Jeff's validation: "Does this count match your independent knowledge of at-risk deals?"

---

**Ready to implement once Jeff answers:**
1. Q016: All-time vs rolling window decision
2. Q012: OR vs AND signal combination logic

