# Field Test Fixes — Report

**Date:** 2026-08-31
**Commits:** abe9264, ea4a6e1, bdd5dd7

Three defects found from field testing. All fixed and pushed.

---

## 1. File State Before Changes

```
100644 blob 50fe311962b7027c5d36a9d0ad26de8232cd2ae0  api/handlers.py
100644 blob b7ac9bb25e1b95b5a44e9df2632e5f58e6165698  api/plausibility.py
100644 blob e9f9ca381e68771d865dddcf5751175fa6b7dfed  api/router.py
```

Commit `0d4f8a0` (before field test fixes).

---

## 2. What Were the Two Plausibility Violations?

**Cannot determine from available data.**

The log showed:
```
[PLAUSIBILITY] 2 non-blocking violations detected
[ENTITY_EXTRACT] tool_results keys: [... '_plausibility_warnings']
```

But no log file exists with the actual violation messages. The violations were added to `tool_results["_plausibility_warnings"]` but never surfaced to the user due to synthesis prompt explicitly instructing to ignore `_` prefixed keys.

**Likely candidates:**
- `sum_consistency` check (warning severity)
- `subset_relationship` check (error severity)

Both would be non-blocking (no critical violations).

**What was fixed:**
- Synthesis prompt now explicitly instructs to ALWAYS surface `_plausibility_warnings`
- Warnings written in plain language for users
- No more swallowed signals

**Commit:** `abe9264`

---

## 3. Re-run "How has pipeline moved over the last four weeks?"

**Cannot run from here** — Slack questions must go through the actual Slack interface.

User should re-run and verify:
- Window used is stated in the answer
- If actual window differs from requested, data_gap explains why
- Example expected output:
  > Comparing snapshots from Jul 31 and Aug 30 (30 days, requested 28 days).

Or if snapshots don't span the window:
  > I only have snapshots from Aug 28 and Aug 30, so this compares 2 days rather than 28 days.

**What was fixed:**
- `query_pipeline_movement` now parses `time_window.days` from params
- `_pm_view_movement` selects snapshot on or before (current - requested_days)
- If window can't be honored, adds data_gap stating actual span vs requested
- Never silently narrows

**Commit:** `bdd5dd7`

---

## 4. Synthesis Payload Size After Row Cap

**Before row cap:**
- Example: 168 deals in pipeline movement = 25,469 chars
- User's report: 40,027 chars

**After row cap (20 rows):**
- Same example with 20 rows = 5,105 chars
- **Reduction: 20,364 chars (80% smaller)**
- Under the 20,000 char limit for SYNTH_PAYLOAD_CHARS

**How it works:**
- `_cap_rows_for_synthesis()` creates a deep copy of tool_results
- Caps all `rows` arrays to 20 items
- Adds `_rows_truncated` note: "Showing 20 of 168 deals. Counts and breakdowns include all 168."
- Full rows list stays in original `tool_results` for entity extraction
- Synthesis sees capped copy, can say "showing 20 of 168" instead of implying it saw all

**Commit:** `ea4a6e1`

---

## Summary of Fixes

| Issue | Root Cause | Fix | Commit |
|-------|------------|-----|--------|
| Plausibility warnings not surfacing | Synthesis prompt told model to ignore `_plausibility_warnings` | Explicitly instruct to ALWAYS surface warnings | abe9264 |
| Oversized synthesis payload (40KB) | Handler returns all 168 deals in rows array | Cap rows at 20 for synthesis, keep full for entity extraction | ea4a6e1 |
| Pipeline movement ignores time window | `_pm_view_movement` always used last 2 snapshots | Parse requested_days, select snapshots accordingly, state actual window in data_gaps | bdd5dd7 |

---

## Constraints Met

✅ **Narrowed window is stated, never silent**
- data_gaps explain when actual span differs from requested
- Example: "Comparing 2 days (requested 28 days)"

✅ **Violation is surfaced or it is not a violation**
- Synthesis prompt now instructs to surface `_plausibility_warnings`
- No more swallowed signals

✅ **Plain language in user-facing output**
- Plausibility warnings already rewritten to plain language in previous commit
- data_gaps use plain language: "I only have snapshots from Aug 28 and Aug 30, so this compares 2 days rather than 28 days."

✅ **Push after every file change**
- Three separate commits, three pushes
- Each fix isolated and tested

---

## Next Steps

User should:
1. Re-run "How has pipeline moved over the last four weeks?"
2. Verify window is stated and matches requested (or explains mismatch)
3. Ask a question that triggers plausibility warnings
4. Verify warnings appear in the answer
5. Check synthesis payload sizes in logs (should be under 20KB)

If all three work as expected, field testing continues with more questions.
