# Wave 4 Calibration - Ready to Run

**Date**: 2026-09-05
**Status**: ✓ Script fixed, workflow created, ready for execution

---

## What Was Fixed

### Issue: Incorrect Environment Variable Name

**Problem**: `run_calibration.py` expected `RAILWAY_API_URL` but repo uses `RAILWAY_URL`

**Evidence**:
- `.github/workflows/gate-tests.yml` line 129: `RAILWAY_URL: ${{ secrets.RAILWAY_URL }}`
- `scripts/smoke_test.py` line 17: `RAILWAY_URL = os.environ.get("RAILWAY_URL", "")`

**Fix Applied**:
```python
# Before (WRONG)
self.api_url = os.getenv('RAILWAY_API_URL', 'http://localhost:8080')

# After (CORRECT)
self.api_url = os.environ.get('RAILWAY_URL', 'http://localhost:8080')
```

### Issue: Hard-wired .env Dependency

**Problem**: Script used `load_dotenv()` unconditionally, expecting local `.env` file

**Reality**: This repo uses GitHub Secrets, not local `.env`

**Fix Applied**:
```python
# Optional: load .env for local dev (GitHub Actions uses Secrets)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # dotenv not installed, use os.environ only
```

**Benefits**:
- Works in GitHub Actions (reads from Secrets)
- Works locally if .env present (optional)
- Doesn't break if python-dotenv not installed

---

## How to Run Calibration

### Method 1: GitHub Actions (Recommended)

**Steps**:
1. Go to repository → Actions tab
2. Select "Wave 4 Calibration Run" workflow
3. Click "Run workflow" → select branch → Run

**Environment**:
- Uses existing `RAILWAY_URL` secret
- Uses existing `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` secrets
- Runs in `Agent` environment (same as gate-tests)

**Workflow file**: `.github/workflows/run-calibration.yml`

### Method 2: Local Execution (If API Accessible)

**Prerequisites**:
- CRO Slack agent API deployed and accessible
- Railway URL known

**Commands**:
```bash
export RAILWAY_URL=https://your-api-url.railway.app
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_SERVICE_KEY=your-service-key

python scripts/run_calibration.py
```

---

## What Calibration Tests

### 19 Questions with Verified Values

**Independently Verified (9)**:
- q002: Renewal pipeline Q3/Q4 ($1.19M, $2.27M)
- q008: Customers due to renew (33 Q3, 21 Q4)
- q009: High champion score deals (0)
- q010: Recent closed-lost (3 deals)
- q011: Active pipeline ($25M, 444 deals)
- q013: Skyscanner deal ($125K, active)
- q016: Historical win rate (10.4%, 159 day cycle)
- q019: forecast_weekly staleness (3 days)
- q020: Missing owner_email (15 deals, 3.4%)

**Internally Consistent (1)**:
- q012: At-risk deals (70) - derived from agent's own placeholder logic

**Previously Verified (7)**:
- q003: Deals with no ARR (127, 28.6%)
- q004: Christian attainment (0%, $0 of $250K)
- q005: Team attainment (12.7%, $197K of $1.55M)
- q006: COMMIT deals (2 deals, $170K)
- q017: GRR Q1 2027 (77%)
- q018: Week-3 conversion (9.9%, deprecated)
- q021: Prospective conversion (7.2%)

**Out of Scope (2)**:
- q014: MEDDICC definition (rubric, not data query)
- q015: Multi-deal MEDDICC analysis (requires call analysis)

**Duplicate (1)**:
- q007: Duplicate of q003

---

## Expected Output

### Calibration Report Structure

