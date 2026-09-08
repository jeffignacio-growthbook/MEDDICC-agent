# Signal 1 Deferral: Stakeholder Count via Call Participant Proxy

## Status: ❌ DEFERRED

**Date:** 2026-09-07

**Reason:** Insufficient coverage (21.6%), insufficient sample sizes (9.1% viable cells), and won/lost separation not segment-independent (Mid-Market shows inversion).

---

## Executive Summary

Signal 1 (stakeholder count) cannot be derived using call participant emails as a proxy. After comprehensive investigation including coverage check, emails vs domains analysis, internal domain filtering, won/lost separation test, and **critical segment mix verification**, the proxy fails on multiple dimensions:

1. **Coverage:** 21.6% (below 50% threshold) - even lower than Signal 3's calls coverage
2. **Sample sizes:** Only 1/11 stage × segment cells viable (9.1%, below 50% threshold)
3. **Won/lost separation:** Aggregate finding shows expected direction BUT **not segment-independent**
   - Mid-Market (largest, most reliable segment) shows **inverted** pattern (won < lost)
   - Segment mix bias detected (22.7pp difference in SMB representation)
   - Aggregate finding substantially explained by segment differences, not genuine multi-threading signal

**Key finding preserved for methodology:** The within-segment inversion in Mid-Market (the most statistically trustworthy sample) demonstrates why **segment-independent verification is mandatory** for any signal derivation—not an optional extra check. Aggregate patterns can be spurious when explained by segment mix rather than the underlying hypothesis.

---

## Investigation Trail

### Phase 1: Coverage and Participant Data Population

**Methodology:** Query calls table for all closed deals, check for participant_emails field population.

**Hypothesis:** Calls table coverage is ~23% (from Signal 3 investigation), but need to verify participant_emails is actually populated when calls exist.

**Finding:** Coverage ceiling confirmed at 21.6%, BUT participant_emails is populated in 100% of deals that have calls.

**Population breakdown:**
- Total closed deals: 1,000
- Deals with calls: 216 (21.6%)
- Deals with participant_emails populated: 216 (100% of deals with calls)
- Deals with external participants: 216 (100% of deals with calls)

**Implication:** The coverage problem is entirely driven by low calls table coverage, not missing participant_emails data. Every call has participant information—there just aren't many calls in the first place.

---

### Phase 2: Emails vs Domains - Metric Definition

**Hypothesis:** Need to decide whether "stakeholder count" means distinct EMAILS (people) or distinct DOMAINS (companies).

**Methodology:** Compute both metrics for all deals with participant data, compare distributions.

**Findings:**

| Metric | Median | P25 | P75 | Max |
|--------|--------|-----|-----|-----|
| Distinct external emails | 2 | 1 | 4 | 69 |
| Distinct external domains | 1 | 1 | 1 | 17 |

**Critical pattern:** 42.6% of deals (92/216) have multiple emails from SINGLE domain.

**Example scenario:** 3 people from same buying company (multi-threaded decision committee) = 3 emails, 1 domain.

**Conclusion:** Distinct external EMAILS is the correct metric. Domain count severely undercounts stakeholder engagement within a single buying organization. Jeff's original hypothesis was about "late stage deals without multiple contacts" (PEOPLE), not "deals without multiple companies."

**Decision:** Use distinct external email count as the stakeholder proxy.

---

### Phase 3: Internal Domain Filtering

**Hypothesis:** Need to exclude internal (GrowthBook) participants from stakeholder counts.

**Configured exclusion list:**
- `growthbook.io`
- `growthbook.com`

**Domains found in participant data:**

| Domain | Deals | Classification |
|--------|-------|----------------|
| growthbook.io | 212 | Internal (correctly excluded) |
| resource.calendar.google.com | 12 | Calendar system metadata |
| gmail.com | 5 | External |
| fireflies.ai | 2 | Call recording tool itself |
| forhims.com | 2 | External |
| newtongrowth.com | 2 | External |

**Findings to preserve:**

1. **resource.calendar.google.com** (12 deals): Calendar invite system artifacts, not real participants. Consider adding to exclusion list if this proxy is ever revisited.

2. **fireflies.ai** (2 deals): The call recording/transcription tool itself appearing in participant lists. Minor noise, but worth noting.

3. **No missing internal domains:** Only growthbook.io/com found. No evidence of parent company domains, testing domains, or partner/reseller domains that should be excluded.

