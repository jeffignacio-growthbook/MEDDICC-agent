---
name: revops-agent-setup
description: >
  Collect all credentials and API keys needed to deploy the RevOps
  MEDDICC agent. Use this skill when setting up a new client deployment,
  when credentials need to be rotated, or when someone asks how to
  configure the agent environment. Walks through each credential one at
  a time, explains where to find it, validates the format, and outputs
  a ready-to-paste .env file for Railway and a GitHub Secrets checklist.
  Triggers on: set up the agent, configure environment, I need credentials,
  where do I get my API keys, Railway setup, GitHub Secrets setup.
---

# RevOps Agent Environment Setup

Walk through each credential in sequence. Explain where to find each one
before asking. Validate format before proceeding. At the end, output two
artifacts: the Railway .env file and the GitHub Secrets checklist.

Never ask for multiple credentials at once. One at a time keeps errors
out and makes it easy to pause and come back.

## Step 1 — Anthropic API Key

Tell the user:
"First we need your Anthropic API key. This is what powers Claude.
To get it: platform.anthropic.com → API Keys → Create Key
Format: starts with sk-ant-"

Ask: "Paste your Anthropic API key:"
Validate: must start with sk-ant-

## Step 2 — Call intelligence platform credentials

First check config/client.yaml for the call_tools.primary setting.
If it's 'gong', collect Gong credentials. Otherwise, collect Fireflies.

### If using Gong (call_tools.primary = 'gong'):

Tell the user:
"You're configured to use Gong for call intelligence.
To get your credentials:
1. Go to: Gong → Settings → Company Settings → API
2. Create a new Technical User or use existing
3. You'll need: Access Key and Access Key Secret

Gong API docs: https://gong.app.gong.io/settings/api/documentation"

Ask: "Paste your Gong Access Key:"
Store as: GONG_ACCESS_KEY

Ask: "Paste your Gong Access Key Secret:"
Store as: GONG_ACCESS_KEY_SECRET

### If using Fireflies (call_tools.primary = 'fireflies' or not set):

Tell the user:
"You're configured to use Fireflies for call intelligence.
To get it: app.fireflies.ai → Integrations → API → copy the key"

Ask: "Paste your Fireflies API key (or SKIP):"
Store as: FIREFLIES_API_KEY

## Step 3 — Apollo API Keys

Tell the user:
"Apollo is used for TWO things in this setup:
1. Apollo Conversation Intelligence (meeting recorder) — for call transcripts
2. Apollo.io (sales intelligence tool) — for SDR call/email metrics

If you use Apollo for BOTH, you can use the same key.
If you only use Apollo for meetings, skip the SDR step later.

To get your Apollo API key:
- Apollo Conversation Intelligence: workspace → Settings → API
- Apollo.io sales intelligence: app.apollo.io → Settings → API

Ask: "Paste your Apollo API key (or SKIP):"
Store as: APOLLO_API_KEY

## Step 4 — HubSpot Private App Token

Tell the user:
"HubSpot is your CRM. The agent reads active deals and writes
MEDDICC scores back as deal properties.

To get it:
1. HubSpot → Settings → Integrations → Private Apps
2. Required scopes: crm.objects.deals.read, crm.objects.deals.write,
   crm.objects.contacts.read, crm.objects.companies.read,
   timeline, timeline.read, timeline.write
3. Copy the access token (starts with pat-na1-)

Important: rotate this token if it was ever in a public repo."

Ask: "Paste your HubSpot private app token:"
Validate: should start with pat-

## Step 5 — Supabase credentials

Tell the user:
"Supabase is the query database for the Slack agent.
Go to: Supabase dashboard → your project → Settings → API
You need two things: Project URL and service_role key (not anon)."

Ask: "Paste your Supabase Project URL:"
Validate: must start with https:// and end with .supabase.co

Ask: "Paste your Supabase service_role key:"
Validate: starts with eyJ

## Step 6 — SDR tools credentials (optional)

Tell the user:
"These are for SDR activity metrics (calls, emails, connects).
Skip any tools you don't use.

### Salesloft (skip if not used)

To get it: Salesloft → Settings → API
You need a Bearer token with access to calls and activities."

Ask: "Paste your Salesloft API key (or SKIP):"
Store as: SALESLOFT_API_KEY

### Aircall (skip if not used)

Tell the user:
"To get your Aircall credentials:
1. Aircall Dashboard → Integrations → API Keys
2. You need: API ID and API Token (both required)"

Ask: "Paste your Aircall API ID (or SKIP):"
Store as: AIRCALL_API_ID

If they provided an API ID, ask:
"Paste your Aircall API Token:"
Store as: AIRCALL_API_TOKEN

## Step 7 — GitHub repository

Ask: "Enter your GitHub repo (owner/repo-name):"
Example: acme/AI_for_revops_lecture_6

## Step 8 — Zapier catch hook URL

Tell the user:
"This is the Zap 2 catch hook URL — skip if not set up yet."

Ask: "Paste your Zapier catch hook URL (or SKIP):"

## Step 9 — Generate outputs

Write a .env file to the repo root with all collected values.

Then print the GitHub Secrets checklist:

GitHub Secrets — Environment: Agent

Core credentials:
□ ANTHROPIC_API_KEY
□ HUBSPOT_API_KEY
□ SUPABASE_URL
□ SUPABASE_SERVICE_KEY

Call intelligence (choose one):
□ FIREFLIES_API_KEY         (blank if using Gong)
□ GONG_ACCESS_KEY           (blank if using Fireflies)
□ GONG_ACCESS_KEY_SECRET    (blank if using Fireflies)

SDR tools (optional, blank if not used):
□ APOLLO_API_KEY            (for dialer metrics + call recordings)
□ SALESLOFT_API_KEY         (for sequencer metrics)
□ AIRCALL_API_ID            (for dialer metrics)
□ AIRCALL_API_TOKEN         (for dialer metrics)

Zapier integration:
□ ZAP_RESPONSE_URL          (blank if not set up yet)
□ SLACK_RELAY_SECRET        (blank if not set up yet)

Fastest way to add them:
  gh secret set --env Agent --env-file .env

Note: GITHUB_TOKEN and GITHUB_REPO are automatic — do not add them.

Tell the user: "Credentials done. Now run the context onboarding:
say 'start client onboarding'"
