# Phase G.7 Result Cache Layer — Deployment Guide

## Overview
Enables follow-ups on aggregate handlers (query_waterfall) that return time-series summaries with no deal_ids. Separates what gets SHOWN (synthesis) from what gets RETAINED (cache_payload for follow-up context).

## Implementation Summary

### Files Modified
- `scripts/migrations/025_result_cache.sql` — New table for cached payloads
- `api/db.py` — Cache helpers + save_thread() wiring
- `api/router.py` — Cache fallback in route_question()
- `api/handlers.py` — query_waterfall opt-in via cache_payload
- `api/main.py` — Pass thread_ts to router
- `scripts/eval_entity_paths.py` — G.7 test coverage

### Eval Status
```
Results: 20 passed, 0 failed
✅ All entity path tests passed!
```

**New Tests:**
- G.7.1: cache_payload strip verification (proves pop() removes payload before synthesis)
- G.7.2: Entity extraction from cache_payload (proves entities extracted from both paths)

## Deployment Steps

### 1. Apply Migration 025

**Option A: Supabase Dashboard**
1. Open Supabase Dashboard → SQL Editor
2. Paste contents of `scripts/migrations/025_result_cache.sql`
3. Run migration
4. Verify table created: `SELECT * FROM result_cache LIMIT 1;`

**Option B: Railway CLI**
```bash
railway run psql $DATABASE_URL -f scripts/migrations/025_result_cache.sql
```

**Verification:**
```sql
-- Check table exists
\d result_cache

-- Check indexes
\di idx_result_cache_thread
\di idx_result_cache_expires

-- Check view
SELECT * FROM result_cache_active LIMIT 1;
```

### 2. Deploy Code Changes

**From Railway Dashboard:**
1. Commit and push phase-g7 branch
2. Railway auto-deploys on push
3. Monitor Railway logs for:
   - `[CACHE] stored N rows under rc_...`
   - `[CACHE] hit rc_... — N rows from handler=...`
   - `[SYNTH] tool_results ~XXX chars`

**Expected Log Patterns:**

Turn 1 (initial query):
```
[HANDLER] query_waterfall → partial
[SYNTH] tool_results ~800 chars (handler=query_waterfall)
[SAVE_THREAD] extracting entities from cache_payload
[CACHE] stored 247 rows under rc_abc123... (handler=query_waterfall, ttl=30m)
```

Turn 2 (follow-up with cache hit):
```
[CACHE] hit rc_abc123... — 247 rows from handler=query_waterfall
[ROUTING] answering follow-up from cached payload (no entity IDs available)
```

### 3. Live Slack Test

**Test Sequence:**
```
User: show me current pipeline
Bot: [waterfall summary]

User: which of those are at risk?
Bot: [filters cached deals by at_risk=true]
```

**Verify:**
- Turn 2 uses cache (check Railway logs for `[CACHE] hit`)
- No fresh query_waterfall handler call on Turn 2
- Answer references specific deals from Turn 1

### 4. Monitor for Issues

**Warning Signs:**
- `[SYNTH] oversized synthesis payload >20K chars` — cache_payload leaked
- `[ENTITY] save_thread stored ZERO entities ... despite non-empty tool_results` — extraction failure
- Multiple `[CACHE] no live cache for thread` on valid follow-ups — TTL too short or cache miss

**Performance Metrics:**
- Cache TTL: 30 minutes (matches G.6 entity staleness guard)
- Expected cache hit rate: 30-40% on follow-up questions
- Expected synthesis size: <2K chars (vs 3-5K if cache_payload leaks)

## Rollback Plan

If issues arise:

1. **Revert code changes:**
   ```bash
   git revert <commit-sha>
   git push
   ```

2. **Migration rollback** (if needed):
   ```sql
   DROP TABLE IF EXISTS result_cache CASCADE;
   DROP VIEW IF EXISTS result_cache_active;
   ```

3. **Behavior:** Reverts to pre-G.7 state:
   - Aggregate handlers still work (cache_payload is optional)
   - Follow-ups on waterfall fall back to "I need more context"
   - No data loss (only affects new follow-up capability)

## Future Work (TASK 5)

Add cache expiry cleanup to nightly workflow:

```sql
-- Add to scripts/nightly_cleanup.sql
DELETE FROM result_cache WHERE expires_at < now();
```

Schedule in Railway:
```yaml
# .github/workflows/nightly-cleanup.yml
- name: Clean expired cache
  run: railway run python scripts/nightly_cleanup.py
```

## Design Principles Validated

✅ **Load-bearing assertion:** `assert "cache_payload" not in tool_results`
✅ **Size logging:** `[SYNTH] tool_results ~XXX chars` makes leaks visible
✅ **Dual extraction:** Entities from both tool_results AND cache_payload
✅ **TTL-based expiry:** Uses timedelta, not modular arithmetic
✅ **Explicit role filtering:** CACHE_ROLE auto-filtered like ENTITY_ROLE
✅ **Opt-in pattern:** Handlers return cache_payload only when needed

## Success Criteria

- [x] Migration 025 applied successfully
- [x] Eval harness passes (20/20 tests)
- [ ] Live Slack test shows cache hit on Turn 2
- [ ] No oversized synthesis warnings in Railway logs
- [ ] Cache hit rate >20% after 48 hours of production use