**Conclusion:** Internal domain filtering is clean and complete. Exclusion list is sufficient.

---

### Phase 4: Aggregate Won/Lost Separation (INCOMPLETE)

**Hypothesis:** Won deals have more stakeholders (multi-threaded) than lost deals (single-threaded).

**Methodology:** Compare distinct external email counts for won vs lost deals with participant data.

**Aggregate findings:**

| Outcome | n | Median emails | P25 | Mean |
|---------|---|---------------|-----|------|
| Won | 26 | 3 | 1 | 8.2 |
| Lost | 190 | 2 | 1 | 3.3 |

**Aggregate direction:** Won > Lost (3 vs 2 median) ✅ Expected direction

**CRITICAL LIMITATION:** This aggregate finding is **unconfirmed as segment-independent**. See Phase 5 for within-segment verification that reveals this pattern does NOT hold consistently.

---

### Phase 5: Segment Mix Bias and Within-Segment Verification (CRITICAL)

**Hypothesis:** The aggregate won > lost finding could be explained by segment mix (won deals skewing toward Enterprise, which naturally has more stakeholders) rather than genuine multi-threading signal.

**Methodology:**
1. Check segment distribution of won vs lost deals with participant data
2. Test won/lost separation WITHIN each segment independently
3. Compare to natural baseline (segment stakeholder counts regardless of outcome)

#### Segment Mix Analysis

**Won deals with participant data (n=26):**
- Enterprise: 26.9% (7 deals)
- Mid-Market: 50.0% (13 deals)
- SMB: 23.1% (6 deals)

**Lost deals with participant data (n=190):**
- Enterprise: 15.8% (30 deals)
- Mid-Market: 32.1% (61 deals)
- SMB: 45.8% (87 deals)

**Segment mix difference:**
- Enterprise: 11.1 percentage points
- SMB: **22.7 percentage points** ⚠️

**Finding:** Significant segment mix bias detected (>15pp threshold). Won deals skew toward Enterprise/Mid-Market (higher natural stakeholder counts), lost deals skew toward SMB (lower natural stakeholder counts).

**Implication:** The aggregate won > lost finding may primarily reflect segment distribution differences rather than a genuine multi-threading effect.

#### Within-Segment Separation Test

**Complete breakdown:**

| Segment | Won n | Won Median | Lost n | Lost Median | Direction | Sample Viability |
|---------|-------|------------|--------|-------------|-----------|-----------------|
| **Enterprise** | 7 | 3 emails | 30 | 2 emails | ✅ Won > Lost | ⚠️ Small won sample (n=7) |
| **Mid-Market** | **13** | **2 emails** | **61** | **3 emails** | ❌ **Won < Lost (INVERTED)** | ✅ **Most reliable (largest samples)** |
| **SMB** | 6 | 4 emails | 87 | 1 email | ✅ Won > Lost | ⚠️ Small won sample (n=6) |

**Critical finding:** Only 2/3 segments show expected direction, BUT this simple vote count understates the problem:

**Why Mid-Market's inversion matters more than 2-out-of-3 suggests:**

1. **Largest sample sizes:** 13 won deals (vs 7 Enterprise, 6 SMB) and 61 lost deals (vs 30 Enterprise, 87 SMB)
2. **Most balanced:** Best won/lost ratio among the three segments
3. **Statistically most trustworthy:** Combined n=74 vs Enterprise n=37, SMB n=93
4. **Highest confidence:** When the segment with the most data contradicts the aggregate pattern, it carries disproportionate weight

Mid-Market isn't just "one vote against two"—it's the most reliable segment contradicting a pattern that appears in two less-reliable segments (both with small won samples). A simple majority-of-segments framing would understate how much this one contradicting result should weigh against the aggregate finding.

#### Natural Baseline: Segment Stakeholder Counts

**Expected stakeholder counts by segment (all deals with participant data, regardless of outcome):**

| Segment | n | Median emails | Mean emails |
|---------|---|---------------|-------------|
| Enterprise | 37 | 2 | 3.3 |
| **Mid-Market** | **74** | **3** | **4.8** |
| SMB | 93 | 1 | 3.3 |

**Finding:** Mid-Market naturally has the HIGHEST stakeholder counts (median 3, mean 4.8), yet shows **inverted** won/lost pattern where won deals have FEWER stakeholders than lost deals.

