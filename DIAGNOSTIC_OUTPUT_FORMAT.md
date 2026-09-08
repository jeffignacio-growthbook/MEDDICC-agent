# Diagnostic Output Format — Operationalizing Honest Labeling

**Purpose:** Ensure humans reviewing escalations can catch classifier misclassifications

**Problem:** Diagnostic classifier misclassifies ~40% of edge cases (2 of 5). A wrong label sends someone down the wrong investigative path.

---

## Required Output Format

### Current Diagnostic Returns

```python
{
    "type": "missing_rule",  # or "impossible_target" or "partial_progress"
    "severity": "needs_new_rule",
    "message": "Significant improvement (97.9%) but still 155,000 from target..."
}
```

**Problem:** Label presented as verdict, not suggestion. Human can't independently judge if classification is likely wrong.

### Required Output Format

```python
{
    "type": "missing_rule",  # SUGGESTION, not verdict
    "severity": "needs_new_rule",

    # RAW NUMBERS (always visible to human)
    "improvement_pct": 97.9,
    "remaining_gap_pct": 2.2,
    "naive_value": 14221230,
    "final_value": 7160865,
    "target_value": 7005865,

    # Classification confidence
    "classification_confidence": "high",  # high/medium/low based on distance from boundaries

    # Human-readable message
    "message": "...",

    # Diagnostic quality warning
    "classifier_status": "heuristic_pending_validation",
    "known_wrong_zones": [
        "High improvement (>95%) with moderate gap (8-15%): May misclassify as partial_progress",
        "Low improvement (<40%) with high gap (>65%): May misclassify as partial_progress"
    ]
}
```

**Key changes:**
1. **Raw numbers always visible** - Human can independently judge
2. **Classification confidence** - Signals proximity to boundary conditions
3. **Classifier status** - Reminds human this is heuristic, not validated
4. **Known wrong zones** - Documents where misclassification likely

---

## Confidence Calculation

```python
def calculate_classification_confidence(improvement_pct, remaining_gap_pct, classification_type):
    """
    Calculate confidence in classification based on distance from boundaries.

    Returns: "high", "medium", "low"
    """
    if classification_type == "missing_rule":
        # Strongly matches missing_rule: >95% improvement, <3% gap
        if improvement_pct > 95 and remaining_gap_pct < 3:
            return "high"
        # Near boundary: 90-95% improvement or 3-5% gap
        elif improvement_pct >= 90 and remaining_gap_pct <= 5:
            return "medium"
        else:
            return "low"  # Shouldn't happen, but flag if it does

    elif classification_type == "impossible_target":
        # Strongly matches impossible_target: <40% improvement or >70% gap
        if improvement_pct < 40 or remaining_gap_pct > 70:
            return "high"
        # Near boundary: 40-60% improvement and 50-70% gap
        elif improvement_pct <= 60 and remaining_gap_pct >= 50:
            return "medium"
        else:
            return "low"

    elif classification_type == "partial_progress":
        # partial_progress is catch-all, so confidence depends on
        # whether we're far from other categories
        if 60 <= improvement_pct <= 85 and 10 <= remaining_gap_pct <= 40:
            return "high"  # Solidly in middle range
        else:
            return "medium"  # Near boundaries of other categories

    return "low"
```

---

## Slack Escalation Message Format

### Example: Missing Rule (High Confidence)

```
⚠️  METRIC VALIDATION FAILED

Metric: pipeline_value
Target: $7,005,865
Result: $7,160,865 (after applying all available rules)

📊 CONVERGENCE ANALYSIS
  Improvement: 97.9% (naive $14.2M → final $7.2M)
  Remaining gap: 2.2% of final value ($155K)

🔍 DIAGNOSTIC (HEURISTIC - pending validation)
  Classification: missing_rule (HIGH confidence)

  This pattern suggests: A filtering rule is needed that's NOT in the
  current registry. Existing rules made massive progress (97.9%) but a
  small gap (2.2%) remains.

  ⚠️  CLASSIFIER STATUS: This is a hand-picked heuristic tested on 7
  synthetic cases. Review raw numbers to confirm classification.

✅ RECOMMENDED ACTION
  1. Investigate what differentiates target ($7.0M) from result ($7.2M)
  2. Define new hygiene rule to close this gap
  3. Add to config/field_semantics.yaml
  4. Re-run backtest to verify convergence

📋 RAW DATA (for independent review)
  Naive: $14,221,230
  After exclude_renewals: $7,160,865
  Target: $7,005,865
  Rules tried: exclude_renewals
  Tolerance: $100,000
```

