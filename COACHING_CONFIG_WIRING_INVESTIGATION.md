# Coaching Config Wiring Investigation

**Date:** 2026-09-07
**Context:** After MEDDICC interpretation corrections (stage-relative EB expectations, champion-behavior-over-component-color), investigate whether coaching rubric already encodes this logic or if it's still unwired.

---

## 1. Config Files Existence and Content

### Files Found

All three config files exist:
- `config/coaching_seed.yaml` (3,708 bytes) — universal primitives
- `config/coaching_client.yaml` (13,755 bytes) — GrowthBook-specific
- `config/context.yaml` (11,954 bytes) — legacy, partially overlapping

### Top-Level Keys

**coaching_seed.yaml:**
```yaml
methodology: "MEDDICC"
blocker_taxonomy:
  technical: {...}
  resourcing: {...}
  cultural: {...}
  commercial: {...}
ownership_calibration: {...}
discovery_five_numbers_structure: {...}
discovery_quality_rubric:
  strong_call_signals: [...]
  weak_call_signals: [...]
learning_defaults: {...}
```

**coaching_client.yaml:**
```yaml
client_name: "GrowthBook"
company: {...}
competitors: [LaunchDarkly, Statsig, EPPO, Optimizely, Homegrown]
discovery_numbers: {volume, win_rate, value_per_win, incumbent_cost, the_clock}
objection_categories:
  switching_cost: {...}
  technical: {...}
  product_gap: {...}
  budget: {...}
  timing: {...}
  internal_politics: {...}
feature_gaps: {}
value_metrics: [...]
good_discovery:
  questions_to_ask: [...]
  signals_of_strong_call: [...]
  signals_of_weak_call: [...]
learning: {...}
objection_category_to_blocker: {...}
stage_focus_questions:
  discovery: {Economic Buyer: [...], Champion: [...], ...}
  scoping: {Economic Buyer: [...], Champion: [...], ...}
  proposal: {Economic Buyer: [...], Champion: [...], ...}
```

**context.yaml:**
```yaml
company: {...}
methodology: "MEDDICC"
competitors: [...]
objection_categories: {...}
feature_gaps: {}
value_metrics: [...]
good_discovery: {...}
learning: {...}
coaching_frameworks:
  discovery_five_numbers: {...}
  blocker_taxonomy: {...}
  discovery_quality_rubric: {...}
  ownership_calibration: {...}
```

### Key Content Summary

**objection_categories** (in both coaching_client.yaml and context.yaml):
- switching_cost, technical, product_gap, budget, timing, internal_politics
- Each has: label, signals (prospect language), best_responses, typical_stage
- Maps to blocker taxonomy via objection_category_to_blocker

**good_discovery** (in both files):
- questions_to_ask: 6 core discovery questions
- signals_of_strong_call: 8 ICP signals (warehouse-native commitment, experimentation scale, etc.)
- signals_of_weak_call: 5 disqualifying signals (marketing-only, low traffic, no warehouse)

**coaching_frameworks** (context.yaml only):
- discovery_five_numbers: volume, win_rate, value_per_win, incumbent_cost, the_clock
- blocker_taxonomy: technical, resourcing, cultural, commercial (with signals and right_response)
- discovery_quality_rubric: strong_call_signals vs weak_call_signals
- ownership_calibration: over_apologising vs under_owning vs calibrated_position

**discovery_numbers** (coaching_client.yaml only):
- Concrete GrowthBook definitions for the five numbers structure

---

## 2. load_coaching_config() Function and Call Sites

### Function Definition

**Location:** `scripts/coaching_config.py`

```python
@lru_cache(maxsize=1)
def load_coaching_config() -> dict:
    """
    Merged coaching config: seed values as base, client values override/
    extend. Cached — call config-reload utilities if hot-reload is ever
    needed, but coaching config changing mid-process is not expected.
    """
    seed = yaml.safe_load(SEED_PATH.read_text()) or {}
    client = yaml.safe_load(CLIENT_PATH.read_text()) or {}
    merged = {**seed, **client}   # client keys override seed keys at top level
    return merged
```

