================================================================================
BACKTEST ENGINE — AUDIT TRAIL
================================================================================

Metric: cycle_time
Description: Median days from deal created_at to close_date for won deals
Ground truth: 52 days
Validated by: Jeff (Q016 investigation, Sep 2026)
Tolerance: ±3 days

────────────────────────────────────────────────────────────────────────────────
ITERATION HISTORY
────────────────────────────────────────────────────────────────────────────────

Iteration 0: won deals only
  Applied rules: ['exclude_renewals']
  Result: 95 days (n=121)
  Expected: 52 days
  Delta: 43.0 days
  Status: ✗ MISMATCH

Iteration 1: won deals only + exclude renewal pipeline
  Applied rules: ['exclude_renewals']
  NEW RULE: exclude_renewals (is_renewal_base)
  Result: 52 days (n=23)
  Expected: 52 days
  Delta: 0.0 days
  Status: ✓ CONVERGED

────────────────────────────────────────────────────────────────────────────────
FINAL RESULT
────────────────────────────────────────────────────────────────────────────────

✓ CONVERGED
  Converged on iteration: 1
  Final value: 52 days (n=23)
  Applied rules: ['exclude_renewals']

Validated query ready for production use.

================================================================================