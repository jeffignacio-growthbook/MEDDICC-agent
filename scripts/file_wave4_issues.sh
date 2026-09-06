#!/bin/bash
# Wave 4 Bug Documentation - Create GitHub Issues
#
# Prerequisites:
# 1. Enable Issues on GitHub: Repo → Settings → General → Features → Check "Issues"
# 2. Run this script to file all 5 Wave 4 bug issues
#
# All bugs are marked CLOSED since they were fixed during Wave 4 remediation.

set -e

echo "Filing Wave 4 bug documentation issues..."

# Get commit SHAs
COMMIT_ITEMS_1_5=$(git log --oneline --grep="Wave 4 Item" | grep "Item 5" | cut -d' ' -f1)
COMMIT_ITEM_6=$(git log --oneline --grep="Wave 4 Item 6" | cut -d' ' -f1)
COMMIT_ITEM_7=$(git log --oneline --grep="Wave 4 Item 7" | cut -d' ' -f1)
COMMIT_ITEM_8=$(git log --oneline --grep="Wave 4 Item 8" | cut -d' ' -f1)
COMMIT_ITEM_9=$(git log --oneline --grep="Wave 4 Item 9" | cut -d' ' -f1)

echo "Commit SHAs:"
echo "  Items 1-5 (at-risk consolidation): $COMMIT_ITEMS_1_5"
echo "  Item 6 (q020): $COMMIT_ITEM_6"
echo "  Item 7 (q003): $COMMIT_ITEM_7"
echo "  Item 8 (q011): $COMMIT_ITEM_8"
echo "  Item 9 (q016): $COMMIT_ITEM_9"
echo

# Issue 1: q012 - Duplicate at-risk logic
gh issue create \
  --title "[Wave 4] q012 - Duplicate at-risk logic with divergent results" \
  --label "bug,wave4" \
  --body "**Problem:** Agent returned two different at-risk counts in same conversation:
- First answer (pipeline response): 94 deals flagged at-risk
- Follow-up answer: 33 deals are flagged at-risk
- Neither matched verified value (70 deals)

