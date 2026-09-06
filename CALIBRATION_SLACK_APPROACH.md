# Wave 4 Calibration - Slack-Based Approach

**Date**: 2026-09-06
**Status**: Redesigned for async webhook architecture

---

## Why the Original Approach Failed

**Architecture Mismatch**:
```
Original (BROKEN):
  Calibration Script → POST /slack/question → Wait for HTTP response → Nothing returned

Actual Production Flow:
  User asks in Slack → Zapier webhook → Railway API → Process → Webhook response → Zapier → Slack
```

**Result**: 100% unanswerable because responses go to Slack, not HTTP

---

## New Approach: Test Through Slack

**Mimics actual user flow**:
```
1. Script posts question to test Slack channel
2. Agent processes via production webhook flow
3. Agent responds in thread
4. Script polls thread for response
5. Compare response to verified value
```

**Benefits**:
- Tests actual production flow
- No API changes needed
- Validates real user experience
- Works with async webhook architecture

---

## Requirements

### GitHub Secrets

Add these to repo secrets:

1. **SLACK_BOT_TOKEN** (Required - NEW)
   - Create Slack app with `chat:write` and `channels:history` scopes
   - Install to workspace
   - Copy Bot User OAuth Token
   - Format: `xoxb-...`

2. **SUPABASE_URL** (Existing)
   - For fallback rate checking

3. **SUPABASE_SERVICE_KEY** (Existing)
   - For fallback rate checking

### GitHub Variables (Optional)

**CALIBRATION_CHANNEL** - Slack channel ID for posting test questions
- Default: `C07PZ7ZDH0N` (current test channel)
- Format: Channel ID (e.g., `C07PZ7ZDH0N`)
- Must invite bot to this channel

---

## Setup Steps

### 1. Create Slack Bot

If not already exists:

```bash
# Go to https://api.slack.com/apps
# Create New App → From Scratch
# Name: "Calibration Runner"
# Workspace: Your workspace

# Add Bot Token Scopes:
#   - chat:write
#   - channels:history
#   - channels:read

# Install to workspace
# Copy "Bot User OAuth Token" (starts with xoxb-)
```

### 2. Invite Bot to Test Channel

```
# In Slack test channel:
/invite @Calibration Runner
```

### 3. Add Secrets to GitHub

```bash
# Using GitHub CLI:
gh secret set SLACK_BOT_TOKEN

# Or via GitHub UI:
# Repo → Settings → Secrets and variables → Actions → New repository secret
```

### 4. Run Calibration

```bash
# Via GitHub Actions:
# Actions → Wave 4 Calibration Run → Run workflow

# Or locally (if secrets available):
export SLACK_BOT_TOKEN=xoxb-your-token
export SUPABASE_URL=your-supabase-url
export SUPABASE_SERVICE_KEY=your-key
export CALIBRATION_CHANNEL=C07PZ7ZDH0N

python scripts/run_calibration_via_slack.py
```

---

## How It Works

### Posting Questions

```python
# Script posts to Slack
result = slack_client.chat_postMessage(
    channel=test_channel,
    text="What is our pipeline this quarter?",
    username="Calibration Runner"
)
thread_ts = result['ts']  # Track thread
```

### Waiting for Response

```python
# Poll thread every 2 seconds for up to 30 seconds
while time < timeout:
    replies = slack_client.conversations_replies(
        channel=test_channel,
        ts=thread_ts
    )

    # Look for bot response
    for msg in replies:
        if msg.get('bot_id') or msg.username == 'Deal Intelligence':
            return msg['text']

    time.sleep(2)
```

### Comparing Responses

```python
# Extract values using regex
if shape == "rep_attainment":
    pct = re.findall(r'(\d+\.?\d*)\s*%', response_text)
    if abs(pct - verified_pct) <= 2.0:
        return 'correct'
```

---

## Expected Output

