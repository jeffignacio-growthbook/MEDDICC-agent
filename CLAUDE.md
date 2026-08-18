# RevOps MEDDICC Agent — Claude Code Instructions

## What this repo is

Production nightly MEDDICC analysis agent. Analyzes sales calls
for active HubSpot deals, scores them on 7 MEDDICC components,
writes scores back to HubSpot, and self-improves via a PR-based
learning loop. Built for RevOps School at Pavilion.

---

## Auto-setup for fresh forks

When this project is opened in Claude Code, check immediately:
- Does config/client.yaml exist?
- Does config/context.yaml exist?

If either is missing, this is a fresh fork. Say proactively:

"I can see this is a new deployment — config files are missing.
I'll guide you through setup. Takes about 20 minutes. Ready?"

Then run setup in this order:

### Step 1: Credentials interview

Read skills/revops-agent-setup/SKILL.md and run that interview
inline. Collect every credential one at a time. Write the
results to .env in the repo root (it's gitignored). Print the
GitHub Secrets checklist at the end.

### Step 2: Context interview

Read skills/revops-client-context/SKILL.md and run that
interview inline. Ask about product, ICP, competitors,
objections, feature gaps, HubSpot stages, and learning
preferences. Write the four output files directly:
- config/client.yaml
- config/context.yaml
- prompts/CLAUDE.md  (overwrites existing)
- prompts/evaluator_rubric.md  (overwrites existing)

Also read and use these reference files during the interview:
- skills/revops-client-context/references/context-schema.md
- skills/revops-client-context/references/claude-md-template.md
- skills/revops-client-context/references/rubric-template.md
- skills/revops-client-context/references/client-yaml-template.md

### Step 3: Stage discovery

Run: python scripts/discover_stages.py

Show the output. Help the student identify which stage IDs
to add to excluded_stages in config/client.yaml.
Update the file with their choices.

### Step 4: Supabase setup

Run: python scripts/setup_supabase.py

If SUPABASE_URL is not yet set, remind them to add it to
.env first and export it.

### Step 5: Hand off

Tell the student:
"Add the GitHub Secrets from your .env file, then go to
Actions → MEDDICC Agent Nightly Run → Run workflow
to trigger the first run."

If config files already exist, skip setup and help with
whatever the student needs.

---

## Architecture

```
2am UTC: GitHub Actions (nightly.yml)
  → Load deals from memory/deals/index.json
  → For each deal:
      Load calls from memory/calls/<slug>.json (cache-first)
      → context_builder.py (Haiku) → cumulative MEDDICC state
      → meddicc_agent.py: Generator (Sonnet) → Evaluator (Haiku)
                          → Reflection gate (Haiku)
      → Write output/*.md
      → Write HubSpot deal properties (hubspot_deals.py)
      → Write Supabase analyses table (supabase_client.py)
      → Write memory/learnings/*.json if learning found
  → Self-improvement: learnings → synthesizer → PR to prompts/CLAUDE.md
```

---

## Key files

| File | Purpose |
|---|---|
| `scripts/run_nightly.py` | Main orchestration |
| `scripts/meddicc_agent.py` | Generator, evaluator, reflection |
| `scripts/context_builder.py` | Haiku cumulative state synthesis |
| `scripts/github_memory.py` | All file read/write operations |
| `scripts/hubspot_deals.py` | HubSpot API + MEDDICC write-back |
| `scripts/etl_deals.py` | CSV → memory/deals/index.json |
| `scripts/etl_calls.py` | CSVs → memory/calls/*.json cache |
| `scripts/supabase_client.py` | Parallel write to Supabase |
| `scripts/token_tracker.py` | Per-role cost tracking |
| `scripts/setup_supabase.py` | One-time DB migration runner |
| `scripts/discover_stages.py` | HubSpot stage ID discovery |
| `config/client.yaml` | Stage IDs, pipeline names, thresholds, team roster, reporting TZ, SDR tools |
| `config/context.yaml` | Competitors, objections, feature gaps |
| `prompts/CLAUDE.md` | Generator system prompt — per client |
| `prompts/evaluator_rubric.md` | Evaluation criteria |
| `prompts/voice.md` | Persona-aware voice rules documentation |
| **SDR Metrics** | |
| `scripts/sdr_utils.py` | Timezone and data utilities for SDR adapters |
| `scripts/etl_sdr_metrics.py` | SDR metrics ETL (Apollo, Salesloft, Aircall) |
| `scripts/adapters/apollo_dialer.py` | Apollo call metrics adapter |
| `scripts/adapters/salesloft_sequencer.py` | Salesloft email/call metrics adapter |
| `scripts/adapters/aircall_dialer.py` | Aircall call metrics adapter |
| `scripts/seed_user_personas.py` | Seed user personas from team roster |
| `scripts/migrations/012_add_sdr_metrics.sql` | SDR metrics tables (sdr_metrics, sdr_users) |
| `scripts/migrations/013_add_user_personas.sql` | User personas table |
| **CRO Slack Agent** | |
| `api/main.py` | FastAPI entry point, /slack/question, /slack/dm-intake |
| `api/router.py` | Intent classification, persona lookup, synthesis |
| `api/handlers.py` | Query handlers (pipeline, SDR metrics, win/loss, etc.) |
| `api/time_resolver.py` | Fiscal quarter calculation (reporting TZ aware) |
| `api/db.py` | Supabase client, thread context, entity cache |

---

## Models and roles

| Role | Model | Why |
|---|---|---|
| Generator | claude-sonnet-4-5-20250929 | Open-ended synthesis |
| Context builder | claude-haiku-4-5-20251001 | Structured extraction |
| Evaluator | claude-haiku-4-5-20251001 | Checklist scoring |
| Reflection gate | claude-haiku-4-5-20251001 | Binary classification |

---

## Common failure patterns

Counter not incrementing → script crashes before update,
check all API keys are set in GitHub Secrets.

Context builder runs but no generator → Guard 3 firing on
short summaries, check call cache has real content.

All deals skipped → cache miss or since_date guard firing,
check memory/calls/ has files.

Push rejected → concurrent commit, workflow needs
git pull --rebase before git push.

HubSpot scores all zero → score extraction regex not matching,
check _extract_scores_from_analysis() in hubspot_deals.py.

---

## What is built vs pending

### Built and running

**Nightly MEDDICC Agent:**
- [x] Generator/evaluator/reflection loop
- [x] Context builder with carry-forward rule
- [x] Call cache and deal index
- [x] Self-improvement loop
- [x] HubSpot 6-property write-back
- [x] Supabase parallel write
- [x] Token cost tracker
- [x] ETL for deals and calls

**CRO Slack Agent (api/ directory):**
- [x] Railway FastAPI service
- [x] Zapier integration
- [x] Pipeline query handlers (waterfall, at-risk, win/loss, etc.)
- [x] SDR metrics handlers (team/user activity tracking)
- [x] Persona-aware voice routing (executive/sales/operational/IC)
- [x] User persona registration via DM intake
- [x] Dynamic query tool for complex questions

**SDR Metrics Layer:**
- [x] Apollo dialer adapter (Analytics API + calls fallback)
- [x] Salesloft sequencer adapter (email + call metrics)
- [x] Aircall dialer adapter (outbound call metrics)
- [x] Timezone-aware ETL (scripts/etl_sdr_metrics.py)
- [x] Supabase tables (sdr_metrics, sdr_users)
- [x] Seed script for team roster personas

**Timezone Infrastructure:**
- [x] Reporting timezone configuration (config/client.yaml)
- [x] Timezone utilities (scripts/sdr_utils.py)
- [x] UTC → reporting TZ conversion for all ETLs
- [x] API date filter formatting (iso, iso_str, epoch)

### Pending features
- [ ] Objection vault extraction
- [ ] Daily brief email
- [ ] Multi-quarter trend analysis
- [ ] Automated coaching recommendations

---

## Style rules

Cache first, API second.
Haiku for classification, Sonnet for generation.
Every LLM call goes through tracker.record().
Fail gracefully — individual deal failures must not stop the run.
No_learning is the default from the reflection gate.
