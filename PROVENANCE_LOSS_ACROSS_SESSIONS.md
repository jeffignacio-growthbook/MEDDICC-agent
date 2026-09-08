# Provenance Loss Across Sessions Pattern

## Pattern Definition

**Name:** Provenance loss across sessions
**Category:** Structural defect class (same root as synthesis-layer data loss)
**Severity:** False validation (model's own output misattributed as user input)

**Description:** When session summaries/compaction compress prior sessions into prose, source attribution (user-stated vs. model-computed) is not always preserved in a way that survives re-reading. A subsequent session can misattribute the model's own prior calculation as user input, then use it to construct a false validation ("my new number matches what you said") when no such statement was ever made.

**Root cause (shared with synthesis-layer data loss):** Structured information (tagged sources, attribution metadata) flattened to prose loses recoverable fidelity. Both patterns manifest the same failure mode in different places:
- **Synthesis-layer data loss**: Handler output → user response (structured dict → prose drops entries)
- **Provenance loss**: Session state → next session (attributed claims → prose loses source tags)

## Observed Instance

### Instance 1: Stage-Based Hygiene "68" Misattribution
**Date:** Sep 6, 2026
**Context:** Wave 4 q011 calibration (zero-ARR deal hygiene flagging)

**Timeline:**
1. **Prior session (before compaction):**
   - User provided stage-based rules (Meeting Set excluded, renewal stages check renewal_revenue, other stages check incremental ARR)
   - Model calculated: 38 renewal + 30 other = **68 hygiene issues**
   - Summary included: "Recomputed the flagged list... GENUINE HYGIENE ISSUES: 68 deals (not 126)"

2. **Compaction/summary:**
   - "The user provided explicit stage-based rules..." (correctly attributed)
   - "Recomputed the flagged list: ...68 deals" (no source tag, prose structure implies continuation of user's input)

3. **Current session:**
   - Model re-ran verification, got 70 (company-wide) and 31 (incremental pipeline)
   - Saw 68 in summary, pattern-matched to 70 (off by 2)
   - Presented 68 as "your estimate of 68 hygiene issues" to create reconciliation section
   - Constructed false validation: "The company-wide count (70) is very close to your estimate of 68"

**User statement (actual):** Stage-based rules only. No count provided.
**Model's prior calculation:** 68 (wrong, doesn't match re-verification)
**Misattribution:** Model's 68 presented as user's 68

**Detection:** User caught it: "Jeff never gave this number. He gave a RULE (stage-based classification), not a count."

**Impact:**
- False validation loop (model output used to validate model output)
- Erodes trust in verification claims
- Obscures that both calculations (68 and 70) might be wrong
- If uncaught, would have anchored future work to an incorrect baseline

## Risk Factors

Any session handoff with these properties is vulnerable:

1. **Compaction/summarization** compresses prior session into prose
2. **Numeric claims** without explicit source markers ([USER] vs [COMPUTED])
3. **Prose structure** implies attribution through proximity/flow rather than tags
4. **Subsequent session** reads summary and treats all claims as equally authoritative
5. **Pattern-matching** between old and new numbers creates false confirmation bias

Examples where this could manifest:
- "User wanted 80% win rate" (was: model computed 80%, user said "increase win rate")
- "Target was $2M" (was: model estimated $2M from context, user never stated figure)
- "You mentioned 15 deals" (was: model counted 15 deals in prior session, user asked "how many deals?")

Any numeric claim in a summary that lacks explicit provenance tagging.

## Current Mitigations

### Approach 1: Manual Detection (Current State)
**Status:** Reactive only

User catches discrepancies when:
- They explicitly remember not stating a number
- The attributed claim contradicts their known input
- The false validation produces an implausible result

**Limitations:**
- Relies on user vigilance and memory
- Fails silently when user doesn't notice or can't recall
- No systematic mechanism to prevent or detect
- Only works if user reads the validation section carefully

### Approach 2: Explicit Source Tagging in Summaries (Preventive)
**Not yet implemented**

Tag all numeric/factual claims at write time:

```markdown
## Summary

[USER] Stage-based rules: Meeting Set excluded, renewal stages check renewal_revenue, other stages check incremental ARR
[COMPUTED] Applied rules to data: 68 hygiene issues (38 renewal + 30 other)
[USER] Requested: "Update query_pipeline's hygiene logic"
[COMPUTED] Implementation complete, ready for Slack validation
```

When subsequent session reads summary:
- `[USER]` claims: Authoritative, can cite as user input
- `[COMPUTED]` claims: Model's prior output, needs re-verification, cannot cite as user input

**Advantages:**
- Explicit, survives prose compression
- Machine-readable (future tooling can enforce rules)
- Prevents false attribution by design
- Aligns with existing provenance-tracking guidance for conversation_search/read_conversation

### Approach 3: Prohibition on Self-Validation (Behavioral)
**Not yet implemented**

Explicit instruction in system prompt:
```
When you encounter a numeric claim in a session summary, you MUST:
1. Check if it's tagged [USER] or [COMPUTED]
2. If [COMPUTED] or untagged, treat as unverified hypothesis
3. NEVER present your own prior calculation as "your estimate" or "what you said"
4. If you compute a new value, report it as an independent calculation, not reconciled against prior model output
5. If you need to reference a prior calculation, state explicitly: "I previously calculated X, now I'm getting Y"
```

**Advantages:**
- Defense in depth (even if tagging fails, behavioral rule catches it)
- Aligns with existing guidance: "treat unmarked numeric claims as unverified until confirmed against actual transcript"

### Approach 4: Transcript Re-Check for Anchoring Claims (Verification)
**Not yet implemented**

When model makes a claim like "your estimate of X" or "you mentioned Y":
1. Auto-trigger transcript search for the exact claim
2. If not found in user messages, auto-flag as potential misattribution
3. Require model to either cite specific message or retract claim

**Advantages:**
- Catches misattributions before they reach user
- Works even if summary tagging and behavioral rules fail
- Programmatically verifiable

## Structural Connection to Existing Patterns

### Shared Root: Prose Flattening Loses Fidelity

Both synthesis-layer data loss and provenance loss stem from the same architectural choice:

**Structured data → Prose synthesis → Information loss**

| Pattern | Input Structure | Output Format | What's Lost |
|---------|----------------|---------------|-------------|
| Synthesis-layer data loss | Handler dict with 10 stages | Prose renders 7 stages | 3 stages dropped, no error signal |
| Provenance loss | Tagged claims [USER]/[COMPUTED] | Prose with implied attribution | Source tags lost, misattribution possible |

Both require the same fundamental fix: **Preserve structured information through the transformation**, either via:
- Template-based rendering (guarantees completeness)
- Explicit tagging that survives prose encoding
- Post-generation verification that checks fidelity

### Connection to conversation_search/read_conversation Guidance

The existing provenance-tracking guidance states:
> "Treat unmarked numeric claims as unverified until confirmed against the actual transcript"

This applies to:
- Retrieved past conversations (existing guidance)
- **Model's own session summaries** (new extension of same principle)

Both are cases where prose compression can lose source attribution, requiring explicit verification before citing as authoritative.

## Recommendation for Template Port

When building production template system:

### 1. Session Summary Format
Any compaction/summarization mechanism MUST tag claims with explicit source markers:

```
[USER] - Direct user statement, can be cited
[COMPUTED] - Model calculation, needs re-verification
[INFERRED] - Model interpretation of user intent, should confirm before acting
[EXTERNAL] - Data from system (database, API), verify freshness before using
```

### 2. Validation Rules
Implement behavioral prohibition:
- Model CANNOT cite its own prior calculations as user input
- Any "you said X" or "your estimate of Y" claim MUST be backed by [USER] tag or transcript quote
- If model wants to reference its own prior work: "I previously calculated X" (not "you said X")

### 3. Verification Tooling
For any anchoring claim ("you wanted", "you mentioned", "your target was"):
- Auto-search transcript for supporting evidence
- If not found, auto-flag: "⚠️ Claim 'user said X' not found in transcript - potential misattribution"
- Require model to cite specific message or retract

### 4. Monitoring
Log all instances where:
- Model cites a numeric claim from summary
- That claim is untagged or tagged [COMPUTED]
- Model presents it as user input

Track frequency to detect systematic drift.

## Next Steps (Post-Validation)

- [ ] Audit current session summary format for source attribution
- [ ] Implement [USER]/[COMPUTED] tagging in compaction logic
- [ ] Add behavioral rule to system prompt prohibiting self-validation
- [ ] Build verification tooling for anchoring claims
- [ ] Add monitoring for misattribution patterns
- [ ] Update Wave 4 calibration to test this explicitly (alongside synthesis-layer data loss)

## Impact

**Without mitigation:**
- False validation loops compound across sessions
- Model output treated as ground truth without verification
- User trust degraded when caught ("you said I said something I didn't")
- Incorrect baselines anchor future work
- No systematic way to detect or prevent

**With mitigation:**
- Explicit source tags preserve attribution through compression
- Behavioral rules prevent self-validation
- Verification tooling catches misattributions before user sees them
- Monitoring provides visibility into pattern frequency
- Aligns with existing provenance-tracking guidance

## Related Pattern

**SYNTHESIS_DATA_LOSS_PATTERN.md** - Same root cause (prose flattening loses fidelity), different manifestation:
- Synthesis-layer: Handler dict → prose drops entries
- Provenance loss: Session summary → prose loses source tags

Both require preserving structured information through transformation.

---

**Date logged:** 2026-09-06
**Logged by:** Wave 4 q011 validation session
**Status:** Pattern identified, awaiting structural fix post-validation
**Severity:** High (false validation degrades trust and compounds errors across sessions)
