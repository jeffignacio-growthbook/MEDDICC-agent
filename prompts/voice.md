# Voice Layer — CRO Slack Agent

## Overview

The agent adapts its communication style based on the user's persona, registered via DM intake or seeded from the team roster.

## Persona Types

| Persona | Who | Voice Characteristics |
|---------|-----|----------------------|
| **executive** | CEO, CRO, CTO, VPs | Headline → judgment. Risk callouts. Bottom line first. |
| **sales_leadership** | Directors, Managers | Current → gap → risk → coaching insight. |
| **operational** | RevOps, Analysts | Metric → breakdown → methodology. Data quality flags. |
| **ic** | AEs, SDRs, BDRs | Direct answer. Specific deals/names. Actionable next steps. |
| **other** | Unknown/default | Standard professional voice. |

## Detail Levels

| Level | Length | When to Use |
|-------|--------|-------------|
| **brief** | 2-3 lines | Quick check-ins. Status updates. Single metric questions. |
| **standard** | 4-6 lines | Most questions. Default for first-time users. |
| **detailed** | 7+ lines | Deep dives. Complex questions. Full context needed. |

## Voice Rules by Persona

### Executive Voice

**Principles:**
- Lead with the number that matters most
- Call out risk explicitly (never bury it in a list)
- Close with one sentence of judgment
- Scannable in 15 seconds

**Brief (2-3 lines):**
```
📊 $14.4M pipeline across 144 deals.

⚠️ 12 deals missing ARR — get these updated before they skew the forecast.
```

**Standard (4-6 lines):**
```
📊 *Current Pipeline — $14.4M across 144 deals*

*By Stage:* Discovery $2.0M | Scoping $3.5M | Technical Eval $5.0M | Negotiating $2.9M

⚠️ *Needs Attention:* 12 deals missing ARR (incl. Company A, Company B); 8 deals flagged at-risk.

Bottom line: pipeline is healthy in volume but ARR hygiene is lagging.
```

**Detailed (7+ lines):**
- Full stage breakdown with deal counts
- Specific at-risk deals by name + owner
- MEDDICC scores when available
- Trend vs last period

### Sales Leadership Voice

**Principles:**
- Show the gap to target
- Name specific deals and reps
- End with coaching-oriented insight

**Brief (2-3 lines):**
```
$14.4M pipeline, $2.1M short of $16.5M target (87% coverage).

At-risk: Acme Corp (Sara), TechCo (Nate) — both weak on champion.
```

**Standard (4-6 lines):**
```
*Pipeline: $14.4M | Target: $16.5M | Gap: -$2.1M (87% coverage)*

*At Risk (weak MEDDICC):*
• Acme Corp — $500K | Sara | Champion 3/10
• TechCo — $350K | Nate | Economic Buyer 2/10

Coaching focus: Both reps need multi-threading — single contact risk.
```

**Detailed (7+ lines):**
- Breakdown by rep with quota attainment
- Stage velocity and conversion rates
- MEDDICC component scores per deal
- Specific next steps per at-risk deal

### Operational Voice

**Principles:**
- Show the methodology
- Flag data quality issues
- Include comparisons (vs target, vs last period)

**Brief (2-3 lines):**
```
Total ARR: $2.4M (target: $2.8M, 86% attainment).

Data gap: 12 deals missing ARR values.
```

**Standard (4-6 lines):**
```
*ARR Metrics*
- Total: $2.4M (86% of $2.8M target)
- By Segment: Enterprise $1.2M | Mid-Market $800K | SMB $400K

*Data Quality:* 12 deals missing ARR (8% of pipeline). Breakdown: 5 in Discovery, 7 in Scoping.

Trend: -3% vs last quarter (Q1: $2.47M).
```

**Detailed (7+ lines):**
- Full calculations shown
- Data lineage ("ARR calculated as...")
- Missing data by stage/owner
- Historical comparison table

### IC Voice

**Principles:**
- Direct answer, no fluff
- Specific deals/companies by name
- Focus on actionable info (close dates, next steps, scores)

**Brief (2-3 lines):**
```
Your deals: Acme Corp ($500K, closes 2026-08-30), TechCo ($350K, closes 2026-09-15).

Champion gap on Acme — multi-thread this week.
```

**Standard (4-6 lines):**
```
*Your Pipeline — 2 deals, $850K*

• *Acme Corp* — $500K | Negotiating | 2026-08-30 | Champion 3/10
• *TechCo* — $350K | Technical Eval | 2026-09-15 | Economic Buyer 2/10

Next: Schedule exec intro at Acme (champion risk); confirm budget authority at TechCo.
```

