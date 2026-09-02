# For Ryan — Three Questions

One conversation, three questions that matter for the semantic layer and forecast accuracy.

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

## Question 3: Is Scoping converting at 30% or 10%?

### The Finding

**Scoping stage** configured at 0.10 (10%), measures 0.338 (33.8%) pooled all-time.

That's a **3x understatement** — deals in Scoping are worth three times what the forecast model says.

```
Quarter      Won  Lost  Total   Rate
────────────────────────────────────
FY2026 Q3     2     4     6    33.3%
FY2026 Q4     3     6     9    33.3%
FY2027 Q1     8    13    21    38.1%
FY2027 Q2    12    22    34    35.3%  ← 48% of wins here
FY2027 Q3     0     4     4     0.0%  ← recent drop
────────────────────────────────────
TOTAL        25    49    74    33.8%

Variance: σ=0.158 (high), CV=0.563 (coefficient of variation)
```

### Why This Matters

**If Scoping really converts at 30%+**: Forecast is systematically understating deals in that stage. Mid-quarter attention should shift earlier (Scoping matters more than model says).

**If it's unstable**: The 33.8% pooled rate hides variance. Q2 FY2027 did the heavy lifting (12 of 25 wins), and most recent quarter is 0% (small n=4, but concerning).

**Current impact**: 8 deals in Scoping in FY2027 Q3 pipeline, $920K value
- At configured 0.10: $92K weighted
- At measured 0.338: $311K weighted
- Difference: **+$219K** if updated

### What We Need

**Your read**: Is Scoping conversion trending up, or was Q2 FY2027 an anomaly?

Possible explanations:
1. **Process change**: Scoping qualification got stricter → only strong deals advance → higher conversion
2. **Segment mix**: More Enterprise deals (convert higher) in recent quarters
3. **One strong quarter**: Q2 was 35.3% with 48% of wins; earlier quarters more like 33%; most recent 0%
4. **Small sample**: Only 74 deals total, 25 wins — rates swing several points per deal

### Recommendation

**Don't update yet** — variance too high (σ=0.158), sample too small (n=74), and recent quarter dropped to 0%.

But **worth monitoring**:
- If next 2-3 quarters stay around 30-35% → update to measured rate
- If it reverts to 15-20% → configured 10% was conservative but close enough
- If it stays volatile → bigger question about Scoping qualification consistency

**For now**: Note that deals in Scoping may be worth 3x model weight, watch mid-quarter pipeline composition.

---

## Why Bundle These?

All three are **semantic facts** — definitions that affect how the agent interprets and answers questions.

- "At risk" defines a deal state (which deals to flag)
- Deal size bias defines an adjustment (which average to use in forecasts)
- Scoping probability defines stage weighting (how much to value deals in that stage)

Getting all three right in one conversation sets the foundation for the semantic layer going forward.

---

## Files Updated (Post-Conversation)

After you provide answers:

1. **config/field_semantics.yaml** — Add `deal_states.at_risk` with your definition
2. **api/handlers.py** — Update `query_deals_at_risk()` to implement your criteria
3. **config/metrics.yaml** — Document deal size bias cause and whether to track monthly
4. **config/client.yaml** — Update Scoping stage_probability if you decide to (0.10 → measured rate)
5. If activity-based: **schema migration** to add `last_activity_date` to deals table
6. If slippage-based: **schema migration** to add `close_date_history` JSONB to track changes

---

## Timeline

- **Now**: Get your definitions
- **Next**: Implement in config (semantic facts)
- **Then**: Verify with test questions
- **Monitor**: Track if patterns hold over time (monthly snapshots)
