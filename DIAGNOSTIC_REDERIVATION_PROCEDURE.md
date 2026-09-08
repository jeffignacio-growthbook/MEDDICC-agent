# Diagnostic Classifier Re-Derivation Procedure

**Purpose:** Operationalize the "20+ production escalations" re-derivation trigger

**Problem:** Good intention without owner/mechanism becomes the same as EXTRAPOLATED-components 4-week review risk - quietly never happens.

---

## Current State

**Trigger defined:** "After 20+ production escalations"

**Issues:**
- What counts an escalation?
- What tracks the count?
- Who gets notified at 20?
- What does "re-derivation" concretely mean?

**Without answers:** Trigger is a good intention that quietly never fires.

---

## Tracking Mechanism

### What Counts as an Escalation

**Definition:** Any backtest non-convergence that escalates to human review.

**Includes:**
- LLM-generated metrics that don't converge
- Manual metrics that don't converge
- Any case where diagnostic classifier fires

**Excludes:**
- Successful convergences (didn't escalate)
- Test/development runs
- Synthetic validation cases

### Tracking Implementation

**Option 1: Supabase table (RECOMMENDED)**

```sql
CREATE TABLE diagnostic_escalations (
    id SERIAL PRIMARY KEY,
    escalated_at TIMESTAMP DEFAULT NOW(),

    -- Metric info
    metric_name TEXT NOT NULL,
    metric_type TEXT NOT NULL,  -- sum_dollars, median_days, percentage

    -- Convergence results
    naive_value NUMERIC,
    final_value NUMERIC,
    target_value NUMERIC,
    improvement_pct NUMERIC,
    remaining_gap_pct NUMERIC,

    -- Classification
    classifier_type TEXT,  -- missing_rule, impossible_target, partial_progress
    classifier_confidence TEXT,  -- high, medium, low

    -- Human feedback
    human_reviewed BOOLEAN DEFAULT FALSE,
    human_classification TEXT,  -- missing_rule, impossible_target, partial_progress, other
    human_notes TEXT,
    reviewed_at TIMESTAMP,
    reviewed_by TEXT,

    -- Audit trail
    rules_tried TEXT[],
    iterations_count INTEGER,
    converged BOOLEAN DEFAULT FALSE
);

-- Index for counting escalations
CREATE INDEX idx_escalation_count ON diagnostic_escalations(escalated_at);

-- Index for human-reviewed cases
CREATE INDEX idx_human_reviewed ON diagnostic_escalations(human_reviewed, escalated_at);
```

**Option 2: Log file + periodic grep (NOT RECOMMENDED)**

Too fragile - relies on someone remembering to grep logs periodically.

### Logging Each Escalation

**In backtest_engine_generalized.py:**

```python
def log_escalation(sb: Client, diagnostic: dict, metric_spec: dict):
    """
    Log non-convergence escalation to Supabase for re-derivation tracking.

    Called when backtest fails to converge and escalates to human.
    """
    escalation_record = {
        "metric_name": metric_spec.get("metric_name", "unknown"),
        "metric_type": metric_spec.get("metric_type"),
        "naive_value": diagnostic["naive_value"],
        "final_value": diagnostic["final_value"],
        "target_value": diagnostic["target_value"],
        "improvement_pct": diagnostic["improvement_pct"],
        "remaining_gap_pct": diagnostic["remaining_gap_pct"],
        "classifier_type": diagnostic["type"],
        "classifier_confidence": diagnostic.get("classification_confidence"),
        "rules_tried": diagnostic["rules_tried"],
        "iterations_count": diagnostic["iterations_count"],
        "converged": False
    }

    sb.table("diagnostic_escalations").insert(escalation_record).execute()
```

---

## Re-Derivation Trigger

### Checking Escalation Count

**Monthly automated check:**

```python
#!/usr/bin/env python3
"""Check if diagnostic re-derivation trigger has fired."""

import os
from datetime import datetime
from supabase import create_client

sb = create_client(
    os.environ['SUPABASE_URL'],
    os.environ['SUPABASE_SERVICE_KEY']
)

# Count total escalations
result = sb.table("diagnostic_escalations").select("id", count="exact").execute()
total_escalations = result.count

# Count human-reviewed escalations (required for re-derivation)
reviewed = sb.table("diagnostic_escalations").select(
    "id", count="exact"
).eq("human_reviewed", True).execute()
reviewed_count = reviewed.count

print(f"Total escalations: {total_escalations}")
print(f"Human-reviewed: {reviewed_count}")

if reviewed_count >= 20:
    print()
    print("⚠️  RE-DERIVATION TRIGGER FIRED")
    print(f"   {reviewed_count} escalations have human feedback")
    print("   Action required: Run re-derivation procedure")
    print("   See: DIAGNOSTIC_REDERIVATION_PROCEDURE.md")
    print()
    print("   Owner: [TO BE ASSIGNED]")
    print("   Deadline: Within 2 weeks of trigger")
```

**GitHub Actions monthly check:**

```yaml
# .github/workflows/diagnostic-rederivation-check.yml
name: Diagnostic Re-derivation Check

on:
  schedule:
    - cron: '0 9 1 * *'  # 9am UTC on 1st of each month
  workflow_dispatch:

jobs:
  check-rederivation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Check escalation count
        run: python scripts/check_diagnostic_rederivation.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
```

---

## Re-Derivation Procedure

### What "Re-Derivation" Means

**For Signal 2:** Derived from historical ground truth (P75 of won deal time-in-stage)

**For diagnostic classifier:** No historical ground truth exists. Instead:

1. **Collect real production cases** (improvement%, gap%, correct classification)
2. **Re-tune boundary thresholds** against real dataset
3. **Validate against held-out cases**
4. **Update thresholds in code**

**This is tuning from real data, not deriving from historical ground truth.**

### Step-by-Step Procedure

#### Step 1: Export Human-Reviewed Escalations

```python
#!/usr/bin/env python3
"""Export human-reviewed escalations for re-derivation."""

import pandas as pd
from supabase import create_client

sb = create_client(...)

# Fetch all human-reviewed escalations
escalations = sb.table("diagnostic_escalations").select("*").eq(
    "human_reviewed", True
).execute()

df = pd.DataFrame(escalations.data)

# Save for analysis
df.to_csv("diagnostic_rederivation_dataset.csv", index=False)

print(f"Exported {len(df)} human-reviewed escalations")
print()
print("Columns:")
print(f"  - improvement_pct: {df['improvement_pct'].describe()}")
print(f"  - remaining_gap_pct: {df['remaining_gap_pct'].describe()}")
print()
print("Human classifications:")
print(df['human_classification'].value_counts())
```

#### Step 2: Analyze Classification Accuracy

```python
#!/usr/bin/env python3
"""Analyze current classifier accuracy on real data."""

import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("diagnostic_rederivation_dataset.csv")

# Calculate accuracy
df['classifier_correct'] = (df['classifier_type'] == df['human_classification'])
accuracy = df['classifier_correct'].mean()

print(f"Current classifier accuracy: {accuracy:.1%}")
print()

# Confusion matrix
from sklearn.metrics import confusion_matrix, classification_report

print("Confusion Matrix:")
print(confusion_matrix(df['human_classification'], df['classifier_type']))
print()

print("Classification Report:")
print(classification_report(df['human_classification'], df['classifier_type']))

# Plot decision boundaries
plt.figure(figsize=(10, 8))
plt.scatter(
    df['improvement_pct'],
    df['remaining_gap_pct'],
    c=df['human_classification'].map({
        'missing_rule': 'green',
        'impossible_target': 'red',
        'partial_progress': 'blue'
    }),
    alpha=0.6
)
plt.xlabel('Improvement %')
plt.ylabel('Remaining Gap %')
plt.title('Escalations by Human Classification')
plt.savefig('diagnostic_decision_space.png')
print("Decision space plot saved to diagnostic_decision_space.png")
```

#### Step 3: Re-Tune Thresholds

**Method:** Use real production cases to find optimal thresholds

```python
#!/usr/bin/env python3
"""Re-tune classifier thresholds from real data."""

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier

df = pd.read_csv("diagnostic_rederivation_dataset.csv")

# Features: improvement_pct, remaining_gap_pct
X = df[['improvement_pct', 'remaining_gap_pct']]
y = df['human_classification']

# Train/test split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.3, random_state=42
)

# Train simple decision tree to find optimal thresholds
clf = DecisionTreeClassifier(max_depth=3, random_state=42)
clf.fit(X_train, y_train)

# Evaluate
train_acc = clf.score(X_train, y_train)
test_acc = clf.score(X_test, y_test)

print(f"Training accuracy: {train_acc:.1%}")
print(f"Test accuracy: {test_acc:.1%}")
print()

# Extract decision rules
from sklearn.tree import export_text
tree_rules = export_text(clf, feature_names=['improvement_pct', 'remaining_gap_pct'])
print("Suggested decision rules:")
print(tree_rules)
print()

print("Recommended thresholds (based on tree splits):")
# Extract threshold values from tree
# ... (implementation would extract actual threshold values)
```

#### Step 4: Validate New Thresholds

```python
#!/usr/bin/env python3
"""Validate new thresholds against held-out cases."""

# Test new thresholds on held-out data
# Compare accuracy to current heuristic
# Ensure no regression on original 7 test cases

def test_new_thresholds(df_test, new_thresholds):
    """Test new thresholds and compare to current heuristic."""

    # Apply new thresholds
    predictions_new = apply_new_classifier(df_test, new_thresholds)
    accuracy_new = (predictions_new == df_test['human_classification']).mean()

    # Apply current heuristic
    predictions_current = apply_current_classifier(df_test)
    accuracy_current = (predictions_current == df_test['human_classification']).mean()

    print(f"Current heuristic accuracy: {accuracy_current:.1%}")
    print(f"New thresholds accuracy: {accuracy_new:.1%}")
    print(f"Improvement: {(accuracy_new - accuracy_current):.1%}")

    return accuracy_new > accuracy_current
```

#### Step 5: Update Code and Documentation

**If new thresholds are better:**

1. Update thresholds in `enhanced_diagnostic()` function
2. Document in DIAGNOSTIC_CLASSIFIER_HEURISTIC.md:
   - Re-derivation date
   - Dataset size (n=X escalations)
   - Old vs new thresholds
   - Accuracy improvement
3. Update status from "heuristic_pending_validation" to "heuristic_tuned_from_production"
4. Reset escalation count for next re-derivation cycle

**If new thresholds are NOT better:**

- Document why (insufficient data, no clear pattern, etc.)
- Wait for more escalations (reset trigger to 30 or 50)
- Consider alternative approaches (ML model, rule-based system, etc.)

---

## Owner Assignment

### Responsibility

**Owner:** Jeff Ignacio (@jeff in Slack)
- Primary: jeff@revopsimpact.com
- Backup: [TO BE ASSIGNED if delegation needed]

**Responsibilities:**
1. Monitor monthly escalation count
2. Trigger re-derivation procedure when threshold reached
3. Review human classifications for quality
4. Execute re-derivation steps 1-5
5. Update code and documentation

**Time commitment:** ~4-8 hours when trigger fires (every 3-6 months expected)

**Notification channels:**
- Slack: @jeff in #revenue-ops
- Email: jeff@revopsimpact.com
- GitHub: Auto-created issue with @jeffignacio assigned

### Fallback

**If owner unavailable:**
- GitHub Actions workflow sends notification to #revenue-ops Slack channel
- Issue auto-created in GitHub with re-derivation procedure checklist
- Escalate to team lead if not completed within 2 weeks

**Delegation procedure:**
- Update scripts/check_diagnostic_rederivation.py with new owner
- Update this document with new owner name/contact
- Brief new owner on re-derivation procedure
- Test notification flow with new owner

---

## Success Criteria

**Re-derivation procedure is operational when:**

1. ✅ Escalations automatically logged to Supabase
2. ✅ Monthly check runs via GitHub Actions
3. ✅ Owner assigned and notified when trigger fires
4. ✅ Procedure documented with concrete steps
5. ✅ Mechanism tested (run manually to verify it works)

**Without these:** Re-derivation trigger is a good intention that quietly never fires (same as EXTRAPOLATED components 4-week review risk).

---

## Testing the Procedure

### Before Production

**Simulate 20 escalations:**

```python
#!/usr/bin/env python3
"""Simulate escalations to test re-derivation procedure."""

# Insert 20 synthetic escalations with human feedback
for i in range(20):
    escalation = {
        "metric_name": f"test_metric_{i}",
        "metric_type": "sum_dollars",
        "naive_value": 10000 + i * 100,
        "final_value": 5000 + i * 50,
        "target_value": 4500,
        "improvement_pct": 50 + i * 2,
        "remaining_gap_pct": 10 + i,
        "classifier_type": "partial_progress",
        "classifier_confidence": "medium",
        "human_reviewed": True,
        "human_classification": "missing_rule" if i % 2 == 0 else "partial_progress",
        "rules_tried": ["exclude_renewals"],
        "iterations_count": 1
    }
    sb.table("diagnostic_escalations").insert(escalation).execute()

# Run check script
# Verify trigger fires
# Verify notification sent
```

---

## Summary

**Re-derivation trigger is operationalized when:**

1. ✅ **Tracking:** Supabase table logs all escalations
2. ✅ **Mechanism:** GitHub Actions monthly check
3. ✅ **Trigger:** Notification at 20+ human-reviewed escalations
4. ✅ **Procedure:** 5-step concrete process documented
5. ✅ **Owner:** Assigned with clear responsibilities
6. ✅ **Fallback:** Auto-notification if not completed

**This ensures the trigger actually fires and re-derivation actually happens** (not a good intention that quietly never occurs).
