# Wave 6: Monitoring & Alerting — Status Report

**Date:** 2026-09-05
**Status:** Infrastructure Complete, Trigger 7 Added
**Blockers Cleared:** Both investigation tickets resolved

---

## Summary

Wave 6 monitoring infrastructure built with 7 triggers. Investigation of April 6 anomaly led to discovery of departed-rep cleanup pattern, which became the basis for new Trigger 7 (bulk_closed_lost detection).

---

## Completed Work

### 1. Investigation Phase ✅

**Ticket 1: April 13 Anomaly** — CLOSED
- Root cause: Ivan Gomez (departed rep) pipeline cleanup
- 281 deals bulk-closed April 6, 2026 in 59 minutes
- Confirmed intentional by Jeff, no remediation needed
- **Key learning:** High-magnitude events can go undetected for months without real-time monitoring

**Ticket 2: Pagination Bug** — FIXED
- Already resolved in commit `7addf1a`
- `snapshot_deals.py` now uses `select_all()` pagination
- No backfill needed

### 2. Configuration ✅

**File:** `config/monitoring.yaml`

**Updates:**
- Enabled `snapshot_coverage` trigger (baseline established)
- Added Trigger 7: `bulk_closed_lost` event detection
- Configured thresholds based on Ivan Gomez investigation:
  - min_deal_count: 50 (would catch 281-deal event)
  - time_window: 60 minutes
  - min_owner_concentration: 0.5 (catches single-actor cleanups)

### 3. Trigger 7 Implementation ✅

**File:** `scripts/monitor_bulk_closed_lost.py`

**Features:**
- Detects high-volume closed-lost transitions within rolling time window
- Analyzes owner concentration (catches departed-rep cleanups)
- Provides evidence: deal_count, timestamp span, owner distribution, sample deals
- Uses generic monitoring alert payload structure
- Configurable thresholds via monitoring.yaml

**Evidence Payload:**
```python
{
  'deal_count': 281,
  'time_window': {'start': '2026-04-06T22:04:06', 'end': '2026-04-06T23:03:17', 'span_minutes': 59},
  'owner_distribution': {'unassigned': 145, '371635471': 136, ...},
  'sample_deals': [...],
  'activity_summary': {'with_notes': 11, 'sample_size': 20}
}
```

### 4. Alert Payload Generalization ✅

**Demo:** `demo_monitoring_alert_payloads.py`

**Pattern:**
```python
def send_monitoring_alert(monitor_name, threshold_config, evidence, message):
    payload = {
        "type": "monitoring_alert",  # vs "etl_failure"
        "monitor": monitor_name,
        "fired_at": datetime.utcnow().isoformat(),
        "threshold_config": threshold_config,  # What triggered alert
        "evidence": evidence,                   # Trigger-specific data
        "message": message                      # Human-readable Slack text
    }
```

**Benefits:**
- No forced `failure_count` field
- Each trigger provides its own evidence structure
- Type discriminator separates from ETL failures
- Threshold snapshot enables audit trail

---

## All 7 Triggers

| # | Trigger | Status | Config Key | Purpose |
|---|---------|--------|------------|---------|
| 1 | Metric Divergence | Config | `metric_divergence` | Verified metric vs live computation |
| 2 | Snapshot Coverage | **Enabled** | `snapshot_coverage` | Weekly row count vs trailing median |
| 3 | ETL Failure | Existing | (separate file) | Consecutive job failures |
| 4 | Data Quality Anomaly | Config | `data_quality_anomaly` | Spike in exclusions |
| 5 | Stage Classification | Config | `stage_classification` | Unclassifiable stages |
| 6 | Conversion Shift | Config | `conversion_shift` | Week-over-week rate changes |
| **7** | **Bulk Closed-Lost** | **Enabled** | `bulk_closed_lost` | High-volume close-lost events |

---

## Known Limitations

### Trigger 7: Real-Time Detection Challenge

**Issue:** Current implementation uses `deals_snapshot` table, which is populated weekly. This means bulk events would only be detected on next snapshot run (up to 7 days later).