```
====================================================================================================
WAVE 4 CALIBRATION RESULTS
====================================================================================================

Questions Tested: 19
API Endpoint: https://your-api-url.railway.app/slack/question

CORRECT (X questions):
  q003: Deals with no ARR
    Agent: 127 (28.6%)
    Verified: 127 (28.6%)
    ✓ Match

  q011: Active pipeline value
    Agent: $24,985,788
    Verified: $24,985,788
    ✓ Match

  [... more correct answers]

WRONG (Y questions):
  q016: Historical win rate
    Agent: 8.2%
    Verified: 10.4%
    ✗ Divergence: 2.2 percentage points

  [... more wrong answers]

UNANSWERABLE (Z questions):
  q009: High champion score deals
    Agent: "I don't have access to that information"
    ✗ Failed to answer

  [... more unanswerable]

====================================================================================================
FALLBACK RATE
====================================================================================================

Total queries: 19
Fallback to dynamic: 8 (42.1%)

⚠️  ALERT: Fallback rate >40% indicates semantic layer issues
    - Fast-path handlers missing or broken
    - Each fallback is slower and less reliable
    - Recommend: Add handlers for high-fallback questions

====================================================================================================
SUMMARY
====================================================================================================

Accuracy: X/19 correct (Y%)
Fallback rate: Z%

NEXT STEPS:
1. Investigate "wrong" answers (verify query logic)
2. Add handlers for "unanswerable" questions
3. Reduce fallback rate to <40%
4. Wire Trigger 5 (metric_divergence) once stable
```

---

## Files Modified

1. **scripts/run_calibration.py**
   - Changed `RAILWAY_API_URL` → `RAILWAY_URL`
   - Made `load_dotenv()` optional (file existence check)
   - Now works in both GitHub Actions and local dev

2. **.github/workflows/run-calibration.yml** (NEW)
   - Manual workflow trigger (`workflow_dispatch`)
   - Uses existing `RAILWAY_URL` secret
   - 15-minute timeout
   - Runs in `Agent` environment

3. **WAVE_4_STATUS.md**
   - Updated Task 3 status to "READY"
   - Documented correct variable name
   - Added workflow instructions

---

## Next Steps After Calibration

### If Calibration Passes (High Accuracy, Low Fallback)

1. **Wire Trigger 5** (metric_divergence):
   - Implement `compute_metric()` in `scripts/monitor_metric_divergence.py`
   - Map metric IDs to canonical question IDs
   - Set tolerance thresholds
   - Enable in `config/monitoring.yaml`

2. **Add Key Metrics** to `config/metrics.yaml`:
   ```yaml
   metrics:
     commit_coverage:
       verified_result:
         value: 0.5
         count: 2
         arr: 170000
         tolerance: 0.2

     prospective_conversion:
       verified_result:
         value: 7.2
         tolerance: 1.0
   ```

3. **Test Trigger 5 Dry-Run**:
   ```bash
   python scripts/monitor_metric_divergence.py --dry-run
   ```

### If Calibration Fails

1. **Investigate "Wrong" Answers**:
   - Check query logic in handlers
   - Verify data hasn't changed since verification
   - Update verified values if legitimate change

2. **Debug "Unanswerable" Questions**:
   - Check if handler exists for question type
   - Review intent classification
   - Add missing handlers if needed

3. **Reduce Fallback Rate** (if >40%):
   - Identify high-fallback questions
   - Add fast-path handlers
   - Test semantic layer coverage

---

## Deployment Checklist

Before running calibration:

- [ ] Verify CRO Slack agent is deployed to Railway
- [ ] Confirm `RAILWAY_URL` secret points to correct deployment
- [ ] Check API health: `curl https://your-url.railway.app/health`
- [ ] Verify `/slack/question` endpoint is accessible

After calibration:

- [ ] Review accuracy percentage (target: >80%)
- [ ] Review fallback rate (target: <40%)
- [ ] Document any "wrong" answers with investigation notes
- [ ] Update verified values if data legitimately changed
- [ ] Plan fixes for any handler gaps

---

## Status

**Wave 4 Progress**: 50% complete (2 of 4 tasks)
- [x] Task 1: Update verified values from debugging
- [x] Task 2: Get verified values for pending questions
- [ ] Task 3: Run full calibration ← **READY TO RUN**
- [ ] Task 4: Wire Trigger 5 (metric_divergence)

**Blocker**: CRO Slack agent deployment status unknown
**Action**: Check if Railway deployment is live, then run workflow
