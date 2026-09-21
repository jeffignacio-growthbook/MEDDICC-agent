# Supabase Write Investigation - Sept 21, 2026

## Initial Misdiagnosis

**Original claim (WRONG):** "Only 4/327 closed-won deals have analyses, 1.2% coverage"
- Based on misunderstanding of which deals should have analyses
- Closed-won deals (328) are NOT the population being analyzed
- Nightly agent analyzes ACTIVE/OPEN deals (179/night)

**Correct population:** Active deals being processed by nightly workflow

---

## Actual Failure Rates - Two Distinct Periods

### Historical (Aug 24 - Sept 20, PRE-FIX)
**Period:** 28 days, before commit a90e7c8 (Bug #1 fix)
- Deals processed/night: 179
- Unique deals with analyses in Supabase: 33
- **Success rate: 18.4% (33/179)**
- **Failure rate: 81.6% (146/179 avg)**
- Error messages in logs: 0 ("Supabase analysis write failed" never appeared)

### Current (Sept 21, POST-FIX)
**Period:** Tonight only, after commit a90e7c8 (Bug #1 "pain" → "identified_pain" fix)
- Deals processed: 179
- Analyses written to Supabase: 98
- **Success rate: 54.7% (98/179)**
- **Failure rate: 45.3% (81/179)**
- Error messages in logs: 0 (still silent)

**Improvement:** 33 → 98 unique deals (+197% increase), but still 81 failures remain

---

## Direct ID Overlap Analysis (VERIFIED - SHOCKING FINDING)

**Hypothesis:** The 81 Supabase failures correlate with Bug #1's HubSpot 400 errors
**Result:** **HYPOTHESIS COMPLETELY WRONG**

### Actual ID Overlap (Sept 21, 2026):

**Set A: HubSpot 400 errors (Bug #1)**
- Count: 98 deals
- Error: "400 Client Error: Bad Request" on component score writes

**Set B: Supabase successful writes**
- Count: 98 deals
- Successfully inserted to analyses table

**Overlap: 100% (98/98 deals are IDENTICAL)**

**The 98 deals that FAILED HubSpot writes are the EXACT SAME deals that SUCCEEDED in Supabase writes!**

---

**Set C: Supabase missing writes**
- Count: 81 deals
- Processed by nightly workflow but NO row in analyses table

**Overlap with HubSpot 400 errors: 0% (0/81 deals overlap)**

**The 81 deals that FAILED Supabase writes had NO HubSpot 400 errors at all!**

---

### Conclusion: Two INDEPENDENT, DISJOINT Bug Populations

```
179 deals processed tonight:
├─ 98 deals: HubSpot FAILED, Supabase SUCCEEDED (Bug #1)
└─ 81 deals: HubSpot succeeded (?), Supabase FAILED (Bug #?)
```

**This means:**
1. Bug #1 (HubSpot 400) does NOT cause Supabase failures
2. Supabase failures are a SEPARATE, UNDIAGNOSED bug
3. The two failure modes are completely independent
4. Bug #1 fix (a90e7c8) did NOT improve Supabase write rate
5. The 33 → 98 improvement was coincidental or a separate effect

**Root cause of 81 Supabase failures: COMPLETELY UNKNOWN**
- No error messages in logs (still silent)
- No correlation with HubSpot failures
- Different deal population
- Need actual exception text to diagnose

---

## Code Path Analysis

```python
# scripts/rollup_deal_scores.py lines 165-185
if hubspot:
    try:
        hubspot.write_component_scores(deal_id, component_details)
    except Exception as e:
        print(f"⚠️ {company}: HubSpot component scores failed: {e}")
        # CONTINUES - does not prevent Supabase write

if sb_writer:
    try:
        scores = hs._extract_scores_from_analysis(analysis)  # Parses markdown
        sb_writer.insert_analysis(
            deal_id=str(deal_id),
            company_name=company,
            scores=scores,  # If malformed, insert fails
            ...
        )
    except Exception as e:
        print(f"⚠️ {company}: Supabase analysis write failed: {e}")
        # ERROR SWALLOWED - no exit, no re-raise, no counter
```

**Both writes depend on `_extract_scores_from_analysis()` parsing markdown correctly.**
- Bug #1 fixed call_scorer.py to generate "identified_pain" in markdown
- But if parser still expects "pain", extraction fails
- Malformed `scores` dict → Supabase schema validation error

**This is speculation until actual error messages are captured.**

---

## Silent Failure Pattern

**The fatal flaw:**
- Exceptions caught and logged as warnings
- Workflow continues as "success" regardless
- No counters, no success-rate tracking
- No workflow-level signal (no failure threshold)

**Result:** 81.6% failure rate invisible for 28 days, 45.3% failure rate invisible tonight

---

## Next Steps (IN ORDER)

### Step 1: Direct ID Comparison (IMMEDIATE)
Compare Sept 21 deal IDs:
- 98 HubSpot 400 errors from Bug #1 logs
- 81 missing from Supabase (179 total - 98 written)
- Check overlap percentage

### Step 2: Fix Silent Failure Logging (IMMEDIATE)
Add real exception logging:
```python
except Exception as e:
    import traceback
    print(f"⚠️ {company}: Supabase analysis write failed")
    print(f"   Exception type: {type(e).__name__}")
    print(f"   Message: {str(e)}")
    print(f"   Traceback: {traceback.format_exc()}")
```

### Step 3: Live Dispatch (AFTER LOGGING FIX)
Manually trigger nightly workflow to capture real error messages for the 81 failures

### Step 4: Root Cause Confirmation
Once actual error known, determine:
- Same root cause as Bug #1 (incomplete fix)?
- Separate bug (unrelated to property naming)?
- Schema mismatch? Auth issue? Connection issue?

### Step 5: Success Rate Tracking (AFTER FIX VERIFIED)
Add monitoring:
- Count successes vs attempts
- Fail workflow if success rate < 90%
- Log summary: "Supabase: 179/179 succeeded" or "98/179 succeeded (54.7%)"

### Step 6: Backfill (ONLY AFTER 100% SUCCESS VERIFIED)
Do NOT backfill until success rate = 100% for at least 2 consecutive nights

---

## Status: INVESTIGATION IN PROGRESS

- ✅ Nightly agent DOES write to Supabase (architecture confirmed)
- ✅ Bug #1 fix improved rate from 18.4% → 54.7%
- ❌ Root cause of remaining 45.3% failures UNKNOWN (no error messages)
- ❌ ID overlap between HubSpot 400s and Supabase failures UNVERIFIED
- ❌ Success rate tracking NOT IMPLEMENTED
