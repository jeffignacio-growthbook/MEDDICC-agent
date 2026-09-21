# Nightly Workflow Bugs - Root Cause Analysis
**Date**: 2026-09-21
**Analyst**: Claude Sonnet 4.5

## Bug #1: HubSpot 400 Bad Request on Component Score Writes

### Symptoms
- 98/179 deals (54.7%) failing with "HubSpot component scores failed: 400 Client Error: Bad Request"
- Each failure followed by "Future failed: 'iterations'" KeyError
- Affects `write_component_scores()` in rollup_deal_scores.py

### Root Cause
**Property name mismatch between code and HubSpot schema**

Code sends (scripts/call_scorer.py line 35):
```python
("Identified Pain", "pain")  # Key is "pain"
```

This creates properties:
- `meddicc_pain_score`
- `meddicc_pain_status`
- `meddicc_pain_rationale`

HubSpot schema has (scripts/setup_hubspot_properties.py line 20):
```python
("identified_pain", "Identified Pain")  # Key is "identified_pain"
```

Actual properties:
- `meddicc_identified_pain_score`
- `meddicc_identified_pain_status`
- `meddicc_identified_pain_rationale`

### Git Blame
- **Aug 12, 2026** (be16c07c): setup_hubspot_properties.py created with `"identified_pain"` key
- **Aug 23, 2026** (17aaecfb): Progressive Scoring Phase 1 introduced call_scorer.py with `"pain"` key
- **Mismatch created**: Aug 23, 2026

### Timeline Analysis
NOT a Sept 15 regression:
- Sept 14 run (marked "success"): **HAD SAME 400 ERRORS** (10+ deals failed)
- Sept 12-13 runs: **ALSO HAD 400 ERRORS** (checked logs)
- Bug existed since **Aug 23, 2026** (43+ days)
- Workflow completes as "success" because errors caught as warnings

### Impact Scope
- **124 out of 834 qualifying calls** (14.9%) have component scores in Supabase
- **All deals with pain scores**: Failed to write pain component to HubSpot
- **Other 6 components**: Write successfully
- **HubSpot deal properties**: Overall score/status write successfully (different code path)

### Secondary Bug: 'iterations' KeyError
After HubSpot 400 error, code attempts to access `result['iterations']` which doesn't exist in error response.

**Location**: Likely in async/futures handling code that expects successful HubSpot response

---

## Bug #2: Git Push Failure "cannot pull with rebase: You have unstaged changes"

### Symptoms
- Every nightly run since Sept 15: exit code 128
- Error: "error: cannot pull with rebase: You have unstaged changes"
- Occurs in final step: "Commit memory and analysis updates"

### Git Logic (`.github/workflows/nightly.yml:150-160`)
```bash
git config --local user.email "github-actions[bot]@users.noreply.github.com"
git config --local user.name "github-actions[bot]"
git add memory/ output/
git diff --quiet && git diff --staged --quiet || git commit -m "Update MEDDICC agent memory and analyses [skip ci]"
git pull --rebase origin main || {
  git rebase --abort
  git pull origin main --no-rebase -X ours
}
git push
```

### Root Cause
**UNCONFIRMED - Initial race condition theory contradicted by actual timestamps**

**Initial hypothesis (DISPROVEN):**
Suspected workflow timing race between Daily Calls ETL and Nightly MEDDICC Agent, but actual GitHub Actions timestamps show:

| Date | Daily Deal ETL | Daily Calls ETL | Nightly | Overlap? |
|------|---------------|-----------------|---------|----------|
| Sept 12 ✅ | 05:26→05:27 | 06:02→06:08 | 06:58→06:59 | NO - 49min gap |
| Sept 13 ✅ | 05:42→05:43 | 06:26→06:29 | 07:16→07:17 | NO - 47min gap |
| Sept 14 ✅ | 05:52→05:53 | 06:36→06:41 | 07:40→07:42 | NO - 59min gap |
| Sept 15 ❌ | 05:55→05:55 | 06:19→06:26 | 07:23→07:26 | NO - 57min gap |
| Sept 16+ ❌ | (same pattern) | (same pattern) | (all failed) | NO overlap |

**Daily Calls ETL completes 45-60 minutes BEFORE Nightly starts - no timing overlap on any date.**

**What changed Sept 15? (Three unverified hypotheses):**
1. **Merged PR hypothesis**: PRs updating `prompts/CLAUDE.md` merged around Sept 15, and the nightly workflow may have started writing to that file locally (not just via PR), creating unstaged changes outside `memory/` and `output/`
2. **New file creation hypothesis**: Code changes around Sept 15 introduced new file writes outside `memory/output/` directories that `git add memory/ output/` doesn't capture
3. **GitHub Actions runner change hypothesis**: GitHub infrastructure change around Sept 15 affecting how git rebase behaves with concurrent remote updates

