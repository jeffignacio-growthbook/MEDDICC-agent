# Task B3: Stage-Aware Risk Validation

## Expected Changes: Old vs New Logic

Based on automated test coverage and config requirements, here's what the new stage-aware logic will produce compared to the old flat-threshold approach:

### Discovery Stage Deals

**Config Requirements (Discovery → Scoping):**
- Pain: 5+
- Champion: 4+

**Example: USIM at Discovery**
- OLD: "no champ, no EB" (flagged for EB=0 and Champion=2)
- NEW: "Champion 2/10 (need 4+ to advance from Discovery)"
- **KEY CHANGE**: EB flag removed (EB not required until Scoping→Proposal)

**Example: Discovery deal with EB=0 but Champion=5**
- OLD: "no EB" (false positive)
- NEW: NOT flagged (EB not yet due, Champion meets requirement)

### Scoping Stage Deals

**Config Requirements (Scoping → Proposal):**
- Metrics: 6+
- Economic Buyer: 6+
- Champion: 6+
- Decision Criteria: 5+

**Example: Scoping deal with all components ≥6 except EB=3**
- OLD: "no EB" (correct but not stage-contextualized)
- NEW: "Economic Buyer 3/10 (need 6+ to advance from Scoping)"
- **KEY CHANGE**: Stage-specific threshold and context

### Tech Eval (Proposal) Stage Deals

**Config Requirements (Tech Eval → Negotiating):**
- All components: 6+
- Decision Process: 7+
- Competition: 6+

**Example: Tech Eval deal with DP=4**
- OLD: "low overall" (if overall < 40, otherwise not flagged)
- NEW: "Decision Process 4/10 (need 7+ to advance from Technical Evaluation)"
- **KEY CHANGE**: Catches specific component gaps that flat threshold missed

### Terminal/Excluded Stages

**Closed Won, Closed Lost, Disqualified, Meeting Set:**
- OLD: Could still be flagged if scores low
- NEW: Never flagged (empty requirements, terminal or excluded)
- **KEY CHANGE**: No noise from resolved/out-of-scope deals

## Automated Test Coverage

All scenarios above are covered by `scripts/eval_stage_aware_risk.py`:

✅ Test 1: Discovery deal with EB=0 but Champion=5 NOT flagged
✅ Test 2: Discovery deal with Champion=0 IS flagged (stage-aware reason)
✅ Test 3: Tech Eval deal with EB=3 IS flagged (EB required at this stage)
✅ Test 4: Closed Won deal has empty requirements, never flagged
✅ Test 5: Excluded stage (Meeting Set) has empty requirements

## Production Validation Steps

To validate against real production data (requires Supabase credentials):

```bash
cd /tmp/MEDDICC-agent
python scripts/validate_stage_aware_against_prod.py
```

This will show side-by-side comparison for the 10 deals from live test:
- USIM, MedCof, Zoro, Box, Zalando, BESTSELLER, Square, ECCO, Chaos, OpenTable

Expected output format:
```
Company              | Stage           | OLD Flags                           | NEW Flags
------------------------------------------------------------------------------------------------
USIM                 | Discovery       | no champ, no EB                     | Champion 2/4
MedCof               | Tech Eval       | no EB                               | Economic Buyer 3/6
...
```

## Key Improvements

1. **Fewer False Positives**: No longer flags components not yet due at current stage
2. **More Accurate Signals**: Only flags genuinely overdue components
3. **Better Communication**: Risk reasons include stage context and thresholds
4. **Config-Driven**: Uses same stage_progression table as other parts of system
5. **Trust-Building**: CRO sees accurate, stage-aware risk assessment instead of noise

## Implementation Files

- **api/stage_requirements.py** (NEW): Loads progression requirements from config
- **api/handlers.py**: query_deals_at_risk rewritten with stage-aware logic
- **config/client.yaml**: Single source of truth for stage requirements
- **scripts/eval_stage_aware_risk.py** (NEW): Comprehensive test coverage
- **scripts/validate_stage_aware_against_prod.py** (NEW): Production validation tool
