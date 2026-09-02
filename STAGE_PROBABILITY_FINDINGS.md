# Stage Probability Findings — Measured vs Configured

**Executive summary**: Configured stage probabilities are PROVISIONAL guesses. Measured historical conversion rates differ significantly. **Correcting them would increase FY2027 Q3 forecast from $1.9M to $2.5M (+28.7%)** — but that breaks convergence with historical conversion ($1.8M) and rep calls ($1.899M).

---

## Measured vs Configured (All-Time Pooled)

| Stage | Configured | Measured | Δ | Impact | Sample |
|-------|-----------|----------|---|--------|--------|
| **Review** | **0.50** | **0.013** | **-0.487** | **OVERSTATING 49pp** ⚠️ | 2/151 won |
| **Scoping** | **0.10** | **0.287** | **+0.187** | **UNDERSTATING 19pp** ⚠️ | 25/87 won |
| Meeting Set | 0.05 | 0.136 | +0.086 | UNDERSTATING 9pp | 88/649 won |
| Discovery | 0.10 | 0.164 | +0.064 | UNDERSTATING 6pp | 23/140 won |
| Technical Evaluation | 0.40 | 0.438 | +0.037 | Close ✓ | 28/64 won |
| Negotiating | 0.60 | 0.681 | +0.081 | Close ✓ | 62/91 won |
| Awaiting Signature | 0.90 | 0.974 | +0.074 | Close ✓ | 37/38 won |

**Critical issues**:
1. **Review stage**: Only 2 of 151 deals (1.3%) that reached Review won. Configured at 0.50 (50%). Massive overstatement.
2. **Scoping stage**: 25 of 87 deals (28.7%) won. Configured at 0.10 (10%). Understatement.

---

## Impact on FY2027 Q3 Forecast (Default Pipeline)

**Current pipeline**: $7.6M open, 126 deals

| Stage | Count | Value | @Configured | @Measured |
|-------|-------|-------|-------------|-----------|
| Technical Evaluation | 21 | $2.76M | $1.11M | $1.21M |
| Discovery | 38 | $2.61M | $0.26M | $0.43M |
| Scoping | 8 | $0.92M | $0.09M | $0.26M |
| Meeting Set | 50 | $0.71M | $0.04M | $0.10M |
| Negotiating | 6 | $0.45M | $0.27M | $0.31M |
| Awaiting Signature | 2 | $0.16M | $0.14M | $0.16M |
| Review | 1 | $0.01M | $0.01M | $0.00M |
| **TOTAL** | **126** | **$7.62M** | **$1.91M** | **$2.46M** |

**Impact**: +$548K (+28.7%)

---

## The Convergence Problem

### Before Correction (Current State)
```
Historical conversion: $1.79M  [$1.67M-$1.90M]
Stage-weighted:        $1.91M  (configured probabilities)
Rep calls:             $1.90M

Range: $1.79M-$1.91M (6.7% spread) ✓ CONVERGED
```

### After Correction (Measured Probabilities)
```
Historical conversion: $1.79M  [$1.67M-$1.90M]
Stage-weighted:        $2.46M  (measured probabilities)
Rep calls:             $1.90M

Two methods at ~$1.8-1.9M, one at $2.5M ✗ DIVERGED
```

---

## Possible Explanations

### 1. Configured probabilities are wrong (templates)

**Evidence**: Labeled PROVISIONAL in config, never validated against actuals.

**Implication**: Stage-weighted forecast has been wrong for months. Correction brings it closer to reality, but historical conversion and rep calls are also directionally accurate methods.

**Action**: Update config with measured values, accept that stage-weighted was understating.

### 2. Historical data not representative

**Evidence**:
- Review stage: 2/151 won (1.3%) seems implausibly low
- Scoping stage: High quarterly variance (σ=0.107, range 18.8%-42.9%)

**Possible causes**:
- Stage usage changed over time (Review deprecated? Scoping redefined?)
- Sample includes deals from before process changes
- Stage hygiene poor (deals skip stages, land in wrong stages)

**Action**: Filter to recent quarters only, recompute. If measured rates stabilize, use those. If still volatile, stick with configured.

### 3. Scope contamination

**Evidence**: Default pipeline filter applied, but stage_id mapping might include historical stages that contaminate the calculation.

**Check**: Review stage is `decisionmakerboughtin`. Is that still an active stage in the pipeline, or is it historical like `contractsent`?

**Action**: Verify stage_id list matches current active pipeline only.

### 4. Multiple effects (compound)

Templates were wrong AND historical data is contaminated AND stage usage changed.

**Action**: Audit stages individually, particularly Review and Scoping.

