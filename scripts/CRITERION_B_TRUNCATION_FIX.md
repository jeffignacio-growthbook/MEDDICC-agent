# Criterion B Transcript Truncation Fix

## Problem Identified (2026-09-19)

Initial implementation used `transcript[:8000]` - a **prefix truncation** that:
- Kept only first 8,000 chars of transcript
- **Dropped 74.5% of average transcript** (23,404 of 31,404 chars)
- Silently cut everything after char 8000

## Critical Risk

**What got cut:**
- ❌ Late-call champion elicitation: "Would you introduce me to the EB?"
- ❌ Commitment questions: "What materials help you present internally?"
- ❌ Decision process questions asked after rapport established
- ❌ Next steps / closing questions (always at end)

**Impact on Criterion B:**
- Champion genuine_champion signals (THE key behavior check) often happen mid-to-late call
- Discovery questions don't always come at start - reps build rapport first
- Same pattern as synthesis truncation bug - arbitrary cutoff drops relevant data

## Fix Applied

**New limit: 100,000 chars**

### Why This is Safe

**Haiku's Capacity:**
- Input context window: **200,000 tokens = ~800,000 chars**
- New 100k limit uses only **12.5% of capacity**
- Leaves 87.5% for prompt + response (plenty of headroom)

**Coverage:**
- Average transcript: 31,404 chars → **100% captured**
- Long transcripts (p95 ~60k chars) → **100% captured**
- No smart excerpting needed - just use full transcript

**Verification:**
- All Criterion B tests pass with 100k limit ✅
- No risk of cutting champion signals or late-call questions ✅
- Still well within Haiku's capacity ✅

## Lesson

**Always check truncation patterns against:**
1. Real data distributions (avg, p95, p99)
2. Model's actual capacity (not assumed limits)
3. WHAT gets cut (beginning/end/middle)
4. WHETHER cut content matters for the specific use case

For Criterion B, late-call content matters critically - champion elicitation and commitment questions happen after rapport building, not at call start.