**None of these hypotheses have been verified against actual evidence.**

**The mechanism (confirmed from logs):**
1. Nightly workflow stages changes with `git add memory/ output/`
2. Tries `git pull --rebase origin main`
3. Error: "cannot pull with rebase: You have unstaged changes"
4. This means files OUTSIDE `memory/` and `output/` were modified but not staged

**What's missing:**
- No `git status` output in logs showing WHICH files are unstaged
- No confirmation whether the unstaged files are in the working tree or elsewhere
- No investigation of what the nightly run actually writes to disk

### Git Blame
- **nightly.yml**: Last modified Aug 10, 2026 (6efc7b18)
- **daily-calls-etl.yml**: Created Aug 8, 2026, but working fine until Sept 15
- **What changed Sept 15**: Unknown - likely combination of:
  - Increased Daily Calls ETL duration (more calls to process?)
  - Increased Nightly runtime (more deals to analyze?)
  - More frequent conflicts in `memory/calls/` files both workflows touch

### Timeline
- Aug 8: Daily Calls ETL created (ran at 1:30 AM UTC)
- Aug 10: Nightly workflow git logic last modified
- Sept 12-14: Both workflows succeed (no timing conflict)
- Sept 15+: Both workflows fail with "unstaged changes" (conflict every night)

---

## Recommended Fixes

### Fix #1: Property Name Mismatch (CRITICAL)
**Option A**: Update call_scorer.py to use "identified_pain"
```python
# scripts/call_scorer.py line 35
("Identified Pain", "identified_pain"),  # Match HubSpot schema
```

**Option B**: Recreate HubSpot properties with "pain" key
- Run modified setup script
- Less preferred (requires HubSpot admin action)

**Recommendation**: Option A - one-line code fix

### Fix #2: Git Conflict (Status: ROOT CAUSE UNKNOWN)
**Problem**: Nightly workflow fails with "cannot pull with rebase: You have unstaged changes" since Sept 15

**What we know doesn't work:**
- Workflow timing overlap is NOT the issue (verified via timestamps)
- All three ETL workflows complete without overlap on both passing and failing dates

**Defensive fix (recommended despite unknown root cause):**
Stagger workflow schedules anyway - eliminates one potential failure mode even if it's not the current trigger:

```yaml
# .github/workflows/daily-deal-etl.yml
cron: '0 0 * * *'  # Midnight UTC (was 1 AM)

# .github/workflows/daily-calls-etl.yml
cron: '0 1 * * *'  # 1 AM UTC (was 1:30 AM)

# .github/workflows/nightly.yml
cron: '0 3 * * *'  # 3 AM UTC (was 2 AM)
```

**Why apply this fix despite not confirming it addresses the root cause:**
- Staggering is defensive and low-risk
- Eliminates one class of potential conflicts (even if not the current one)
- Doesn't prevent further investigation
- If it doesn't fix the issue, the failure continues and we get more diagnostic data

**Alternative diagnostic approach (if schedule change doesn't fix it):**
Add `git status` output to workflow before the commit step:
```yaml
- name: Show git status before commit
  run: git status --porcelain
```

This would show WHICH files have unstaged changes, revealing whether it's:
- Files outside memory/output/ that need to be added to `git add`
- A git state issue unrelated to file modifications
- Something else entirely

---

## Testing Plan

### Test Fix #1
1. ✅ COMPLETED - Updated call_scorer.py line 35 (commit a90e7c8)
2. ✅ VERIFIED - test_hubspot_400.py returns 200 OK with properties written
3. PENDING - Dispatch nightly workflow manually
4. PENDING - Verify 0 component score 400 errors in workflow logs

### Test Fix #2
1. Update workflow schedule times (Option A recommended)
2. Commit and push workflow changes
3. Monitor next 3 nights (Sept 22-24):
   - Check Daily Deal ETL completes before Daily Calls ETL starts
   - Check Daily Calls ETL completes before Nightly starts
   - Verify all three workflows succeed with no git conflicts
4. If still failing:
   - Check workflow logs for timing overlaps
   - Consider Option B (workflow dependencies) or Option C (merge workflows)

---

## Historical Context

Both bugs demonstrate:
1. **Incomplete test coverage**: Property mismatch not caught in testing
2. **Silent failures**: 400 errors logged as warnings, workflow marked "success"
3. **Monitoring gap**: No alerts on HubSpot write failures
4. **Schema drift**: Code and setup scripts diverged without detection