---

## Quarter-to-Quarter Variance

High variance suggests instability (rates changing over time):

| Stage | σ (stdev) | Range | Stable? |
|-------|-----------|-------|---------|
| Review | 0.575 | [0.0%, 100%] | ✗ Volatile |
| Negotiating | 0.203 | [45.2%, 100%] | ⚠️ High variance |
| Scoping | 0.107 | [18.8%, 42.9%] | ⚠️ Moderate variance |
| Meeting Set | 0.106 | [0.0%, 27.8%] | ⚠️ Moderate variance |
| Discovery | 0.092 | [0.0%, 23.3%] | ✓ Acceptable |
| Technical Evaluation | 0.105 | [37.5%, 60.0%] | ✓ Acceptable |
| Awaiting Signature | 0.041 | [90.9%, 100%] | ✓ Stable |

**Stable stages** (Awaiting Signature, Technical Evaluation, Discovery): Use pooled measured rate.

**Volatile stages** (Review, Negotiating): Either (a) use configured conservative guess, or (b) investigate why variance is high (stage usage changed? small samples?).

---

## Recommendation

### Option 1: Update All (Measured Rates)

**Pro**: Data-driven, closes PROVISIONAL gap
**Con**: Breaks forecast convergence, Review stage rate seems implausibly low (1.3%)

**Result**: Stage-weighted forecast → $2.46M (vs $1.79M historical, $1.90M rep calls)

### Option 2: Selective Update (Stable Stages Only)

**Update these** (stable, well-sampled):
- Technical Evaluation: 0.40 → 0.438 (+0.037)
- Negotiating: 0.60 → 0.681 (+0.081)
- Awaiting Signature: 0.90 → 0.974 (+0.074)

**Keep configured** (volatile or suspicious):
- Review: Keep 0.50 (measured 0.013 seems wrong, σ=0.575)
- Scoping: Keep 0.10 (σ=0.107, wide variance)
- Discovery: Keep 0.10 (close enough, 0.164 measured but σ=0.092)
- Meeting Set: Keep 0.05 (early stage, exclusion from qualified scope makes rate misleading)

**Result**: Stage-weighted forecast → ~$2.0M (closer to historical/rep calls)

### Option 3: Audit First (Recommended)

Before updating config:

1. **Check Review stage usage**: Is `decisionmakerboughtin` still active? Or deprecated like `contractsent`? 2/151 won (1.3%) is implausibly low for a stage configured at 50%.

2. **Filter to recent data**: Recompute using last 4 quarters only (FY2027 Q1-Q3, FY2026 Q3-Q4). If rates stabilize, use those. If Review is still 1.3%, that's real (not contamination).

3. **Check stage hygiene**: Do deals progress through stages linearly, or do they skip? Does "landed in Review" mean different things over time?

4. **Compare cohorts**: Break down by segment, rep, or quarter. If Enterprise converts at 40% in Scoping but SMB at 15%, pooled rate (28.7%) hides that dynamic.

**After audit**: Make targeted updates, document reasoning, recompute forecast.

---

## Next Steps

1. **Audit Review stage** (priority): Why 1.3% conversion? Historical? Deprecated? Hygiene issue?

2. **Audit Scoping stage**: 28.7% measured vs 10% configured — is this real or artifact?

3. **Filter to recent quarters**: Recompute using last 4 quarters only.

4. **Check stage progression**: Are deals skipping stages? Reverting?

5. **After audit**: Update config/client.yaml with justified values, document provenance.

6. **Recompute forecast**: Run compute_forecast.py with corrected probabilities.

7. **Reconcile convergence**: If stage-weighted moves to $2.5M, why do historical ($1.8M) and rep calls ($1.9M) land lower? Is historical conversion missing a cohort? Are rep calls sandbagged?

---

## Files

- **measure_stage_probabilities.py**: Script that generated these findings
- **config/client.yaml**: Current PROVISIONAL stage probabilities
- **FOR_RYAN_TWO_QUESTIONS.md**: Bundle with "at risk" definition request

---

## Why This Matters

Stage probabilities are **the most sensitive input to stage-weighted forecast**. A 28.7% error compounds across every deal in pipeline.

If PROVISIONAL guesses have been wrong for months, **every board forecast using stage-weighted was wrong**. Historical conversion and rep calls converging at $1.8-1.9M suggests reality is closer to that range, not $2.5M.

But measured data says stages convert higher than configured. One of these is wrong:
1. Measured data is contaminated (historical stages, hygiene issues)
2. Configured probabilities were pessimistic templates
3. Both are partially right (some stages measured correctly, others not)

Audit determines which.