### All Call Sites

**Production handler (1 call site):**
1. `api/handlers.py:3011` — **query_pre_call_brief** (ONLY handler using it)

**Evaluation/testing scripts (6 call sites):**
- `scripts/eval_coaching_config.py:71`
- `scripts/eval_coaching_config_proof_of_life.py:77`
- `scripts/eval_coaching_config_proof_of_life.py:138`
- `scripts/eval_coaching_config_migration.py:140`
- `scripts/eval_coaching_config_migration.py:170`
- `scripts/eval_coaching_config_migration.py:187`

### Critical Finding: query_deal Does NOT Call It

**Handlers that do NOT use coaching_config:**
- ❌ `query_deal` (line 913) — reads analyses.component_details, uses api/rubric.py
- ❌ `query_coaching_priorities` (if it exists)
- ❌ Any other MEDDICC synthesis handlers

**Only handler that uses it:**
- ✅ `query_pre_call_brief` (line 2980) — uses stage_focus_questions, objection_category_to_blocker, blocker_taxonomy

---

## 3. Stage-Relative Logic in Coaching Config

### Stage-Aware Content Found

**A. stage_focus_questions (coaching_client.yaml:235-325)**

Different coaching questions per MEDDICC component per stage:

```yaml
stage_focus_questions:
  discovery:
    Economic Buyer:
      - "Who has final budget authority for this decision?"
      - "What's the approval threshold above which procurement gets involved?"
      - "At what dollar amount does this need C-level sign-off?"
    Champion:
      - "Who internally is most invested in solving this problem?"
      - "Who has skin in the game if experimentation doesn't improve?"
      - "Is there someone who's already tried to build internal momentum for this?"
    # ... (Metrics, Decision Criteria, Decision Process, Pain, Competition)

  scoping:
    Economic Buyer:
      - "Has the economic buyer been briefed on this yet?"
      - "What does [EB name] need to see to approve this?"
      - "When will you be able to loop in [EB name]?"
    Champion:
      - "What does your champion need from us to build the business case internally?"
      - "Do they have access to the economic buyer?"
      - "What would make them look good by championing this?"
    # ... (other components)

  proposal:
    Economic Buyer:
      - "When is [EB name] reviewing the proposal?"
      - "What questions or concerns does the economic buyer have?"
      - "Is there anyone above [EB name] who needs to approve?"
    Champion:
      - "What does your champion need to present this to the committee?"
      - "Are there internal objections they need help addressing?"
      - "What would make them confident presenting this to leadership?"
    # ... (other components)
```

**Interpretation:** Different questions reflect different expectations at each stage:
- Discovery: "Who has budget authority?" (identification)
- Scoping: "Has EB been briefed?" (engagement)
- Proposal: "When is EB reviewing?" (commitment)

**This is stage-relative BEHAVIOR guidance, but NOT stage-relative SCORING rules.**

### B. typical_stage in objection_categories

Each objection category specifies when it typically appears:
- switching_cost: "Discovery / Scoping"
- technical: "Discovery / Technical Evaluation"
- product_gap: "Scoping / Proposal"
- budget: "Proposal / Negotiating"
- timing: "Discovery / Qualification"
- internal_politics: "Scoping / Proposal"

**Interpretation:** Stage context for objection handling, but not MEDDICC component interpretation.

### What's NOT in the Config

**Missing stage-relative MEDDICC interpretation rules:**

❌ **No rules** about which MEDDICC components are expected to be red/yellow/green at which stages

❌ **No guidance** on "Economic Buyer red is acceptable in Discovery but concerning in Proposal"

❌ **No distinction** between genuine champion behavior vs. coordinator behavior

❌ **No stage-adjusted thresholds** for red/yellow/green bands per component

❌ **No logic** for "what counts as sufficient champion evidence at Discovery vs. Scoping"

**What exists instead:**
- Stage-specific QUESTIONS to ask (stage_focus_questions)
- Stage context for OBJECTION types (typical_stage)
- Universal red/yellow/green bands in api/rubric.py (NOT stage-aware)

