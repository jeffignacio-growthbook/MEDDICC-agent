# Synthesis-Layer Data Loss Risk Pattern

## Pattern Definition

**Name:** Synthesis-layer data loss
**Category:** Structural defect class
**Severity:** Silent data corruption (incorrect output without error signal)

**Description:** When structured data with checkable totals (sum of parts = whole) passes through free-form LLM synthesis, there's a risk of silent truncation, dropping, or selective omission of data elements.

## Observed Instances

### Instance 1: q003 No-ARR Deals Count Discrepancy
**Date:** Sep 2-3, 2026
**Handler:** Dynamic query
**Issue:** Agent found 127 deals with no ARR internally, but displayed different numbers in Slack response
**Root cause:** Synthesis layer didn't faithfully render the count from tool_results
**Detection:** User caught discrepancy between stated count and expected value

### Instance 2: Stage Breakdown Truncation (q011)
**Date:** Sep 6, 2026
**Handler:** query_pipeline
**Issue:** Handler returned 306 deals across 10 stages in `by_stage` dict. Synthesis displayed 287 deals across 7 stages. Missing 19 deals across 3 stages (Review: 14, Renewal Engaged: 4, empty: 1).
**Root cause:** LLM synthesis selectively dropped certain stage names from the breakdown without error
**Detection:** User reconciled displayed stage sum (287) against stated total (306)

**Common characteristics:**
- Handler output was correct (306 deals, 10 stages)
- Synthesis truncated structured data (7 stages shown)
- No error signal (response looked complete)
- Arithmetic didn't reconcile (287 ≠ 306)
- Not "top N" filtering (kept #10, dropped #5)

## Risk Factors

Any handler output with these properties is vulnerable:
1. **Structured data** (dicts, arrays with counts)
2. **Checkable totals** (sum of parts should equal stated whole)
3. **Free-form LLM synthesis** (not template-based rendering)
4. **No post-generation verification** (no programmatic check that displayed sum == source total)

Examples in current codebase:
- `by_stage`: dict of stage counts (should sum to total_deals)
- `by_owner`: dict of owner counts (should sum to total_deals)
- `deals`: array of top deals (with _truncated note if capped)
- Any breakdown with "X deals across Y categories"

## Current Mitigations

### Approach 1: Prompt Engineering (Weak)
**Current fix for stage breakdown:**
```
_synthesis_note: "Show ALL stages from by_stage dict (typically 10).
Do NOT drop or skip stages. Sum ALL stage counts and verify it equals
total_deals (306). If sum < total_deals, explicitly state the gap."
```

**Limitations:**
- Relies on LLM compliance (prompt instructions can be ignored)
- No programmatic enforcement
- Fails silently when ignored
- Requires per-handler custom instructions

### Approach 2: Programmatic Post-Generation Verification (Strong)
**Not yet implemented**

Concept:
1. After synthesis, extract displayed counts from response
2. Verify: sum of displayed parts == stated total
3. If mismatch: auto-flag error or auto-correct with template fallback
4. Log discrepancy for monitoring

Example for stage breakdown:
```python
def verify_stage_breakdown(response_text: str, total_deals: int) -> bool:
    """Extract stage counts from response and verify sum == total."""
    # Parse stage counts from response (regex)
    displayed_counts = extract_stage_counts(response_text)
    displayed_sum = sum(displayed_counts.values())

    if displayed_sum != total_deals:
        logger.error(f"[SYNTHESIS_LOSS] Stage sum {displayed_sum} != total {total_deals}")
        # Option A: Auto-correct with template
        # Option B: Return error to user
        # Option C: Flag for manual review
        return False
    return True
```

### Approach 3: Template-Based Rendering (Strongest)
**Not yet implemented**

For structured data sections, use deterministic templates instead of LLM synthesis:

```python
def render_stage_breakdown(by_stage: dict, total_deals: int) -> str:
    """Template-based rendering guarantees completeness."""
    lines = ["Stage breakdown (all {total_deals} deals):"]

    for stage, stats in sorted(by_stage.items(), key=lambda x: x[1]['count'], reverse=True):
        lines.append(f"• {stage}: {stats['count']} deals")

    displayed_sum = sum(s['count'] for s in by_stage.values())
    if displayed_sum != total_deals:
        lines.append(f"⚠️ Gap: {total_deals - displayed_sum} deals not in breakdown")

    return "\n".join(lines)
```

**Advantages:**
- Guaranteed completeness (no LLM discretion)
- Guaranteed arithmetic correctness
- Guaranteed format consistency
- No prompt engineering needed

**Tradeoffs:**
- Less natural language fluency
- Requires maintaining templates
- May need hybrid approach (templates for data, LLM for prose)

## Recommendation for Template Port

When porting to production template system:

1. **Identify vulnerable outputs:** Any handler returning structured data with checkable totals
2. **Apply mitigation hierarchy:**
   - **Tier 1** (Critical): Template-based rendering (stage breakdowns, by_owner, any sum-of-parts)
   - **Tier 2** (Important): Programmatic post-generation verification + auto-correction
   - **Tier 3** (Nice-to-have): Prompt engineering only

3. **Monitor pattern:** Log all instances where synthesis drops/truncates data, not just the ones caught by users

## Related Pattern

**PROVENANCE_LOSS_ACROSS_SESSIONS.md** - Same root cause (prose flattening loses fidelity), different manifestation:
- Synthesis-layer data loss: Handler dict → prose drops entries
- Provenance loss: Session summary → prose loses source tags

Both require preserving structured information through transformation (templates, explicit tagging, or post-generation verification).

## Next Steps (Post-Validation)

- [ ] Audit all handlers for vulnerable structured outputs
- [ ] Implement programmatic verification for stage/owner breakdowns
- [ ] Consider template-based rendering for dict-shaped outputs
- [ ] Add monitoring for synthesis-layer data loss
- [ ] Update Wave 4 calibration to test this explicitly
- [ ] Apply same principles to session summary format (see PROVENANCE_LOSS_ACROSS_SESSIONS.md)

## Impact

**Without mitigation:**
- Silent data loss continues in production
- User trust degraded by arithmetic discrepancies
- Debugging requires user-reported "numbers don't add up" issues

**With mitigation:**
- Programmatic guarantee of completeness
- Auto-detection of synthesis failures
- Reduced user-facing errors
- Easier debugging (logged at generation time)

---

**Date logged:** 2026-09-06
**Logged by:** Wave 4 q011 validation session
**Status:** Pattern identified, awaiting structural fix post-validation
