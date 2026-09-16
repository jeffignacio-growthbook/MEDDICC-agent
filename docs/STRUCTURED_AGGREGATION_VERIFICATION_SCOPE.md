# Structured Aggregation Verification — Scope Document

## Problem Statement

**Current state:**
- `AGGREGATION_VERIFY` (lines 3640-3726 in router.py) protects `dynamic_query_loop`
- Works by extracting stated totals from model-generated prose, recomputing from raw data
- Only fires for answers flowing through dynamic loop (exploration queries)
- Dedicated handlers like `query_pipeline` return structured data, bypass verification entirely

**Gap:**
- Phase 1a refactored query_pipeline to use `aggregate_results()` (code deduplication ✓)
- But query_pipeline's aggregations have NO corruption protection (verification ✗)
- Stated justification was "getting query_pipeline's totals under the same verification net"
- That didn't happen — verification benefit never landed

## Proposed Solution

Extract AGGREGATION_VERIFY's **core comparison logic** into a standalone function that:
- Takes **structured** handler output (not prose)
- Takes underlying data used to produce it
- Recomputes aggregations deterministically
- Compares structured output vs. recomputed values
- Returns match/discrepancy same format as existing verification

**Signature sketch:**
```python
def verify_structured_aggregations(
    underlying_data: List[dict],     # Raw deals/rows used for aggregation
    structured_output: dict,          # Handler's aggregated result
    verification_spec: dict,          # What to verify (see below)
    tolerance: float = 0.01           # Float comparison tolerance
) -> dict:
    """
    Verify structured aggregation outputs against underlying data.

    Returns:
        {"match": True} if all aggregations match within tolerance
        {"match": False, "discrepancies": [...]} if mismatches found
    """
```

**Verification spec example for query_pipeline:**
```python
{
    "total_pipeline": {
        "type": "sum",
        "field": "_incremental_value",
        "expected": structured_output["total_pipeline"]
    },
    "total_deals": {
        "type": "count",
        "expected": structured_output["total_deals"]
    },
    "by_stage": {
        "type": "group_by",
        "group_field": "_stage_label",
        "aggregations": {"count": "count", "value": "sum:_incremental_value"},
        "expected": structured_output["by_stage"]
    },
    "by_owner": {
        "type": "group_by",
        "group_field": "_owner",
        "aggregations": {"count": "count", "value": "sum:_incremental_value"},
        "expected": structured_output["by_owner"],
        "limit": 10  # Only top 10 verified
    }
}
```

## Integration Point

**In query_pipeline (api/handlers.py), before return statement:**

```python
# Verify aggregations before returning (Phase 1a+ structured verification)
from api.aggregation_verification import verify_structured_aggregations

verification_result = verify_structured_aggregations(
    underlying_data=incremental_deals,
    structured_output={
        "total_pipeline": total_pipeline,
        "total_deals": total_deals,
        "by_stage": by_stage,
        "by_owner": by_owner,
    },
    verification_spec={
        "total_pipeline": {
            "type": "sum",
            "field": "_incremental_value",
            "expected": total_pipeline
        },
        "total_deals": {
            "type": "count",
            "expected": total_deals
        },
        "by_stage": {
            "type": "group_by",
            "group_field": "_stage_label",
            "aggregations": {"count": "count", "value": "sum:_incremental_value"},
            "expected": by_stage
        },
        "by_owner": {
            "type": "group_by",
            "group_field": "_owner",
            "aggregations": {"count": "count", "value": "sum:_incremental_value"},
            "expected": by_owner,
            "limit": 10
        }
    },
    tolerance=0.01  # Same float tolerance as baseline tests
)

if not verification_result["match"]:
    # Corruption detected - return error instead of corrupted data
    logger.error(f"[AGGREGATION_VERIFY] Structured verification failed: "
                 f"{verification_result['discrepancies']}")
    return {
        "error": "aggregation_verification_failed",
        "discrepancies": verification_result["discrepancies"],
        "note": "Aggregation outputs did not match recomputed values from underlying data"
    }
```

## Test Strategy: Prove the Trap Springs

**Test file:** `tests/test_structured_aggregation_verification.py`

**Test case 1: Plant a total_pipeline discrepancy**
```python
def test_catches_wrong_total_pipeline():
    """Verify catches when total_pipeline != sum of underlying deals."""
    deals = [
        {"_incremental_value": 100000, "_stage_label": "Discovery"},
        {"_incremental_value": 200000, "_stage_label": "Scoping"},
        {"_incremental_value": 300000, "_stage_label": "Proposal"},
    ]

    # Plant a wrong total (should be 600000)
    result = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={"total_pipeline": 500000},  # WRONG
        verification_spec={
            "total_pipeline": {
                "type": "sum",
                "field": "_incremental_value",
                "expected": 500000
            }
        }
    )

    assert not result["match"]
    assert result["discrepancies"][0]["field"] == "total_pipeline"
    assert result["discrepancies"][0]["expected"] == 500000
    assert result["discrepancies"][0]["actual"] == 600000
```

