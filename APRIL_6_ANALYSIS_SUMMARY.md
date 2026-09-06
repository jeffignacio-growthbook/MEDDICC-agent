# April 6, 2026 Bulk Close Analysis — Ready for Sales Leadership

**Date:** 2026-09-05
**Deals analyzed:** 328 closed on April 6, 2026
**Pattern:** RAPID BULK ACTION (likely workflow/admin cleanup)

---

## Key Findings

### 1. Timestamp Clustering: HIGHLY CONCENTRATED

**89% closed within 5 minutes, 100% within 1 hour**

```
First close: 2026-04-06 22:04:06 UTC (3:04 PM PT / 6:04 PM ET)
Last close:  2026-04-06 23:03:17 UTC (4:03 PM PT / 7:03 PM ET)
Time span:   59 minutes
```

**Distribution:**
- 22:00-22:59 UTC: **321 deals** (97.9%)
- 23:00-23:59 UTC: **7 deals** (2.1%)

**Within first 5 minutes: 292/328 (89.0%)**

**Interpretation:** This is NOT 328 individual decisions spread across a day. This is a bulk action — either:
- Automated workflow execution
- Manual bulk selection + close
- API script run

### 2. Owner Distribution: MOSTLY UNASSIGNED + ONE OWNER

| Owner                | Deals | % of Total |
|----------------------|-------|------------|
| **Unassigned**       | **145** | **44.2%**    |
| **Owner 371635471**  | **136** | **41.5%**    |
| Owner 53912388       | 23    | 7.0%       |
| Owner 87079750       | 14    | 4.3%       |
| 4 other owners       | 10    | 3.0%       |

**Combined: Unassigned + One Owner = 281/328 (85.7%)**

**Interpretation:**
- Either one person bulk-closed their deals + unassigned deals
- OR a workflow targeted unassigned deals + deals owned by one person
- Need to identify owner 371635471 (API permissions insufficient to fetch email)

### 3. Activity History: MANY HAD RECENT ACTIVITY

**Sample of 20 deals:**
- Active (notes present): **11/20 (55%)**
- Dormant (no notes): **9/20 (45%)**

**Examples of "active" deals closed:**
- ThriftBooks: 4 notes
- Prezzee: 14 notes
- pens.com: 13 notes
- Sonae MC: 7 notes
- GuzmanyGomez: 6 notes

**Interpretation:** This was NOT just a "clean up stale deals" action. Over half the deals had documented activity/notes, suggesting some were potentially active or in-progress.

---

## Pattern Classification

**RAPID COORDINATED ACTION**

This exhibits characteristics of:
1. **Bulk workflow run** (89% within 5 minutes)
2. **Concentrated ownership** (86% unassigned or one owner)
3. **Mixed activity** (some dormant, some active)

**Most likely scenario:** Workflow or manual bulk action targeting specific criteria (unassigned + specific owner's deals), executed around 3-4 PM Pacific Time on April 6.

---

## Recommended Question for Sales Leadership

**Primary question:**
> "Was there a bulk close-lost workflow or cleanup action run on April 6, 2026, around 3 PM Pacific Time?"

**Follow-up specifics:**
1. Who is HubSpot owner ID 371635471? (136 of the 328 deals)
2. Why were 145 unassigned deals bulk-closed on that date?
3. Was this part of Q1 end-of-quarter pipeline hygiene?
4. Were criteria used (e.g., "stale for X days" or "no activity since Y")?

---

## Investigation Approach

### Step 1: Identify Owner 371635471
- Check HubSpot → Settings → Users & Teams
- Or query: Which owner has ID 371635471?
- Contact them directly about April 6 actions

### Step 2: Check Workflow Logs
- HubSpot → Automation → Workflows
- Filter by "April 6, 2026" + "Deal updates"
- Look for workflow execution around 22:00-23:00 UTC (3-4 PM PT)
- Check workflow criteria: Was it "close unassigned + stale deals"?

### Step 3: Review Audit Logs
- HubSpot → Settings → Activity Log
- Filter: April 6, 2026, bulk deal updates
- Look for admin or API actions affecting 300+ deals

### Step 4: Business Context
- Was there an end-of-Q1 cleanup directive?
- Pipeline hygiene initiative?
- CRM data quality project?

---

## Decision Tree

### If workflow/automation found:
1. **Review workflow criteria** — were they appropriate?
2. **Check if active deals were incorrectly caught** — the 55% with notes
3. **Decide:**
   - If criteria correct → Document as intentional cleanup, metrics valid
   - If criteria incorrect → May need to re-open incorrectly closed deals

### If manual bulk action by owner 371635471:
1. **Interview owner** — Why bulk close 136 deals on April 6?
2. **Check selection criteria** — How were these 136 identified?
3. **Review active deals in the set** — Should they have been closed?
4. **Decide:**
   - If justified → Document rationale
   - If error → Identify and re-open incorrectly closed deals

### If neither workflow nor intentional action:
1. **Data integrity issue** — Investigate HubSpot API/integration logs
2. **Check for accidental bulk edits**
3. **May need to restore from backup or re-open deals**

---

## Next Steps

1. **Immediate:** Identify owner 371635471 (check HubSpot users list)
2. **Today:** Check workflow execution logs for April 6
3. **This week:** Interview owner + review audit logs
4. **Once determined:** Update TICKET_1_APRIL_ANOMALY.md with findings

---

## Artifacts

- **Full analysis:** `april_6_analysis.json`
- **Script:** `analyze_april_6_bulk_close_v2.py`
- **Raw output:** `april_6_analysis_output.txt`

---

**Status:** Ready for sales leadership conversation with specific, answerable questions.
