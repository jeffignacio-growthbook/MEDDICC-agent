# Data Quality - Manual Review Required

**Date:** 2026-09-04

## 4 Zero-Day Won Deals Requiring Review

These deals were created and won on the same day with ARR < $5,000. They may be legitimate same-day closes (self-serve, fast renewals, inbound conversions) rather than data quality errors.

**Action:** Review each deal manually to determine if it should be excluded or kept in conversion analysis.

---

### Deal 1: PepsiCo
- **Deal ID:** 15596726917
- **Date:** 2023-10-12
- **ARR:** $1,000
- **Owner:** None
- **Assessment:** Small deal, no owner - possibly self-serve trial upgrade

**Decision:** [ ] EXCLUDE  [ ] KEEP

**Notes:**
_Add context from HubSpot (deal notes, activity history, etc.)_

---

### Deal 2: Paceline
- **Deal ID:** 9086864786
- **Date:** 2022-06-03
- **ARR:** $1,000
- **Owner:** graham@growthbook.io
- **Assessment:** Old small deal - check if this was a pilot/trial

**Decision:** [ ] EXCLUDE  [ ] KEEP

**Notes:**
_Add context from HubSpot (deal notes, activity history, etc.)_

---

### Deal 3: 7shifts
- **Deal ID:** 43422063231
- **Date:** 2025-09-05
- **ARR:** $1,531
- **Owner:** jennifer@growthbook.io
- **Assessment:** Small deal with owner - check if this was inbound conversion

**Decision:** [ ] EXCLUDE  [ ] KEEP

**Notes:**
_Add context from HubSpot (deal notes, activity history, etc.)_

---

### Deal 4: knowunity.ai
- **Deal ID:** 60234076206
- **Date:** 2026-05-13
- **ARR:** $4,000
- **Owner:** cary@growthbook.io
- **Assessment:** Just under $5k threshold - check deal history

**Decision:** [ ] EXCLUDE  [ ] KEEP

**Notes:**
_Add context from HubSpot (deal notes, activity history, etc.)_

---

## Review Process

1. For each deal, check HubSpot:
   - Deal notes/description
   - Activity timeline (emails, calls, meetings)
   - Time between first touch and close
   - Deal source/origin

2. Determine if same-day close was legitimate:
   - **Self-serve signup → paid conversion same day:** KEEP
   - **Inbound demo request → quick close:** KEEP if documented activity
   - **Renewal/upsell of existing customer:** KEEP
   - **No activity/context, suspicious timing:** EXCLUDE

3. If EXCLUDE, add to data_quality_exclusions:
   ```sql
   INSERT INTO data_quality_exclusions (deal_id, reason, cycle_days, create_date, close_date, company_name, notes)
   VALUES ('[deal_id]', 'ZERO_DAY_WON', 0, '[date]', '[date]', '[company]', '[reason for exclusion]');
   ```

4. Update this file with decisions and reasoning.

---

## General Guidance

**Same-day closes CAN be legitimate when:**
- Small ARR (< $5k) suggests self-serve or low-touch
- Deal has documented activity (emails, calls) showing relationship
- Company is existing customer (renewal/upsell)
- Deal source indicates inbound/PLG motion

**Same-day closes are SUSPICIOUS when:**
- Zero ARR (should not be marked won)
- Large ARR (> $20k) with no documented activity
- No owner assigned
- Create and close dates exactly match with no explanation
