# Token Budget Optimization Options

## Current Situation

**Problem:**
- Schema context increased from 1,288 → 5,535 tokens (+330%)
- 68.4% of total tokens across 3 iterations is schema context repetition
- 4-turn test exceeded budget: 24,289 / 20,000 tokens (121.4%)
- System prompt is 74.8% of each iteration (6,058 tokens)

## Option A: Pre-filter Schema to Relevant Tables

**How it works:**
Use cheap classification (keywords or Haiku) to identify which tables are relevant to the question, then only send those table schemas.

**Implementation:**
```python
def get_filtered_schema_context(sb, question: str):
    # Quick keyword match or Haiku classification
    relevant_tables = classify_relevant_tables(question)
    # Example: "deals with low champion scores" → ["deals", "analyses"]

    # Fetch only relevant rows
    rows = select_all(sb, "data_dictionary",
        columns="...",
        filters=[
            ("eq", "is_queryable", True),
            ("in", "supabase_table", relevant_tables)
        ])
    # Build context as before
```

**Token savings:**
- Average question uses 3-5 tables (not all 15)
- Example: 3 tables = ~2,000 tokens (vs 5,535)
- Savings: ~3,500 tokens/iteration = ~10,500 over 3 iterations

**Cost:**
- +1 Haiku call per question (~$0.0001) for classification
- OR keyword matching (free but less accurate)

**Risks:**
- May filter out tables needed for joins
- Requires maintaining table→topic mapping
- Classification errors could break queries

**Recommendation score:** 7/10
- High savings potential
- Moderate implementation complexity
- Some accuracy risk

---

## Option B: Truncate Descriptions in Loop Context

**How it works:**
Send abbreviated descriptions (e.g., first 30 chars) in loop, keep full text in data_dictionary table for reference.

**Implementation:**
```python
# In get_schema_context():
for c in cols:
    col, dtype = c["supabase_column"], c["data_type"]
    full_desc = c.get("description") or ""

    # Loop context: truncated
    if abbreviated:
        cdesc = full_desc[:30] + "..." if len(full_desc) > 30 else full_desc
    else:
        cdesc = full_desc[:80]  # Current behavior
```

**Token savings:**
- Average description: 80 chars → 30 chars (62% reduction)
- 202 columns × 50 char reduction = ~10,000 chars = ~2,500 tokens
- Savings: ~2,500 tokens/iteration = ~7,500 over 3 iterations

**Cost:**
- Negligible implementation cost
- No API calls

**Risks:**
- Loss of context could hurt query quality
- Model may need trial-and-error to find right columns
- Unclear descriptions → more iterations → more tokens

**Recommendation score:** 4/10
- Moderate savings
- Simple implementation
- High risk to quality (defeats purpose of backfill)

---

## Option C: Raise Token Budget

**How it works:**
Increase TOKEN_BUDGET from 20,000 to 30,000 or 40,000.

**Implementation:**
```python
TOKEN_BUDGET = 35000  # ~$0.35 at Sonnet pricing
```

**Token savings:**
- None (opposite — allows more usage)

**Cost:**
- Directly increases cost per complex question
- 20,000 → 35,000 = 75% cost increase for questions that hit budget
- Most questions don't hit budget, so impact is limited

**Benefits:**
- Allows more complex queries (multi-table joins, aggregations)
- Doesn't sacrifice quality
- No implementation complexity

**Risks:**
- Doesn't address root cause (schema repetition)
- Could encourage inefficient queries
- Runaway token usage on malformed questions

**Recommendation score:** 3/10
- Zero savings (increases cost)
- Treats symptom, not cause
- Should be last resort

---

## Option D: Progressive Schema Disclosure

**How it works:**
- Iteration 0: Send table/column names only (no descriptions)
- Iterations 1+: Send full descriptions ONLY for tables the model queried
- Model learns schema progressively as needed

