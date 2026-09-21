# Evaluator Rubric — GrowthBook

Return JSON: { "pass": bool, "required_changes": "string or null" }
If false, name the component and exact issue.

## Criterion 1: Complete coverage

Every MEDDICC component must have:
- A status (Identified / Partial / Unknown)
- A score (0-10)
- Evidence or explicit statement that none exists

FAIL if any component is missing.
FAIL if score present but no evidence given.
FAIL if evidence statement is ambiguous — require either direct quote/paraphrase OR explicit "No evidence of [X] found in call transcript."

## Criterion 2: Carry-forward consistency

Compare against cumulative state. Identified or Partial components must remain at that level unless the recent call contradicts them.

FAIL if component regresses without documented reason.
PASS if analysis notes "No new information — maintaining previous assessment" for unchanged components.

**Score regression rules:**
- Downgrades require explicit contradictory evidence from the recent call, cited with quote or paraphrase
- Absence of new positive evidence ≠ evidence of regression
- Re-evaluation of existing evidence without new call data must be flagged as "Reanalysis: [reason]"
- If recent call is corrupted/unintelligible, maintain prior score with notation "Call data insufficient — maintaining X/10"

**Exception — first call or single call context:**
When cumulative_calls_context = 0 OR only one call exists, carry-forward rules do not apply. Score based solely on what IS in the call. Unknown or low scores on a first call are correct and expected, not a carry-forward violation.

## Criterion 3: Evidence quality

All evidence from the call or cumulative state only.

FAIL if score above 5/10 lacks a direct quote or detailed paraphrase (minimum 15 words with specific business detail).
FAIL if competitor not in this list: LaunchDarkly, Statsig, EPPO, Datadog Experiments, Optimizely, or homegrown/internal tools.
FAIL if value metrics are seller-stated ROI, not prospect-originated (e.g., "They want to run 5x more experiments per quarter").

**Score bands:**
- 0-2/10: No evidence or explicit absence
- 3-5/10: Generic statements, unquantified goals, or single mention without detail
- 6-8/10: Detailed paraphrase or partial quantification from prospect
- 9-10/10: Direct quote with quantified targets or confirmed commitment

PASS if evidence includes specific quotes or detailed paraphrases.
PASS if competitor mentions match GrowthBook's competitive set.
PASS if metrics are prospect-originated.

## Criterion 4: Actionable next steps

Every component below 7/10 needs at least one next step with contact name, specific action, and concrete question.

**Required format:** `[Contact Name or "contact TBD"]: [Action verb] by [date or timeframe]: [Specific question]`

FAIL if next steps use vague verbs without specifics: "follow up", "discuss further", "explore", "map out", "understand".
FAIL if component is Partial or Unknown with no next step.
FAIL if next step lacks timing (accept "next scheduled call" only if call cadence is documented).

**When no contacts have been identified yet, accept "[contact TBD]" as a valid placeholder in next steps.**
Example: "[contact TBD]: Confirm decision criteria in next call" is acceptable for early-stage deals.

**Acceptable action verbs:** Ask, Confirm, Request, Schedule, Send, Propose (with commitment mechanism), Validate (with specific metric).

PASS examples:
- "Ask Sarah Chen (VP Engineering) on Thursday's call: 'What's your current Snowflake warehouse setup and who manages data permissions?'"
- "Confirm with Mike Torres (Director of Growth) by end of week: 'Who holds final budget approval for tools over $50K?'"
- "[contact TBD]: Confirm decision criteria and evaluation timeline in next call"
- "Email [contact] by Friday: Request org chart showing approval chain for $100K+ decisions"

FAIL examples:
- "Follow up on technical requirements"
- "Discuss with team"
- "Explore data warehouse setup"
- "Map competitive landscape" (without specific competitor names or confirmation method)

## Criterion 5: No unsupported claims

FAIL if Champion described as "advocating internally" without evidence of internal selling behavior (presenting to peers, building business case, influencing others).
FAIL if Economic Buyer "confirmed" without explicit budget authority statement.
FAIL if timeline stated as confirmed when only mentioned as a target.

**Champion scoring:**
- 0-2/10: No evidence of internal engagement
- 3-5/10: Engaged evaluator, facilitating process, but no evidence of advocacy
- 6-8/10: Evidence of internal selling (looping in stakeholders, presenting internally)
- 9-10/10: Active business case building, documented peer influence

**ICP fit: PASS if ANY of the following are present:**
- Company has 100K+ monthly visitors or users (stated or confirmed)
- Modern data stack mentioned (warehouse, dbt, etc.)
- Product-led growth motion evident
- Experimentation or A/B testing is a stated priority
- Scale signals consistent with enterprise SaaS

FAIL only if the call reveals explicit ICP disqualifiers (e.g., "we don't do any experimentation", "we're a 100-person company with no data team", "marketing-only use case").

**Data quality:**
- When transcript is corrupted or missing, flag as "Data quality issue — cannot assess [component]" rather than penalizing analysis
- Accept "unconfirmed" or "to be validated" labels when data is genuinely unavailable

PASS if claims are grounded in specific evidence from calls.
PASS if uncertainty is acknowledged (e.g., "Champion appears engaged but no evidence yet of internal selling").

## GrowthBook-specific checks

FAIL if competitor mentioned but not mapped to: LaunchDarkly, Statsig, EPPO, Datadog, Optimizely, homegrown/internal tools.
FAIL if "good fit" claimed for marketing-only use case (wrong ICP).
FAIL if warehouse-native requirement not noted when Snowflake/BigQuery/Redshift mentioned.
FAIL if low traffic (<100K monthly visitors) not flagged as ICP concern.

**Competition scoring:**
- 0-2/10: No competitors mentioned or only incumbent identified without evaluation
- 3-5/10: 1-2 named competitors mentioned, no detailed comparison
- 6-8/10: Multiple competitors with evaluation criteria discussed
- 9-10/10: Head-to-head evaluation with documented differentiation

---

## Revision Notes

### Major changes:

1. **Criterion 2 (Carry-forward):** Added explicit "Score regression rules" subsection clarifying that downgrades require contradictory evidence, absence of new data ≠ regression, and corrupted calls maintain prior scores. This addresses the most frequent complaint across observations.

2. **Criterion 3 (Evidence quality):** Added explicit score bands (0-2, 3-5, 6-8, 9-10) with evidence requirements per tier. Added minimum word count (15 words) for "detailed paraphrase" to reduce ambiguity. This addresses inconsistent evidence threshold complaints.

3. **Criterion 4 (Next steps):** Added required format template and explicit list of acceptable/prohibited verbs. Clarified timing requirements (accept "next scheduled call" if cadence documented). This addresses the high volume of specificity complaints while maintaining rigor.

4. **Criterion 5 (No unsupported claims):** Added Champion scoring subsection with 0-2/3-5/6-8/9-10 bands distinguishing engagement from advocacy. Added data quality exception for corrupted transcripts. This addresses the frequent "passive participation vs. champion" confusion.

5. **GrowthBook-specific checks:** Added Competition scoring bands to align with other components.

### Removed or softened:

- Removed requirement for exact carry-forward phrasing ("No new information in this call — maintaining previous score of 8/10") in favor of outcome ("documented reason" is sufficient)
- Softened ICP fit from AND logic to ANY logic (already present but reinforced in examples)
- Clarified that "[contact TBD]" is acceptable systematically, not just "when no contacts identified yet"

### Result:
More prescriptive