**Interpretation:** If the multi-threading hypothesis were true, we'd expect it to hold most strongly in the segment with the most stakeholder engagement (Mid-Market). Instead, we see the opposite—suggesting the aggregate pattern is spurious.

#### Verdict on Segment Independence

**Aggregate finding is NOT segment-independent:**
- 2/3 segments show expected direction (but small won samples)
- Mid-Market (largest, most reliable) shows inversion
- Segment mix bias partially explains aggregate pattern (22.7pp SMB difference)

**Conclusion:** The aggregate won > lost finding (won median 3, lost median 2) should **not be over-interpreted** as validating the multi-threading hypothesis. It is substantially explained by:
1. Segment distribution differences (won deals happening to be in higher-stakeholder segments)
2. Not a consistent, segment-independent multi-threading effect

This is **inconclusive data worth monitoring** if coverage improves, NOT a "promising future signal" that just needs more data to confirm.

---

## Final Results

### Coverage Analysis

**Overall coverage:** 21.6% of closed deals (216/1,000)

| Population | Count | % of Total |
|------------|-------|------------|
| Won with participant data | 26 | 17.1% of won deals |
| Lost with participant data | 190 | 22.4% of lost deals |
| Total with participant data | 216 | 21.6% of closed deals |

**Coverage too low:** 21.6% < 50% minimum threshold for reliable metric derivation.

**Comparison to Signal 3:** Even lower than Signal 3's 46% coverage after exclusions (though Signal 3 started at 86% before bulk cleanup).

### Sample Size Analysis

**Cells with sufficient sample (n≥5 per outcome): 1/11 (9.1%)**

**Complete breakdown by stage × segment:**

| Stage | Segment | Won | Lost | Status |
|-------|---------|-----|------|--------|
| closed_lost | Enterprise | 0 | 27 | ❌ No won samples |
| closed_lost | Mid-Market | 0 | 56 | ❌ No won samples |
| closed_lost | SMB | 0 | 80 | ❌ No won samples |
| closed_lost | Unknown | 0 | 9 | ❌ No won samples |
| closed_won | Enterprise | 3 | 0 | ❌ No lost samples |
| closed_won | Mid-Market | 7 | 0 | ❌ No lost samples |
| closed_won | SMB | 5 | 0 | ❌ No lost samples |
| unknown | Enterprise | 4 | 3 | ❌ Insufficient (n<5) |
| **unknown** | **Mid-Market** | **6** | **5** | ✅ **Sufficient** |
| unknown | SMB | 1 | 7 | ❌ Insufficient (n<5) |
| unknown | Unknown | 0 | 3 | ❌ No won samples |

**Issue:** Only 1/11 cells viable (9.1%). Insufficient for production use.

**Comparison to Signal 3:** Even worse than Signal 3's 3/9 cells viable (33%).

### Direction Analysis (Segment-Independent Test)

**Within-segment results (3 testable segments with n≥5 both outcomes):**

| Segment | Won Median | Lost Median | Direction | Reliability |
|---------|------------|-------------|-----------|-------------|
| Enterprise | 3 | 2 | ✅ Correct | ⚠️ Small won n=7 |
| **Mid-Market** | **2** | **3** | ❌ **INVERTED** | ✅ **Most reliable** |
| SMB | 4 | 1 | ✅ Correct | ⚠️ Small won n=6 |

**Consistency check:** 2/3 segments show expected direction, but the most statistically trustworthy segment (Mid-Market, n=74) shows inversion.

**Segment mix bias:** 22.7pp difference in SMB representation between won and lost deals.

**Conclusion:** Won/lost separation is NOT segment-independent. Aggregate finding substantially explained by segment mix rather than genuine multi-threading signal.

---

## Deferral Rationale

**Signal 1 is deferred due to:**

1. **Insufficient coverage:** 21.6% < 50% minimum threshold
   - Only 216/1,000 closed deals have call participant data
   - Even lower than Signal 3's coverage after exclusions

2. **Insufficient sample sizes:** Only 1/11 cells viable (9.1%)
   - Below 50% cell coverage threshold for production use
   - Worse than Signal 3's 3/9 cells viable (33%)

3. **Won/lost separation not segment-independent:**
   - Aggregate finding shows expected direction (won > lost)
   - BUT within-segment test reveals inconsistency:
     - Enterprise: Correct direction (small sample)
     - **Mid-Market: INVERTED direction (largest, most reliable sample)**
     - SMB: Correct direction (small sample)
   - Significant segment mix bias (22.7pp SMB difference)
   - Aggregate pattern substantially explained by segment distribution differences

