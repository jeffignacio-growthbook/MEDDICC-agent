================================================================================
GENERALIZED BACKTEST ENGINE — AUDIT TRAIL
================================================================================

Metric: pipeline_value
Metric type: sum_dollars
Description: Total value of open pipeline (incremental ARR only, exclude renewals)
Ground truth: 7160865

────────────────────────────────────────────────────────────────────────────────
ITERATION HISTORY
────────────────────────────────────────────────────────────────────────────────

Iteration 0: naive (no hygiene rules)
  Applied rules: ['exclude_renewals']
  Result: 14221229.699996 (n=263)
  Expected: 7160865
  Delta: 7060364.699996
  Status: ✗ MISMATCH

Iteration 1: exclude_renewals
  Applied rules: ['exclude_renewals']
  NEW RULE: exclude_renewals (is_renewal_base)
  Result: 7160865.0 (n=115)
  Expected: 7160865
  Delta: 0.0
  Status: ✓ CONVERGED

────────────────────────────────────────────────────────────────────────────────
FINAL RESULT
────────────────────────────────────────────────────────────────────────────────

✓ CONVERGED
  Converged on iteration: 1
  Final value: 7160865.0 (n=115)
  Applied rules: ['exclude_renewals']

Validated query ready for production use.

================================================================================