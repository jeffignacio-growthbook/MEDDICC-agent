# Post-8/21 call transcript gap: investigation (2026-09-22)

Status: **root-caused; fixes landed on `claude/exciting-bohr-qb365q` (see Update at the bottom). Backfill not yet run.**

Evidence:
- `scripts/audit_apollo_transcript_gap.py`: read-only production audit, run
  [35783899650](https://github.com/jeffignacio-growthbook/MEDDICC-agent/actions/runs/35783899650)
  on 2026-09-22 21:00 UTC.
- Daily Calls ETL job logs for runs 14–49 (8/18 → 9/22).

## 1. Scope (real numbers, call_date > 2026-08-21)

| source | calls | with text | missing | missing % |
|---|---|---|---|---|
| apollo | 19 | 2 | 17 | **89.5%** |
| fireflies | 285 | 101 | 184 | **64.6%** |
| **total** | **304** | **103** | **201** | **66.1%** |

Coaching-relevant subset (excludes `call_intent='skip'` and `is_internal`):
- Apollo: 16/17 missing (94.1%).
- Fireflies: 133/218 missing (61.0%).

Baseline on or before 8/21:
- Apollo: 2/553 missing (0.4%).
- Fireflies: 83/2189 missing (3.8%).

**Shape of the gap:** 199 of the 201 have **no `call_transcripts` row at all**. Only 2 are rows with `transcript IS NULL`, and both are Fireflies calls with `retry: no transcript yet`. A `LEFT JOIN` makes these look like NULL transcripts, but the transcript was never written, not written empty.

**The text exists at the source.** A live Apollo spot-check of 5 missing calls returned full transcripts for 4 of them:
- Bet365: 13,118 chars.
- Rich Lane: 17,536 chars.
- BambooHR: 36,010 chars.
- MrQ: 42,438 chars.

The fifth, A24, genuinely has only 104 chars at the source.

## 2. Not Apollo-specific

Fireflies has 184 missing calls, ten times Apollo's 17. Apollo's *percentage* is higher only because its few calls happened to land on the bad nights.

Apollo's real role is narrower: Apollo is the **trigger** of one of the failures (cause B below). That failure takes out every source's transcripts that night.

## 3. Ingestion path

Call metadata reaches `calls` through three writers. Transcripts reach `call_transcripts` through exactly one:

| step (daily-calls-etl.yml) | writes `calls` | writes `call_transcripts` |
|---|---|---|
| `etl_calls.py --mode incremental`, `bulk_upsert_calls` | yes | yes, **but only if the calls upsert succeeded** (same `try`) |
| `enrichment/fireflies_participants.py --only-new` | yes (metadata) | no |
| `enrichment/apollo_participants.py --only-new` | yes (metadata) | no |

This is why metadata is present while transcripts are missing. The participant steps run separately and succeed every night. The only transcript writer, `etl_calls.py:885-912`, sits inside the `try` whose first statement is the `calls` upsert:

```python
try:
    ... sb.bulk_upsert_calls(...)          # raises -> jumps to line 913
    try:
        ... fetch_utterances / bulk_upsert_transcripts
    except Exception as te:
        print("⚠️  Transcript persist failed (calls unaffected)")
except Exception as e:
    print(f"  ⚠️  Supabase write failed: {e}")   # etl_calls.py:913-914
```

When the calls upsert raises, the transcript block is skipped entirely.

## 4. Silent failure: yes, the same shape as the MEDDICC/Supabase bug

`etl_calls.py:913-914` catches the exception, prints one warning line, and the script exits 0. The workflow step reports success, and `Alert on failure` (`if: failure()`) never fires. Runs 30–49 are all green in Actions.

The skip is also permanent. `get_last_cache_date()` advances the cutoff from the JSON cache, which *was* written (`save_call_caches` runs before Supabase). So a failed night's calls are never re-attempted.

## 5. Three causes, with dates and counts

All 201 missing calls fall into one of three causes:

| cause | nights (ETL run) | missing call dates | missing | apollo / fireflies |
|---|---|---|---|---|
| **A → B.** Backlog blocked by schema drift, then flushed into a duplicate-key failure | runs 14–29 (8/18–9/2): `PGRST204 Could not find the 'competitors_mentioned' column`. Run 30 (9/3): caught up 184 calls, failed `21000` | 8/24 – 9/3 (every day 100% missing) | 149 | 10 / 139 |
| **B.** Duplicate Apollo row in one upsert: `21000 ON CONFLICT DO UPDATE command cannot affect row a second time` | run 46 (9/19), run 49 (9/22) | 9/18, 9/21 (100% missing) | 22 | 5 / 17 |
| **C.** Cutoff drops late-arriving same-day calls | runs 38–41, 42–45 | 9/8–9/16 (9/10: 10/12, 9/11: 11/12, scattered others) | 28 | 2 / 26 |
| NULL rows (source still processing) | — | 9/14, 9/17 | 2 | 0 / 2 |

### Cause A: schema drift (runs 14–29, 8/18 → 9/2)

The `calls` upsert failed on a column missing from the schema. Commits `1ef2ff03` / `235cc87a` (9/2, migration 050) fixed it.

The job also failed later, in `Resolve calls to deals` (`ANTHROPIC_API_KEY not set`). That happened before `Commit updated call cache`, so the cutoff stayed at 8/18 and the backlog kept growing.

The go-forward transcript persist shipped 8/22 (`b19857fa`). It **never ran successfully** until 9/5. The 8/22–8/23 one-time backfill covered everything already in `calls`, which is why the gap begins right after 8/21.

### Cause B: Apollo is ingested twice

Commit `893ddefa` (2026-08-18 23:54 PT) routed calls through `get_call_sources()`. `config/client.yaml` lists `priority: [fireflies, apollo]`, so `ApolloAdapter` now returns Apollo calls. But `main()` still also calls the legacy `fetch_apollo_incremental()` (`etl_calls.py:862`), which appends the same conversation id to the same company slug a second time.

`write_cache()` dedupes the JSON file, but the in-memory `calls_by_company` sent to `bulk_upsert_calls` does not. Postgres rejects the batch with `21000`.

It fires only on nights when the legacy path actually appends an Apollo call (transcript ≥50 chars) that Fireflies dedup did not already drop. That explains runs 30, 46 and 49. Runs 36 and 45 had Apollo calls but no duplicate, and they succeeded.

Run 49 shows it directly. `Found 6 calls from apollo` and `Found 3 new Apollo calls` cover the same Bet365 / Rich Lane / BambooHR ids, followed by the `21000` failure.

### Cause C: cutoff drops late-arriving calls (independent of A and B)

`get_last_cache_date()` returns the max cached call date. Both fetchers then skip `call_date <= since_date` (`etl_calls.py:258`, `:327`).

Once any call dated D is cached, every later-arriving call dated D is dropped for good. The participant steps still create their `calls` rows, so again: metadata, no transcript.

## Blast radius

- `call_transcripts` has nothing usable for **201 of 304** calls since 8/22. That covers **every** call from 8/24–9/3, 9/18 and 9/21.
- Rep-coaching Criterion B/C (talk ratio, question share, speaker identity) have no input for those calls. The same goes for anything else reading `call_transcripts`:
  - `backfill_call_scores.py`
  - `coaching_talk_ratio.py`
  - the calibration audits
- `participant_identities` (migration 065, Criterion C) is missing for 16 of the 17 in-scope Apollo calls.
- Separate but same root: the `calls` upsert from `etl_calls.py` also failed those nights. So those calls' `calls` rows lack `formatted_summary` / `company_slug` / `duration_minutes` from this path. They hold only the participant-step metadata. Measured later: 50 of the 201 (see Update).
- The JSON call cache (the MEDDICC nightly input) is not affected by causes A/B, because it is written before Supabase. It **is** affected by cause C: those calls were never cached, so never MEDDICC-analyzed (see Update).
- Nothing about this is recoverable by waiting. No path re-attempts these calls on its own.

## Fix options (not applied, for decision)

1. **Backfill the 201 now.** `scripts/backfill_transcripts.py` treats absent rows as to-do, so a plain re-run fills them. Its workflow's `branch` input defaults to a stale `claude/...` branch, so pass `main`. This needs no code change.
2. **Stop the double Apollo ingestion (B).** Drop the legacy `fetch_apollo_incremental()` call now that `ApolloAdapter` covers Apollo. At minimum, dedupe `calls_by_company` by `call_id` before the upsert.
3. **Decouple the transcript persist from the calls upsert.** Give it its own `try`, and make an upsert failure exit non-zero so `Alert on failure` fires, instead of printing and exiting 0.
4. **Fix the cutoff (C).** Use `>=` with id-dedup, or a lookback of a few days, instead of `call_date > max_cached_date`.
5. Optional guard: a monitor comparing `calls` vs `call_transcripts` counts by day, in the style of `monitor_data_completeness.py`.

---

## Update: fixes landed on `claude/exciting-bohr-qb365q` (backfill not yet run)

Live baseline was re-run before any fix (audit run 35783899650, attempt 2, 21:06 UTC). It is unchanged:
- **201 missing:** Apollo 17/19, Fireflies 184/285.
- **Per-cause split:** A→B 149, B 22, C 28, NULL 2.

**Cause A open item, now measured** (audit run 35785110841, section 6):
- **50 of the 201** transcript-missing calls also have metadata-only `calls` rows: no `formatted_summary`, no `company_slug`. That is 7 Apollo and 43 Fireflies.
- The other 151 do have summaries. On the failed nights, the companies processed before the bad batch were written.
- Cause C calls are also missing from the JSON cache, which means they were never MEDDICC-analyzed:

  | call date | `calls` table | JSON cache |
  |---|---|---|
  | 9/10 | 12 | 2 |
  | 9/11 | 12 | 1 |
  | 9/14 | 14 | 11 |

**Is removing `fetch_apollo_incremental()` safe? No.**
- In run 29 the adapter found 4 Apollo calls and the legacy path found 13.
- The adapter only ever reads search page 1. The `etl_calls.py` loop breaks when the *filtered* batch is under 50, and at REST volume page 1 covers about 2 days.
- The legacy copy is also what `write_cache` keeps today (8 of the 10 post-8/21 Apollo cache entries).
- So: dedupe now; fix adapter pagination, then remove the legacy path later.

| cause | fix | commit |
|---|---|---|
| B: duplicate Apollo id in one upsert (21000) | `dedupe_calls_by_id()`, last copy wins, applied before both cache and Supabase | 0b011dd2 |
| D: silent swallow | Per-company upsert; transcript persist independent of the calls upsert (only the FK parent must exist). Every state counted per source and shown in `$GITHUB_STEP_SUMMARY`. Exit 1 on lost data. Capped nightly self-heal step. | 0b011dd2 |
| C: late same-day arrivals dropped | 3-day lookback plus skip of already-cached ids, in both fetchers | d3d65849 |
| A: schema drift left bare calls rows | Source already fixed 9/2. New `--resync-cache-since` repair (targets bare rows only). The D fix makes a repeat loud. | 4e8ff6a5 |
