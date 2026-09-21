# Apollo.io API Usage - Executive Summary
**Date:** September 21, 2026  
**Analysis Period:** Last 30 days (Aug 22 - Sept 21, 2026)

---

## TL;DR

Your Apollo.io API usage is **excellent and cost-effective**. No action needed.

- **31 credits used** in 15 days (projected 50-62/month)
- **100% from Daily Calls ETL** workflow
- **No errors, no rate limiting**
- **83% cache hit rate** = highly efficient
- **Well under quota** (typical plans: 1,000+ credits/month)

---

## Key Metrics

| Metric | Value | Status |
|--------|-------|--------|
| Total Credits (15 days) | 31 | ✅ Low |
| Daily Average | 2.07 | ✅ Consistent |
| Monthly Projection | 50-62 | ✅ Well under limits |
| GET Calls (billable) | 31 | ✅ Minimal |
| POST Calls (free) | 180 | Efficient searching |
| Error Rate | 0% | ✅ Perfect |
| Rate Limit Issues | 0 | ✅ None |

---

## What's Using Apollo API?

### Daily Calls ETL (100% of usage)
- Runs daily at 1:30 AM UTC
- Fetches new sales call transcripts
- Only calls API for net-new conversations
- Cache-first strategy = minimal API usage

### Other Workflows
- **Nightly Run:** 0 credits (uses cached data)
- **Apollo Audit:** 0 credits (reads from DB)
- **SDR Backfill:** Not run in last 30 days

---

## Usage Pattern

```
Daily: 0-5 credits per day
Peak: Sept 19 (5 credits)
Low: Sept 11 (1 credit)
Typical: 2-3 credits/day
```

Pattern is stable and predictable, driven by sales call volume.

---

## Cost Impact

**Current Spend:** ~$0-5/month depending on your Apollo plan

Most Apollo plans include 1,000+ credits/month:
- You're using ~5% of typical allowance
- No risk of overage charges
- No need for plan upgrade

---

## Recommendations

### Keep Doing ✅
- Current caching strategy is excellent
- Workflow scheduling is optimal
- No changes needed

### Monitor 🔍
- Watch for weekly spikes above 20 credits
- Ensure cache stays healthy
- Review monthly (next: Oct 21, 2026)

### Don't Do ❌
- Don't reduce caching (already optimal)
- Don't add Apollo calls to Nightly workflow
- Don't change API patterns without measuring

---

## Bottom Line

**Your Apollo integration is working perfectly.** The cache-first architecture you've built is highly efficient and cost-effective. Continue as-is and review monthly.

**Risk Level:** 🟢 LOW  
**Action Required:** None - monitoring only

---

## Full Reports

- [Detailed Analysis](/Users/jeffignacio/MEDDICC-agent/docs/reports/apollo_usage_analysis_2026-09-21.md)
- [Visual Chart](/Users/jeffignacio/MEDDICC-agent/docs/reports/apollo_usage_chart_2026-09-21.txt)
- [Raw Data (JSON)](/Users/jeffignacio/MEDDICC-agent/docs/reports/apollo_usage_data_2026-09-21.json)

---

**Next Review Date:** October 21, 2026
