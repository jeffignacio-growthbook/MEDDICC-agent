# query_pipeline_movement Convergence Audit
## Phase 1b, Handler 1 - Step 1

**Date**: 2026-09-17
**Handler**: `query_pipeline_movement` (api/handlers.py:4561-4958)

---

## EXECUTIVE SUMMARY

This handler has a demonstrated track record of silent failures (2 real bugs fixed this session). Audit identifies **4 HIGH severity**, **3 MEDIUM severity**, and **2 LOW severity** duplications totaling **9 instances** of hand-rolled logic that should converge to primitives or field_semantics.

**Critical Finding**: pipeline_filter/stage_filter parameters are NOT declared in classifier schema for this handler (only for query_pipeline), creating the same silent failure mode already fixed for query_pipeline.

---

## DETAILED FINDINGS

### HIGH SEVERITY (4 instances)

#### H1. Multiple in-memory filtering passes (lines 4715-4813)
**Location**: Main handler body
**Current**: 5 sequential in-memory filter passes on already-loaded rows:
```python
# Pass 1: deal_ids filter (lines 4715-4717)
if deal_ids:
    wanted = {str(d) for d in deal_ids}
    rows = [r for r in rows if str(r.get("deal_id")) in wanted]

# Pass 2: snapshot_source filter (lines 4783-4784)
grid_rows = [r for r in rows
             if (r.get("snapshot_source") or "unknown") == chosen_source]

# Pass 3: current position rows (lines 4787-4791)
if base.get("_current_position_date")...
    position_rows = [r for r in rows if r.get("snapshot_date") == ...]
    grid_rows.extend(position_rows)

# Pass 4: analytics scope filter (lines 4794-4795)
scoped = [r for r in grid_rows
          if _pm_in_scope(r, excluded_pipelines, stage_cfg, is_in_scope)]

# Pass 5: close_date_scope filter (lines 4801-4813)
if close_date_scope == "current_quarter" and scoped:
    ...
    scoped = [r for r in scoped
              if r.get("close_date") and lo <= r["close_date"][:10] <= hi]
```

**Should use**: filter_table() with combined filters pushed server-side
**Why HIGH**: Performance penalty (5 full scans of large result sets), same anti-pattern already fixed in query_pipeline
**Complexity**: HIGH - filters depend on computed values (chosen_source, excluded_pipelines), requires careful staging

---

#### H2. Manual stage-by-stage aggregation (lines 4372-4395 in _pm_view_movement)
**Location**: `_pm_view_movement` helper
**Current**: Hand-coded loop computing stage-level counts:
```python
by_stage = []
for name in sorted(stage_names, key=_order):
    p = prior_sets.get(name, set())
    c = current_sets.get(name, set())
    entered = c - p
    entered_new = entered & new_ids
    entered_moved = entered - new_ids
    by_stage.append({
        "stage": name,
        "prior": len(p),
        "current": len(c),
        "net": len(c) - len(p),
        "entered": len(entered),
        "entered_from_other_stage": len(entered_moved),
        "new_to_pipeline": len(entered_new),
        "exited": len(p - c),
        ...
    })
```

**Should use**: aggregate_results() with group_by="stage" and computed fields
**Why HIGH**: Core aggregation primitive exists for exactly this pattern
**Complexity**: MEDIUM - set arithmetic (entered_new vs entered_moved) may need pre-computation

---

#### H3. Snapshot selection reimplements time window logic (lines 4310-4350 in _pm_view_movement)
**Location**: `_pm_view_movement` snapshot selection
**Current**: Parallel date math to find prior snapshot:
```python
if requested_days:
    # ALLOW-RAW-DATE-MATH comment claims this is downstream of resolve_time_window()
    target_date = date.fromisoformat(current_date) - timedelta(days=requested_days)
    target_str = target_date.isoformat()
    valid_prior = [d for d in all_dates if d <= target_str]
    if valid_prior:
        prior_date = valid_prior[-1]
    else:
        prior_date = all_dates[0]
        # ... data_gaps warning
else:
    prior_date = all_dates[-2]
```

**Should use**: resolve_snapshot_anchors() from api/snapshot_diff.py
**Why HIGH**: Parallel implementation of snapshot anchor selection, bypasses governed primitive
**Complexity**: MEDIUM - needs requested_days passed through, but primitive already handles this
**Note**: ALLOW-RAW-DATE-MATH comment is a red flag - claims downstream but reimplements anyway

---

#### H4. Schema gap: pipeline_filter/stage_filter not declared (api/router.py:899-900)
**Location**: Classifier schema
**Current**: Lines 899-900 declare these params "for query_pipeline" only:
```python
"pipeline_filter": "new_business|renewal|null — set to 'new_business' when question explicitly asks for new business...",
"stage_filter": "qualified|discovery|scoping|proposal|null — for query_pipeline: filter to specific stage bucket...",
```

Handler accepts pipeline_id (line 4622) but classifier won't extract it for this handler.

