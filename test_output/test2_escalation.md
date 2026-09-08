================================================================================
GENERALIZED BACKTEST ENGINE — AUDIT TRAIL
================================================================================

Metric: pipeline_value_meddicc_only
Metric type: sum_dollars
Description: Pipeline value for deals with complete MEDDICC scores only
Ground truth: 3000000

────────────────────────────────────────────────────────────────────────────────
ITERATION HISTORY
────────────────────────────────────────────────────────────────────────────────

Iteration 0: naive (no hygiene rules)
  Applied rules: ['exclude_renewals']
  Result: 14221229.699996 (n=263)
  Expected: 3000000
  Delta: 11221229.699996
  Status: ✗ MISMATCH

Iteration 1: exclude_renewals
  Applied rules: ['exclude_renewals']
  NEW RULE: exclude_renewals (is_renewal_base)
  Result: 7160865.0 (n=115)
  Expected: 3000000
  Delta: 4160865.0
  Status: ✗ MISMATCH

────────────────────────────────────────────────────────────────────────────────
FINAL RESULT
────────────────────────────────────────────────────────────────────────────────

✗ DID NOT CONVERGE
  Total iterations: 1
  Final delta: 4160865.0

⚠️  NON-CONVERGENCE DETECTED
Action required: Human review needed

Possible causes:
  - Missing hygiene rule (not in registry)
  - Incorrect ground truth
  - Data quality issue

DO NOT attempt unsupervised LLM iteration.
Surface this diagnostic to human for review.

================================================================================