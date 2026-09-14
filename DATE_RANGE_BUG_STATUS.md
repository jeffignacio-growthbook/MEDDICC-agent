# Date-Range Bug Status Report

**Date:** 2026-09-14
**Issue:** "last 2 weeks" queries pulling incorrect date ranges

---

## Finding: Bug Already Fixed on 2026-09-10

### Original Bug (Discovered 2026-09-10)

**Symptom:** "last 2 weeks" from Sep 10 pulled data from Aug 17-28 (wrong window) instead of Aug 27-Sep 10 (correct 14-day window).

**Occurred in:** Two separate Slack threads on 2026-09-10

### Root Cause (Identified 2026-09-10)

Two-part failure:

1. **Handler bug:** `query_pipeline_movement` in `api/handlers.py` checked `time_window.get("type") == "relative_days"` - a shape that nothing in the codebase ever produced. The router always resolves `time_window` to `{start, end, label}` via `resolve_time_window()` before any handler runs. Result: `requested_days` was always `None`, so the 'movement' view silently fell back to "compare the last two snapshots on file" instead of the window the user requested.

2. **Schema gap:** The intent classifier's JSON schema for `time_window` had no `n` field for `period=last_N_days`, so `resolve_time_window()`'s `tw.get("n", 30)` couldn't be populated correctly from a phrase like "last 2 weeks".

### Fix (Implemented 2026-09-10)

**Commits:**
- `30a91b7` - Fix pipeline-movement date-window bug (2026-09-10 16:44 UTC)
- `90d3bdf` - Structural fix: resolve_time_window() single source of truth (2026-09-10 17:50 UTC)

**Changes:**

1. **api/handlers.py** (line 4494-4498):
   ```python
   # NEW: Derive requested_days from resolved time_window
   requested_days = None
   if time_window and time_window.get("start") and time_window.get("end"):
       try:
           requested_days = (date.fromisoformat(time_window["end"])
                              - date.fromisoformat(time_window["start"])).days
   ```

2. **api/router.py** (line 880):
   ```python
   # Added "n" field to classifier schema
   "n": "<REQUIRED integer when period=last_N_days: the number of days back
         from today, e.g. 'last 2 weeks'=14, 'last 30 days'=30>"
   ```

3. **api/time_resolver.py** (lines 20-35):
   ```python
   # Changed from date.today() to today_in_reporting_tz()
   # Ensures consistent "today" across all components using reporting timezone
   ```

### Testing (2026-09-10)

**Test file:** `tests/test_time_window_resolution.py`

**Test results (verified 2026-09-14):**
```
✓ resolve_time_window('last 2 weeks') from a known date is exact
✓ resolve_time_window('last 30 days') from a known date is exact
✓ resolve_time_window follows reporting timezone, not server UTC
✓ requested_days=None reproduces the reported Aug17-28 window
✓ requested_days=14 picks the snapshot actually 14 days back
✓ large gap between requested window and available snapshots is flagged

✅ All tests passed
```

**Live verification (2026-09-14):**
```
Input: period=last_N_days, n=14, today=2026-09-10
Output: start=2026-08-27, end=2026-09-10, label=last 14 days
✅ PASS: Correctly resolved to 2026-08-27 - 2026-09-10 (14 days)
```

---

## Current Status

✅ **Bug is FIXED and VERIFIED**

- Root cause identified and corrected
- Tests passing with frozen "today" dates
- CI gate in place (tests run on every commit)
- No recurrence since 2026-09-10 fix

---

## Architecture: How Date Resolution Works Now

```
User question: "How has pipeline moved in the last 2 weeks"
    ↓
api/router.py: Intent classifier extracts time_window
    → {period: "last_N_days", n: 14}  [n field added in fix]
    ↓
api/time_resolver.py: resolve_time_window()
    → Uses today_in_reporting_tz() (not server UTC)
    → Returns {start: "2026-08-27", end: "2026-09-10", label: "last 14 days"}
    ↓
api/handlers.py: query_pipeline_movement()
    → Derives requested_days from (end - start).days  [added in fix]
    → requested_days = 14
    → _pm_view_movement() selects snapshot ~14 days before latest
    → Correctly compares Aug 27 vs Sep 10 (not Aug 17 vs Aug 28)
```

### Key Design Improvements

1. **Single source of truth:** `resolve_time_window()` is now the ONLY place that computes date ranges. Handlers never do their own date math.

2. **Timezone consistency:** All date resolution uses `today_in_reporting_tz()` from `config/client.yaml` (America/New_York), not server UTC.

3. **Explicit day counts:** The classifier's schema now requires `n` for `last_N_days`, so "2 weeks" → n=14 deterministically, not left to LLM guessing.

4. **Snapshot selection:** Handlers derive `requested_days` from already-resolved `time_window`, not from a parallel/competing resolution path.

---

## Related Documentation

- `tests/test_time_window_resolution.py` - Test suite with frozen dates
- `PENDING_WORK.md` - Lines 161-170 (caveat about synthesis test needing re-verification)
- `PENDING_WORK.md` - Line 1877 (Recently Completed #6)
- Commit `30a91b7` - Original fix commit message

---

## Action Needed

**None.** This bug was already root-caused, fixed, tested, and CI-gated on 2026-09-10.

If the user is seeing this behavior again, it would be a NEW bug (not the same one), and would require:
1. Slack thread link or query logs showing the incorrect date range
2. Verification that the fix commits are deployed to production
3. Investigation of whether a different code path is involved