**For true real-time detection, need:**
1. **Option A:** HubSpot webhook subscription
   - Subscribe to deal.propertyChange events
   - Filter for dealstage → closed-lost
   - Accumulate in rolling window cache
   - Check threshold hourly

2. **Option B:** Frequent HubSpot polling
   - Query deals with `hs_lastmodifieddate` in last hour
   - Filter for recently closed-lost
   - Higher API cost, but works without webhooks

3. **Option C:** Property history backfill approach
   - Daily batch job fetches property history for all deals
   - Analyzes transitions in last 24 hours
   - Less real-time (daily), but captures everything

**Recommendation:** Start with Option C (daily batch), move to Option A (webhooks) if high-frequency detection needed.

**Current state:** Monitor works for historical analysis (can detect past events), but not real-time alerting.

---

## Testing Checklist

### Unit Tests Needed
- [ ] `test_monitor_bulk_closed_lost.py`
  - Mock transitions data
  - Test threshold logic
  - Test owner concentration filtering
  - Test evidence payload structure

### Integration Tests Needed
- [ ] Run against Ivan Gomez event (April 6 data)
  - Should detect 281 deals in 59 minutes
  - Should identify owner concentration (85.7%)
  - Should include correct evidence

- [ ] Run against normal days (no bulk events)
  - Should not false-alarm on distributed closes

### Alert Delivery Test
- [ ] Send test alert to Zapier webhook
  - Verify Slack formatting
  - Verify evidence appears correctly
  - Verify links work

---

## Deployment Steps

### 1. Environment Variables
```bash
# Add to .env
ZAPIER_MONITORING_WEBHOOK_URL=https://hooks.zapier.com/hooks/catch/...

# Add to GitHub Secrets (if running in Actions)
gh secret set ZAPIER_MONITORING_WEBHOOK_URL --env Agent
```

### 2. Schedule Monitor (Option C approach)
```yaml
# .github/workflows/daily-monitoring.yml
name: Daily Monitoring Checks

on:
  schedule:
    - cron: '0 10 * * *'  # 10 AM UTC daily
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    environment: Agent
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - name: Check bulk closed-lost events
        run: python scripts/monitor_bulk_closed_lost.py --lookback-hours 24
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          ZAPIER_MONITORING_WEBHOOK_URL: ${{ secrets.ZAPIER_MONITORING_WEBHOOK_URL }}
```

### 3. Test Run
```bash
# Dry run (no alert sent)
python scripts/monitor_bulk_closed_lost.py --lookback-hours 168 --dry-run

# Live test (sends alert)
python scripts/monitor_bulk_closed_lost.py --lookback-hours 168
```

### 4. Enable Additional Triggers
After 2 weeks of burn-in:
- Enable Trigger 1 (metric_divergence) if verified values set
- Enable Trigger 4 (data_quality_anomaly) if exclusions table active
- Tune thresholds based on false-positive rate

---

## Success Criteria

✅ **Ticket 1 resolved** - Ivan Gomez cleanup confirmed intentional
✅ **Ticket 2 resolved** - Pagination already fixed
✅ **Trigger 7 built** - Bulk closed-lost detection implemented
✅ **Config updated** - monitoring.yaml includes new trigger
✅ **Payload generalized** - Type discriminator pattern demonstrated
⏳ **Real-time detection** - Needs webhook/polling implementation (future)
⏳ **Testing** - Unit/integration tests pending
⏳ **Deployment** - Scheduled workflow pending

---

## Next Steps

1. **Immediate:**
   - Create unit tests for monitor_bulk_closed_lost.py
   - Test against April 6 data (should detect Ivan event)
   - Set up Zapier webhook and test alert delivery

2. **This week:**
   - Deploy daily monitoring workflow
   - Monitor for false positives
   - Document first real detection

3. **Future enhancements:**
   - Implement real-time detection (webhook or polling)
   - Add remaining triggers (1, 4, 5, 6)
   - Build monitoring dashboard

---

**Status:** Wave 6 core infrastructure complete. Trigger 7 (bulk_closed_lost) ready for testing and deployment.
