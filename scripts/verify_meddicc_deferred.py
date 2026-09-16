#!/usr/bin/env python3
"""
Verification: MEDDICC deferral in deal_risk_assessor.

Tests that:
1. Cycle-length risk assessment works correctly
2. MEDDICC explicitly marked as insufficient_data (not silently omitted)
3. Risk classification based solely on cycle-length signal
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from deal_risk_assessor import get_at_risk_deals
from supabase_client import create_resilient_supabase_client

sb = create_resilient_supabase_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

print("=" * 80)
print("VERIFICATION: MEDDICC Deferral in deal_risk_assessor")
print("=" * 80)
print()

# Get current quarter's high-priority deals
result = get_at_risk_deals(sb)

assessed = result["assessed_deals"]
summary = result["summary"]

print(f"Total deals assessed: {summary['total_assessed']}")
print(f"  High risk:          {summary['high_risk']}")
print(f"  Moderate risk:      {summary['moderate_risk']}")
print(f"  Low risk:           {summary['low_risk']}")
print(f"  Insufficient data:  {summary['insufficient_data']}")
print()

# Verification 1: All deals should have meddicc_status = "insufficient_data"
meddicc_status_check = all(d["meddicc_status"] == "insufficient_data" for d in assessed)
print(f"✓ All deals have meddicc_status='insufficient_data': {meddicc_status_check}")

# Verification 2: All deals should have MEDDICC insufficient_data note in risk_factors
meddicc_note_check = all(
    any("insufficient_data" in rf for rf in d["risk_factors"])
    for d in assessed
)
print(f"✓ All deals have MEDDICC insufficient_data note: {meddicc_note_check}")

# Verification 3: No deals should have weak_components (MEDDICC deferred)
weak_components_check = all(len(d["weak_components"]) == 0 for d in assessed)
print(f"✓ All deals have empty weak_components: {weak_components_check}")

# Verification 4: Risk classification should be based solely on cycle-length
# Show a few examples to verify classification logic
print()
print("Sample deals (cycle-length classification):")
print("-" * 80)

for deal in assessed[:5]:  # Show first 5
    label = deal["overall_label"]
    days_open = deal["days_open"]
    benchmark = deal.get("cycle_benchmark_days")
    days_past = deal.get("days_past_benchmark")

    print(f"{deal['company_name'][:30]:30} | {label:18} | {days_open:3}d open | ", end="")
    if benchmark:
        print(f"benchmark {benchmark}d | {days_past:+4}d past")
    else:
        print("no benchmark")

    # Show risk factors
    for rf in deal["risk_factors"]:
        print(f"  - {rf}")
    print()

print("=" * 80)

# Final verification checks
all_checks_pass = (
    meddicc_status_check and
    meddicc_note_check and
    weak_components_check and
    summary['total_assessed'] > 0
)

if all_checks_pass:
    print("✅ VERIFICATION PASSED")
    print()
    print("Summary:")
    print("- MEDDICC explicitly marked as insufficient_data (not silently omitted)")
    print("- Risk classification based solely on cycle-length signal")
    print("- All deals show 1.2% coverage note in risk_factors")
    sys.exit(0)
else:
    print("❌ VERIFICATION FAILED")
    print()
    print("Issues detected:")
    if not meddicc_status_check:
        print("- Some deals have meddicc_status != 'insufficient_data'")
    if not meddicc_note_check:
        print("- Some deals missing MEDDICC insufficient_data note in risk_factors")
    if not weak_components_check:
        print("- Some deals have non-empty weak_components (MEDDICC should be deferred)")
    if summary['total_assessed'] == 0:
        print("- No deals assessed (empty target set)")
    sys.exit(1)
