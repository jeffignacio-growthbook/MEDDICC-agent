# Wave 4 Calibration - Questions Requiring Client-Verified Values

**Date**: 2026-09-05
**Purpose**: Get known-true values from Jeff for 11 canonical questions currently marked `null`

These verified values will be used to:
1. Test the CRO Slack agent's accuracy (calibration run)
2. Power Trigger 5 (metric divergence monitor)
3. Validate semantic layer correctness

---

## Instructions

For each question below, please provide:
- The **exact value** as of today (Sep 5, 2026)
- **Source** (HubSpot report, dashboard screenshot, or manual query)
- Any **caveats** (date range, exclusions, etc.)

---

## 11 Questions Needing Values

### 1. Renewal Pipeline - Q3 & Q4 (q002)

**Question**: *"How much expansion ARR is in the renewal pipeline for Q3 and Q4?"*

**What we need**:
```yaml
q3_renewal_pipeline:
  base_renewal: $___________
  expansion: $___________
  total: $___________

q4_renewal_pipeline:
  base_renewal: $___________
  expansion: $___________
  total: $___________
```

**Where to find**: HubSpot forecast report filtered to renewal pipeline, grouped by quarter

---

### 2. Customers Due to Renew (q008)

**Question**: *"Get a list of all customers due to renew in Q3 and then Q4"*

**What we need**:
```yaml
q3_renewals:
  count: ___
  arr_value: $___________

q4_renewals:
  count: ___
  arr_value: $___________
```

**Where to find**: Renewal pipeline deals with close date in each quarter

---

### 3. Recent Closed-Lost Count (q010)

**Question**: *"Why did we lose our last three deals?"*

**What we need**:
```yaml
recent_closed_lost:
  count: ___ (last 3, or count in past 30 days if < 3 recently)
  deals:
    - company_name: ___________
      loss_reason: ___________
      close_date: YYYY-MM-DD
    # ... (list 3)
```

**Where to find**: HubSpot deals filtered to closed-lost, sorted by close date descending

---

### 4. Active Pipeline Value (q011)

**Question**: *"What is our pipeline this quarter?"*

**What we need**:
```yaml
q3_active_pipeline:
  total_arr: $___________
  deal_count: ___
  by_stage:  # Optional, but helpful
    - stage_name: ___________
      arr: $___________
      count: ___
```

**Where to find**: HubSpot pipeline report for Q3 active deals (exclude closed won/lost)

---

### 5. At-Risk Deals (q012)

**Question**: *"Which of those are at risk?"*

**What we need**:
```yaml
at_risk_deals:
  count: ___
  arr_value: $___________
  definition: "Deals flagged as at-risk based on: ___________"
  # (e.g., "no activity in 30 days", "stage duration > 2x normal", etc.)
```

**Where to find**: Define "at-risk" criteria first, then query HubSpot or provide manual list

---

### 6. Historical Win Rate by Stage (q016 part 1)

**Question**: *"Would you be able to calculate historical win rates by stage?"*

**What we need**:
```yaml
historical_win_rates:
  overall: ___%
  by_stage:  # For each key stage
    - stage_name: "Discovery"
      win_rate: ___%
      sample_size: ___
    - stage_name: "Proposal"
      win_rate: ___%
      sample_size: ___
    # ... (add more stages as needed)
  date_range: "YYYY-MM-DD to YYYY-MM-DD"
```

**Where to find**: HubSpot reports > Deals > Win rate by stage (use deals that closed in past 6-12 months)

---

### 7. Sales Cycle Time by Stage (q016 part 2)

**Question**: *"Calculate sales cycle times by stage?"*

**What we need**:
```yaml
sales_cycle_times:
  overall_median_days: ___
  by_stage:
    - stage_name: "Discovery"
      median_days_in_stage: ___
    - stage_name: "Proposal"
      median_days_in_stage: ___
    # ... (add more)
  date_range: "YYYY-MM-DD to YYYY-MM-DD"
```

**Where to find**: HubSpot deals > Create date to close date for won deals, stage duration analysis

---

### 8. Deals with Champion Score > 6, Close in Q3 (q009)

**Question**: *"Which deals have a champion score above 6 and close in Q3?"*

**What we need**:
```yaml
high_champion_q3_deals:
  count: ___
  arr_value: $___________
  deals:  # Optional - list a few examples
    - company_name: ___________
      champion_score: ___
      arr: $___________
```

**Where to find**: MEDDICC agent analyses table filtered by champion component score > 6, join with deals closing in Q3

---

### 9. Owner Email Completeness (q020)

**Question**: *"How many active deals are missing owner_email?"*

**What we need**:
```yaml
missing_owner_email:
  count: ___
  total_active_deals: ___
  pct: ___%
```

**Where to find**: HubSpot deals > Active > Filter where owner is unknown/unassigned

---

### 10. Skyscanner Deal Details (q013)

**Question**: *"Show me the Skyscanner deal"*

**What we need**:
```yaml
skyscanner_deal:
  exists: true/false
  # If exists:
  deal_id: ___________
  stage: ___________
  arr: $___________
  owner: ___________
  close_date: YYYY-MM-DD
  status: active/won/lost
```

**Where to find**: HubSpot search for "Skyscanner" in deals

---

### 11. Stale Forecast Table Status (q019)

**Question**: *"When was forecast_weekly last updated?"*

**What we need**:
```yaml
forecast_weekly_status:
  last_computed: "YYYY-MM-DD HH:MM"
  days_since_update: ___
  expected_refresh_interval: "daily/weekly"
```

**Where to find**: Supabase query: `SELECT MAX(computed_at) FROM forecast_weekly`

**NOTE**: This one can be queried programmatically - we may not need Jeff's input for this specific question.

---

## How to Submit

**Option 1**: Fill out this document directly and save as `WAVE_4_JEFF_RESPONSES.md`

**Option 2**: Provide values in Slack/email, referencing question IDs (q002, q008, etc.)

**Option 3**: Screen share and walk through HubSpot reports together

---

## Priority Order

If time is limited, prioritize in this order:
1. **q011** (Active pipeline value) - Most commonly asked
2. **q016** (Historical win rates & cycle times) - Needed for forecast modeling
3. **q002** (Renewal pipeline Q3/Q4) - Business critical
4. **q012** (At-risk deals) - Define criteria first
5. **q010** (Recent closed-lost) - For loss analysis
6. Rest as time allows

---

## Once Complete

After Jeff provides these values:
1. Update `config/canonical_questions.yaml` with verified_value for each
2. Run full calibration: `python scripts/run_calibration.py`
3. Report accuracy (Correct/Wrong/Unanswerable lists + fallback rate)
4. Wire Trigger 5 (metric_divergence) to use these verified values

---

**Status**: Awaiting Jeff's input (11 questions with null verified_value)
**Deadline**: Before enabling Trigger 5 (metric divergence monitor)
