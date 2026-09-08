# Design Lesson: Correct Numbers vs. Confident Narratives

**Date:** 2026-09-08
**Context:** Region classification implementation (EMEA pipeline analysis)

---

## The Principle

**A correct number doesn't automatically license a confident narrative about WHY it looks the way it does.**

The system should present facts and, where it has genuine uncertainty about organizational context, **stay descriptive or explicitly ask** rather than infer a story.

This is the same discipline already established for stage-relative MEDDICC interpretation - now showing up at the org-structure level instead of the deal level.

---

## What Happened

### The Correct Finding
Geography-based region classification revealed:
- 639 total EMEA deals (vs 155 under owner proxy)
- 29 EMEA deals moved in Aug 22 - Sep 8 window ($411K)
- Owner breakdown: James (10), Jake Stangl (7), Cary (3), others (9)

### The Overreach
The system inferred from this distribution:
- "Territory coverage crisis" ❌
- "Who's responsible for EMEA quota?" (framed as open question) ❌
- "Competitive intelligence gaps" ❌
- "62% of EMEA pipeline reveals a broken territory model" ❌

### Why This Was Wrong
**Missing organizational context:**

1. **Jake Stangl (BDR)**: 7 deals are pipeline in qualification, pending handoff to AE
   - This is NORMAL pipeline flow, not a coverage gap
   - BDRs generate and qualify deals before handing off

2. **Cary (AM)**: 3 deals are AM-owned expansion on existing accounts
   - This is a different motion (retention/expansion)
   - NOT evidence of misassigned new-business territory

3. **Other AEs**: EMEA accounts with non-EMEA AEs are known, redistribution already in progress
   - NOT a newly-discovered crisis
   - "Known and being cleaned up" ≠ "nobody realized this was happening"

### The Corrected Framing
**Facts to keep:**
- 29 real EMEA deals moved ($411K)
- Ownership breakdown by name
- Geography-based classification captures full 639-deal EMEA population

**Interpretation to remove:**
- Organizational implications (territory, quota, competitive intelligence)
- Speculative questions about coverage gaps
- "Crisis" framing without business context

**Accurate summary:**
> "Geography-based classification captures the full 639-deal EMEA population instead of the 155-deal owner proxy, enabling accurate regional reporting. The ownership distribution reflects normal pipeline flow (BDRs qualifying deals, AMs handling expansion, known redistribution of EMEA accounts)."

---

## The Design Principle for Advisor/Coaching Layer

### DO: Present Facts with Precision
✅ "29 EMEA deals moved in the last 2 weeks ($411K)"
✅ "Owner breakdown: James (10), Jake Stangl (7), Cary (3), Dan (2), Christian (2), Marsh (3), Marcel (1)"
✅ "Geography-based classification found 639 EMEA deals vs 155 under owner proxy"

