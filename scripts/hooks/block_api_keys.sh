#!/bin/bash
# Block commits containing API key patterns
# Called by pre-commit framework (see .pre-commit-config.yaml)

# Check for Anthropic API keys (sk-ant-...)
# Check for HubSpot tokens (pat-na1-..., pat-eu1-...)
# Check for generic long hex strings (32+ chars, likely secrets)

if git diff --cached | grep -nE "sk-ant-|pat-na1|pat-eu1|[a-f0-9]{32,}" >/dev/null; then
  echo "❌ BLOCKED: Staged changes contain what looks like an API key or secret."
  echo ""
  echo "Detected patterns:"
  git diff --cached | grep -nE "sk-ant-|pat-na1|pat-eu1|[a-f0-9]{32,}" | head -5
  echo ""
  echo "Fix: Move credentials to environment variables (.env) before committing."
  echo "Never commit API keys, access tokens, or other secrets to version control."
  exit 1
fi
