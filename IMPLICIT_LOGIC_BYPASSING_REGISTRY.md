# IMPLICIT_LOGIC_BYPASSING_REGISTRY — Pattern Documentation

**Status:** Template-portable failure mode (alongside SYNTHESIS_DATA_LOSS_PATTERN.md, PROVENANCE_LOSS_ACROSS_SESSIONS.md)

**Date discovered:** 2026-09-07 (Backtest Engine stress testing)

**Occurrences in this build:** 2 (both in same session)

---

## Pattern Definition

**Business logic executing outside the mechanism meant to control it**, producing results that LOOK like the registry/config is controlling behavior when it isn't.

A hygiene or business rule gets applied **unconditionally** inside a calculation function, independent of whether the orchestrating registry/config actually selected that rule. The system appears to work correctly because the output matches expectations, but for the wrong reason - the registry isn't actually controlling what it claims to control.

---

## Why This Is Dangerous

### 1. False Validation

System appears to pass tests when the tested mechanism isn't actually functioning:
- Test: "Does registry-driven rule application work?"
- Observation: Output is correct
- Conclusion: ✓ Registry working
- **Reality:** Registry is being bypassed, correctness is coincidental

### 2. Silent Divergence

When registry is updated, behavior doesn't change:
- Add new rule to registry → no effect
- Remove rule from registry → behavior unchanged
- Modify rule logic → original hardcoded path still executes

**Result:** Config drift - documented registry doesn't match actual behavior.

### 3. Debugging Confusion

Developers trust the registry as source of truth:
- "Why isn't my new rule firing?" → Rule is firing, but hardcoded path overrides it
- "How do I disable this rule?" → Can't, it's unconditional in calculation code
- Wasted hours debugging config when the issue is implementation

---

## This Build's Examples

### Occurrence 1: Backtest Engine (First Pass)

**Location:** `scripts/backtest_engine.py`, execute_candidate_query()

**Code:**
```python
cycle_days = (close_date - create_date).days

if cycle_days >= 0:  # IMPLICIT FILTERING
    cycle_times.append(cycle_days)
```

**Problem:** Negative cycle times filtered **unconditionally**, regardless of whether `exclude_invalid_cycle_time` was in `applied_rules`.

**Impact:**
- Engine appeared to converge with first rule (exclude_renewals)
- Actually working because second rule was implicitly applied
- Multi-rule iteration looked successful but wasn't actually tested

**How discovered:** Stress test #1 forced re-examination. Realized -658 day outlier should have affected result but didn't.

**Fix:**
```python
cycle_days = (close_date - create_date).days

# Include ALL cycle times (even negative) unless explicit rule applied
cycle_times.append(cycle_days)  # No implicit filtering
```

### Occurrence 2: Verification Script (Same Session)

**Location:** `scripts/verify_convergence_population.py`, calc_median_cycle_time()

**Code:**
```python
cycle_days = (close_date - create_date).days
if cycle_days >= 0:  # IMPLICIT FILTERING (same pattern)
    cycle_times.append(cycle_days)
```

**Problem:** Same implicit filtering pattern copied into verification script.

**Impact:**
- Verification showed "both populations produce same result"
- True, but only because both were implicitly filtering negative values
- Made it appear second rule was never needed, when actually it was always being applied

**How discovered:** Same debugging pass caught both instances.

**Fix:** Same as Occurrence 1 - remove implicit filtering, make all filtering explicit via rule parameters.

---

## Pattern Characteristics

### How to Recognize

**1. "Helpful" defaults in calculation functions**
```python
def calc_metric(deals):
    # ANTI-PATTERN: Implicit filtering
    clean_deals = [d for d in deals if is_valid(d)]  # Always filters, even if not requested
    return compute(clean_deals)
```

**2. Business logic inside utility functions**
```python
def parse_date(date_str):
    # ANTI-PATTERN: Implicit business rule
    if date_str is None:
        return datetime.now()  # Fallback applied unconditionally
    return datetime.fromisoformat(date_str)
```

**3. Conditional logic that doesn't check parameters**
```python
def apply_hygiene_rules(deals, rules):
    # ANTI-PATTERN: Hardcoded check ignoring rules parameter
    deals = [d for d in deals if d.get('status') != 'test']  # Always excludes test deals

    for rule in rules:
        deals = apply_rule(deals, rule)

    return deals
```

### How It Happens

**1. Premature optimization**
- "We always want to exclude invalid data, so let's do it once at the start"
- Seems efficient, breaks modularity

**2. Defensive coding**
- "Can't trust upstream to filter, so I'll filter here too"
- Seems safe, creates hidden dependencies