**Root Cause:** Two separate at-risk implementations with different logic:
1. \`query_waterfall\` used simple thresholds: \`overall_score < 40 OR champion_score < 4\` → 94 deals
2. \`query_deals_at_risk\` used stage-aware MEDDICC band checking → 33 deals

This violated single-source-of-truth principle and caused user-visible inconsistency.

**Fix (Items 1-5):**
1. Moved at-risk definition to \`config/field_semantics.yaml\` as canonical source
2. Generated \`is_at_risk_quick()\` helper in \`api/field_semantics.py\`
3. Created unified \`compute_at_risk_deals()\` function in \`api/handlers.py\` with:
   - Quick check mode (simple thresholds for performance)
   - Stage-aware mode (canonical MEDDICC band checking)
4. Rewired both handlers to call unified function
5. Added drift test (\`scripts/test_at_risk_isolation.py\`) to prevent recurrence

**Result:** Single source of truth with two modes (quick/canonical), consistent results, drift prevention.

**Commits:**
- Items 1-5: ${COMMIT_ITEMS_1_5}

**Status:** ✅ FIXED - All handlers now route through unified function, drift test passing" \
&& echo "✓ Filed issue 1: q012"

# Issue 2: q020 - Wrong field extraction
gh issue create \
  --title "[Wave 4] q020 - Wrong field extracted for 'missing X' questions" \
  --label "bug,wave4" \
  --body "**Problem:**
- Question: \"How many active deals are missing owner_email?\"
- Agent queried: \`deal_value=eq.0\` (wrong field!)
- Should query: \`owner_email=is.null\`

**Root Cause:** DYNAMIC_SYSTEM_PROMPT had specific guidance for \"No ARR recorded\" ambiguity but no general rule for \"missing X\" questions. Agent fell through to ARR-related defaults.

**Fix (Item 6):**
Added explicit MISSING VALUE DETECTION guidance before ARR-specific section:
\`\`\`
For \"missing X\" questions, extract field name and filter with [\"is_\", \"field_name\", \"null\"].

Example: \"missing owner_email\" → filter owner_email with is_ null operator
Example: \"no close_date\" → filter close_date with is_ null
\`\`\`

**Result:** Dynamic query agent now correctly extracts field names from \"missing X\" patterns.

**Commit:** ${COMMIT_ITEM_6}

**Status:** ✅ FIXED - Added field extraction guidance to dynamic prompt" \
&& echo "✓ Filed issue 2: q020"

# Issue 3: q003 - Synthesis truncation
gh issue create \
  --title "[Wave 4] q003 - Total count lost during synthesis truncation" \
  --label "bug,wave4" \
  --body "**Problem:**
- Agent queried correctly: found 142 deals with no ARR recorded
- Final answer only showed \"~19 deals\" without total count
- User saw sample size instead of full count

**Root Cause:**
\`_cap_rows_for_synthesis\` caps arrays at 20 items and adds \`_truncated\` note with full count (e.g., \"Showing 20 of 142 items\"). But synthesis prompt had rule:

\`\`\`
OPERATOR METADATA: Keys prefixed with _ EXCEPT _plausibility_warnings are for operators only
\`\`\`

So agent was explicitly told to IGNORE the \`_truncated\` field containing the count.

**Fix (Item 7):**
1. Added \`_truncated\` to exceptions list: \"_ EXCEPT _plausibility_warnings and _truncated\"
2. Added new TRUNCATION NOTES section:
   - Always lead with total count when _truncated present
   - Format: \"*142 deals* (showing 20 examples):\" not \"~20 deals\"
   - Extract count from _truncated note text

**Result:** Synthesis agent now surfaces total count prominently when data is capped.

**Commit:** ${COMMIT_ITEM_7}

**Status:** ✅ FIXED - _truncated now surfaced, synthesis preserves counts" \
&& echo "✓ Filed issue 3: q003"

# Issue 4: q011 - Pipeline over-filtering
gh issue create \
  --title "[Wave 4] q011 - Over-filtering on generic pipeline queries" \
  --label "bug,wave4" \
  --body "**Problem:**
- Question: \"What is our pipeline this quarter?\"
- Agent returned: \$17.1M / 162 qualified new-business deals
- Should return: \$25M / 444 ALL active deals

**Root Cause:** Dynamic query loop added \"qualified\" + \"new business\" filters without being asked. Question said \"pipeline\" generically, not \"qualified pipeline\" or \"new business pipeline\".

**Fix (Item 8):**
Added DEFAULT SCOPING section to DYNAMIC_SYSTEM_PROMPT:
\`\`\`
For GENERIC pipeline questions:
- Include ALL active deals (deal_status = 'active')
- Do NOT add filters for qualified/new business/stages/owners
- ONLY add filters when explicitly requested

Generic \"pipeline\" means EVERYTHING active. Resist the urge to assume qualifiers.
\`\`\`

**Result:** Agent no longer adds implicit filters. Generic \"pipeline\" returns all active deals.

**Commit:** ${COMMIT_ITEM_8}

**Status:** ✅ FIXED - Added explicit no-filtering rule for generic queries" \
&& echo "✓ Filed issue 4: q011"

# Issue 5: q016 - Wrong cycle time calculation
gh issue create \
  --title "[Wave 4] q016 - Wrong median cycle time (80 vs 159 days)" \
  --label "bug,wave4" \
  --body "**Problem:**
- Question: \"Calculate historical sales cycle times\"
- Agent said: \"median closer to 80 days\"
- Verified value: 159 days median cycle
- Off by 50% (almost double)

**Root Cause:** No explicit instructions for cycle time calculation in DYNAMIC_SYSTEM_PROMPT. Agent likely used wrong date fields (maybe last_updated instead of create_date) or calculated average of stage-specific durations.

**Fix (Item 9):**
Added CYCLE TIME CALCULATION section to DYNAMIC_SYSTEM_PROMPT:
\`\`\`
For \"sales cycle time\" or \"time to close\":
- Use ALL closed deals (won + lost), not just won
- Calculate: (close_date - create_date) in days
- Report MEDIAN not average (robust to outliers)
- Do NOT use stage-specific durations or last_updated field

Cycle time = deal creation to deal closure, inclusive of all stages.
\`\`\`

**Result:** Agent now uses correct date fields and calculation method.

**Commit:** ${COMMIT_ITEM_9}

**Status:** ✅ FIXED - Added explicit cycle time calculation guidance" \
&& echo "✓ Filed issue 5: q016"

echo
echo "✅ All 5 Wave 4 bug issues filed successfully!"
echo
echo "Next: Close all issues since fixes are already committed:"
echo "  gh issue list --label wave4 --json number --jq '.[].number' | xargs -I {} gh issue close {}"