### DON'T: Infer Organizational Story Without Context
❌ "This reveals a territory coverage crisis"
❌ "Who's responsible for EMEA quota?" (as if it's unclear)
❌ "Most EMEA pipeline sits with non-EMEA reps" (without explaining BDR/AM roles)
❌ "Competitive intelligence gaps" (speculation beyond the data)

### Instead: Stay Descriptive or Ask
✅ "Jake Stangl (BDR role) has 7 EMEA deals - is this pipeline pending handoff to an AE?"
✅ "Cary has 3 EMEA deals - are these AM-owned expansions on existing accounts?"
✅ "Several EMEA deals sit with non-EMEA AEs - is this a known distribution being cleaned up?"

---

## Why This Matters

### 1. Same Pattern as Stage-Aware MEDDICC Scoring
**MEDDICC scoring principle:**
- Don't assume a low score means "bad" without checking stage context
- Discovery stage SHOULD have incomplete metrics/decision criteria
- Proposal stage with same gaps IS a red flag

**Org-structure principle (same idea, different level):**
- Don't assume ownership distribution means "broken territory model" without checking role context
- BDR-owned deals SHOULD be pending handoff
- Non-EMEA AE with EMEA deals MIGHT be normal (AM expansion) or known cleanup

### 2. Correct Numbers ARE Valuable Even Without Confident Narratives
The geography-based classification is still a major improvement:
- 639 real EMEA deals vs 155 owner proxy (4.1x larger population)
- 90.9% accuracy from HubSpot Company.country
- Explicit UNKNOWN handling (9.1%)

**This finding holds regardless of WHY ownership is distributed the way it is.**

The system correctly found and fixed a real classification error. It just isn't the system's place to editorialize about org structure, quota assignment, or competitive intelligence from that number alone.

### 3. Domain Knowledge Sits on Top of Correct Numbers
**Correct number:** 639 EMEA deals, with ownership across multiple reps
**Domain knowledge (Jeff):** BDR handoff model, AM expansion motion, active redistribution
**Accurate interpretation:** Normal pipeline flow + known cleanup, not a crisis

A human with context (Jeff) must attach judgment before organizational implications become stated findings.

---

## Application to Query Handlers

When building Slack/API responses that include regional breakdowns:

### Pattern 1: Pure Facts (Always Safe)
```python
def handle_emea_pipeline_query(deals):
    emea_deals = [d for d in deals if get_region(d) == "EMEA"]

    # Report numbers
    print(f"EMEA pipeline: {len(emea_deals)} deals, ${sum_value(emea_deals):,.0f}")

    # Show ownership breakdown
    by_owner = group_by(emea_deals, 'owner_email')
    for owner, owner_deals in by_owner:
        print(f"  {owner}: {len(owner_deals)} deals")
```

### Pattern 2: Descriptive Context (Safe if Role-Aware)
```python
def handle_emea_pipeline_query(deals):
    emea_deals = [d for d in deals if get_region(d) == "EMEA"]

    # Group by role (if available in data)
    by_role = group_by_role(emea_deals)

    print(f"EMEA AEs: {len(by_role['AE'])} deals")
    print(f"BDRs (pending handoff): {len(by_role['BDR'])} deals")
    print(f"AMs (expansion): {len(by_role['AM'])} deals")
```

### Pattern 3: Avoid Organizational Speculation
```python
# ❌ BAD - infers crisis without context
def handle_emea_pipeline_query(deals):
    emea_with_non_emea_owner = [d for d in emea_deals if d.owner not in EMEA_TEAM]
    print(f"WARNING: {len(emea_with_non_emea_owner)} EMEA deals with unclear ownership")
    print("This suggests territory coverage gaps and unclear quota assignment")

# ✅ GOOD - reports facts, lets user interpret
def handle_emea_pipeline_query(deals):
    emea_with_non_emea_owner = [d for d in emea_deals if d.owner not in EMEA_TEAM]
    print(f"Note: {len(emea_with_non_emea_owner)} EMEA deals owned by non-EMEA-designated reps")
    # Stop there - let user decide if this is normal BDR/AM flow or something else
```

---

## Key Takeaway

**The system's job:**
1. Calculate correct numbers (region classification, pipeline movement, ownership breakdown)
2. Present facts clearly
3. When context is uncertain, ask or stay descriptive

**NOT the system's job:**
1. Infer organizational implications (territory models, quota assignment, competitive intelligence)
2. Frame findings as "crises" without business context
3. Answer "why does it look this way" when role/process context is unknown

**Human's job (Jeff/RevOps leader):**
- Attach domain knowledge to correct numbers
- Distinguish normal (BDR handoff, AM expansion) from abnormal (true coverage gaps)
- Decide when a distribution pattern requires action vs explanation

---

## Related Design Principles

1. **Stage-aware MEDDICC scoring** (already established)
   - Low scores in discovery = normal
   - Same scores in proposal = red flag
   - Context matters for interpretation

2. **Explicit UNKNOWN handling** (established in this project)
   - Don't default missing geography to NAM/ROW
   - Surface UNKNOWN explicitly like no_signal_at_risk
   - Honest data quality reporting

3. **Facts before narratives** (this lesson)
   - Present correct numbers with precision
   - Stay descriptive when context is uncertain
   - Let humans with domain knowledge attach organizational interpretation

---

## Test: Would This Pass the "Jeff Check"?

Before presenting organizational implications from a number, ask:
1. Do I know the BDR/AE/AM handoff process?
2. Do I know if this distribution is normal for this company?
3. Do I know if leadership is already aware of this pattern?

If any answer is "no" → stay factual, don't frame as crisis or open question.

**The bar:** Would Jeff say "that's overreaching from the data" or "correct, but needs context"?

If it needs context you don't have → present the number, skip the narrative.

---

## Summary

**Correct numbers are valuable even without confident narratives.**

The geography-based region classification is a major improvement (639 real EMEA deals vs 155 owner proxy). The system correctly found and fixed a real classification error.

But **a correct number doesn't license organizational speculation.** Present facts with precision, stay descriptive when context is uncertain, and let humans with domain knowledge attach interpretation.

Same discipline as stage-aware MEDDICC scoring - just showing up at the org-structure level instead of the deal level.