### Example: Edge Case (Low Confidence)

```
⚠️  METRIC VALIDATION FAILED

Metric: average_deal_size
Target: $50,000
Result: $60,000 (after applying all available rules)

📊 CONVERGENCE ANALYSIS
  Improvement: 85.0% (naive $100K → final $60K)
  Remaining gap: 16.7% of final value ($10K)

🔍 DIAGNOSTIC (HEURISTIC - pending validation)
  Classification: partial_progress (LOW confidence)

  ⚠️  BOUNDARY CASE WARNING: This falls near the edge of multiple
  classification zones. The raw numbers suggest this might actually be
  a "missing_rule" case (high improvement, moderate gap).

  Known wrong zone: High improvement (>85%) with moderate gap (8-20%)
  sometimes misclassifies as partial_progress instead of missing_rule.

  ⚠️  CLASSIFIER STATUS: This is a hand-picked heuristic tested on 7
  synthetic cases. REVIEW RAW NUMBERS - classification may be incorrect.

⚡ MANUAL REVIEW REQUIRED
  This case requires human judgment. Review raw numbers and decide:
  - If gap is small relative to progress → missing_rule (one more filter)
  - If gap is large relative to progress → impossible_target (verify ground truth)
  - If unclear → partial_progress (multiple rules needed)

📋 RAW DATA (for independent review)
  Naive: $100,000
  After exclude_renewals: $60,000
  Target: $50,000
  Rules tried: exclude_renewals
  Tolerance: $5,000
```

---

## Implementation Changes Required

### Update enhanced_diagnostic() function

```python
def enhanced_diagnostic(...) -> dict:
    """Generate diagnostic with raw numbers and confidence."""

    # ... existing classification logic ...

    # Calculate confidence
    confidence = calculate_classification_confidence(
        improvement_pct, remaining_gap_pct, diagnostic["type"]
    )

    # Add required fields
    diagnostic.update({
        "improvement_pct": improvement_pct,
        "remaining_gap_pct": remaining_gap_pct,
        "naive_value": naive_value,
        "final_value": final_value,
        "target_value": target_value,
        "classification_confidence": confidence,
        "classifier_status": "heuristic_pending_validation",
        "known_wrong_zones": [
            "High improvement (>95%) with moderate gap (8-15%): May misclassify as partial_progress",
            "Low improvement (<40%) with high gap (>65%): May misclassify as partial_progress"
        ]
    })

    # Add boundary warning if confidence is low
    if confidence == "low":
        diagnostic["boundary_warning"] = (
            "This case falls near classification boundaries. "
            "Review raw numbers to independently judge classification."
        )

    return diagnostic
```

---

## Operationalizing This

### For Phase 2d (Slack Integration)

**Slack message must include:**
1. ✅ Raw improvement% and remaining_gap%
2. ✅ Classification label + confidence level
3. ✅ Classifier status ("heuristic pending validation")
4. ✅ Known wrong zones
5. ✅ Boundary warning if confidence is low

**Label must be presented as SUGGESTION:**
- "Classification: missing_rule (HIGH confidence)" ✓
- NOT "This is a missing_rule case" ✗

### For Human Review

**Reviewer checklist:**
1. Look at raw improvement% and remaining_gap%
2. Compare to known wrong zones
3. If confidence is LOW, independently judge classification
4. Log whether you agree/disagree with classifier

---

## Success Criteria

**Before honest labeling:**
- Diagnostic returns label only
- Human trusts label blindly
- Misclassification (40% rate) sends them down wrong path

**After honest labeling:**
- Diagnostic returns label + raw numbers + confidence
- Human can independently judge if label seems wrong
- Known wrong zones documented
- Boundary cases flagged for manual review

**Operational test:**
- Show diagnostic output to someone unfamiliar with system
- Ask: "Can you tell this is a heuristic, not proven?"
- Ask: "Can you judge if the classification might be wrong?"
- Expected: Yes to both questions

---

## Summary

**Honest labeling is operationally load-bearing when:**
1. ✅ Raw numbers always visible (not just label)
2. ✅ Confidence level calculated and shown
3. ✅ Classifier status included ("heuristic pending validation")
4. ✅ Known wrong zones documented
5. ✅ Boundary warnings for low-confidence cases
6. ✅ Label presented as SUGGESTION, not verdict

**This ensures ~40% misclassification rate doesn't send humans down wrong investigative path.**
