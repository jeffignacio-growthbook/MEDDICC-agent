# Wave 4 Issue Filing - Instructions

## Status

**5 bugs fixed, documentation ready to file.**

All Wave 4 bugs have been fixed and committed. This document explains how to file the GitHub Issues to create a documentation trail.

---

## Manual Step Required: Enable GitHub Issues

GitHub Issues is currently disabled on this repository.

**To enable:**
1. Go to: https://github.com/jeffignacio-growthbook/MEDDICC-agent/settings
2. Scroll to "Features" section
3. Check the box next to "Issues"
4. Click "Save"

---

## After Enabling Issues: Run the Script

Once Issues is enabled, run:

```bash
./scripts/file_wave4_issues.sh
```

This will create 5 GitHub Issues documenting each bug:

1. **[Wave 4] q012** - Duplicate at-risk logic with divergent results
2. **[Wave 4] q020** - Wrong field extracted for 'missing X' questions
3. **[Wave 4] q003** - Total count lost during synthesis truncation
4. **[Wave 4] q011** - Over-filtering on generic pipeline queries
5. **[Wave 4] q016** - Wrong median cycle time (80 vs 159 days)

Each issue includes:
- Problem statement
- Root cause analysis
- Fix summary
- Commit SHA(s)
- Status: ✅ FIXED

All issues will have labels: `bug`, `wave4`

---

## Closing the Issues

Since all bugs are already fixed, close them immediately after filing:

```bash
gh issue list --label wave4 --json number --jq '.[].number' | xargs -I {} gh issue close {}
```

This creates a clean documentation trail: issues exist, are labeled correctly, reference the fix commits, and are marked resolved.

---

## Summary of Fixes

### PART A: q012 At-Risk Consolidation (Items 1-5)
**Problem:** Two divergent at-risk implementations (94 vs 33 deals)

**Fix:**
- Moved definition to `config/field_semantics.yaml`
- Generated `is_at_risk_quick()` helper
- Created unified `compute_at_risk_deals()` function
- Rewired both handlers to use unified logic
- Added drift test to prevent recurrence

**Commits:** 5 separate commits (Items 1-5)

---

### PART B: Individual Bugs (Items 6-9)

#### Item 6: q020 - Wrong Field Extraction
**Problem:** Queried `deal_value` when should filter `owner_email`

**Fix:** Added "missing X" pattern guidance to DYNAMIC_SYSTEM_PROMPT

**Commit:** Item 6

---

#### Item 7: q003 - Synthesis Truncation
**Problem:** Total count lost when results capped (showed "~19 deals" not "142 deals")

**Fix:** Added `_truncated` to synthesis exceptions, instructed agent to lead with total count

**Commit:** Item 7

---

#### Item 8: q011 - Pipeline Over-Filtering
**Problem:** Added "qualified + new business" filters to generic "pipeline" question

**Fix:** Added DEFAULT SCOPING section - no implicit filters unless requested

**Commit:** Item 8

---

#### Item 9: q016 - Wrong Cycle Time
**Problem:** Calculated 80 days median when verified is 159 days

**Fix:** Added CYCLE TIME CALCULATION section with explicit date fields and method

**Commit:** Item 9

---

## Why This Matters

Wave 4 calibration found 52.9% accuracy (9/17 correct). After these fixes:
- 5 genuine bugs resolved
- Drift prevention in place for at-risk logic
- Dynamic query prompt hardened with explicit guidance
- All fixes tested and committed

Filing these issues creates:
1. Documentation trail for future reference
2. Clear problem → root cause → fix linkage
3. Searchable history for similar bugs
4. Evidence of systematic debugging approach

---

## Next Steps After Filing

1. ✅ Enable GitHub Issues (manual)
2. ✅ Run `./scripts/file_wave4_issues.sh`
3. ✅ Close all wave4 issues (already fixed)
4. Run full Wave 4 calibration with fresh verified values
5. Establish new clean baseline

The clean slate calibration should show significantly higher accuracy now that these bugs are fixed.
