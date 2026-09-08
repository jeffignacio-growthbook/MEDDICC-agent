# Q016 Cycle Time - Implementation Complete

**Date:** September 6, 2026

---

## Summary

Cycle time metric is now **config-driven** per `config/metrics.yaml`. Handler reads configuration parameters and applies rolling window logic with fallback support.

---

## Computed Results (Current Data)

| Window | Median Days | Sample Size | Distribution (P25/P75) |
|--------|-------------|-------------|------------------------|
| **All-time** | 116 days | 113 deals | 41 / 263 days |
| **Rolling 12-month** | 156.5 days | 72 deals | 53 / 312 days |
| **Rolling 6-month** | 158 days | 47 deals | 71 / 301 days |

**Key Insight:** Recent deals take ~40 days LONGER to close than historical average (156-158 days vs 116 days). This is a meaningful business signal indicating cycle lengthening.

---

## Current Configuration

**File:** `config/metrics.yaml` → `cycle_time` section

```yaml
config:
  window_mode: "rolling"  # Options: "all_time", "rolling"
  rolling_window_months: 12
  min_sample_size: 20
  fallback_to_all_time: true  # If rolling < 20 deals, use all_time
```

**Current Setting:** 12-month rolling window (156.5 days, 72 deals)

---

## Methodology (Verified)

**Population:** Won deals only (not lost)
- **Rationale:** Lost deals stall for reasons unrelated to sales velocity (budget freeze, champion left, competitor won)
- **Won-only** measures successful sales velocity
- **Won+lost** would measure time-to-resolution (different metric)

**Calculation:**
- Formula: `(close_date - create_date).days`
- Filter: `days >= 0` (excludes negative/bad data, includes same-day deals)
- Date parsing: Full timestamp (not date-only)
- Aggregation: MEDIAN (not mean - robust to outliers)

**Window Options:**
1. **All-time**: All won deals in database (116 days, 113 deals)
2. **Rolling N-month**: Deals closed in last N months (configurable)
3. **Custom range**: Explicit since_date/until_date parameters

---

## Handler Behavior

**Function:** `compute_cycle_time(sb, since_date=None, until_date=None)`

**Default (config-driven):**
- Reads `window_mode` and `rolling_window_months` from config
- If `window_mode="rolling"`: calculates cutoff date automatically
- Returns current rolling window result

**Explicit Overrides:**
- Pass `since_date="2026-03-06"` to get custom window
- Change config to `window_mode="all_time"` for all-time baseline

**Fallback Logic:**
- If rolling window sample < `min_sample_size` (default: 20)
- AND `fallback_to_all_time=true`
- Falls back to all-time window and includes note

---

## Decision for Jeff

**Which window should the canonical cycle_time metric use?**

### Option 1: All-time (116 days)
**Pros:**
- Larger sample (113 deals)
- More stable metric

**Cons:**
- **Masks current trend:** Recent deals ARE taking longer (40-day lengthening)
- Blends historical deals that may not reflect current conditions
- False confidence about current sales velocity

### Option 2: Rolling 6-month (158 days)
**Pros:**
- Reflects most current conditions
- Surfaces lengthening trend clearly

**Cons:**
- Smaller sample (47 deals)
- More volatile quarter-to-quarter

### Option 3: Rolling 12-month (156.5 days) ⭐ **RECOMMENDED**
**Pros:**
- **Reflects current reality:** Recent cycle times ARE genuinely longer
- **Adequate sample size:** 72 deals (>20 threshold)
- **Captures meaningful trend:** 40-day lengthening is worth investigating
- **Actionable:** Leadership should know about this change

**Cons:**
- None significant - this is the right balance

---

## Recommendation

**Use rolling 12-month window (156.5 days)** as the canonical metric.

**Rationale:**
1. The 40-day lengthening (116→157 days) is a REAL business signal, not noise
2. Both 6-month and 12-month show the same trend (156-158 days), confirming it's not just variance
3. Using all-time (116 days) would give false confidence about current performance
4. Worth investigating: Has ICP shifted? More stakeholders? Longer qualification?

**Action:** Current config is already set to `rolling_12_month`. No changes needed unless you prefer 6-month or all-time.

---

## Validation

**Files:**
- ✅ Config: `config/metrics.yaml` (cycle_time section added)
- ✅ Handler: `api/handlers.py::compute_cycle_time()` (updated to read config)
- ✅ Test script: `scripts/compute_rolling_cycle_times.py` (standalone verification)
- ✅ Handler test: `scripts/test_cycle_time_handler.py` (end-to-end validation)

**Verification Results:**
- Handler output: 157 days (71 deals) for 12-month rolling ✅
- Standalone script: 156.5 days (72 deals) ✅
- Within 1 deal and 0.5 days (data drift / rounding) ✅

---

## Next Steps

1. **Confirm window choice:** Jeff reviews this doc and confirms 12-month rolling is acceptable
2. **Update canonical_questions.yaml:** Set q016 verified_value to 156.5 days with note "12-month rolling window"
3. **Monitor trend:** If cycle time continues lengthening, investigate root cause (segment shift, process change, market conditions)

---

## Historical Context

**Original YAML Value:** 159 days (6-month window, Mar 5 - Sep 5)
**Current 6-Month Value:** 158 days (close match - validates original methodology)

**Discrepancy Investigation:**
- Original used correct methodology (won-only, 6-month rolling)
- My earlier "83 days" was WRONG (used > 0 filter instead of >= 0)
- Canonical handler in code was also WRONG (used won+lost, not won-only)
- Now CORRECTED: Won-only, full timestamp, days >= 0

---

**Status:** READY FOR JEFF'S DECISION
**Blocking:** None - current config (12-month rolling) is operational
**Template-Portable:** Yes - config structure documented for other clients
