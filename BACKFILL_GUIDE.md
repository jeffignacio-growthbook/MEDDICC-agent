# ETL Backfill Guide

**Context:** Calls ETL has been failing since August 7 (4 weeks). Schema mismatch caused PGRST204 errors on every write, silently discarding all calls since then. MEDDICC scores and deal health answers have been reasoning from stale transcripts.

**Schema fixed:** Applied migrations 050 and 051 directly to production (duration_minutes, formatted_summary, has_feature_gap, has_objection columns added).

---

## Manual Steps Required

### 1. Add Slack Webhook (for failure alerts)

GitHub repo → Settings → Secrets and variables → Actions → New repository secret:
- Name: `SLACK_WEBHOOK_URL`
- Value: Your Slack incoming webhook URL

Future ETL failures will alert after 2 consecutive failures.

### 2. Add HubSpot Owners Scope

HubSpot → Settings → Integrations → Private Apps → Your app → Scopes:
- Add: `crm.objects.owners.read`
- Save

This fixes the 403 error that leaves `deals.owner_email` null.

### 3. Backfill Calls (4-week gap)

**Check what args the ETL script accepts:**
```bash
python scripts/etl_calls.py --help
```

**Run backfill covering Aug 7 - present:**
```bash
python scripts/etl_calls.py --mode incremental --start-date 2026-08-07
```

Or trigger manually via GitHub Actions:
- Go to Actions → Daily Calls ETL → Run workflow
- If workflow doesn't support date override, run locally with above command

**Verify backfill:**
```sql
SELECT DATE(call_date) as date, COUNT(*) as calls
FROM calls
WHERE call_date >= '2026-08-07'
GROUP BY DATE(call_date)
ORDER BY 1;
```

Should show calls distributed across August and September, not empty.

### 4. Backfill Deals (missing Airalo + stale amounts)

**Run deals ETL in history mode:**
```bash
python scripts/etl_deals.py --mode history
```

This fetches ALL deals including closed, catching:
- Missing: Airalo - $95,000 (closed 2026-09-01)
- Amount mismatches on Apify and Philo

**Verify Q3 won deals after backfill:**
```sql
SELECT deal_id, company_name, deal_value, close_date, owner_email
FROM deals
WHERE deal_status = 'won'
  AND close_date >= '2026-08-01'
  AND close_date <= '2026-10-31'
ORDER BY close_date;
```

Should show **5 deals totaling $185,840** (not 4 deals at $102,400).

### 5. Re-test Christian's Attainment

Ask in Slack: **"How is Christian tracking?"**

Should now return:
- Target: $250,000
- Won: $X (whatever Christian closed in Q3)
- Attainment: X%
- No longer "partial" or empty

If still shows $0 won but owner_email is now populated, that's real - Christian may not have closed deals yet this quarter.

---

## Verification Checklist

After backfill, verify:

- [ ] Calls table has entries for every day Aug 7 - present
- [ ] Deals table shows 5 Q3 won deals ($185,840 total)
- [ ] All won deals have owner_email populated (not null/empty)
- [ ] Christian's attainment query returns data
- [ ] MEDDICC scores exist for recent calls (check analyses table)
- [ ] Next daily ETL runs complete successfully
- [ ] Slack alert fires if ETL fails twice in a row

---

## Why This Happened

**Silent failure cascade:**

1. **Schema divergence** - Table modified outside migration system, dropped 4 columns
2. **ETL tried to write to missing columns** - PGRST204 error on every call write
3. **Error didn't propagate** - Exit code 0 despite failure, GitHub Actions showed green
4. **No alerts** - Failure went unnoticed for 4 weeks
5. **Stale data served** - All deal health answers used pre-Aug-7 transcripts

**Fixes applied:**

- ✓ Schema restored (4 columns added)
- ✓ Failure tracking table created
- ✓ Alert system added (Slack on 2+ consecutive failures)
- ✓ Both ETL workflows now alert on failure

**Guard rails added:**

- Email consistency test (`tests/test_email_consistency.py`)
- ETL failure alerting (after 2 consecutive failures)
- Migration 050 documents the divergence for future reference

---

## Long-term Fixes

**Schema drift prevention:**
- Never modify tables outside migrations
- Add pre-deployment schema validation test
- Consider `setup_supabase.py --verify-all` in CI

**ETL reliability:**
- Monitor failure_count in etl_failures table
- Weekly review of fallback_log for missing handlers
- Add health check endpoint that queries recent data freshness

**Data quality:**
- Add last_etl_run timestamp to relevant tables
- Query should warn if data is >48 hours stale
- Dashboard showing ETL run times and row counts
