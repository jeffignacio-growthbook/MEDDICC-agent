# For Ryan — Two Questions

One conversation, two questions that matter for the semantic layer.

---

## Question 1: What does "at risk" mean to you?

### Why This Matters

**Evidence**: "At risk" is the #1 most-asked unanswered question (7x in Wave 1 analysis).

Users are asking:
- "Which of those are at risk?"
- "Show me at-risk deals"
- "How many deals are at risk this quarter?"

The agent has a handler (`query_deals_at_risk`) but no definition of what "at risk" means. Currently it uses **placeholder logic**: flags deals where any MEDDICC component required at the current stage is below threshold.

**This is the first user-facing definition in the semantic layer.** If it doesn't match what you mean by "at risk," every answer using it will be subtly wrong.

### What We Need

Your definition of "at risk" — what conditions make a deal risky?

**Candidate criteria** (common in sales ops):
- No champion identified?
- Overall MEDDICC score below X (what threshold)?
- No activity (calls/emails/meetings) in 30+ days?
- Stalled in current stage for X days?
- Close date slipped N times?
- Something else?

Can be one condition or a combination. Can be stage-specific (e.g., "at risk in Scoping means no champion; at risk in Review means no activity in 14 days").

**Your answer becomes config** in `field_semantics.yaml`, and the handler implements exactly that logic — no more, no less.

---

## Question 2: Why do larger deals lose?

### The Finding

Won deals are **21-22% smaller** than pipeline deals. This is systematic, not whale losses.

```
Pipeline deals (open, qualified):
  Mean:   $47,809
  Median: $30,000
  Count:  376 deals

Won deals (closed-won, qualified):
  Mean:   $37,662
  Median: $23,400
  Count:  222 deals

Bias:
  Mean:   -21.2%
  Median: -22.0%  ← systematic, not outliers
```

### Why This Matters

**Forecast impact**: Historical conversion was inflated by 40% before we caught this.
- Was using pipeline avg ($62,371) → $4M forecast ❌
- Now using won-deal avg ($37,662) → $2M forecast ✓

The $2M forecast converges with stage-weighted ($1.9M) and rep calls ($1.899M) — three independent methods agreeing within $200K. That's the forecast in front of you now.

### What's Causing It?

Possible explanations:
1. **Sandbagging**: Reps inflate deal sizes early in discovery, adjust down at close
2. **Discovery bias**: Larger deals get more scrutiny; smaller deals qualify and close faster
3. **Expansion confusion**: "Deal size" field includes future expansion that doesn't actually close
4. **Pricing pressure**: Larger deals negotiate harder, final contract smaller than initial quote
5. **Over-qualification**: We're qualifying $50K+ deals too aggressively (should we raise the bar?)

### What We Need

**Your hypothesis**: Which of these (or something else) is driving the 22% bias?

**Possible actions** (depends on your answer):
- If sandbagging → coach reps on realistic sizing
- If expansion confusion → clarify what goes in deal_value field (TCV vs ARR vs committed-only)
- If over-qualification → tighten qualification criteria for large deals
- If pricing pressure → expected (document as normal pattern)

We can track this monthly to see if it's stable or changing:
```sql
SELECT month, won_avg, pipeline_avg, bias_pct
FROM deal_size_bias_monthly
ORDER BY month DESC LIMIT 12;
```

---

## Why Bundle These?

Both are **semantic facts** — definitions that affect how the agent interprets and answers questions.

"At risk" defines a deal state (which deals to flag).
Deal size bias defines an adjustment (which average to use in forecasts).

Getting both right in one conversation sets the foundation for the semantic layer going forward.

---

## Files Updated (Post-Conversation)

After you provide answers:

1. **config/field_semantics.yaml** — Add `deal_states.at_risk` with your definition
2. **api/handlers.py** — Update `query_deals_at_risk()` to implement your criteria
3. **config/metrics.yaml** — Document deal size bias cause and whether to track monthly
4. If activity-based: **schema migration** to add `last_activity_date` to deals table
5. If slippage-based: **schema migration** to add `close_date_history` JSONB to track changes

---

## Timeline

- **Now**: Get your definitions
- **Next**: Implement in config (semantic facts)
- **Then**: Verify with test questions
- **Monitor**: Track if patterns hold over time (monthly snapshots)