---

## 4. How query_deal Generates MEDDICC Narrative Today

### Current Flow (api/handlers.py:913-999)

```python
async def query_deal(params: dict, sb) -> dict:
    # 1. Fetch deal from deals table
    deals = select_all(sb, "deals", columns="deal_id,company_name,deal_value,stage,...")
    deal = next((d for d in deals if company.lower() in (d.get("company_name") or "").lower()), None)

    # 2. Fetch latest analysis from analyses table
    analyses = select_all(sb, "analyses",
        columns="overall_score,component_details,analyzed_at,status",
        filters=[("eq", "deal_id", deal_id)])
    latest = analyses[0] if analyses else {}

    # 3. Fetch objections
    objections = select_all(sb, "objections", ...)

    # 4. Unpack component_details and attach bands from api/rubric.py
    from api.rubric import band_label
    from api.db import unpack_jsonb
    component_details = unpack_jsonb(latest.get("component_details"), {})
    meddicc_bands = {}
    for component, data in component_details.items():
        if isinstance(data, dict):
            lbl = band_label(component, data.get("score"))
            data["band"] = lbl["band"]               # "red", "yellow", or "green"
            data["band_label"] = lbl["text"]         # e.g. "Budget holder not identified"
            data["borderline"] = lbl["borderline"]
            meddicc_bands[component] = lbl["text"]

    # 5. Get next steps from api/rubric.py
    from api.rubric import get_next_steps
    for component, data in component_details.items():
        if isinstance(data, dict):
            data["next_steps"] = get_next_steps(component, data.get("score", 0))

    # 6. Return to LLM for synthesis
    return {
        "deal": deal,
        "latest_analysis": latest,
        "meddicc_bands": meddicc_bands,
        "objections": objections,
        "next_steps_source": "rubric_fallback"
    }
```

### Key Insights

**Data sources:**
1. `analyses.component_details` (JSON blob with score, evidence, reasoning per component)
2. `api/rubric.py` RUBRIC (universal red/yellow/green bands and next_steps)
3. Deal-specific analysis file if it exists (memory/analyses/{slug}.md)

**NO coaching config consulted:**
- query_deal does NOT call load_coaching_config()
- query_deal does NOT read stage_focus_questions
- query_deal does NOT apply stage-relative interpretation

**api/rubric.py bands are UNIVERSAL (NOT stage-aware):**

```python
RUBRIC = {
    "economic_buyer": {
        "bands": {
            "red": (0, 3, "Budget holder not identified"),
            "yellow": (4, 6, "Suspected but not confirmed"),
            "green": (7, 10, "Confirmed with access"),
        },
        "next_steps": {
            "red": "Ask: 'Who has final budget approval for [dollar amount] purchases?' Get introduced.",
            "yellow": "Confirm: 'Is [name] the final approver or does it need to go higher?' Validate authority.",
            "green": "Engage: 'What does [EB name] need to see to approve this?' Align on their success criteria.",
        }
    },
    "champion": {
        "bands": {
            "red": (0, 3, "No internal advocate"),
            "yellow": (4, 6, "Engaged but not selling"),
            "green": (7, 10, "Actively selling internally"),
        },
        # ...
    },
    # ... (other components)
}
```

**These bands are the SAME regardless of deal stage.**

### LLM Synthesis at Response Time

After query_deal returns its result:
1. LLM receives: deal.stage, component_details with bands, next_steps, objections
2. LLM synthesizes narrative using in-context judgment (NOT governed by config rules)
3. LLM interpretation varies run-to-run based on:
   - Exact prompt wording
   - Temperature (if non-zero)
   - Context from earlier conversation
   - **Jeff's corrections applied turn-by-turn in conversation**

**Result:** Stage-relative judgment (e.g., "EB-red acceptable in Discovery") lives in Jeff's head, NOT in queryable config.

---

## 5. What's Required to Wire Coaching Config into query_deal

### Minimal Change Scope