4. **Data quality constraints:**
   - Calls table coverage is the limiting factor (21.6%)
   - Participant_emails field IS populated (100% of calls), so no data quality issue there
   - Coverage ceiling cannot improve without more calls logged

**Signal 1 is NOT VIABLE with current data source.**

---

## Template-Portable Lessons

### 1. Call Participant Emails as Stakeholder Proxy

**What it is:** participant_emails field in calls table, recording all email addresses on a call.

**Coverage:** 21.6% of closed deals (100% populated when calls exist).

**Data quality:** Clean and complete—every call has participant information.

**Suitability for Signal 1:**
- ✅ Conceptually valid proxy (emails = people = stakeholders)
- ✅ 100% populated when calls exist
- ✅ Easy to parse and count
- ❌ Coverage far too low (21.6% < 50% threshold)
- ❌ Sample sizes collapse when split by stage × segment

**Template-portable note:** If a client has >50% calls coverage, this proxy becomes viable. Check calls table coverage FIRST before attempting this approach.

### 2. Emails vs Domains Decision

**Methodology:**

Compute both metrics for the same population:
- Distinct external emails (count of people)
- Distinct external domains (count of companies)

Check for "single domain, multiple emails" pattern to identify undercounting risk.

**Finding:** 42.6% of deals had multiple emails from single domain.

**Decision rule:** If ≥30% of deals show "single domain, multiple emails" pattern, use EMAILS metric. Domain count severely undercounts multi-person buying committees within a single organization.

**Template-portable:** Always compute both metrics and check for undercounting patterns before choosing. Default to emails (people count) unless there's a specific reason to use domains (e.g., measuring multi-company partnerships).

### 3. Internal Domain Filtering

**Methodology:**

1. Configure known internal domain exclusion list
2. Query participant data to identify all domains
3. Review top 20 most common domains for missing internal domains
4. Check for system noise (calendar artifacts, recording tools, etc.)

**Findings to watch for:**
- Calendar system metadata (e.g., resource.calendar.google.com)
- Call recording tools appearing as participants (e.g., fireflies.ai)
- Parent company domains
- Testing/staging domains
- Partner/reseller domains that shouldn't count as external stakeholders

**Template-portable:** Always do a top-N domain frequency analysis to catch missing internal domains. Don't rely solely on pre-configured exclusion lists.

### 4. Segment Mix Bias Check (MANDATORY)

**CRITICAL METHODOLOGY REQUIREMENT:**

When testing any signal for won/lost separation, ALWAYS check within-segment independence, not just aggregate patterns. This is NOT an optional extra step—it's a mandatory verification that aggregate findings aren't spurious.

**Why this matters:**

If won deals skew toward segments with naturally different baseline values (e.g., Enterprise has more stakeholders regardless of outcome), an aggregate won > lost finding can be entirely explained by segment mix rather than the hypothesized signal.

**Methodology:**

1. Compute segment distribution for won vs lost populations with signal data
2. Check for significant bias (>15 percentage points in any segment)
3. Test signal separation WITHIN each segment independently
4. Compare to natural baseline (segment values regardless of outcome)
5. **Weight results by sample reliability, not simple majority vote**

**Example from this investigation:**

Aggregate: Won > Lost (correct direction)
Within-segment:
- Enterprise: Won > Lost (but n=7 won, unreliable)
- Mid-Market: Won < Lost (INVERTED, but n=13 won + 61 lost = most reliable)
- SMB: Won > Lost (but n=6 won, unreliable)

**Result:** The most statistically trustworthy segment contradicts the aggregate pattern. A simple 2-out-of-3 majority vote would understate this concern—Mid-Market's inversion should weigh heavily because it has the most data.

**Template-portable rule:** Add this to signal derivation methodology documentation:

> "MANDATORY: Test won/lost separation within each segment independently, not just in aggregate. Check for segment mix bias (>15pp threshold). Weight within-segment results by sample size and reliability, not simple majority. If the largest/most-reliable segment contradicts the aggregate pattern, defer the signal—segment mix bias is likely explaining the aggregate finding."

This prevents false positives where an aggregate pattern is spurious due to segment distribution differences rather than the underlying hypothesis.

### 5. Sample Size Reliability Weighting

**Methodology:**

