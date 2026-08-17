# Phase G.8 Entity Registry - Quick Reference

## Scripts

### Data Dictionary Backfill
```bash
# Show sample descriptions (first 10 columns)
./scripts/backfill_data_dictionary.py --sample

# Dry run - show all descriptions without inserting
./scripts/backfill_data_dictionary.py --dry-run

# Actually insert into database
./scripts/backfill_data_dictionary.py
```

### Pattern Analysis
```bash
# View all successful patterns
./scripts/analyze_entity_patterns.py

# Find high-frequency patterns (>= 5 occurrences)
./scripts/analyze_entity_patterns.py --min-frequency 5

# Analyze specific handler
./scripts/analyze_entity_patterns.py --handler query_objections

# Last 7 days only
./scripts/analyze_entity_patterns.py --recent 7
```

### Handler Generation
```bash
# Dry run - analyze and preview (no PRs created)
./scripts/generate_handler_from_pattern.py --dry-run

# Create PRs for top 3 qualifying patterns
./scripts/generate_handler_from_pattern.py --create-pr

# Adjust frequency threshold (default: 10)
./scripts/generate_handler_from_pattern.py --min-frequency 5 --create-pr

# Four validation gates run automatically:
#   1. Safety check (read-only, no dangerous imports)
#   2. Execution test (runs against real data)
#   3. Answer quality (Haiku validates result)
#   4. Confidence >= 0.6
```

### Eval Suite
```bash
# Run all entity path tests (27 assertions)
python scripts/eval_entity_paths.py
```

---

## Migrations

### Apply Migration 026 (Entity Registry)
```bash
psql $SUPABASE_DB_URL -f scripts/migrations/026_entity_registry.sql
```

### Apply Migration 027 (Pattern Logging)
```bash
psql $SUPABASE_DB_URL -f scripts/migrations/027_entity_scope_patterns.sql
```

### Verify Migrations
```sql
-- Check entity_registry view exists
SELECT * FROM entity_registry LIMIT 5;

-- Check pattern logging table exists
SELECT COUNT(*) FROM entity_scope_patterns;
```

---

## SQL Queries

### View Entity Registry
```sql
SELECT
    supabase_table,
    id_column,
    entity_type,
    entity_label_column,
    description
FROM entity_registry
ORDER BY supabase_table;
```

### Top Patterns by Frequency
```sql
SELECT
    question,
    COUNT(*) as frequency,
    AVG(quality_score)::NUMERIC(3,2) as avg_quality,
    array_agg(DISTINCT handler_name) as handlers_used
FROM entity_scope_patterns
WHERE quality_score >= 0.7
GROUP BY question
HAVING COUNT(*) >= 5
ORDER BY frequency DESC
LIMIT 20;
```

### Handler Performance
```sql
SELECT
    handler_name,
    COUNT(*) as executions,
    AVG(quality_score)::NUMERIC(3,2) as avg_quality,
    MIN(quality_score) as min_quality,
    MAX(quality_score) as max_quality
FROM entity_scope_patterns
GROUP BY handler_name
ORDER BY executions DESC;
```

### Pattern Trends (Last 7 Days)
```sql
SELECT
    DATE(asked_at) as date,
    COUNT(*) as patterns,
    COUNT(DISTINCT question) as unique_questions,
    COUNT(DISTINCT handler_name) as handlers_used,
    AVG(quality_score)::NUMERIC(3,2) as avg_quality
FROM entity_scope_patterns
WHERE asked_at >= NOW() - INTERVAL '7 days'
GROUP BY DATE(asked_at)
ORDER BY date DESC;
```

---

## Workflow: Adding a New Entity Type

1. **Update entity registry:**
   ```sql
   UPDATE data_dictionary
   SET is_entity_id = TRUE,
       entity_type = 'contact',
       entity_label_column = 'email'
   WHERE supabase_table = 'contacts'
     AND supabase_column = 'contact_id';
   ```

2. **Verify extraction works:**
   ```bash
   python scripts/eval_entity_paths.py
   ```