**Goal:** Have query_deal consult coaching config for stage-relative MEDDICC interpretation rules before generating narrative.

### Option A: Extend Existing stage_focus_questions with Scoring Rules

**Current structure:**
```yaml
stage_focus_questions:
  discovery:
    Economic Buyer:
      - "Who has final budget authority?"
      - "What's the approval threshold?"
```

**Add parallel structure for stage-relative scoring rules:**
```yaml
stage_scoring_expectations:
  discovery:
    Economic Buyer:
      acceptable_bands: ["red", "yellow"]  # EB-red is fine in Discovery
      concerning_threshold: null           # No concern if red in Discovery
      interpretation_notes: "Focus is identification, not engagement. Red means 'not yet identified' which is expected."
    Champion:
      acceptable_bands: ["yellow", "green"]  # Yellow acceptable, red concerning
      concerning_threshold: "red"
      interpretation_notes: "Should have at least engaged contact by Discovery. Red means no internal advocate identified."
    # ... (other components)

  scoping:
    Economic Buyer:
      acceptable_bands: ["yellow", "green"]  # Yellow acceptable, red now concerning
      concerning_threshold: "red"
      interpretation_notes: "By Scoping, EB should be identified. Red means structural issue."
    Champion:
      acceptable_bands: ["green"]  # Green expected
      concerning_threshold: "yellow"
      interpretation_notes: "Champion should be actively helping by Scoping. Yellow means coordinator, not champion."
    # ... (other components)

  proposal:
    Economic Buyer:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: "EB must be engaged by Proposal. Yellow or red is deal-killer."
    Champion:
      acceptable_bands: ["green"]
      concerning_threshold: "yellow"
      interpretation_notes: "Champion must be selling internally. Yellow means they're not actually championing."
    # ... (other components)
```

### Option B: Add champion_behavior_criteria (Genuine vs. Coordinator)

**Add behavioral rubric to coaching_client.yaml:**
```yaml
champion_behavior_criteria:
  genuine_champion:
    signals:
      - "Introduces you to EB or other stakeholders unprompted"
      - "Shares internal political landscape proactively"
      - "Asks for materials to sell internally"
      - "Defends you against internal objections"
      - "Guides you on timing and process"
    minimum_signals: 2  # Need at least 2 of these to score yellow

  coordinator_behavior:
    signals:
      - "Schedules meetings when asked"
      - "Answers questions when asked"
      - "Responds to emails"
      - "Attends demos"
    interpretation: "This is a helpful contact, not a champion. Do not score above red/yellow border."

  scoring_rules:
    red: "No engaged contact identified"
    yellow: "Coordinator behavior only (helpful but not selling)"
    green: "Genuine champion behavior (actively selling internally)"
```

### Option C: Minimal Wiring (Stage Context Only)

**Simplest first step:** Pass stage context to synthesis without changing scoring rules.

**Changes required:**

1. **query_deal reads coaching_config:**
```python
# After line 957 in api/handlers.py
from coaching_config import load_coaching_config
coaching_config = load_coaching_config()
stage_scoring = coaching_config.get("stage_scoring_expectations", {})
```

2. **Attach stage context to result:**
```python
# After line 963
result = {
    "deal": deal,
    "latest_analysis": latest,
    "meddicc_bands": meddicc_bands,
    "objections": objections,
    "stage_context": {
        "stage": deal.get("stage"),
        "stage_bucket": stage_bucket(deal["stage"]),  # discovery/scoping/proposal
        "scoring_expectations": stage_scoring.get(stage_bucket(deal["stage"]), {}),
    }
}
```

3. **LLM synthesis instruction references config:**
```
When interpreting MEDDICC scores:
- Current stage: {stage_context.stage} (bucket: {stage_context.stage_bucket})
- Stage-relative expectations: {stage_context.scoring_expectations}
- Apply these expectations when assessing whether a component score is concerning.
```

**Benefit:** Externalizes stage-relative logic from Jeff's head into governed config.

**Limitation:** Still relies on LLM to interpret expectations correctly (not deterministic scoring).

