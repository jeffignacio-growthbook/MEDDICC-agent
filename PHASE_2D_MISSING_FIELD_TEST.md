# Phase 2d Test Case: Missing Input Field Detection

**Status:** Required test before Phase 2d completion
**Priority:** Blocking
**Type:** Conversational flow validation

---

## Test Case Overview

**Purpose:** Verify that conversational agent correctly detects and surfaces MISSING INPUT FIELDS (not just wrong population) during clarifying-questions stage, and refuses to silently compute incomplete metrics.

**This test addresses:** The risk of silently computing a churn-only number and calling it GRR when contraction data is genuinely absent.

---

## Test Scenario

### Setup
Create a test environment where a required field is genuinely missing:
- Field does not exist in HubSpot properties, OR
- Field exists but is null/empty for ALL historical deals (0% populated)

### Example Metrics Requiring Missing Fields

**Option 1: GRR without contraction**
- User request: "Calculate GRR for Q1 2026"
- Missing field: `contraction_revenue` (hypothetically absent)
- Impact: Can only compute churn-based retention, not true GRR

**Option 2: NRR without downsells**
- User request: "Calculate NRR including logo churn, expansion, and downsells"
- Missing field: `downsell_arr` (doesn't exist)
- Impact: Can only compute expansion-based NRR, not complete NRR

**Option 3: Win rate by source without source**
- User request: "Win rate by lead source for inbound vs. outbound"
- Missing field: `lead_source` (never populated)
- Impact: Cannot segment by source at all

---

## Expected Behavior (Required)

### Stage 1: Missing Field Detection
During clarifying-questions, system must:
1. Check if all required fields exist
2. Check if required fields are populated (not just null/empty for all records)
3. Detect gap BEFORE attempting computation

### Stage 2: Surface Explicit Choice
Present user with clear options:

```
⚠️ Data Gap Detected

The metric "GRR" as strictly defined requires contraction data, but the
`contraction_revenue` field is not currently captured in your HubSpot.

You can:
a) Proceed with churn-only GRR approximation (will be labeled as
   "GRR (churn-only approximation, contraction not tracked)")

b) Defer this metric until contraction tracking is implemented

Which would you prefer?
```

### Stage 3: Block Silent Computation
System MUST NOT:
- Silently compute churn-only and call it "GRR"
- Assume missing field = zero without asking
- Proceed without explicit user acknowledgment of limitation

### Stage 4: Honest Labeling (if proceeding)
If user chooses to proceed with approximation:
- Metric stored as: `"GRR (churn-only approximation, contraction not tracked)"`
- Registry entry includes caveat in `description` field
- Diagnostic output labels it as approximation
- Same rigor as Signal 3's hand-picked threshold labeling

---

## Test Implementation

### Test 1: Completely Missing Field

```python
def test_missing_field_detection():
    """Test detection of field that doesn't exist at all."""

    # Setup: Request GRR, but contraction_revenue doesn't exist
    user_request = "Calculate GRR for Q1 2026"

    # Mock HubSpot: no contraction_revenue in properties
    mock_hubspot_properties = [
        "amount", "closedate", "dealstage",
        "renewal_revenue", "expansion_revenue"
        # Note: contraction_revenue deliberately absent
    ]

    # Expected: System detects missing field during clarifying-questions
    response = conversational_agent.clarify(user_request)

    assert "data gap detected" in response.lower()
    assert "contraction" in response.lower()
    assert "not currently captured" in response.lower()
    assert "proceed with" in response.lower() or "defer" in response.lower()
```

### Test 2: Field Exists But Never Populated

```python
def test_unpopulated_field_detection():
    """Test detection of field that exists but is 0% populated."""

    user_request = "Calculate NRR including downsells"

    # Mock: Field exists in schema but null for all deals
    mock_deals = [
        {"downsell_arr": None, "expansion_arr": 5000},
        {"downsell_arr": None, "expansion_arr": 3000},
        {"downsell_arr": None, "expansion_arr": 0},
    ]

    # Expected: System detects 0% population rate
    response = conversational_agent.clarify(user_request)

    assert "downsell data" in response.lower()
    assert "not currently captured" in response.lower()
    assert "expansion-only" in response.lower()
```

### Test 3: User Chooses Approximation

```python
def test_approximation_labeling():
    """Test that approximation is honestly labeled if user proceeds."""

    user_request = "Calculate GRR for Q1 2026"
    user_choice = "a"  # Proceed with churn-only approximation

    # System computes approximation
    metric_spec = conversational_agent.create_metric_spec(
        user_request, user_choice
    )

    # Expected: Honest labeling
    assert "churn-only approximation" in metric_spec["name"]
    assert "contraction not tracked" in metric_spec["description"]
    assert metric_spec["status"] == "approximation"

    # Expected: NOT called just "GRR"
    assert metric_spec["name"] != "GRR"
```

### Test 4: User Defers Metric

```python
def test_defer_until_tracked():
    """Test that system gracefully defers if user chooses to wait."""

    user_request = "Calculate GRR for Q1 2026"
    user_choice = "b"  # Defer until contraction tracking implemented

    response = conversational_agent.handle_deferred_metric(
        user_request, user_choice
    )

    # Expected: Confirmation of deferral, no computation
    assert "deferred" in response.lower()
    assert "implement contraction tracking" in response.lower()
    assert metric_spec not created  # No registry entry
```

---

## Comparison to Other Honest Labeling

This follows the same pattern as:

### Signal 3: Hand-Picked Threshold
- **Status:** `"heuristic_pending_validation"`
- **Label:** "14-day threshold chosen based on 2 test cases"
- **Re-derivation trigger:** After 20+ production cases

### Diagnostic Classifier
- **Status:** `"heuristic_pending_validation"`
- **Label:** Shows raw improvement%/gap% alongside classification
- **Re-derivation trigger:** After 20+ human-reviewed escalations

### GRR Approximation (if contraction missing)
- **Status:** `"approximation_incomplete_data"`
- **Label:** "GRR (churn-only approximation, contraction not tracked)"
- **Re-evaluation trigger:** When contraction tracking is implemented

---

## Success Criteria

Phase 2d test passes if:

1. ✅ System detects missing field during clarifying-questions (not during backtest failure)
2. ✅ User is explicitly asked to choose: proceed with approximation or defer
3. ✅ If proceeding: metric stored with honest label (not full metric name)
4. ✅ If deferring: no computation attempted, graceful exit
5. ✅ Missing field ≠ wrong population (system distinguishes these cases)
6. ✅ No silent fallback to incomplete computation

---

## Related Context

**GRR Contraction Audit:** See `CONTRACTION_DATA_AUDIT.md` for findings that:
- Contraction field EXISTS in this deployment
- Field is 85.9% populated on renewals
- Zeros are real zeros (very low contraction business)
- **This test case is hypothetical** - actual GRR dogfood can proceed with full GRR

**User's original concern:**
> "contraction_arr (or whatever the actual field is called) is genuinely 0/null
> for ALL historical deals, not just currently active ones - check this
> explicitly, since if it's zero for CURRENT deals but was populated
> historically before some data-entry process stopped tracking it, that's a
> different (and more fixable) problem than 'contraction was never captured.'"

**Actual finding:** Contraction WAS captured, IS tracked, and zeros are real.

**Test case requirement:** Add this scenario anyway to prevent future silent failures with genuinely missing fields.
