# Slack Validation Questions — Revised for Boundary Case Testing

**Date:** 2026-09-07
**Purpose:** Test threshold calibration with sales team gut-check on boundary cases

---

## Context: Why This Validation Matters

We've built an at-risk deal detection system (Signal 2: time-in-stage + Signal 3: activity recency) and need to validate it matches operational reality before deploying.

**Critical insight:** The easy cases (deals at 130 days, no activity) don't test threshold calibration — everyone agrees those are stale. The **boundary cases** (deals at 30-50 days) are where your gut-check actually tells us if 35 days is right.

---

## Question 1: Threshold Calibration (Honest Framing)

**❌ DON'T ask (overstates confidence):**
> "We set Enterprise Discovery threshold at 35 days based on the segment's naturally longer evaluation cycles. Does this feel right?"

**✅ DO ask (honest about what we know):**

```
For Enterprise Discovery deals, we're currently using a 35-day threshold as
a PLACEHOLDER.

Context: The derived threshold (19 days, borrowed from Mid-Market/SMB data
where we have enough deals to calculate it) flagged 74% of Enterprise
Discovery deals, which seemed too aggressive. We don't yet have enough
Enterprise-specific data to derive a real number (only 2 Enterprise Discovery
won deals in our clean sample), so 35 days is an educated guess pending more
data.

Question: Does 35 days feel right for Enterprise Discovery, or would you set
it differently? What would you consider a concerning amount of time for an
Enterprise deal to sit in Discovery without progression?

For comparison:
- Mid-Market Discovery: 19 days (derived from data)
- SMB Discovery: 25 days (derived from data)
- Enterprise Discovery: 35 days (placeholder, NOT derived)
```

---

## Question 2: Boundary Case Review (Tests Calibration)

**Sample selection principle:** Focus on deals at 30-60 days, NOT obvious 100+ day cases.

```
Can you review this sample of Enterprise Discovery deals and tell us which
ones you'd consider at-risk vs actively working?

We're specifically interested in deals NEAR our 35-day threshold — these test
whether 35 is well-calibrated. (We're including one obvious stale deal to
prove the system works, but that's not what we're testing.)

BOUNDARY FLAGGED (35-60 days, system says at-risk):
1. Deel ($175k) — 55 days in Discovery, activity 19 days ago [CRITICAL]
2. GitLab Inc. ($250k) — 54 days in Discovery, no activity data [no_signal_at_risk]
3. Amazon — 53 days in Discovery, activity 33 days ago [CRITICAL]
4. Hy-Vee — 44 days in Discovery, activity 13 days ago [WARN]
5. Electronic Arts ($200k) — 37 days in Discovery, activity 12 days ago [WARN]
6. Expedia Group ($62k) — 37 days in Discovery, activity 10 days ago [WARN]

BOUNDARY HEALTHY (25-35 days, system says healthy):
7. Virgin Media O2 UK ($100k) — 35 days in Discovery, activity 21 days ago [HEALTHY]
8. Guidepoint — 32 days in Discovery, activity 12 days ago [HEALTHY]
9. Zurich Insurance Group ($74k) — 28 days in Discovery, activity 5 days ago [HEALTHY]
10. Zurich Insurance ($100k) — 27 days in Discovery, activity 27 days ago [HEALTHY]

CONTROL CASES:
11. Rippling — 130 days in Discovery, activity 82 days ago [CRITICAL - obvious stale]
12. Robinhood ($150k) — 20 days in Discovery, activity 19 days ago [HEALTHY - clearly fine]

For each deal, would you say:
- At-risk (needs intervention)
- Actively working (normal for Enterprise)
- Unclear/depends on context

The boundary cases (#1-10) are what we're really testing.
```

---

## Question 3: Surprises (Catches Calibration Issues)

**This is the most important question** — surprises in either direction reveal threshold problems.

```
Of the deals above, which ones SURPRISE you?

Specifically:
- Are any FLAGGED deals (marked CRITICAL/WARN) actually being worked
  normally and shouldn't be flagged?

- Are any HEALTHY deals (not flagged) actually concerning and should
  have been flagged?

Don't focus on the obvious cases (Rippling at 130 days, Robinhood at 20 days).
Focus on the boundary cases at 30-50 days — those are where a mismatch would
tell us the threshold needs adjusting.

If a flagged deal surprises you: the threshold may be TOO LOW
If a healthy deal surprises you: the threshold may be TOO HIGH
If no surprises: the threshold is probably WELL-CALIBRATED
```

---

## Interpretation Guide (Internal Use)

### Scenario 1: Boundary flagged deals (35-50d) mostly "actively working"
**Signal:** 35-day threshold is **TOO LOW**
**Action:** Raise to 45-60 days
**Example feedback:** "Expedia at 37 days is normal — we're still engaging stakeholders"

### Scenario 2: Boundary healthy deals (25-35d) mostly "at-risk"
**Signal:** 35-day threshold is **TOO HIGH**
**Action:** Lower to 25-30 days
**Example feedback:** "Zurich at 28 days should be flagged — that's concerning"

### Scenario 3: Boundary cases match system classification
**Signal:** 35-day threshold is **WELL-CALIBRATED**
**Action:** Deploy as-is, monitor quarterly
**Example feedback:** "Deals >35 days look stale, deals <35 days look normal"

### Scenario 4: Mixed feedback with no clear pattern
**Signal:** Threshold is in the **RIGHT BALLPARK** but may need minor adjustment
**Action:** Deploy with monitoring, adjust based on operational feedback
**Example feedback:** "Some 35-40 day deals are fine, others are concerning — depends on context"

---

## Follow-Up Questions (If Needed)

**If they say "it depends on context":**
```
What context factors matter most? Deal size? Stakeholder complexity?
Competitive pressure? Knowing what makes some 35-day deals "fine" vs
"concerning" helps us refine the system.
```

**If they suggest different threshold:**
```
What would you set as the threshold? At what point does an Enterprise
Discovery deal sitting in stage become concerning to you?
```

**If they flag specific deals:**
```
For [specific deal], what would you do next? Is this "reach out to rep"
or "flag for manager review" or something else?
```

---

## Documentation of Results

After validation, document:

1. **Threshold assessment:**
   - Too low / too high / well-calibrated / unclear
   - Recommended adjustment (if any)

2. **Specific feedback:**
   - Quote key reactions to boundary cases
   - Note any deal-specific context they provided

3. **Action taken:**
   - Deploy as-is / adjust threshold / re-validate with changes
   - If adjusted, document new threshold and re-run boundary case check

4. **Update files:**
   - config/field_semantics.yaml (if threshold changes)
   - ENTERPRISE_DISCOVERY_OVERRIDE.md (add validation results)
   - SESSION_SUMMARY (record validation outcome)

---

## Key Differences from Original Version

**Original version problems:**
1. ❌ Presented 35 days as derived from Enterprise-specific evidence (it wasn't)
2. ❌ Sample focused on obvious cases (Comcast 130d, Brussels 66d)
3. ❌ Didn't explicitly ask for surprises

**Revised version fixes:**
1. ✅ Honest: "35 days is a placeholder guess, not derived from data"
2. ✅ Boundary case focus: Deals at 30-50 days test threshold calibration
3. ✅ Surprises question: Catches calibration issues in either direction

**Result:** Validation now actually tests whether 35 days is right, not just whether the system can find obviously-dead deals.
