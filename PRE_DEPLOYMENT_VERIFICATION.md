### Pre-Deployment Verification Checklist

Two verification items identified before deploying follow-up fixes. Both require live Supabase connection.

---

## Verification 1: Segment Impact of Cross-Quarter Fix

### Question
Does the 7.2% → 7.9% overall rate change mean segment rates also need recomputation?

### Context
- Original segment rates computed without cross-quarter lookup:
  - **Enterprise**: 8/54 = 14.8%
  - **Mid-Market**: 3/60 = 5.0%
  - **SMB**: 1/41 = 2.4%

- Small denominators (n=41-60) mean adding even 1-2 wins can shift rate materially
- Already flagged as "statistically fragile" with volatility warnings

### The 3 Carry-Over Deals
- **Fellow**: Created Aug 9 (Q2), closed Nov 7 (Q3)
- **Yeet!**: Created Jan 27 (Q3), closed Mar 2 (Q4)
- **Wellhub**: Created Apr 30 (boundary), closed May 23 (Q1)

### Risk Scenario
If all 3 carry-over deals belong to **Enterprise**:
- Enterprise wins: 8 → 11
- Enterprise rate: 14.8% → 20.4% (+5.6pp)
- This is a **material change** given n=54

If distributed across segments:
- Likely <3pp change per segment
- Within statistical noise, no recomputation needed

### Verification Script
```bash
python verify_carry_over_segment_impact.py
```

**Checks:**
1. Looks up Fellow, Yeet!, Wellhub in deals table
2. Gets their segment values
3. Recalculates segment rates with +wins
4. Reports if any segment changes by ≥3pp

### Decision Tree
- **If any segment changes ≥3pp**: Recompute segment rates with cross-quarter enabled
  - Run `conversion_by_qualification_week_CROSS_QUARTER.py` with segment breakdown
  - Update `config/metrics.yaml` with new segment rates
  - Keep volatility warnings in place

- **If all segments change <3pp**: No action needed
  - Changes within noise floor
  - Volatility warning already accounts for thin evidence

---

## Verification 2: Bluesky/Quizlet Duplicate Pattern

### Question
Is "scattered manual entry" the correct explanation, or is there a systematic source?

### Context
- **Bluesky** appears **2x** in data quality errors (both zero-day cycles)
- **Quizlet** appears **2x** (1 negative, 1 zero-day)
- 4 of 8 data quality errors (50%) from just 2 companies

### Pattern History Lesson
Multiple times in this analysis, "no pattern" turned out to need one more dig:
- **Pagination bug**: Initially thought "Q2 has fewer rows because smaller pipeline"
- **Q3 -1 deals**: Initially thought "edge case," turned out to be methodology error
- **Week-3=0**: Initially thought "no deals qualified week 3," turned out to be incremental vs cumulative conflation

Don't accept "scattered" at face value when concentration exists.

### Possible Systematic Sources
1. **Same rep** created/owns all 4 deals (process issue)
2. **Same import batch** touched both companies (import artifact)
3. **Same integration** (e.g., Zapier, API client) created duplicates
4. **Same time window** (e.g., all created same day/hour)

### Verification Script
```bash
python verify_duplicate_pattern_bluesky_quizlet.py
```

**Checks:**
1. Who created the 4 deals (`hs_created_by_user_id`)
2. When were they created (timestamps, clustering)
3. Who owns the deals (`owner_email`)
4. What source created them (`hs_object_source`)
5. Extends analysis to all 8 data quality errors (not just Bluesky/Quizlet)

### Decision Tree

#### If systematic pattern found (≥3/4 deals share creator/owner/source/timing):
- **Update conclusion** from "scattered manual entry" to systematic source
- **Investigate root cause**: What process created these?
- **Fix upstream**: Prevent future occurrences
- **Update documentation**: `DATA_QUALITY_EXCLUSIONS_README.md` to reflect pattern
- **Consider**: Can these deals be corrected at source instead of flagged?

#### If no pattern found (scattered across users/times/sources):
- **Confirm conclusion**: "Scattered manual entry" is correct
- **Accept as limitation**: Individual entry errors, no systematic fix
- **Keep infrastructure**: `data_quality_exclusions` table for ongoing tracking

---

## Why These Matter

### Verification 1 (Segment Impact)
**Without checking:**
- Risk publishing segment rates that materially changed but weren't updated
- Inconsistency: overall rate updated (7.2%→7.9%) but segments stale
- Misleading forecasts for segment-specific planning

**With checking:**
- Confidence that segment rates are accurate given cross-quarter fix
- Clear documentation: "rates recomputed" or "changes <3pp, no update needed"

### Verification 2 (Pattern Analysis)
**Without checking:**
- Risk missing a fixable process issue (e.g., bad integration, specific rep training need)
- Accept data corruption as permanent when it might be preventable
- Miss opportunity to improve data quality upstream

**With checking:**
- Either confirm "scattered" OR identify systematic source
- If systematic: fix root cause, not just symptoms
- Follows analysis pattern: dig one layer deeper when concentration exists

---

## Execution Order

**Run both before deployment:**

1. **Verification 1 first** (quickest, deterministic outcome):
   ```bash
   python verify_carry_over_segment_impact.py
   ```
   - Takes ~30 seconds
   - Clear yes/no decision on segment recomputation

2. **Verification 2 second** (more investigative):
   ```bash
   python verify_duplicate_pattern_bluesky_quizlet.py
   ```
   - Takes ~1 minute
   - May require follow-up investigation if pattern found

3. **Document findings**:
   - Update `FOLLOW_UP_ITEMS_COMPLETE.md` with verification results
   - Update `DATA_QUALITY_EXCLUSIONS_README.md` if pattern found
   - Update `config/metrics.yaml` if segment recomputation needed

4. **Proceed with deployment** only after both verifications complete

---

## Dependencies

Both scripts require:
- Live Supabase connection (`SUPABASE_URL` set)
- Access to `deals` table
- Permissions to query metadata fields

If running without Supabase access:
- Note verification as **pending** in deployment docs
- **Do not deploy** until verified with live data
- Risk: deploying unverified fixes could introduce new inaccuracies

---

## Success Criteria

### Verification 1 Complete When:
- [ ] All 3 carry-over deals (Fellow, Yeet!, Wellhub) located in deals table
- [ ] Segment values retrieved
- [ ] Segment rate changes calculated
- [ ] Decision made: recompute segments (if ≥3pp) or no action (if <3pp)

### Verification 2 Complete When:
- [ ] All 4 Bluesky/Quizlet deals metadata retrieved
- [ ] Creator, owner, source, timing patterns analyzed
- [ ] Cross-reference with all 8 data quality errors completed
- [ ] Conclusion documented: systematic pattern OR scattered (with evidence)

### Both Verifications Complete When:
- [ ] Scripts executed successfully
- [ ] Findings documented in `FOLLOW_UP_ITEMS_COMPLETE.md`
- [ ] Any necessary updates made to `config/metrics.yaml`
- [ ] Ready to proceed with deployment

---

## Notes

- **Don't skip these checks** - both are fast, low-effort, high-value
- **Pattern history teaches us**: Always dig one layer deeper when concentration exists
- **Segment fragility is real**: n=41-60 means small changes matter
- **Data quality matters upstream**: Better to fix source than flag forever

Run both scripts, document findings, then proceed with deployment.
