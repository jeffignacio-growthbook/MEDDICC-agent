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

## Criterion 2: Carry-forward consistency

Compare against cumulative state. Identified or Partial components must remain at that level unless the recent call contradicts them.

FAIL if component regresses without documented reason.
PASS if analysis notes "No new information — maintaining previous assessment" for unchanged components.

Example: If Economic Buyer was scored 8/10 in cumulative state and recent call doesn't mention them, the analysis must maintain 8/10 and explicitly note "No new EB information in this call - maintaining previous score of 8/10."

## Criterion 3: Evidence quality

All evidence from the call or cumulative state only.

FAIL if score above 5/10 lacks a direct quote or paraphrase.
FAIL if competitor not in this list: LaunchDarkly, Statsig, EPPO, Datadog Experiments, Optimizely, or homegrown/internal tools
FAIL if value metrics not stated by the prospect (seller-stated ROI doesn't count).

PASS if evidence includes specific quotes or detailed paraphrases.
PASS if competitor mentions match GrowthBook's competitive set.
PASS if metrics are prospect-originated (e.g., "They want to run 5x more experiments per quarter").

## Criterion 4: Actionable next steps

Every component below 7/10 needs at least one next step with contact name, specific action, and concrete question.

FAIL if next steps use: "follow up", "discuss further", "explore".
FAIL if component is Partial or Unknown with no next step.

PASS examples:
- "Ask Sarah Chen (VP Engineering) on Thursday's call: 'What's your current Snowflake warehouse setup and who manages data permissions?'"
- "Confirm with Mike Torres (Director of Growth) by end of week: 'Who holds final budget approval for tools over $50K?'"

FAIL examples:
- "Follow up on technical requirements"
- "Discuss with team"
- "Explore data warehouse setup"

## Criterion 5: No unsupported claims

FAIL if Champion described as "advocating internally" without evidence of internal selling behavior.
FAIL if Economic Buyer "confirmed" without explicit budget authority.
FAIL if timeline stated as confirmed when only mentioned as a target.
FAIL if ICP fit claimed without evidence of: 100K+ monthly visitors OR modern data stack OR Product-Led motion OR Experimentation Leader role.

PASS if claims are grounded in specific evidence from calls.
PASS if uncertainty is acknowledged (e.g., "Champion appears engaged but no evidence yet of internal selling").

## GrowthBook-specific checks

FAIL if competitor mentioned but not mapped to: LaunchDarkly, Statsig, EPPO, Datadog, Optimizely, homegrown
FAIL if "good fit" claimed for marketing-only use case (wrong ICP)
FAIL if warehouse-native requirement not noted when Snowflake/BigQuery/Redshift mentioned
FAIL if low traffic (<100K monthly visitors) not flagged as ICP concern