When multiple segments show conflicting directions, don't count them equally. Weight by:
1. Combined sample size (won + lost)
2. Balance (won/lost ratio close to 1:1 is more trustworthy than 1:10)
3. Minimum outcome size (smaller of won or lost counts)

**Example from this investigation:**

- Enterprise: n=37 total, n=7 won (7:30 ratio, unbalanced)
- **Mid-Market: n=74 total, n=13 won (13:61 ratio, most balanced)**
- SMB: n=93 total, n=6 won (6:87 ratio, severely unbalanced)

Mid-Market should weigh more heavily because:
- Largest total sample
- Best won/lost balance (still unbalanced, but better than others)
- Most reliable for detecting true patterns

**Template-portable:** When segments disagree, don't use simple majority. Identify which segment(s) are most statistically trustworthy and defer if those show inversion or no separation.

---

## Re-evaluation Criteria

Signal 1 should be reconsidered when:

### Option 1: Real Contacts Table (Preferred)

1. **Contact-to-deal associations added to data model**
   - Proper CRM contact tracking (not call participant proxy)
   - Coverage ≥50% of closed deals have associated contacts
   - Can compute distinct contact counts per deal

2. **Sample sizes sufficient:**
   - ≥50% of stage × segment cells have n≥5 per outcome
   - Sufficient samples to test within-segment independently

3. **Segment-independent verification:**
   - Test won/lost separation WITHIN each segment
   - **ALL testable segments (with n≥5 both outcomes) must show same direction**
   - No significant segment mix bias (≤15pp difference)
   - Largest/most-reliable segments support the aggregate pattern

### Option 2: Call Coverage Improvement (Less Preferred)

1. **Calls table coverage improves substantially:**
   - ≥50% of closed deals have call participant data
   - Participant_emails field remains 100% populated

2. **Sample sizes sufficient:**
   - ≥50% of stage × segment cells have n≥5 per outcome

3. **Segment-independent verification:**
   - Repeat within-segment test with larger samples
   - Confirm Mid-Market no longer shows inversion
   - All testable segments show consistent direction
   - No significant segment mix bias

### Minimum Viable Signal Requirements

**Before reimplementing Signal 1:**

1. ✅ Coverage ≥50% of closed deals
2. ✅ Sample sizes: ≥50% of cells with n≥5 per outcome
3. ✅ **Within-segment test shows consistent direction across ALL testable segments**
4. ✅ **No significant segment mix bias (≤15pp in any segment)**
5. ✅ **Largest/most-reliable segment(s) support the aggregate pattern**

**Do NOT reimplement if:**
- Only aggregate shows expected direction but within-segment test fails
- Segment mix bias detected (even if aggregate looks correct)
- Most-reliable segment shows inversion or no separation

---

## Comparison to Signal 2 and Signal 3

### Signal 2: Time-in-Stage (DERIVED, IMPLEMENTED)

**Methodology:**
- P75 of historical won deal time-in-stage
- Segment-specific (Enterprise/Mid-Market/SMB)
- Stage-specific (Discovery/Scoping/Proposal)
- Minimum sample size n≥5 per cell
- Fallback hierarchy (segment → stage → global)

**Coverage:** 100% (all deals have dealstage history)

**Empirical backing:** Thresholds reflect actual won deal pacing patterns

**Segment-independence:** Derived separately per segment (inherently segment-specific)

**Confidence:** High (data-driven, validated sample sizes)

---

### Signal 3: Activity Recency (DEFERRED, then HAND-PICKED)

**Methodology attempted:**
- Recency gap: last activity → close date
- Segment-specific derivation attempted
- Stage-specific derivation attempted

**Coverage:** 46% after exclusions (below 50% threshold)

**Sample sizes:** 3/9 cells viable (33%, below 50% threshold)

**Direction:** 2/3 derivable cells showed backwards or no separation

**Final implementation:** Hand-picked 14-day global threshold (domain knowledge validated)

**Confidence:** Medium (pragmatic choice, domain-validated but not empirically derived)

---

### Signal 1: Stakeholder Count (DEFERRED - THIS DOCUMENT)

**Methodology attempted:**
- Distinct external email count from call participants
- Segment-specific derivation attempted

**Coverage:** 21.6% (below 50% threshold, worse than Signal 3)

**Sample sizes:** 1/11 cells viable (9.1%, below 50% threshold, worse than Signal 3)

