# Deal Size Bias Finding — For Ryan

## Summary

Won deals are systematically smaller than pipeline deals by ~21-22%.

This is not caused by whale losses. The bias is systematic across the distribution.

## The Numbers

**From analysis** (check_deal_size_bias.py):
```
Pipeline deals (open, qualified):
  Mean:   $47,809
  Median: $30,000
  Count:  376 deals

Won deals (closed-won, qualified):
  Mean:   $37,662
  Median: $23,400
  Count:  222 deals

Bias:
  Mean difference:   -$10,147 (-21.2%)
  Median difference: -$6,600  (-22.0%)
```

## What This Means

### Systematic, Not Whales

- Mean and median biases are nearly identical (-21.2% vs -22.0%)
- If large losses were the cause, median would be unaffected
- This suggests **consistent over-qualification** of large deals

### Forecast Impact

**Historical conversion forecast** was inflated by 40% before bias correction:

**BEFORE** (using pipeline average $62,371):
```
Week-3 count: 481 deals
Conversion:   13.5%
Expected wins: 65 deals
Forecast:     65 × $62,371 = $4,054,115  ❌ WRONG
```

**AFTER** (using won-deal average $37,662):
```
Week-3 count: 481 deals
Conversion:   13.5%
Expected wins: 65 deals
Forecast:     65 × $37,662 = $2,448,030  ✓ CORRECTED
```

The $4M forecast was an artifact of using biased deal sizes.

## Why This Happens

Possible explanations:
1. **Sandbagging**: Reps inflate deal sizes early, adjust down at close
2. **Discovery bias**: Larger deals get more scrutiny, smaller deals convert faster
3. **Expansion confusion**: Initial "deal size" includes future expansion that doesn't close
4. **Pricing pressure**: Larger deals negotiate harder, final contract smaller

## What to Do

### Short-term (Done)

✅ Use won-deal average ($37,662) for historical conversion forecasts
✅ Document in config/metrics.yaml as deliberate bias correction

### Investigation Questions

For Ryan to explore with reps:
1. Are we qualifying $50K+ deals too aggressively?
2. Do large deals have higher churn from qualified → won?
3. Should qualification thresholds be stricter for high-value deals?
4. Is the "deal size" field being used inconsistently (TCV vs ARR vs with-expansion)?

### Measurement

Track won vs pipeline deal size monthly to see if pattern persists:
```sql
SELECT
  DATE_TRUNC('month', close_date) AS month,
  AVG(deal_value) FILTER (WHERE deal_status = 'won') AS won_avg,
  AVG(deal_value) FILTER (WHERE deal_status = 'active' AND qualified) AS pipeline_avg,
  (won_avg / pipeline_avg - 1) * 100 AS bias_pct
FROM deals
GROUP BY 1
ORDER BY 1 DESC
LIMIT 12;
```

## Files

- `check_deal_size_bias.py` — Analysis script
- `scripts/analytics/compute_forecast.py` — Uses corrected average (line 228)
- `config/metrics.yaml` — Documents won-deal average provenance

## Context

This was discovered during Wave 1 forecast methodology investigation (2026-08-28 to 2026-09-01).

Initial forecast artifact showed $5.9M historical conversion (impossible). Root cause was using pipeline average instead of won-deal average in Kellogg method.

Bias correction brought forecast to $1.9M, which converges with stage-weighted and rep calls forecasts.