**3. Copy-paste with context loss**
- Original function had valid reason for unconditional filtering
- Copied to new context where filtering should be conditional
- Original context assumptions no longer hold

### Similar Patterns in Other Contexts

**Field semantics drift (caught earlier today):**
- Business rule defined in field_semantics.py
- Duplicated inline in handler for "performance"
- Original rule updated, duplicate not updated
- Silent divergence

**This pattern is the same failure mode:** Business logic executing outside canonical path.

---

## Mitigation Strategy

### 1. Explicit Parameters Only

**Anti-pattern:**
```python
def calc_cycle_time(deals):
    # Implicitly filters renewals
    deals = [d for d in deals if not is_renewal(d)]
    return compute_median(deals)
```

**Correct:**
```python
def calc_cycle_time(deals, exclude_renewals=False):
    if exclude_renewals:
        deals = [d for d in deals if not is_renewal(d)]
    return compute_median(deals)
```

**Even better (registry-driven):**
```python
def calc_cycle_time(deals, applied_rules):
    if "exclude_renewals" in applied_rules:
        deals = [d for d in deals if not is_renewal(d)]
    return compute_median(deals)
```

### 2. Test Fully-Unfiltered Case

**Add to standard validation:**
```python
# Test with NO rules applied - should return raw, unfiltered result
result_unfiltered = execute_query(deals, applied_rules=[])

# If result is suspiciously clean, implicit filtering is happening
assert result_unfiltered includes_obvious_contaminants, \
    "Implicit filtering detected - unfiltered case returned clean data"
```

**Example for backtest engine:**
```python
# Test naive candidate (no rules) against obviously contaminated dataset
# Should return wrong answer (proving no implicit filtering)
result = execute_candidate_query(sb, applied_rules=[])
assert result['median_days'] != ground_truth, \
    "Naive candidate should fail - if it passes, implicit filtering is masking contamination"
```

### 3. Single Source of Truth for Rules

**Anti-pattern:**
```python
# Rule logic in TWO places
def is_valid_cycle_deal(deal):
    return deal.get('cycle_days', 0) >= 0

def calc_cycle_time(deals):
    # DUPLICATED logic
    return [d for d in deals if d.get('cycle_days', 0) >= 0]
```

**Correct:**
```python
def is_valid_cycle_deal(deal):
    return deal.get('cycle_days', 0) >= 0

def calc_cycle_time(deals, exclude_invalid=False):
    if exclude_invalid:
        deals = [d for d in deals if is_valid_cycle_deal(d)]  # REUSE canonical definition
    return median([d.get('cycle_days') for d in deals])
```

### 4. Document Implicit Assumptions

If a calculation function MUST have implicit filtering (rare), document it explicitly:

```python
def calc_cycle_time(deals):
    """
    Calculate median cycle time.

    IMPLICIT FILTERING (unavoidable):
    - Excludes deals with NULL create_date or close_date (required for calculation)

    EXPLICIT FILTERING (caller-controlled):
    - Renewals: caller must filter before passing deals
    - Invalid cycle time: caller must filter before passing deals

    This function makes minimal assumptions. All business rules are caller's responsibility.
    """
    cycle_times = []
    for deal in deals:
        # Only implicit: skip deals missing required fields
        if not deal.get('create_date') or not deal.get('close_date'):
            continue

        # NO implicit business logic - include ALL values (even negative, even outliers)
        cycle_times.append(calculate_days(deal))

    return median(cycle_times)
```

---

## Detection Methods

### 1. Code Review Checklist

**Flag any of these patterns:**
- [ ] Filtering inside calculation functions not controlled by parameters
- [ ] Business rule logic duplicated across functions
- [ ] "Helpful" defaults that apply rules unconditionally
- [ ] Validation checks inside calculation code not in validation layer

### 2. Test Pattern: Naive Case Should Fail

```python
# GOOD TEST: Proves no implicit filtering
def test_naive_candidate_fails():
    """Naive candidate (no rules) should produce contaminated result."""
    result = backtest_engine.execute(
        ground_truth=52,
        applied_rules=[],  # NO RULES
        tolerance=3
    )

    # Should NOT converge (contamination present)
    assert not result['converged'], \
        "Naive candidate converged - implicit filtering suspected"

    # Should return obviously wrong answer
    assert abs(result['actual'] - 52) > 50, \
        "Naive result too close to ground truth - implicit filtering suspected"
```

### 3. Registry Mutation Test