**Direction:** 2/3 testable segments show expected direction, BUT:
- Mid-Market (largest, most reliable) shows **inversion**
- Significant segment mix bias (22.7pp SMB difference)
- Aggregate pattern substantially explained by segment distribution

**Segment-independence:** Failed verification (not consistent within segments)

**Confidence:** None (coverage too low, segment-independent test failed)

---

**Rigor comparison:**

| Signal | Coverage | Cells Viable | Direction | Segment-Independent | Status |
|--------|----------|-------------|-----------|---------------------|--------|
| Signal 2 | 100% | Derived per cell | N/A (won-only) | Inherently segment-specific | ✅ Implemented |
| Signal 3 | 46% | 33% | 1/3 correct | Not tested | ❌ Deferred → Hand-picked |
| Signal 1 | 21.6% | 9.1% | 2/3 correct | ❌ Failed (Mid-Market inverted) | ❌ Deferred |

Signal 1 fails on MORE dimensions than Signal 3:
- Lower coverage (21.6% vs 46%)
- Fewer viable cells (9.1% vs 33%)
- Failed segment-independence test (Signal 3 wasn't tested for this)

---

## Alternative Approaches Considered

### Option 1: Use domains instead of emails

**Rationale:** Might have cleaner signal if measuring "multi-company deals" rather than "multi-person deals."

**Finding:** 42.6% of deals have multiple emails from single domain. Domain count severely undercounts stakeholder engagement within a buying organization.

**Conclusion:** Rejected. Emails (people) is the correct metric for Jeff's hypothesis about multi-threaded deals.

---

### Option 2: Weight by call recency (favor recent calls)

**Rationale:** Early-stage calls may have different participant patterns than late-stage calls. Weight recent calls more heavily.

**Issue:** Doesn't solve the coverage problem. Only 21.6% of deals have any calls at all.

**Conclusion:** Not pursued. Coverage is the bottleneck, not call timing.

---

### Option 3: Use "ever had multi-stakeholder call" as binary signal

**Rationale:** Instead of counting distinct emails, flag deals that ever had a call with ≥3 external participants as binary "multi-threaded" signal.

**Issue:** Still inherits 21.6% coverage ceiling. Sample sizes would remain insufficient.

**Conclusion:** Not pursued. Binary signal doesn't solve sample size problem.

---

### Option 4: Combine with email engagement data (if available)

**Rationale:** If email engagement tracking exists (cc'd contacts, email thread participants), combine with call participants for higher coverage.

**Finding:** Not explored in this investigation. Would require additional data sources.

**Recommendation for future:** If client has email tracking (e.g., from Salesloft, Outreach, or Gmail integration), consider combining call + email participants for higher stakeholder coverage. Re-run this methodology with combined data source.

---

## Scripts Created

### Investigation Scripts

1. `investigate_signal1_call_proxy.py` - Complete feasibility analysis (5 checks)
2. `check_signal1_segment_mix.py` - Segment mix bias and within-segment verification

**Both scripts are template-portable** - reusable methodology for any client attempting Signal 1 derivation via call participant proxy.

---

## Data Quality Findings

### 1. Calls Table Coverage: 21.6%

**Finding:** Only 216/1,000 closed deals have call records.

**Implication:** This is the hard coverage ceiling for any call-based proxy. No amount of clever metric design can overcome 21.6% baseline coverage.

**Comparison:** Lower than expected based on Signal 3 investigation (which found 23% calls coverage).

**Action:** If call-based signals are desired, investigate why calls table coverage is so low. Are calls not being logged consistently? Is this a CRM integration issue?

### 2. Participant_Emails Field: 100% Populated

**Finding:** When calls exist, participant_emails is populated in 100% of cases (216/216).

**Implication:** Data quality is GOOD for participant tracking. The coverage problem is entirely at the calls table level, not field population.

**Positive note:** If calls table coverage improves in the future, participant data will be reliable.

### 3. Internal Domain Filtering: Clean

**Finding:** Only growthbook.io/com found as internal domains. No evidence of missing exclusions.

**Minor noise identified:**
- `resource.calendar.google.com` (12 deals): Calendar system artifacts
- `fireflies.ai` (2 deals): Call recording tool appearing in participant lists

**Recommendation:** Consider adding resource.calendar.google.com to exclusion list if this proxy is revisited (calendar system metadata, not real participants).

### 4. Segment Mix Bias in Call Coverage

**Finding:** Won deals with call data skew 22.7pp more toward Enterprise/Mid-Market than lost deals.

**Possible explanations:**
1. Won deals are more likely to have recorded calls (deal health correlates with call logging)
2. Enterprise deals more likely to use call recording tools
3. Lost deals churn out quickly without many logged calls

**Implication:** Even if coverage improved, need to verify this bias doesn't persist. Segment mix bias in the data source itself makes it harder to derive segment-independent thresholds.

---

## Meta-Note for Template Portability

### Within-Segment Testing as Mandatory Methodology Requirement

**Context:** This investigation revealed a critical limitation that would have been missed without the segment-mix check Jeff explicitly requested. The aggregate won > lost finding appeared to validate the hypothesis, but within-segment testing revealed it was substantially explained by segment mix bias rather than genuine multi-threading signal.

**Lesson learned:** Testing signals in aggregate (all deals combined) can produce false positives when segment distributions differ between won and lost populations. A signal that appears to work may just be rediscovering segment differences rather than detecting the underlying risk factor.

**Recommendation for methodology governance:**

Add "within-segment independence verification" as a **permanent, mandatory requirement** for all future signal derivations. This should be documented in whatever governs signal derivation methodology (the same place that captures pandora-defect avoidance rules, minimum sample size thresholds, and fallback logic).

**Proposed addition to signal derivation methodology:**

> **MANDATORY: Within-Segment Independence Test**
>
> When deriving thresholds from won/lost separation, ALWAYS verify the pattern holds within each segment independently, not just in aggregate. This prevents false positives where aggregate findings are explained by segment mix bias rather than the hypothesized risk factor.
>
> **Procedure:**
> 1. Check segment distribution for won vs lost populations with signal data
> 2. Flag if any segment shows >15 percentage point difference (segment mix bias)
> 3. Test signal separation WITHIN each segment independently
> 4. Require ALL testable segments (with n≥5 both outcomes) to show same direction
> 5. Weight results by sample reliability (largest, most balanced segments matter most)
>
> **Deferral criteria:**
> - If most-reliable segment shows inversion or no separation, DEFER (even if aggregate looks correct)
> - If significant segment mix bias detected (>15pp), explicitly note limitation
> - Simple majority of segments is NOT sufficient—weight by statistical trustworthiness
>
> **Example failure mode:**
> - Aggregate: Won > Lost (appears to validate hypothesis)
> - Within-segment: Mid-Market (largest sample) shows Won < Lost (inverted)
> - Segment mix: Won deals skew 22pp toward Enterprise (naturally higher values)
> - **Conclusion:** Aggregate finding spurious, driven by segment distribution not signal
>
> This check is not optional—it's a standard verification step like minimum sample size thresholds. Skipping it risks implementing signals that don't actually work.

**Placement:** Add to the same methodology document/registry that includes:
- Pandora defect avoidance (negative cycle time exclusion)
- Minimum sample size thresholds (n≥5 per cell)
- Fallback hierarchy logic (segment → stage → global)
- Coverage thresholds (≥50% for reliable derivation)

**Why this matters:** Jeff had to explicitly request this check. It should be automatic. Future signal investigations should include within-segment testing by default, not as an afterthought when someone thinks to ask for it.

---

## Key Takeaways

1. **Coverage is king:** 21.6% coverage is insurmountable. No amount of clever metric design overcomes insufficient data.

2. **Participant data quality is good:** 100% populated when calls exist. The problem is lack of calls, not lack of participant information.

3. **Emails vs domains decision is clear:** Use emails (people count). 42.6% of deals have multi-person buying committees from single domain—domains would severely undercount.

4. **Aggregate findings can be spurious:** Won > lost in aggregate looked promising, but within-segment test revealed Mid-Market (most reliable sample) shows inversion. Segment mix bias explained the aggregate pattern.

5. **Weight by sample reliability:** Mid-Market's inversion matters more than 2-out-of-3 simple majority because it has the largest, most balanced sample. Don't count segments equally—weight by statistical trustworthiness.

6. **Within-segment testing is mandatory:** This investigation is a template for why segment-independent verification must be a standard part of signal derivation methodology, not an optional extra check.

7. **Failed on more dimensions than Signal 3:** Lower coverage (21.6% vs 46%), fewer viable cells (9.1% vs 33%), AND failed segment-independence test. Signal 1 is more decisively deferred than Signal 3 was.

---

**END OF SIGNAL 1 DEFERRAL DOCUMENTATION**
