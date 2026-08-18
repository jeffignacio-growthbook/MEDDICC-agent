# RevOps MEDDICC Agent

Nightly AI-powered deal qualification for your HubSpot pipeline.
Analyzes sales calls, scores every active deal on MEDDICC,
writes scores back to HubSpot, and gets smarter over time.

---

## Setup — three steps

### Step 1 · Credentials

Open this repo in Claude Code. If this is a fresh fork,
Claude Code will detect the missing config files and guide
you through setup automatically.

Just open the project and say: **"set up this repo"**

Claude Code will:
- Walk through every credential and API key
- Write config/client.yaml and config/context.yaml
- Discover your HubSpot stage IDs
- Set up Supabase
- Verify everything before the first run

### Step 2 · Add GitHub Secrets

After Claude Code generates your .env file, add the
values as GitHub Secrets:

**repo → Settings → Environments → Agent → Add Secret**

Or with the GitHub CLI:
```bash
gh secret set --env Agent --env-file .env
```

### Step 3 · First run

Go to: **Actions → MEDDICC Agent Nightly Run → Run workflow**

Watch the logs. First run analyzes your full active pipeline.
After that the agent runs every night at 2am UTC automatically.

---

## Call intelligence platforms

The agent supports two call recording platforms:

**Fireflies** (default) — Fireflies.ai call transcripts
- Most common for SMB/mid-market
- Simple API key authentication
- Set `call_tools.primary: "fireflies"` in config/client.yaml

**Gong** — Gong.io enterprise call intelligence
- Enterprise standard for larger sales teams
- Provides richer structured data (topics, action items, talk time)
- Requires Access Key + Access Key Secret
- Set `call_tools.primary: "gong"` in config/client.yaml

Claude Code will automatically detect your choice during setup
and collect the right credentials.

---

## What runs nightly

```
2am UTC: GitHub Actions fires
  → Load active deals from deal index
  → For each deal: load call cache → context builder (Haiku)
  → Generator (Sonnet) → Evaluator (Haiku) → Reflection gate
  → Write analysis to GitHub output/
  → Write 6 MEDDICC scores to HubSpot deal properties
  → Write analysis to Supabase for query layer
  → Update CLAUDE.md via PR if new patterns emerge
```

---

## Files to know

| File | What it does |
|---|---|
| `scripts/run_nightly.py` | Main orchestration — runs every night |
| `scripts/meddicc_agent.py` | Generator + evaluator + reflection loop |
| `scripts/etl_calls.py` | Builds call cache from CSV exports |
| `scripts/etl_deals.py` | Builds deal index from HubSpot |
| `prompts/CLAUDE.md` | Generator instructions — edit to calibrate |
| `prompts/evaluator_rubric.md` | Evaluation criteria — auto-improves |
| `config/client.yaml` | Your HubSpot stage IDs and thresholds |
| `config/context.yaml` | Your competitors, objections, feature gaps |
| `memory/calls/` | Call cache — 1 JSON per company |
| `memory/learnings/` | What the agent is learning |
| `output/` | MEDDICC analysis files |

---

## CRO Slack Agent (optional)

Query your pipeline data via Slack using natural language.

**Deployment:** Railway FastAPI service + Zapier integration
**Location:** `api/` directory

### Features

- **Pipeline snapshots:** "show me pipeline", "what deals are at risk"
- **Win/loss analysis:** "why did we lose Acme?", "Q2 win rate"
- **Deal deep-dives:** "tell me about the Acme deal"
- **Competitive intel:** "which deals mentioned LaunchDarkly?"
- **SDR metrics:** "team call metrics this week", "Sarah's connect rate"
- **Persona-aware responses:** Adapts voice for executive/sales/operational/IC users

### Setup

1. Deploy `api/` to Railway
2. Set up Zapier triggers:
   - Zap 1: Slack message → POST /slack/question
   - Zap 2: Catch hook → Slack reply
3. Seed user personas: `python scripts/seed_user_personas.py`
4. Query from Slack: "@agent show me pipeline"

See `api/router.py` for all available handlers.

---

## SDR Metrics (optional)

Track SDR activity across Apollo, Salesloft, and Aircall.

**Enables:** Call/email metrics, connect/reply rates, persona-aware coaching

### Setup

1. Add SDR tool credentials to GitHub Secrets:
   - `APOLLO_API_KEY` (for dialer metrics)
   - `SALESLOFT_API_KEY` (for sequencer metrics)
   - `AIRCALL_API_ID` + `AIRCALL_API_TOKEN` (for dialer metrics)

2. Enable tools in `config/client.yaml`:
```yaml
sdr_tools:
  apollo:
    enabled: true
  salesloft:
    enabled: true
  aircall:
    enabled: false
```

3. Run migration: `python scripts/setup_supabase.py` (runs migration 012)

4. Run ETL: `python scripts/etl_sdr_metrics.py --since 7d`

5. Query from Slack: "@agent team call metrics this week"

### What gets tracked

- **Calls:** made, connected, connect rate, voicemails, no answers
- **Emails** (Salesloft): sent, opened, replied, open/reply rates
- **By user:** Individual and team rollups
- **Timezone-aware:** All dates in your reporting timezone

---

## Timezone-Aware Reporting

All metrics use your configured reporting timezone, not server UTC.

**Why this matters:** A call at 11 PM UTC on March 31 is:
- March 31 in Eastern time (7 PM ET)
- April 1 in India time (4:30 AM IST)

Without timezone awareness, Q1 vs Q2 attribution breaks.

### Configuration

Set in `config/client.yaml`:
```yaml
reporting:
  timezone: "America/New_York"  # IANA timezone name
```

**Supported timezones:** Any valid IANA name (America/New_York, America/Los_Angeles, Europe/London, Asia/Kolkata, etc.)

### What uses reporting timezone

- `scripts/etl_calls.py` — Call date attribution
- `scripts/etl_deals.py` — Deal snapshot dates
- `scripts/etl_sdr_metrics.py` — SDR activity dates
- `api/handlers.py` — Pipeline queries ("this week", "this quarter")
- `api/time_resolver.py` — "today" calculations

---

## Costs

| Scenario | Cost |
|---|---|
| First full pipeline run | ~$3-5 |
| Nightly steady state | ~$0.10-0.30 |
| Monthly total | ~$10-15 |

---

## Skills for Claude.ai

Once the agent is running, install these skills in Claude.ai
for on-demand analysis:

- `skills/revops-agent-setup.skill` — credential setup wizard
- `skills/revops-client-context.skill` — client context onboarding

Open each file in Claude.ai and click Save skill.