**Implementation:**
```python
def get_progressive_schema_context(sb, iteration: int, queried_tables: set):
    rows = select_all(sb, "data_dictionary", ...)

    if iteration == 0:
        # Minimal context: table.column (type) only
        for c in cols:
            lines.append(f"  {c['supabase_column']} ({c['data_type']})")
    else:
        # Full descriptions for queried tables only
        for c in cols:
            if c['supabase_table'] in queried_tables:
                # Full description
                lines.append(f"  {c['supabase_column']} ({c['data_type']}): {c['description']}")
            else:
                # Minimal
                lines.append(f"  {c['supabase_column']} ({c['data_type']})")
```

**Token savings:**
- Iteration 0: ~1,500 tokens (table/column names only)
- Iteration 1+: ~2,500 tokens (2-3 tables with full descriptions)
- Average: ~2,000 tokens/iteration vs 5,535
- Savings: ~3,500 tokens/iteration = ~10,500 over 3 iterations

**Cost:**
- Must track which tables were queried
- More complex schema building logic
- Risk of confusion if model needs schema it didn't query yet

**Benefits:**
- Natural learning curve (model sees what it needs)
- Rewards efficient queries (fewer tables = less overhead)
- Maintains full description quality where needed

**Risks:**
- Model may struggle iteration 0 with minimal context
- Could increase iteration count (more guessing)
- Complexity in tracking queried tables across iterations

**Recommendation score:** 8/10
- High savings potential
- Moderate complexity
- Aligned with iterative learning model

---

## Hybrid Approach (Recommended)

**Combine Option A + D:**

1. **Iteration 0:** Pre-filter to 5-7 most relevant tables (Option A), send column names only (Option D)
   - Tokens: ~1,000 (vs 5,535)

2. **Iteration 1+:** Send full descriptions for tables that were:
   - Pre-filtered as relevant AND
   - Actually queried by the model
   - Tokens: ~2,000 (2-3 tables with full descriptions)

3. **Fallback:** If model requests a table not in initial filter, add it iteration 2+

**Expected savings:**
- Iteration 0: ~4,500 tokens
- Iteration 1-2: ~3,500 tokens each
- Total: ~11,500 tokens over 3 iterations (47% reduction)

**Implementation cost:**
- Medium (2-3 hours)
- Need table relevance classifier (can start with keywords)
- Track queried tables across iterations
- Modify get_schema_context() to accept parameters

**Benefits:**
- Best of both approaches
- Maintains quality (full descriptions when needed)
- Encourages efficient queries
- Stays well within 20K budget

**Risks:**
- More moving parts
- Classification errors need fallback

---

## Recommendation

**Implement Hybrid Approach (A + D) in phases:**

**Phase 1 (immediate):** Option D only
- Lower risk, simpler implementation
- Cuts tokens by 60% (~10,500 saved over 3 iterations)
- Fits within existing budget
- Can be done in 1-2 hours

**Phase 2 (if needed):** Add Option A
- Further optimization if Phase 1 insufficient
- Cuts another 20% (~2,000 tokens)
- 1-2 hours additional work

**DO NOT:**
- Option B (truncate descriptions) - defeats purpose of backfill
- Option C (raise budget) - treats symptom, not cause

**Success metrics:**
- 4-turn test completes within 20K budget (currently 121%)
- Query quality doesn't degrade (eval scores stay ≥ 0.8)
- No increase in iteration count (currently 3)

---

## Cost-Benefit Analysis

| Option | Token Savings | Implementation Cost | Quality Risk | Recommendation |
|--------|---------------|---------------------|--------------|----------------|
| A: Pre-filter tables | ~10,500 (63%) | 2-3 hours | Medium | ⭐⭐⭐⭐ |
| B: Truncate descriptions | ~7,500 (45%) | 1 hour | High | ⭐ |
| C: Raise budget | 0 (increases cost) | 5 minutes | None | ⭐ |
| D: Progressive disclosure | ~10,500 (63%) | 2 hours | Low | ⭐⭐⭐⭐⭐ |
| Hybrid (A+D) | ~11,500 (69%) | 3-4 hours | Low | ⭐⭐⭐⭐⭐ |

**Winner:** Option D (progressive disclosure)
- Highest savings with lowest risk
- Simplest to implement
- Can add Option A later if needed
