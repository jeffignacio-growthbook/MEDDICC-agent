# TICKET 1: April 13, 2026 Pipeline Drop Investigation

**Type:** Business Anomaly Investigation
**Priority:** Medium
**Status:** ✅ CLOSED - Root Cause Confirmed
**Resolved:** 2026-09-05
**Resolution:** Departed-rep pipeline cleanup (intentional, no remediation needed)

---

## Summary

Q1 Week 11 (April 13, 2026) shows 44.2% decline in snapshot coverage (685 → 377 rows), driven by 328 deals closed on April 6, 2026.

## ✅ RESOLUTION (2026-09-05)

**Root Cause:** Departed-rep pipeline cleanup

**What Happened:**
- **Ivan Gomez (HubSpot owner ID 371635471)** left GrowthBook
- **Jeff bulk-closed Ivan's inactive deals on April 6, 2026** in a single cleanup pass
- **281 deals total** (145 auto-unassigned + 136 still tagged to Ivan's ID)
- **Timeframe:** 22:04-23:03 UTC (3:04-4:03 PM PT), 89% within first 5 minutes
- **Remaining 47 deals** (6 other owners) closed same day: separate/coincidental, low-priority

**Decision:** No remediation needed. Intentional cleanup of departed employee's inactive pipeline. Metrics valid post-cleanup.

**Evidence:** Property history shows all 281 deals transitioned to closed-lost on 2026-04-06. Analysis confirmed clustering (89% within 5 min), owner concentration (85.7% unassigned+Ivan), and manual action by Jeff.

## Evidence

### Quarter-End Patterns Comparison

| Quarter  | Week 10 | Week 13 | Change   | Active W10 | Active W13 |
|----------|---------|---------|----------|------------|------------|
| FY2026 Q3| 546     | 653     | +19.6%   | 546        | 653        |
| FY2026 Q4| 670     | 712     | +6.3%    | 670        | 712        |
| **FY2027 Q1** | **685** | **377** | **-44.2%** | **685** | **377** |

### Default Pipeline Impact

- **April 6 (Week 10):** 536 default pipeline deals (78.2% of snapshot)
- **April 13 (Week 11):** 234 default pipeline deals (62.1% of snapshot)
- **Net change:** -339 deals (-56% decline in default pipeline)
- **Renewals impact:** Minimal (149 → 143, -4%)

### Persistence

Drop is PERMANENT, not temporary:
- Q2 weeks 1-13: default pipeline averages 56-67% (vs 78% in Q1 week 10)
- Q3 weeks 1-4: default pipeline averages 61-66%
- Change persists through present day

## Technical Context

**Snapshot data source:** Reconstructed retrospectively in August 2026 from HubSpot property history

**Reconstruction logic:**
```python
def is_deal_open_at_date(create_date, stage_at_date, snapshot_date):
    if create_date > snapshot_date:
        return False
    if stage_at_date is None or not is_terminal_stage(stage_at_date):
        return True
    return False
```

**Key finding:** The reconstruction is working CORRECTLY. 339 deals genuinely transitioned to terminal (won/lost) stages between April 6-13 in HubSpot's historical record.

## Pre-Investigation Analysis Complete

**Date:** 2026-09-05

### Findings (See APRIL_6_ANALYSIS_SUMMARY.md for details)

**Pattern: RAPID BULK ACTION**

1. **Timestamp Clustering:** 89% closed within 5 minutes (292/328), 100% within 1 hour
   - First: 2026-04-06 22:04:06 UTC
   - Last: 2026-04-06 23:03:17 UTC
   - Span: 59 minutes

2. **Owner Distribution:** 85.7% concentrated in unassigned + one owner
   - Unassigned: 145 deals (44.2%)
   - Owner 371635471: 136 deals (41.5%)
   - 6 other owners: 47 deals (14.3%)

3. **Activity History:** 55% of sample had notes (NOT purely dormant deals)

### Narrowed Questions for Sales Leadership

**Primary Question:**
> "Was there a bulk close-lost workflow or cleanup action run on April 6, 2026, around 3 PM Pacific Time?"

**Specific Follow-ups:**
1. Who is HubSpot owner ID 371635471?
2. Why were 145 unassigned deals bulk-closed?
3. Was this Q1 end-of-quarter pipeline hygiene?
4. What criteria were used for selection?

## Investigation Approach (Updated 2026-09-05)

### Step 1: Identify Owner 371635471 (136 deals, 41.5%)
- Check HubSpot → Settings → Users & Teams
- Find owner with ID 371635471
- Contact them: "Did you bulk-close 136 deals on April 6 around 3 PM PT?"

### Step 2: Check Workflow Logs
- HubSpot → Automation → Workflows
- Filter: April 6, 2026, 22:00-23:00 UTC (3-4 PM PT)
- Look for: Deal stage updates affecting 300+ deals
- Document: Workflow name, criteria, execution time

### Step 3: Review Audit Logs
- HubSpot → Settings → Activity Log
- Filter: April 6, 2026, bulk updates
- Look for: Admin actions, API calls, integration activity

### Step 4: Business Context
- Interview: Sales leadership / RevOps lead
- Question: "Was there an end-of-Q1 cleanup directive or automation?"
- Check: Email/Slack for communications about pipeline hygiene

### Step 5: Decision
- **If intentional workflow:** Document criteria, validate appropriateness
- **If manual cleanup:** Review selection logic, check for errors
- **If accidental:** Identify incorrectly closed deals for re-open

## Non-Actions (Things NOT to do)

- ❌ **Do not backfill/adjust snapshot data** without understanding root cause
- ❌ **Do not assume reconstruction bug** - the logic is verified correct
- ❌ **Do not treat as "fixed already"** - the pattern persists in Q2-Q3

## Artifact Locations

- Investigation script: `investigate_q1_snapshot_drop.py`
- Pre-investigation analysis: `analyze_april_6_bulk_close_v2.py`
- Analysis summary: `APRIL_6_ANALYSIS_SUMMARY.md`
- Analysis data: `april_6_analysis.json`
- Reconstruction logic: `scripts/analytics/point_in_time.py:268-308`
- Snapshot backfill: `scripts/analytics/backfill_snapshots.py`

## Lessons Learned

1. **Bulk close-lost events leave clear signatures:**
   - Timestamp clustering (89% within 5 minutes)
   - Owner concentration (85.7% from one source)
   - Property history provides exact timing

2. **Employee departure cleanup is normal but should be flagged:**
   - 281 deals closed in one action is high-magnitude
   - Real-time alerting would have surfaced this immediately
   - Recommended: Add bulk_closed_lost_event trigger to monitoring

3. **Investigation approach worked:**
   - Ruled out reconstruction artifact via retention analysis
   - Narrowed to specific questions before sales leadership interview
   - Pattern analysis (timestamp + owner + activity) pinpointed cause

## Success Criteria

✅ Root cause identified with evidence (Ivan Gomez departure cleanup)
✅ Decision documented: Accept as-is, no remediation needed
✅ Confirmed by Jeff directly

---

**Filed:** 2026-09-05
**Resolved:** 2026-09-05 (same day)
**Investigator:** Claude Sonnet 4.5
**Confirmed By:** Jeff Ignacio
**Status:** CLOSED - Departed-rep pipeline cleanup (intentional)