```python
# GOOD TEST: Proves registry actually controls behavior
def test_registry_controls_behavior():
    """Removing rule from registry should change output."""

    # Run with both rules
    result_both = execute(applied_rules=['rule1', 'rule2'])

    # Run with one rule
    result_one = execute(applied_rules=['rule1'])

    # Outputs MUST differ if rule2 is load-bearing
    assert result_both != result_one, \
        "Removing rule2 didn't change output - either rule2 not load-bearing or implicit bypass happening"
```

---

## Template Port Guidance

### Include This Pattern in Standard Build Validation

Alongside SYNTHESIS_DATA_LOSS_PATTERN.md and PROVENANCE_LOSS_ACROSS_SESSIONS.md:

**1. Test fully-unfiltered case**
- Every registry-driven system should have "naive case" test
- Naive result should be obviously wrong (proving no implicit help)

**2. Test registry mutation**
- Adding/removing rules should change output
- If output unchanged, registry is being bypassed

**3. Code review for implicit logic**
- Flag any filtering not controlled by parameters
- Flag any business rules inside utility functions

### Where This Pattern Appears

**Registry-driven systems:**
- Backtest engines
- Rule-based scoring
- Configurable validations
- Policy enforcement

**Calculation pipelines:**
- Metric computations
- Aggregations with hygiene rules
- ETL transformations with business logic

**Any time:** Business rules should be configurable but might get hardcoded "for convenience"

---

## Relationship to Other Patterns

### SYNTHESIS_DATA_LOSS_PATTERN
- **Similarity:** Both involve silent loss of information
- **Difference:** Data loss is about what gets shown to user; implicit logic is about what gets calculated
- **Connection:** Implicit filtering can cause data loss if calculation silently excludes entities

### PROVENANCE_LOSS_ACROSS_SESSIONS
- **Similarity:** Both involve claims not matching reality
- **Difference:** Provenance loss is about labeling; implicit logic is about execution
- **Connection:** System claims "registry controls rules" (provenance) but actually hardcodes them (execution)

### This Pattern is the Execution Layer Version
- Provenance loss: Claims about where data came from
- Data loss: What gets presented to user
- **Implicit logic: What actually executes beneath the surface**

---

## Success Criteria for Mitigation

**Before:**
- Registry claims to control rules
- Actually rules hardcoded in calculation
- Tests pass because output happens to be correct
- Config updates have no effect

**After:**
- Registry genuinely controls all filtering
- Calculation functions are parameter-driven
- Naive test proves no implicit help
- Mutation test proves registry has effect
- Config updates change behavior as expected

**Validation:** Can demonstrate registry control by running same calculation with different rule sets and observing different outputs.

---

## Example from This Build

**Before fix:**
```python
# WRONG: Implicit filtering
def execute_candidate_query(sb, query_spec):
    deals = fetch_deals(sb)

    cycle_times = []
    for deal in deals:
        cycle_days = calculate_cycle_days(deal)

        if cycle_days >= 0:  # IMPLICIT RULE
            cycle_times.append(cycle_days)

    return median(cycle_times)
```

**Claimed behavior:** "Applies hygiene rules from query_spec"
**Actual behavior:** "Always excludes negative cycle times, regardless of query_spec"

**Test that would have caught this:**
```python
# Naive candidate (no rules) should include negative cycle time
result = execute_candidate_query(sb, applied_rules=[])
assert result['sample_size'] == 23, \
    f"Expected n=23 (includes Netthandelsgruppen outlier), got n={result['sample_size']}"
```

**After fix:**
```python
# CORRECT: Explicit control
def execute_candidate_query(sb, query_spec):
    deals = fetch_deals(sb)

    # Apply hygiene rules from query_spec
    if query_spec['exclude_invalid_cycle']:
        deals = [d for d in deals if is_valid_cycle_deal(d)]

    cycle_times = []
    for deal in deals:
        cycle_days = calculate_cycle_days(deal)
        cycle_times.append(cycle_days)  # NO IMPLICIT FILTERING

    return median(cycle_times)
```

**Now:** Registry genuinely controls behavior. Naive test passes (returns n=23). Mutation test passes (adding/removing rules changes output).

---

## Summary

**Pattern name:** IMPLICIT_LOGIC_BYPASSING_REGISTRY

**Core problem:** Business logic executing outside the mechanism meant to control it

**Why dangerous:** Produces correct-looking results for wrong reasons, breaks config trust

**How to catch:** Test naive case (should fail), test mutation (should change output)

**How to fix:** Make all filtering explicit via parameters, single source of truth for rules

**Template port:** Add to standard build validation alongside synthesis data loss and provenance loss patterns

**This build:** Caught twice (backtest engine, verification script), both fixed before production