**Detailed (7+ lines):**
- Full MEDDICC scorecard per deal
- Call highlights from recent conversations
- Stage progression timeline
- Detailed next steps with deadlines

## SDR Metrics Voice

When answering SDR activity questions, adapt voice but maintain these patterns:

**For team metrics:**
```
📞 *Team Activity This Week*

Calls: 450 (connects: 68, 15% rate) | Emails: 320 (replies: 24, 7.5% rate)

*By Tool:*
• Apollo — 280 calls, 18% connect rate
• Salesloft — 320 emails, 7.5% reply rate

Top performers: Sarah (85 calls, 20% connects), Mike (110 emails, 12% replies)
```

**For individual user metrics:**
```
📊 *Your Activity — Last 7 Days*

Calls: 85 | Connects: 17 (20% rate) | Voicemails: 28
Emails: 45 | Opens: 18 | Replies: 5 (11% rate)

Trend: connect rate up 5pp vs prior week. Reply rate holding steady.
```

## Context Preference

**wants_metrics_context = true** (default):
```
Pipeline is $14.4M — healthy volume but 12 deals need ARR updates before they skew the forecast.
```

**wants_metrics_context = false**:
```
Pipeline: $14.4M across 144 deals.
12 deals missing ARR.
```

## Formatting Rules (All Personas)

- **No markdown tables** — use bullet lists
- **Bold with single asterisks:** `*bold*` not `**bold**`
- **Deal format:** `• *Company* — $Value | Stage | Close | Score`
- **Emojis sparingly:** 📊 for metrics, ⚠️ for risks, ✓ for success
- **Never invent numbers** — only use data from tool results
- **Dollar formatting:** $2.4M not $2,400,000

## Registration Flow

Users register via DM to the bot:

```
User: "Register me as executive with brief updates"
Bot: ✓ Registered you as executive (detail: brief, context: on)
```

Admins can seed from team roster:
```bash
python scripts/seed_user_personas.py
```

## Voice Adaptation Logic

1. Route question → lookup persona (user_personas table)
2. If not found → default to operational/standard
3. Build voice instructions based on persona + detail_level
4. Prepend to SYNTHESIS_SYSTEM_PROMPT
5. Sonnet generates answer with adapted voice
6. Haiku verifies numbers haven't been invented

## Examples by Question Type

### Pipeline Question

**Executive (brief):**
> $14.4M pipeline. 12 deals need ARR — fix before forecast.

**Sales Leadership (standard):**
> $14.4M pipeline ($2.1M short of target). At-risk: Acme (Sara), TechCo (Nate) — both weak champion. Focus on multi-threading.

**Operational (detailed):**
> Pipeline: $14.4M (86% of $16.5M target). Breakdown: Discovery $2.0M (20 deals), Scoping $3.5M (30 deals), Tech Eval $5.0M (40 deals), Negotiating $2.9M (25 deals). Data gap: 12 deals missing ARR (8% of total). Stage distribution matches historical norm (Q1: 21%, 31%, 38%, 10%).

**IC:**
> Your pipeline: Acme ($500K, closes Aug 30), TechCo ($350K, closes Sep 15). Champion gap on Acme — schedule exec intro.

### Win/Loss Question

**Executive:**
> Q2 win rate: 32% (8 won / 25 closed). Lost to pricing (40%), timing (30%), build vs buy (20%). Action: tighten economic buyer qual.

**Sales Leadership:**
> Q2 closed: 8 wins, 17 losses (32% win rate). Top loss reason: pricing (7 deals). Pattern: losing at Negotiating stage when no exec sponsor. Coaching: qualify budget + authority earlier.

**Operational:**
> Win/loss analysis Q2 2026: 25 deals closed (8W/17L, 32% win rate vs 35% target). Loss breakdown: pricing 40% (7 deals), timing 30% (5 deals), build-vs-buy 20% (4 deals), other 10% (1 deal). Stage conversion: Discovery→Scoping 65%, Scoping→Tech 55%, Tech→Neg 70%, Neg→Won 45%. Pricing losses concentrated in mid-market segment (5 of 7).

**IC:**
> Recent losses: Acme (pricing), TechCo (timing), StartupX (build vs buy). Common thread: no exec sponsor at Negotiating. Multi-thread earlier.

## Voice File Location

This file documents voice rules for reference. The actual voice implementation is in:

- **api/router.py** — `build_persona_voice_instructions()`
- **scripts/seed_user_personas.py** — persona inference rules
- **api/main.py** — `/slack/dm-intake` endpoint for registration
