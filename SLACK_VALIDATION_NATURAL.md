# Natural Pipeline Check-In Questions (Validation)

**Approach:** Ask each rep a simple, natural question about their deal. Compare answers against system classification to test threshold calibration.

**Framework:** Core validation = system + rep for ALL 16 deals (see VALIDATION_FRAMEWORK_GOVERNANCE.md)

**DO NOT mention:** thresholds, methodology, statistics, "the system," or ask reps to evaluate anything.

**DO ask:** The same question any manager would ask in a normal pipeline review.

**DO NOT include:** day counts, activity timing, or any numbers (zero anchoring).

---

## Required Signals (This Validation)

1. **System classification** (Signal 2 + Signal 3) — 16/16 deals
2. **Rep's unprompted read** — collect for all 16 deals

**Agreement rate:** matches / 16 (all deals count equally)

**Optional enrichment:** MEDDICC scores available for 7/16 deals, adds diagnostic context but doesn't gate validation.

---

## Questions to Send (One per Rep/Deal)

**CRITICAL: Do NOT include day counts or activity timing in the initial question.**

Let reps answer from their own knowledge. If they ask "how long has it been?" answer honestly, but don't lead with numbers.

### Boundary Flagged Deals (System says at-risk)

**1. Deel rep:**
> "Hey, where's Deel at? Haven't seen movement on it in a bit."

**2. GitLab Inc. rep:**
> "What's the status on GitLab?"

**3. Amazon rep:**
> "How's the Amazon deal looking - still live?"

**4. Hy-Vee rep:**
> "Quick check on Hy-Vee - where are we at?"

**5. Electronic Arts rep:**
> "Electronic Arts - what's happening there?"

**6. Expedia Group rep:**
> "What's the status on Expedia Group?"

**7. DocPlanner rep:**
> "How's DocPlanner looking?"

**8. TRT rep:**
> "Where's TRT at?"

### Boundary Healthy Deals (System says healthy)

**9. Virgin Media O2 UK rep:**
> "How's Virgin Media O2 UK looking - still moving?"

**10. Guidepoint rep:**
> "What's the status on Guidepoint?"

**11. Zurich Insurance Group rep:**
> "Where are we at with Zurich Insurance Group?"

**12. Zurich Insurance rep:**
> "How's Zurich Insurance looking?"

### Control Cases

**13. Rippling rep (obvious stale):**
> "What's happening with Rippling?"

**14. Robinhood rep (obvious healthy):**
> "How's Robinhood looking?"

---

## Response Collection

For each deal, record rep answer:
- **Still moving** (deal is active, progressing normally)
- **Stalled** (deal is stuck, not progressing, needs intervention)
- **Not sure** (unclear status, needs investigation)

---

## Comparison Matrix

| Deal | Days | System Classification | Rep Answer | Match? |
|------|------|----------------------|------------|--------|
| Deel | 55d | CRITICAL | [rep answer] | [compare] |
| GitLab Inc. | 54d | no_signal_at_risk | [rep answer] | [compare] |
| Amazon | 53d | CRITICAL | [rep answer] | [compare] |
| Hy-Vee | 44d | WARN | [rep answer] | [compare] |
| Electronic Arts | 37d | WARN | [rep answer] | [compare] |
| Expedia Group | 37d | WARN | [rep answer] | [compare] |
| DocPlanner | 59d | CRITICAL | [rep answer] | [compare] |
| TRT | 59d | CRITICAL | [rep answer] | [compare] |
| Virgin Media O2 UK | 35d | HEALTHY | [rep answer] | [compare] |
| Guidepoint | 32d | HEALTHY | [rep answer] | [compare] |
| Zurich Insurance Group | 28d | HEALTHY | [rep answer] | [compare] |
| Zurich Insurance | 27d | HEALTHY | [rep answer] | [compare] |
| Rippling | 130d | CRITICAL | [rep answer] | [compare] |
| Robinhood | 20d | HEALTHY | [rep answer] | [compare] |

**Match criteria:**
- ✅ **Correct:** Rep "stalled" + System CRITICAL/WARN
- ✅ **Correct:** Rep "moving" + System HEALTHY
- ❌ **Over-flagging:** Rep "moving" + System CRITICAL/WARN
- ❌ **Under-flagging:** Rep "stalled" + System HEALTHY

---

## Interpretation

### High Agreement (>80% match)
**Signal:** 35-day threshold is **WELL-CALIBRATED**
**Action:** Deploy to production as-is
**Example:** Reps agree deals >35d are stalled, deals <35d are moving

### Moderate Agreement (60-80% match)
**Signal:** Threshold is in the **RIGHT BALLPARK**
**Action:** Deploy with monitoring, minor adjustments if clear pattern
**Example:** Most boundary cases match, but a few edge cases disagree

