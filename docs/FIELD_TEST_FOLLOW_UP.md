# Field Test Follow-Up — Notes and Fixes

**Date:** 2026-08-31
**Test:** Named sets follow-up in Slack

---

## What Worked

**Named sets chain:** Assessor went 0.25 → 0.95 on the follow-up.

- "Where did the 6 that left Negotiating go?" correctly resolved to `exited_Negotiating`
- Handler received 6 IDs, not 20
- Answer confirmed: "Of the 6 that left Negotiating: ..."
- Second follow-up "which of those are enterprise?" kept 6-deal scope (didn't revert to 20)

**Named set resolution working.** The classifier matched the question to the set, narrowed correctly, and subsequent follow-ups maintained scope.

---

## Issues Found

### 1. Stage ID 43449439 Unresolved

**Symptom:**
```
Airalo → Stage ID 43449439 (stage name unresolved, close date Sep 16)
```

**Cause:** A stage in the CRM that `field_semantics.yaml` doesn't know about. Either:
- Retired stage (existed during discovery, removed later)
- New stage (added to CRM after discovery ran)

**Impact:** Answer handled it honestly ("stage name unresolved") but it'll recur on other deals in that stage.

**Fix:** Re-run `scripts/discover_stages.py` to refresh stage mappings.

```bash
cd scripts
python discover_stages.py
```

This will output updated stage IDs and names. Compare against `field_semantics.yaml` to see if 43449439 is missing or renamed.

**Note:** The handler degraded honestly rather than guessing, which is correct behavior. But the stage mapping should be updated to resolve the name.

---

### 2. Persona Lookup Failed

**Log:**
```
Unknown user U07B3Q0TRGR (email=not provided by payload)
```

**Cause:** Different Slack ID than yours, and no email in the Zapier payload. Lazy binding can't fire without email.

**Impact:** Every answer in this thread was un-personalized (no voice adaptation).

**Possible causes:**
1. Someone else asked the question (different user)
2. Zapier payload changed (email field no longer included)
3. Test webhook missing email field

**Diagnosis:**
- Check Zapier run history for this question
- Verify `slack_email` is in the payload sent to `/slack/question`
- If testing via webhook, ensure email is included:
  ```json
  {
    "user_id": "U07B3Q0TRGR",
    "slack_email": "user@example.com",
    "question": "..."
  }
  ```

**Note:** Persona system failed gracefully (answered without personalization). But persona binding should work for production use.

---

### 3. [SYNTH] Log Clarity vs Oversized Warning

**Current log:**
```
[SYNTH] tool_results (uncapped) ~36,695 chars (handler=query_pipeline_movement)
```

Synthesis received 8,923 chars (capped). Log now says "uncapped" clearly.

**Issue:** The oversized warning (threshold 50KB) is gone entirely. Need to confirm it still fires when the **capped** payload exceeds 50KB.

**Test case:**
- Handler returns 300 deals (before cap)
- After capping at 20 rows: still ~45KB due to nested objects
- Should trigger warning if capped payload > 50KB

**Current threshold:**
```python
if synth_size > 50_000:  # 50KB
    logger.warning(f"[SYNTH] Large synthesis payload: {synth_size:,} chars")
```

**Verification needed:** Does `synth_size` measure the capped payload or uncapped? If uncapped, warning may never fire.

**Fix if needed:** Log both sizes, warn on capped size:
```python
uncapped_size = len(json.dumps(tool_results, default=str))
capped_size = len(json.dumps(synthesis_results, default=str))
logger.info(f"[SYNTH] uncapped: {uncapped_size:,} chars, capped: {capped_size:,} chars")
if capped_size > 50_000:
    logger.warning(f"[SYNTH] Large synthesis payload: {capped_size:,} chars (after capping)")
```

---

### 4. Segment Field Missing (FIXED)

**Symptom:** "Which of those are enterprise?" offered ARR as proxy instead of answering directly.

**Cause:** Bulk handlers didn't include `segment` in their selects:
- `query_deal_stages_bulk`
- `query_deal_owners_bulk`
- `query_deal_values_bulk`

Renewals handler has it and groups by Enterprise / Mid-Market / SMB, but bulk handlers didn't.

**Fix:** Added `segment` to all three bulk handler selects.

**Commit:** `567656d`

**Now works:** "Which of those are enterprise?" will see segment data and answer directly.

---

## Action Items

### For User (CRM/Config)

- [ ] Re-run `scripts/discover_stages.py` to refresh stage mappings
- [ ] Check `field_semantics.yaml` for stage ID 43449439
- [ ] Verify Zapier payload includes `slack_email` field
- [ ] Check Zapier run history for U07B3Q0TRGR message

### For Code (If Needed)

- [ ] Verify [SYNTH] oversized warning fires on capped payload > 50KB
- [ ] If not, update log to measure capped size

---

## Testing Next

1. **Deploy to Railway** (restart to pick up segment fix)
2. **Re-run "which of those are enterprise?"** — should answer directly now
3. **Check stage 43449439** after running discover_stages.py
4. **Test persona binding** with correct email in payload

---

## Summary

| Issue | Status | Action |
|-------|--------|--------|
| Named sets resolution | ✅ Working | None — assessor 0.25 → 0.95 |
| Segment missing | ✅ Fixed | Added to bulk handlers (567656d) |
| Stage ID unresolved | ⚠️ Config gap | Re-run discover_stages.py |
| Persona lookup failed | ⚠️ Data gap | Check Zapier payload for email |
| [SYNTH] oversized warning | ⚠️ Verify | Confirm warning fires on capped size |

Named sets working well. Segment fixed. Config gaps to address.
