# Migration Order - Canonical Linear Sequence

## Problem Statement

Migration number collisions existed in the GrowthBook repo:
- Five numbers were used twice (012, 013, 014, 015, 016, 027)
- GrowthBook's live DB is fine (applied by hand in correct order)
- Fresh template DB would have undefined ordering due to filename sort

This document establishes the **canonical linear order** for all migrations.

---

## Renumbering Summary

### 012 Pair
- ✅ **012_add_forecast_weekly.sql** - Kept (creates forecast_weekly table)
- 📝 012_add_sdr_metrics.sql → **028_add_sdr_metrics.sql** (creates sdr_metrics, sdr_users)

### 013 Pair
- ✅ **013_add_segmentation.sql** - Kept (adds segment columns to deals)
- 📝 013_add_user_personas.sql → **029_add_user_personas.sql** (creates user_personas)

### 014 Pair
- ✅ **014_add_segment_reason.sql** - Kept (adds diagnostic column, depends on 013)
- 📝 014_add_sdr_owner_to_deals.sql → **031_add_sdr_owner_to_deals.sql** (adds sdr_owner_email)

### 015 Pair
- ✅ **015_create_pipeline_generation_weekly.sql** - Kept (uses segment from 013)
- 📝 015_user_personas_email_primary_key.sql → **032_user_personas_email_primary_key.sql** (depends on 029)

### 016 Pair
- ✅ **016_add_waterfall_beginning_ending.sql** - Kept (alters waterfall_weekly)
- 📝 016_create_meetings_table.sql → **033_create_meetings_table.sql** (creates meetings)

### 027 Pair
- ✅ **027_entity_scope_patterns.sql** - Kept (entity registry patterns)
- 📝 027_add_proposal_lifecycle.sql → **034_add_proposal_lifecycle.sql** (alters data_dictionary, Phase 5)

---

## Canonical Linear Order (All Migrations)

| # | Filename | Description | Dependencies |
|---|----------|-------------|--------------|
| 001 | initial_schema | Creates base tables (deals, calls, analyses, etc.) | None |
| 002 | add_deal_history | Deal history tracking | 001 |
| 003 | add_component_scores | MEDDICC component scores | 001 |
| 004 | add_qualification_tracking | Qualification tracking | 001 |
| 005 | add_deals_snapshot | Historical snapshots | 001 |
| 006 | add_waterfall_and_winloss | Waterfall and win/loss tables | 001 |
| 007 | add_reporting_fields | Reporting columns | 001 |
| 008 | add_enrichment_tables | Enrichment data tables | 001 |
| 009 | add_enrichment_scans | Enrichment scan tracking | 008 |
| 010 | drop_call_fk_constraints | Remove FK constraints on calls | 001 |
| 011 | add_newly_qualified | Qualification status tracking | 001 |
| 012 | add_forecast_weekly | Forecast snapshots by week | 001 |
| 013 | add_segmentation | Company size segments (SMB/MM/ENT) | 001 |
| 014 | add_segment_reason | Segment diagnostic column | 013 |
| 015 | create_pipeline_generation_weekly | Pipeline gen by segment | 013 |
| 016 | add_waterfall_beginning_ending | Waterfall validation columns | 006 |
| 017 | add_backfill_confidence | Snapshot backfill quality tracking | 005 |
| 018 | add_component_rationales | MEDDICC rationale text | 003 |
| 019 | add_cro_agent_tables | CRO Slack agent infrastructure | 001 |
| 020 | add_data_dictionary | Field metadata for dynamic queries | 001 |
| 021 | add_learning_log | Learning/improvement tracking | 001 |
| 022 | add_sales_signals_and_category_monitor | Competitive/pipeline signals | 001 |
| 023 | calls_resolution_table | Call metadata resolution | 001 |
| 024 | add_company_domain | Company domain field | 001 |
| 025 | result_cache | Query result caching | 001 |
| 026 | entity_registry | Entity tracking and resolution | 001 |
| 027 | entity_scope_patterns | Entity scope configuration | 026 |
| 028 | add_sdr_metrics | **RENUMBERED** - SDR activity tracking | 001 |
| 029 | add_user_personas | **RENUMBERED** - User persona registration | 001 |
| 030 | add_call_quality | Call quality scoring | 001 |
| 031 | add_sdr_owner_to_deals | **RENUMBERED** - SDR attribution | 001 |
| 032 | user_personas_email_primary_key | **RENUMBERED** - Alter user_personas PK | 029 |
| 033 | create_meetings_table | **RENUMBERED** - Meeting tracking | 001 |
| 034 | add_proposal_lifecycle | **RENUMBERED** - Field definition proposals (Phase 5) | 020 |

---

## Critical Dependencies

These migrations MUST run in order due to table/column dependencies:

1. **014_add_segment_reason** depends on **013_add_segmentation**
   - Adds segment_reason which references segment column

2. **015_create_pipeline_generation_weekly** depends on **013_add_segmentation**
   - Uses segment column for grouping

3. **032_user_personas_email_primary_key** depends on **029_add_user_personas**
   - Alters user_personas table structure

4. **034_add_proposal_lifecycle** depends on **020_add_data_dictionary**
   - Alters data_dictionary table

---

## GrowthBook Applied State

GrowthBook's production database has all migrations applied in the correct dependency order, even though some had duplicate numbers. The renumbering does NOT require re-running migrations on GrowthBook.

**Mapping for GrowthBook's applied migrations:**

```
Applied as 012_add_sdr_metrics → Now numbered 028
Applied as 013_add_user_personas → Now numbered 029
Applied as 014_add_sdr_owner_to_deals → Now numbered 031
Applied as 015_user_personas_email_primary_key → Now numbered 032
Applied as 016_create_meetings_table → Now numbered 033
Applied as 027_add_proposal_lifecycle → Now numbered 034
```

GrowthBook's migration state remains valid. The renumbering fixes template's fresh database setup.

---

## template Fresh Database Setup

For a fresh template deployment, apply migrations in numeric order (001 → 034):

```bash
for migration in scripts/migrations/*.sql; do
  echo "Applying $migration..."
  psql $DATABASE_URL -f $migration
done
```

The numeric order now correctly respects all dependencies.

---

## Testing

Run `scripts/eval_migrations.py` to verify:
- No duplicate migration numbers
- All migrations exist
- Dependency order is respected

---

## Renumbering Policy

**Going forward:**
- Check for highest existing number before creating new migration
- Never reuse a number
- Document dependencies in migration header
- Run `test_no_duplicate_migration_numbers()` before committing
