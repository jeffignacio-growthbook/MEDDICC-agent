# V2 Semantic Layer — Full Scope

**Parts 1-3:** Complete and shipped (awaiting field testing)
**Parts 4-5:** Spec only (don't build until 1-3 validated)

---

## Part 4: Memory (Corrections Persist Beyond Threads)

### Problem

Today: User corrects the agent in a Slack thread. That correction lives in that thread and nowhere else. Next question makes the same mistake.

Example from Aug 30:
- User: "The value field was wrong for renewals"
- Agent: "You're right, it's renewal_revenue not arr_usd"
- Next day, different thread: agent uses arr_usd again

### Solution

When someone says the agent got something wrong:

1. **Classification** — Ask: is this general or specific to this question?
   - General: "Renewals always use renewal_revenue, not arr_usd"
   - Specific: "This deal's amount is wrong because it was merged"

2. **Proposal creation** — Write to proposal queue:
   ```json
   {
     "type": "correction",
     "scope": "general|specific",
     "domain": "retention|pipeline|deals|sdr",
     "statement": "Renewals use renewal_revenue field, not arr_usd",
     "evidence": {
       "thread_url": "https://...",
       "user": "Ryan",
       "timestamp": "2026-08-30T14:32:00Z",
       "context": "Asked about Q1 GRR, agent used arr_usd and got 100% vs verified 77%"
     },
     "proposed_action": "Update handlers_retention.py line 70 to use renewal_revenue",
     "status": "pending_review"
   }
   ```

3. **Human approval** — Agent proposes, human disposes
   - Proposal posted to #agent-proposals channel
   - User reviews: approve, reject, or modify
   - Nothing auto-applies

4. **Application** — On approval:
   - General corrections → update handler, config, or prompt
   - Specific corrections → note in deal metadata
   - Log to memory/corrections/ with before/after

### Implementation Notes

**Don't build until:**
- Parts 1-3 validated through field testing
- Clear where corrections should persist (handlers? config? prompts?)
- Approval workflow decided (Slack reactions? Web UI? CLI?)

**Files:**
- `api/memory.py` — proposal creation and queue management
- `scripts/apply_correction.py` — human-approved application
- `memory/corrections/` — log of applied corrections
- `memory/proposals/` — pending proposals

**Guard rails:**
- User must be in approved list (ops team, not everyone)
- Corrections to code require PR review
- Corrections to data go through validation
- All changes logged with who/when/why

---

## Part 5: Monitoring Loop (Nightly Unprompted Surfaces)

### Problem

Valuable signals sit in the database until someone asks. By the time they ask, it's too late.

Examples:
- Renewal with no amount recorded, close date is next week
- Deal committed for three weeks, close date hasn't moved
- MEDDICC score dropped from 8 to 3, no one noticed

### Solution

Nightly pass over substrate that posts to Slack unprompted when thresholds crossed.

### Monitor Types

**1. Renewals with no amount near close**

Threshold:
- `renewal_revenue IS NULL`
- `close_date` within 14 days
- Stage is open (not won/lost)

Evidence:
- Deal name, close date, owner
- Days until close
- Last activity date

Suppression:
- Fire once per deal per quarter
- Don't repeat if owner acknowledged

Output:
```
🔔 Renewal hygiene alert

*Acme Corp* renewal closes in 8 days — no amount recorded yet.
Owner: Jennifer
Last activity: 3 days ago (call with procurement)

This affects Q3 forecast accuracy.
```

**2. Committed deals with stale close dates**

Threshold:
- Stage = "Commit" or forecast_category = "Commit"
- `close_date` unchanged for 21+ days
- Close date is future (not past-due)

Evidence:
- Deal name, amount, close date
- Weeks in commit
- Last stage change date

Suppression:
- Fire once per deal per month
- Suppress if close date updated within 7 days

Output:
```
📅 Stale close date

*Bestseller* ($850K) has been committed for 3 weeks with close date Oct 15.
Owner: Scott

If the date moved, update the deal. If it's stuck, move it out of Commit.
```

**3. MEDDICC score material shifts**

Threshold:
- Score changed by 3+ points in single analysis
- Deal is open and > $50K
- Shift is negative (8→5, not 5→8)

Evidence:
- Deal name, owner, old/new scores
- Which components changed (M, E, D, D, I, C, C)
- Call that triggered the shift
- Specific quotes from call

Suppression:
- Fire once per deal per score shift
- Don't repeat unless score shifts again

Output:
```
⚠️  MEDDICC score dropped

*GrowthBook* score: 8 → 5 (Champion and Decision Criteria both dropped)

From Sep 3 call with Sarah:
- Champion: "Sarah said 'I'll try to get buy-in' (was: 'I'm driving this')"
- Decision Criteria: "Timeline shifted from Q3 to 'sometime next quarter'"

Owner: Jake H
Call recording: [link]
```

### Implementation Notes

**Don't build until:**
- Parts 1-3 validated
- Answers are trustworthy (otherwise monitoring loop surfaces garbage)
- Thresholds calibrated (too sensitive = noise, too loose = miss signals)

**Files:**
- `scripts/monitoring_loop.py` — nightly runner
- `config/monitors.yaml` — threshold and suppression config
- `api/monitors/` — one module per monitor type
- `memory/monitors/` — log of what fired when

**Each monitor needs:**
- Threshold (when to fire)
- Evidence bar (what to show)
- Suppression window (don't spam)
- Slack channel (where to post)
- Escape hatch (mute per deal/owner)

**Guard rails:**
- Dry run mode (log what would fire, don't post)
- Rate limit (max 5 posts per day initially)
- Disable switch (kill switch if it goes wrong)
- Feedback loop (track whether posts were useful)

---

## Sequencing

**Now (Aug 30):**
- Parts 1-3 shipped, awaiting field testing
- User runs dozen questions over next few days
- Bring back what reads wrong, gets blocked, or feels robotic

**Next (based on test results):**
- Fix what broke
- Decide what's next from observations, not from plan

**Later (after validation):**
- Part 4 (Memory) if corrections are happening regularly
- Part 5 (Monitoring) only when answers are trustworthy

**Don't build:**
- Memory until current changes validated
- Monitoring until answers can be trusted unprompted

---

## Why This Sequencing

**Parts 1-3 first:**
- Without plausibility checks, monitoring loop surfaces wrong numbers
- Without reconciliation explains, corrections have no reference
- Without handlers, memory has nowhere to persist

**Field testing before building more:**
- Four substantial changes shipped in one day
- None exercised beyond single test case
- More valuable to find what breaks than to add features
- User needs to read answers as Ryan would, not as author

**Memory and monitoring are force multipliers:**
- Only worth building if the base layer works
- Bad monitoring is worse than no monitoring (trains people to ignore)
- Corrections that persist garbage are worse than no memory

---

## Open Questions

**Memory:**
- Where do corrections persist? (handlers? config? prompts?)
- Who can propose? (ops team only? anyone?)
- How to approve? (Slack reactions? web UI?)
- What's the evidence bar for auto-apply? (never? high confidence?)

**Monitoring:**
- Which monitors first? (renewals? committed deals? scores?)
- What are the right thresholds? (14 days? 21 days?)
- Which channel? (#revenue-alerts? #cro-daily?)
- How to suppress noise? (per deal? per owner? global?)

**Answer these after field testing, not before.**