### Systematic Over-Flagging Pattern
**Signal:** Threshold is **TOO LOW** (too aggressive)
**Evidence:** Multiple reps say "moving" for deals system flagged CRITICAL/WARN
**Action:** Raise threshold (try 45-50 days)
**Example:**
- Electronic Arts 37d: Rep "moving" but System WARN
- Expedia 37d: Rep "moving" but System WARN
- Hy-Vee 44d: Rep "moving" but System WARN

### Systematic Under-Flagging Pattern
**Signal:** Threshold is **TOO HIGH** (too lenient)
**Evidence:** Multiple reps say "stalled" for deals system said HEALTHY
**Action:** Lower threshold (try 25-30 days)
**Example:**
- Virgin Media O2 35d: Rep "stalled" but System HEALTHY
- Guidepoint 32d: Rep "stalled" but System HEALTHY
- Zurich 28d: Rep "stalled" but System HEALTHY

### Low Agreement (<60% match)
**Signal:** Threshold is **WRONG** or deal status highly context-dependent
**Action:** Investigate specific mismatches, consider additional factors beyond time-in-stage
**Example:** No clear pattern, depends on deal-specific context

---

## Follow-Up Questions (If Mismatches)

**If rep says "moving" but system flagged:**
> "Got it - what's the next step on this one? When do you expect it to move to next stage?"

**If rep says "stalled" but system said healthy:**
> "What's blocking it? Is this something that needs escalation?"

**If rep says "not sure":**
> "What would you need to know to determine if this is moving or stalled?"

---

## Analysis Template

After collecting answers:

```
VALIDATION RESULTS
==================

Sample size: 14 boundary cases (excluding 2 control cases)

Agreement: [X]/14 matches ([Y]%)
- System correct: [X] deals
- System over-flagging: [X] deals (rep says moving, system flagged)
- System under-flagging: [X] deals (rep says stalled, system healthy)

Pattern:
[Describe any systematic over/under-flagging pattern]

Specific mismatches:
[List each mismatch with deal name, days, rep answer, system classification]

Recommendation:
[Deploy as-is / Adjust threshold to X days / Needs further investigation]
```

---

## Key Advantages of This Approach

**1. Natural question reps answer routinely**
- Not asking them to evaluate methodology they don't understand
- Just "where's this deal at?" which they answer all the time

**2. Zero anchoring - genuinely unprompted**
- No day counts given ("55 days" would anchor their answer)
- No "last touched X weeks ago" (anchors on system's numbers)
- Just "what's the status?" and let them answer from memory
- If they ask "how long?" that's fine to answer, but don't lead with it

**3. Real test of system vs reality**
- Rep's unprompted answer reflects their actual read of the deal
- System's classification reflects computed metrics
- Agreement = system captures what reps independently know
- If you tell them the numbers first, you're just asking them to confirm

**4. Direct calibration test**
- Agreement rate = how well threshold matches reality
- Mismatches show exactly where threshold is wrong
- Same signal as statistical approach, better elicitation

**5. Actionable results**
- Clear pattern of over-flagging → raise threshold
- Clear pattern of under-flagging → lower threshold
- High agreement → threshold is right

---

## Sample Slack Message Format

**Channel:** #sales-pipeline or direct to individual reps

```
Quick pipeline check on a few deals - one-line answers appreciated:

@[rep]: Hey, where's [Deal name] at?
@[rep]: What's the status on [Deal name]?
@[rep]: How's [Deal name] looking - still moving?
```

**IMPORTANT:**
- Do NOT include day counts or "last touched X days ago"
- Let reps answer from their own knowledge
- If they ask "how long?" answer honestly, but don't lead with it

Keep it casual, manager-style, not a formal audit.

---

## Implementation Steps

1. **Identify rep owners** for each of the 16 deals
2. **Send natural questions** (one per rep/deal)
3. **Collect answers** in comparison matrix
4. **Calculate agreement rate** (matches vs mismatches)
5. **Analyze patterns** (systematic over/under-flagging?)
6. **Make decision:**
   - High agreement (>80%) → Deploy as-is
   - Systematic pattern → Adjust threshold
   - Low agreement (<60%) → Investigate context factors
7. **Document results** in ENTERPRISE_DISCOVERY_OVERRIDE.md

---

## What This Actually Tests

**Same calibration signal as statistical approach, but cleaner elicitation:**

- If reps say deals >35d are "stalled" → threshold appropriate
- If reps say deals >35d are "moving" → threshold too aggressive
- If reps say deals <35d are "stalled" → threshold too lenient
- If reps say deals <35d are "moving" → threshold appropriate

**But asked in a way reps can actually answer**, without asking them to validate methodology they have no context for.