```
================================================================================
WAVE 4 — CALIBRATION RUN (via Slack)
================================================================================
Loaded 21 canonical questions
Test channel: C07PZ7ZDH0N
Bot: xoxb-12345...

⚠️  This will post 21 questions to Slack
⚠️  Agent responses will be collected and compared to verified values

[q003] Which deals have no ARR recorded?
      Shape: list_with_count
      Status: ✓ CORRECT

[q004] How is Christian tracking?
      Shape: rep_attainment
      Status: ✓ CORRECT

[q005] What is team attainment for Q3?
      Shape: team_attainment
      Status: ✗ WRONG (Expected: 12.7%, Got: 13.2%)

...

================================================================================
CALIBRATION SUMMARY
================================================================================

✓ CORRECT:        15 / 19 (78.9%)
✗ WRONG:           2 / 19 (10.5%)
? UNANSWERABLE:    2 / 19 (10.5%)

Fallback rate: 8/19 (42.1%)
  ⚠️  High fallback rate - semantic layer needs improvement

Full results saved to: outputs/calibration/calibration_slack_20260906_123045.json
```

---

## Timing Considerations

**Each question takes ~5-10 seconds**:
- 2s: Post to Slack
- 3-8s: Agent processing
- 1s: Fallback log check

**Total run time**: ~2-3 minutes for 20 questions

**Timeout per question**: 30 seconds
- If agent doesn't respond in 30s, marked unanswerable
- Check Slack manually to see if response eventually arrived

---

## Debugging

### If questions post but no responses

**Check**:
1. Bot invited to test channel? `/invite @Calibration Runner`
2. Agent webhook working? Test manually in Slack
3. Agent responding to other users? Check recent Slack history

### If "Failed to post" errors

**Check**:
1. `SLACK_BOT_TOKEN` correct format (starts with `xoxb-`)
2. Bot has `chat:write` scope
3. Channel ID correct (right-click channel → Copy link → extract ID)

### If responses marked "unanswerable"

**Check**:
1. Agent response format - does it include numbers/percentages?
2. Regex extraction logic - update `_extract_value_from_response()`
3. Verified values correct - check canonical_questions.yaml

### If fallback rate >40%

**Action needed**: Add fast-path handlers for high-fallback questions
- Check `outputs/calibration/*.json` for which questions used fallback
- Add dedicated handlers in `api/handlers.py`

---

## Cleanup After Calibration

**Test channel messages**:
```
# Archive test thread or clear channel
# Calibration posts 20+ messages with agent responses
```

**Fallback logs**:
```sql
-- Clear calibration entries from fallback_log if needed
DELETE FROM fallback_log
WHERE question IN (SELECT question FROM canonical_questions.yaml);
```

---

## Next Steps After Successful Calibration

### If accuracy >80%

1. **Wire Trigger 5** (metric_divergence):
   ```python
   # scripts/monitor_metric_divergence.py
   def compute_metric(metric_id: str) -> float:
       # Map to canonical question queries
       pass
   ```

2. **Enable monitoring**:
   ```yaml
   # config/monitoring.yaml
   metric_divergence:
     enabled: true
   ```

3. **Schedule daily runs**:
   ```yaml
   # .github/workflows/daily-calibration.yml
   schedule:
     - cron: '0 6 * * *'  # 6am daily
   ```

### If accuracy <80%

1. **Investigate "wrong" answers**:
   - Check if data changed since verification
   - Update verified values if legitimate
   - Fix handler logic if buggy

2. **Debug "unanswerable"**:
   - Add missing handlers
   - Improve response parsing
   - Increase timeout if agent slow

3. **Reduce fallback rate**:
   - Add fast-path handlers
   - Improve intent classification
   - Check semantic layer coverage

---

## Files Modified

1. **scripts/run_calibration_via_slack.py** (NEW)
   - Slack-based calibration runner
   - Posts questions, collects responses
   - Compares to verified values

2. **.github/workflows/run-calibration.yml** (UPDATED)
   - Uses SLACK_BOT_TOKEN secret
   - Runs new Slack-based script
   - Removed direct API call approach

3. **scripts/run_calibration.py** (DEPRECATED)
   - Original HTTP-based approach
   - Doesn't work with webhook architecture
   - Keep for reference only

---

## Status

**Wave 4 Progress**: 50% complete
- [x] Task 1: Update verified values
- [x] Task 2: Get verified values for pending questions
- [x] Task 3a: Create calibration infrastructure
- [ ] Task 3b: Run calibration successfully (pending SLACK_BOT_TOKEN)
- [ ] Task 4: Wire Trigger 5

**Blocker**: Need SLACK_BOT_TOKEN secret in GitHub
**Action**: Add secret, then run workflow
