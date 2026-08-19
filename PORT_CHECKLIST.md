# Port Checklist: GrowthBook → Template

This document tracks template-level artifacts that must carry over when
porting GrowthBook's MEDDICC agent harness into the reusable template.

**Port path:** GrowthBook (client-specific) → Template (harness only) → template (new client)

## Template-Level Artifacts (Must Carry Over)

These are harness infrastructure that ships with the template.
Client-specific VALUES get blanked/placeholdered, but STRUCTURE travels.

### Secret Protection
- ✅ `.pre-commit-config.yaml` - Pre-commit framework config for secret detection
- ✅ `scripts/hooks/block_api_keys.sh` - Local hook blocking Anthropic/HubSpot API patterns
- ✅ `scripts/install_hooks.sh` - Hook installer (required onboarding step)
- ✅ `.secrets.baseline` - Detect-secrets baseline file
- ✅ `.gitignore` - Corrected version (no `test_*.py` landmine)
- **Action:** Document in deployment runbook: "After cloning, run `./scripts/install_hooks.sh`"

### Field Semantics (Stage/Field Abstraction)
- ✅ `config/field_semantics.yaml` - STRUCTURE travels (stage_map, outcome_buckets, field_units)
- ✅ `scripts/field_semantics_generator.py` - Generates field_semantics.py from YAML
- ✅ `scripts/field_semantics.py` - Generated module (DO NOT EDIT marker)
- ✅ `scripts/eval_field_semantics.py` - Drift tests (YAML ↔ generated module match)
- ✅ Harness boundary isolation tests (handlers never import data_dictionary)
- **Action:** Blank stage_map VALUES in template (GrowthBook stage IDs → placeholder)

### Migration System
- ✅ `scripts/migrations/001-035_*.sql` - Renumbered migration sequence (collision-free)
- ✅ `scripts/eval_migrations.py` - No-duplicate-number test
- ✅ Migration runner (`scripts/setup_supabase.py` uses sorted glob)
- **Action:** Template ships with 001-035, template starts new migrations at 036+

### CI Adapter Abstraction (Conversation Intelligence)
- ✅ `scripts/call_source.py` - Abstract interface (CallSourceAdapter, NormalizedCall)
- ✅ `scripts/adapters/fireflies_adapter.py` - Fireflies implementation
- ✅ `scripts/adapters/gong_adapter.py` - Gong implementation
- ✅ `scripts/adapters/apollo_adapter.py` - Apollo implementation
- ✅ `scripts/call_source_factory.py` - Source-agnostic factory (priority-driven)
- ✅ `scripts/eval_call_adapters.py` - Interface compliance tests
- ✅ `scripts/etl_calls.py` - Source-agnostic ETL (no adapter_type checks)
- **Action:** Template includes all 3 adapters; client sets `call_sources.priority` in config

### Coaching Seed/Client Split
- ✅ `config/coaching_seed.yaml` - Universal coaching primitives (MEDDICC, blocker taxonomy)
- ✅ `config/coaching_client.yaml` - STRUCTURE travels (objection categories, stage questions)
- ✅ `scripts/coaching_config.py` - Single loader (merges seed + client)
- ✅ `scripts/eval_coaching_config.py` - Seed/client split validation tests
- ✅ `scripts/eval_coaching_config_migration.py` - Behavior-preservation tests
- ✅ `scripts/eval_coaching_config_proof_of_life.py` - Seed+client consumption tests
- ✅ `api/handlers.py` - query_pre_call_brief wired to load_coaching_config()
- **Action:** coaching_seed.yaml travels as-is; coaching_client.yaml → placeholder values

### Harness Boundary Tests
- ✅ Field semantics isolation (handlers never access data_dictionary)
- ✅ No raw stage IDs outside field_semantics
- ✅ No duplicate migration numbers
- ✅ Call adapter interface compliance
- ✅ Coaching config purity (seed has no client terms)
- **Action:** All eval_*.py tests travel with template

---

## Client-Level Artifacts (Must Be Blanked/Placeholdered)

These contain GrowthBook-specific values that must NOT travel to template.
Template ships with placeholder structure; template fills with their values.

### Coaching Client Config
- `config/coaching_client.yaml` contents:
  - `client_name: "GrowthBook"` → placeholder
  - `company.name`, `company.product`, `company.positioning` → blanked
  - `competitors` list → example placeholders (CompetitorA, CompetitorB)
  - `objection_categories` → example structure only
  - `stage_focus_questions` → example questions (actual questions are client IP)
  - `discovery_numbers` → generic slot names

### Field Semantics Values
- `config/field_semantics.yaml` stage_map:
  - GrowthBook's HubSpot stage IDs (appointmentscheduled, qualifiedtobuy, etc.) → blanked
  - Template ships with STRUCTURE + example/placeholder stage names
  - template runs `scripts/discover_stages.py` against their HubSpot to populate

### Operational Config
- `config/client.yaml` contents:
  - `organization.portal_id` → placeholder
  - `pipeline.sales_pipeline_id`, `pipeline.forecast_category_field` → blanked
  - `team.owners` list → empty array
  - `segmentation.rules` → example structure
  - Client-specific thresholds → defaults

### Persona Seeds
- `scripts/seed_user_personas.py` references to GrowthBook team members → blanked
- Template documents the STRUCTURE (SDR/AE/IC personas), not GrowthBook's actual team

---

## Deployment/Onboarding Updates Required

Add to template deployment docs (create `docs/DEPLOYMENT.md` if missing):

1. **After cloning the template:**
   ```bash
   ./scripts/install_hooks.sh
   ```
   This installs pre-commit hooks for secret protection (required).

2. **Discover client's HubSpot stages:**
   ```bash
   python scripts/discover_stages.py
   ```
   Populate `config/field_semantics.yaml` stage_map with client's actual stage IDs.

3. **Run client context interview:**
   Follow `skills/revops-client-context/SKILL.md` to populate:
   - `config/coaching_client.yaml` (competitors, objections, discovery numbers)
   - `config/client.yaml` (portal ID, pipeline IDs, team roster)

4. **Verify harness tests pass:**
   ```bash
   python scripts/eval_field_semantics.py
   python scripts/eval_coaching_config.py
   python scripts/eval_migrations.py
   python scripts/eval_call_adapters.py
   ```

---

## Port Execution Notes

- **Landed this session (2026-08-19):** All items marked ✅ above
- **Next session additions:** Add new template-level artifacts as they land
- **Port readiness gate:** All harness tests passing + client placeholders verified empty
- **template onboarding:** Follow deployment docs above after forking template