### Option D: Deterministic Stage-Relative Bands

**Most explicit:** Compute stage-relative bands programmatically in query_deal.

**Changes required:**

1. **Add stage_scoring_expectations to coaching_client.yaml** (per Option A)

2. **New function in api/rubric.py:**
```python
def band_label_stage_aware(component: str, score: int, stage: str, coaching_config: dict) -> dict:
    """
    Return band label WITH stage-relative interpretation.

    Example:
    - Economic Buyer score=2 (red) in Discovery → band="red", severity="acceptable"
    - Economic Buyer score=2 (red) in Proposal → band="red", severity="critical"
    """
    universal_band = band_label(component, score)  # existing function

    stage_bucket = stage_bucket(stage)
    expectations = coaching_config.get("stage_scoring_expectations", {}).get(stage_bucket, {}).get(component, {})

    acceptable_bands = expectations.get("acceptable_bands", [])
    concerning_threshold = expectations.get("concerning_threshold")

    if universal_band["band"] in acceptable_bands:
        severity = "acceptable"
    elif universal_band["band"] == concerning_threshold:
        severity = "concerning"
    else:
        severity = "critical"

    return {
        **universal_band,
        "stage_severity": severity,
        "stage_interpretation": expectations.get("interpretation_notes"),
    }
```

3. **Update query_deal to use stage-aware bands:**
```python
# Replace line 979 in api/handlers.py
lbl = band_label_stage_aware(component, data.get("score"), deal["stage"], coaching_config)
```

**Benefit:** Stage-relative interpretation is deterministic, governed by config, not LLM judgment.

---

## Summary: Current State

### What's Built

✅ **Coaching config infrastructure exists:**
- coaching_seed.yaml (universal primitives)
- coaching_client.yaml (GrowthBook-specific content)
- load_coaching_config() (merger function)

✅ **Rich content in coaching config:**
- objection_categories with typical_stage
- good_discovery questions and signals
- stage_focus_questions (different questions per stage per component)
- blocker_taxonomy with prescribed responses

✅ **Coaching config IS wired into query_pre_call_brief:**
- Uses stage_focus_questions to generate coaching questions
- Uses objection_category_to_blocker for blocker classification
- Uses blocker_taxonomy for prescribed responses

### What's Unwired

❌ **query_deal does NOT use coaching config:**
- Reads purely from analyses.component_details
- Uses universal bands from api/rubric.py (NOT stage-aware)
- LLM synthesizes narrative with in-context judgment
- No stage-relative interpretation rules applied

❌ **Coaching config does NOT contain stage-relative MEDDICC scoring rules:**
- Has stage-specific QUESTIONS (behavior guidance)
- Does NOT have stage-specific INTERPRETATION rules (scoring expectations)
- Does NOT have champion-behavior-criteria (genuine vs. coordinator)

❌ **Stage-relative judgment lives in Jeff's head:**
- Applied turn-by-turn in conversation
- Not encoded in queryable config
- Not consistently applied by LLM across queries

---

## Priority Assessment

**HIGH PRIORITY FIX** per user request.

**Reason:** Today's MEDDICC interpretation corrections (stage-relative EB expectations, champion-behavior-over-component-color) are EXACTLY the kind of judgment the coaching rubric exists to encode.

**Current cost:**
- Judgment applied inconsistently (varies by LLM context, prompt, Jeff's availability)
- Same correction gets re-explained across sessions
- No single source of truth for MEDDICC interpretation rules

**Recommended approach:**
1. **Phase 1:** Add stage_scoring_expectations to coaching_client.yaml (Option A content)
2. **Phase 2:** Wire query_deal to load_coaching_config and pass stage context (Option C changes)
3. **Phase 3:** Implement band_label_stage_aware for deterministic interpretation (Option D)
4. **Phase 4:** Add champion_behavior_criteria for genuine vs. coordinator distinction (Option B)

**Expected outcome:** Stage-relative MEDDICC interpretation becomes governed, consistent, and queryable.