3. **Monitor patterns:**
   ```bash
   ./scripts/analyze_entity_patterns.py --recent 7
   ```

4. **Generate handler if needed:**
   ```bash
   ./scripts/generate_handler_from_pattern.py
   ```

---

## Workflow: Generating a Handler from Pattern

1. **Identify high-frequency pattern:**
   ```bash
   ./scripts/analyze_entity_patterns.py --min-frequency 10
   ```

2. **Generate handler PR:**
   ```bash
   ./scripts/generate_handler_from_pattern.py --create-pr
   # Processes top 3 patterns automatically
   # Creates GitHub PR for each passing handler
   ```

3. **Review PR on GitHub:**
   - Check handler code is read-only (no writes/deletes)
   - Verify return dict structure makes sense
   - Confirm validation gates all passed
   - Check PR description for manual additions needed

4. **Merge PR and add HANDLER_DESCRIPTIONS:**
   - Merge PR to add handler to `api/handlers.py`
   - Add HANDLER_DESCRIPTIONS entry to `api/router.py` (shown in PR)
   - Deploy to production

5. **Verify and monitor:**
   ```bash
   # Test locally
   python scripts/eval_entity_paths.py

   # Monitor in production
   SELECT * FROM entity_scope_patterns
   WHERE handler_name = 'query_new_handler'
   ORDER BY asked_at DESC;
   ```

---

## Code Locations

**Core Files:**
- `api/router.py` - HANDLER_DESCRIPTIONS, classify_entity_scope_handler(), route_entity_scoped_question()
- `api/handlers.py` - All handler implementations
- `api/db.py` - extract_entity_context(), _to_legacy_entity_shape()
- `api/evaluator.py` - evaluate_result() quality scoring

**Scripts:**
- `scripts/backfill_data_dictionary.py` - Data dictionary population
- `scripts/analyze_entity_patterns.py` - Pattern frequency analysis
- `scripts/generate_handler_from_pattern.py` - Auto-generate handlers
- `scripts/eval_entity_paths.py` - Regression test suite

**Migrations:**
- `scripts/migrations/026_entity_registry.sql` - Entity registry schema
- `scripts/migrations/027_entity_scope_patterns.sql` - Pattern logging table

**Documentation:**
- `docs/G8_ENTITY_REGISTRY_COMPLETE.md` - Full implementation guide
- `docs/G8_QUICK_REFERENCE.md` - This file

---

## Troubleshooting

### Pattern logging fails
**Error:** `relation "entity_scope_patterns" does not exist`
**Fix:** Apply migration 027
```bash
psql $SUPABASE_DB_URL -f scripts/migrations/027_entity_scope_patterns.sql
```

### Entity extraction returns empty
**Check:** Is entity registered?
```sql
SELECT * FROM entity_registry WHERE entity_type = 'deal';
```
**Fix:** Update data_dictionary to mark ID column as entity

### Handler generation fails
**Error:** `No patterns found with frequency >= 10`
**Fix:** Lower threshold or wait for more data
```bash
./scripts/generate_handler_from_pattern.py --min-frequency 5
```

### Eval suite fails after changes
**Error:** `AssertionError: ...`
**Fix:** Review changes in router.py, ensure backward compatibility
```bash
git diff api/router.py
git diff api/handlers.py
```

---

## Monitoring

### Daily Check
```bash
# Check pattern accumulation
./scripts/analyze_entity_patterns.py --recent 1

# Look for candidates
./scripts/analyze_entity_patterns.py --min-frequency 10
```

### Weekly Review
```sql
-- Handler performance this week
SELECT
    handler_name,
    COUNT(*) as executions,
    AVG(quality_score)::NUMERIC(3,2) as avg_quality
FROM entity_scope_patterns
WHERE asked_at >= NOW() - INTERVAL '7 days'
GROUP BY handler_name
ORDER BY executions DESC;
```

### Monthly Cleanup
```sql
-- Archive old patterns (keep 90 days)
DELETE FROM entity_scope_patterns
WHERE asked_at < NOW() - INTERVAL '90 days';
```

---

*Phase G.8 completed 2026-08-17*