**Test case 2: Plant a by_stage discrepancy**
```python
def test_catches_missing_stage_in_aggregation():
    """Verify catches when by_stage drops a stage entirely."""
    deals = [
        {"_incremental_value": 100000, "_stage_label": "Discovery"},
        {"_incremental_value": 200000, "_stage_label": "Scoping"},
        {"_incremental_value": 300000, "_stage_label": "Proposal"},
    ]

    # Plant wrong by_stage (drops Scoping)
    result = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={
            "by_stage": {
                "Discovery": {"count": 1, "value": 100000},
                "Proposal": {"count": 1, "value": 300000},
                # Scoping missing!
            }
        },
        verification_spec={
            "by_stage": {
                "type": "group_by",
                "group_field": "_stage_label",
                "aggregations": {"count": "count", "value": "sum:_incremental_value"},
                "expected": {
                    "Discovery": {"count": 1, "value": 100000},
                    "Proposal": {"count": 1, "value": 300000},
                }
            }
        }
    )

    assert not result["match"]
    assert "Scoping" in str(result["discrepancies"])
```

**Test case 3: Correct aggregations pass**
```python
def test_correct_aggregations_pass():
    """Verify doesn't false-alarm on correct aggregations."""
    deals = [
        {"_incremental_value": 100000, "_stage_label": "Discovery"},
        {"_incremental_value": 200000, "_stage_label": "Scoping"},
    ]

    result = verify_structured_aggregations(
        underlying_data=deals,
        structured_output={
            "total_pipeline": 300000,
            "by_stage": {
                "Discovery": {"count": 1, "value": 100000},
                "Scoping": {"count": 1, "value": 200000},
            }
        },
        verification_spec={
            "total_pipeline": {
                "type": "sum",
                "field": "_incremental_value",
                "expected": 300000
            },
            "by_stage": {
                "type": "group_by",
                "group_field": "_stage_label",
                "aggregations": {"count": "count", "value": "sum:_incremental_value"},
                "expected": {
                    "Discovery": {"count": 1, "value": 100000},
                    "Scoping": {"count": 1, "value": 200000},
                }
            }
        }
    )

    assert result["match"]
```

## Scope Assessment

**Is this appropriately scoped?**

✅ **YES** — this is a focused, valuable addition:

1. **Clear boundary:** Extract comparison logic only, not the prose extraction
2. **Reuses existing patterns:** Same discrepancy dict format as current AGGREGATION_VERIFY
3. **Single responsibility:** Verify structured data, not synthesize or route
4. **Testable:** Planted discrepancies prove the trap springs (standard gate tonight)
5. **Immediate value:** Protects query_pipeline (highest-traffic handler, 313 deals, $20M)
6. **Scales naturally:** Same function works for all Phase 1b handlers

**What it is NOT:**
- Not a full architectural refactor of AGGREGATION_VERIFY
- Not changing how dynamic_query_loop works
- Not adding new aggregation primitives
- Not rewriting synthesis or verification layers

**Estimated effort:**
- New function: ~100 lines (similar to verify_aggregation_completeness)
- Integration in query_pipeline: ~30 lines (before return statement)
- Tests: ~150 lines (3 core test cases + edge cases)
- Total: ~280 lines, single file change + new test file

**Risks:**
- Low: Self-contained function, doesn't touch existing verification
- If it catches real bugs in query_pipeline's aggregations, that's success (same as any gate)
- Worst case: False positives from float precision → adjust tolerance (0.01 already proven in baseline)

## Decision Point

**If yes:** Implement verify_structured_aggregations, wire into query_pipeline, prove trap springs with planted discrepancies, then apply to next handler in Phase 1b

**If bigger than expected:** Report back before committing, Phase 1b deduplication can proceed in parallel

## Files to Create/Modify

1. **New:** `api/structured_verification.py` — verify_structured_aggregations() function
2. **Modify:** `api/handlers.py` — query_pipeline() calls verification before return
3. **New:** `tests/test_structured_aggregation_verification.py` — prove trap springs
4. **Update:** `PRIMITIVE_CHECKLIST.md` — document new verification primitive

**No changes to:**
- api/router.py (AGGREGATION_VERIFY stays as-is)
- api/aggregation_verification.py (prose verification untouched)
- api/tools.py (aggregate_results unchanged)
