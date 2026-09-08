================================================================================
GENERALIZED BACKTEST ENGINE — AUDIT TRAIL
================================================================================

Metric: pipeline_value_unfiltered
Metric type: None
Description: Total pipeline value WITH NO FILTERS (should be contaminated)
Ground truth: 14221230

────────────────────────────────────────────────────────────────────────────────
ITERATION HISTORY
────────────────────────────────────────────────────────────────────────────────

Iteration 0: naive (no hygiene rules)
  Applied rules: none
  Result: 14221229.699996 (n=263)
  Expected: 14221230
  Delta: 0.30000399984419346
  Status: ✓ CONVERGED

────────────────────────────────────────────────────────────────────────────────
FINAL RESULT
────────────────────────────────────────────────────────────────────────────────

✓ CONVERGED
  Converged on iteration: 0
  Final value: 14221229.699996 (n=263)
  Applied rules: []

Validated query ready for production use.

================================================================================