**Should**: Duplicate param declarations for query_pipeline_movement or make schema say "for query_pipeline and query_pipeline_movement"
**Why HIGH**: Same silent failure mode (parameter never reaches handler) already fixed for query_pipeline
**Complexity**: LOW - schema-only change, no logic impact

---

### MEDIUM SEVERITY (3 instances)

#### M1. Manual totals computation (lines 4403-4414 in _pm_view_movement)
**Location**: `_pm_view_movement` totals
**Current**:
```python
totals = {
    "prior": len(prior_rows),
    "current": len(current_rows),
    "net": len(current_rows) - len(prior_rows),
}
summary = {
    "new_to_pipeline": len(new_ids),
    "left_pipeline": len(left_ids),
    "moved_between_stages": len(moved_between),
}
```

**Should use**: aggregate_results() with deal-level data and computed fields
**Why MEDIUM**: Simple counts, low bug risk, but duplicates aggregation primitive's purpose
**Complexity**: LOW - straightforward refactor

---

#### M2. _pm_by_date groups manually (lines 4231-4237)
**Location**: Helper function
**Current**:
```python
def _pm_by_date(scoped):
    by_date = {}
    for r in scoped:
        date_key = r.get("snapshot_date")
        by_date.setdefault(date_key, []).append(r)
    return by_date
```

**Should use**: aggregate_results() with group_by="snapshot_date"
**Why MEDIUM**: Duplicates grouping primitive, but simple/low-risk code
**Complexity**: LOW - one-line refactor

---

#### M3. _pm_stage_sets groups by stage (lines 4238-4247)
**Location**: Helper function
**Current**: Manual grouping into sets per stage name
**Should use**: aggregate_results() with group_by and set accumulation
**Why MEDIUM**: Duplicates grouping, but set-based (not just counts) adds complexity
**Complexity**: MEDIUM - set accumulation may not map cleanly to aggregate_results()

---

### LOW SEVERITY (2 instances)

#### L1. _pm_company_map fetches names (lines 4249-4269)
**Location**: Helper function
**Current**: Direct select_all call for company names
**Should use**: Could use filter_table() for consistency, but minimal benefit
**Why LOW**: Simple lookup, no filtering/aggregation logic, low refactor value
**Complexity**: LOW - but low value too

---

#### L2. Manual confidence computation (lines 4211-4220)
**Location**: `_pm_confidence_mix` helper
**Current**: Aggregates forecast_category manually
**Should use**: aggregate_results() with group_by="forecast_category"
**Why LOW**: Simple count by category, but small/focused function
**Complexity**: LOW - but isolated, low urgency

---

## SCHEMA VERIFICATION

### Parameters Currently Declared (router.py:895-901)
✅ view
✅ fiscal_quarter
✅ weeks
✅ stage (for stage_deals view)
✅ close_date_scope
❌ pipeline_filter (declared for query_pipeline only, line 899)
❌ stage_filter (declared for query_pipeline only, line 900)
❌ pipeline_id (not declared at all, but handler accepts it line 4622)
❌ owner_email (not declared, but handler accepts it line 4617)

### Already Fixed Issues Confirmed
✅ owner_email uses ilike (line 4682) - canonicalization gap FIXED
✅ fiscal_quarter normalization (line 4609) - exact-match gap FIXED

---

## SNAPSHOT HANDLING ASSESSMENT

**Current approach**: Handler does NOT use api/snapshot_diff.py primitives:
- resolve_snapshot_anchors() - NOT USED, reimplemented in _pm_view_movement
- diff_snapshots() - NOT USED, handler computes diffs inline

**Why legitimate complexity**:
- Handler needs 5 different views (movement/composition/deal_changes/curve/stage_deals)
- Multi-grid handling (weekly vs mid-week snapshots) is handler-specific
- Set-based stage movement logic (entered_new vs entered_moved) is domain-specific

**Recommendation**: H3 (snapshot selection) CAN converge to resolve_snapshot_anchors(), but diff logic may be too specialized to force into diff_snapshots(). Evaluate during Step 3.

---

## PRIORITY RANKING FOR REFACTOR

1. **H4** (schema gap) - MUST FIX, blocks parameter extraction
2. **H1** (multiple filter passes) - HIGH VALUE, performance impact
3. **H3** (snapshot selection) - HIGH VALUE, governance gap
4. **H2** (stage aggregation) - MEDIUM VALUE, primitive convergence
5. **M1-M3** - LOW-MEDIUM VALUE, nice-to-have convergence
6. **L1-L2** - LOW VALUE, optional polish

---

## STOP CONDITIONS TRIGGERED?

❌ **Snapshot-diffing doesn't map cleanly**: PARTIAL - snapshot selection (H3) can converge, but diff logic is legitimately complex. Will evaluate in Step 3 - if awkward, report back.

✅ **New bugs found**: YES - H4 schema gap is a new finding (pipeline_filter/stage_filter not declared for this handler).

---

## NEXT STEPS

Proceed to Step 2 (Baseline) only after user review of this audit.
