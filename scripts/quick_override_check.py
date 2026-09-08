"""
Quick Enterprise Discovery Override Check

Use cached results from clean derivation, just adjust Enterprise Discovery
threshold from 19d to 35d and report new flagging rate.
"""

# From signal2_clean_derivation.txt, we know:
# - Enterprise Discovery deals flagged under 19d fallback: 34/46 (73.9%)
# - These deals have time_in_stage ranging 20-130 days

# Sample of Enterprise Discovery deals from check_enterprise_discovery_fallback.py:
enterprise_discovery_deals = [
    {'name': 'Rippling', 'days': 130},
    {'name': 'Comcast', 'days': 130},
    {'name': 'DM', 'days': 116},
    {'name': 'Square', 'days': 110},
    {'name': 'Khan Academy', 'days': 102},
    {'name': 'Zocdoc', 'days': 102},
    {'name': '1800Flowers', 'days': 96},
    {'name': 'Solotopia', 'days': 95},
    {'name': 'RingCentral', 'days': 94},
    {'name': 'Signet Jewelers Ltd.', 'days': 94},
    {'name': 'Douglas', 'days': 91},
    {'name': 'Genius Sports', 'days': 88},
    {'name': 'Zurich Insurance Group Ltd', 'days': 87},
    {'name': 'Decathlon', 'days': 83},
    {'name': 'Stitch Fix', 'days': 74},
    {'name': 'Wipro', 'days': 70},
    {'name': 'Brussels Airlines', 'days': 66},
    {'name': 'The New York Times', 'days': 61},
    {'name': 'Carrefour', 'days': 61},
    {'name': 'DocPlanner', 'days': 59},
    {'name': 'TRT', 'days': 59},
    {'name': 'Deel', 'days': 55},
    {'name': 'GitLab Inc.', 'days': 54},
    {'name': 'Amazon', 'days': 53},
    {'name': 'Hy-Vee', 'days': 44},
    {'name': 'Electronic Arts', 'days': 37},
    {'name': 'Expedia Group', 'days': 37},
    {'name': 'Virgin Media O2 UK Limited', 'days': 35},
    {'name': 'Zynga', 'days': 32},
    {'name': 'Guidepoint', 'days': 32},
    {'name': 'Zurich Insurance Group', 'days': 28},
    {'name': 'Zurich Insurance', 'days': 27},
    {'name': 'ATrack Solutions', 'days': 25},
    {'name': 'Robinhood', 'days': 20},
    # Healthy deals (≤19 days)
    {'name': 'Royal Caribbean International', 'days': 19},
    {'name': 'Salesforce', 'days': 17},
    {'name': 'Kaizen Gaming', 'days': 12},
    {'name': 'Signature Aviation', 'days': 11},
    {'name': 'Tubi', 'days': 10},
    {'name': 'Noxtua', 'days': 10},
    {'name': 'Grupo SBF RI', 'days': 10},
    {'name': 'Centerfield', 'days': 9},
    {'name': 'Vi', 'days': 5},
    {'name': 'SATS', 'days': 5},
    {'name': 'DoorDash', 'days': 4},
    {'name': 'Clipboard', 'days': 4},
]

print("=" * 80)
print("ENTERPRISE DISCOVERY OVERRIDE IMPACT")
print("=" * 80)

# Count under 19-day threshold
flagged_19d = [d for d in enterprise_discovery_deals if d['days'] > 19]
healthy_19d = [d for d in enterprise_discovery_deals if d['days'] <= 19]

# Count under 35-day override
flagged_35d = [d for d in enterprise_discovery_deals if d['days'] > 35]
healthy_35d = [d for d in enterprise_discovery_deals if d['days'] <= 35]

# Newly healthy (between 19-35 days)
newly_healthy = [d for d in enterprise_discovery_deals if 19 < d['days'] <= 35]

print(f"\nTotal Enterprise Discovery deals: {len(enterprise_discovery_deals)}")

print("\n" + "-" * 80)
print("19-DAY FALLBACK (CLEAN DERIVATION)")
print("-" * 80)
print(f"  Flagged (>19 days): {len(flagged_19d)}/{len(enterprise_discovery_deals)} ({len(flagged_19d)/len(enterprise_discovery_deals)*100:.1f}%)")
print(f"  Healthy (≤19 days): {len(healthy_19d)}/{len(enterprise_discovery_deals)} ({len(healthy_19d)/len(enterprise_discovery_deals)*100:.1f}%)")

print("\n" + "-" * 80)
print("35-DAY MANUAL OVERRIDE")
print("-" * 80)
print(f"  Flagged (>35 days): {len(flagged_35d)}/{len(enterprise_discovery_deals)} ({len(flagged_35d)/len(enterprise_discovery_deals)*100:.1f}%)")
print(f"  Healthy (≤35 days): {len(healthy_35d)}/{len(enterprise_discovery_deals)} ({len(healthy_35d)/len(enterprise_discovery_deals)*100:.1f}%)")

print("\n" + "-" * 80)
print("CHANGE")
print("-" * 80)
print(f"  Flagging rate: {len(flagged_19d)/len(enterprise_discovery_deals)*100:.1f}% → {len(flagged_35d)/len(enterprise_discovery_deals)*100:.1f}%")
print(f"  Reduction: {len(flagged_19d) - len(flagged_35d)} deals no longer flagged")

print("\n" + "=" * 80)
print(f"NEWLY HEALTHY DEALS (20-35 days, n={len(newly_healthy)})")
print("=" * 80)

print("\nDeals that were flagged under 19d but healthy under 35d:\n")
for deal in sorted(newly_healthy, key=lambda x: -x['days']):
    print(f"  {deal['name']}: {deal['days']} days")

print("\n" + "=" * 80)
print(f"STILL FLAGGED DEALS (>35 days, n={len(flagged_35d)})")
print("=" * 80)

print("\nTop 10 by time in stage:\n")
for deal in sorted(flagged_35d, key=lambda x: -x['days'])[:10]:
    print(f"  {deal['name']}: {deal['days']} days")

# Assessment
print("\n" + "=" * 80)
print("ASSESSMENT")
print("=" * 80)

flagging_rate = len(flagged_35d)/len(enterprise_discovery_deals)*100

if flagging_rate < 30:
    print(f"\n✅ REASONABLE FLAGGING RATE ({flagging_rate:.1f}%)")
    print("   Less than 30% of Enterprise Discovery deals flagged.")
    print("   35-day override appears appropriate for Enterprise evaluation cycles.")
elif flagging_rate < 50:
    print(f"\n⚠️  MODERATE FLAGGING RATE ({flagging_rate:.1f}%)")
    print("   30-50% of Enterprise Discovery deals flagged.")
    print("   This is a significant portion, but may reflect real pipeline issues.")
    print("   Review flagged deals - deals >35 days should be genuinely at-risk.")
else:
    print(f"\n⚠️  STILL HIGH FLAGGING RATE ({flagging_rate:.1f}%)")
    print("   More than 50% of Enterprise Discovery deals still flagged.")
    print("   May need higher override (45-60 days) or indicates real pipeline issue.")

print("\n" + "=" * 80)
print("OVERALL IMPACT ON CLASSIFICATION")
print("=" * 80)

# From signal2_clean_derivation.txt:
# Total at-risk with 19d: 149 deals (102 CRITICAL + 47 WARN)
# Enterprise Discovery contributed: ~15-20 deals to at-risk

reduction_in_flagged = len(flagged_19d) - len(flagged_35d)
estimated_new_total_at_risk = 149 - reduction_in_flagged

print(f"\nEstimated impact on overall at-risk count:")
print(f"  With 19d fallback: 149 at-risk deals (33.6% of pipeline)")
print(f"  With 35d override: ~{estimated_new_total_at_risk} at-risk deals (~{estimated_new_total_at_risk/444*100:.1f}% of pipeline)")
print(f"  Reduction: ~{reduction_in_flagged} deals")

print("\n" + "=" * 80)
print("✅ OVERRIDE CHECK COMPLETE")
print("=" * 80)

print("\nNext steps:")
print("  1. Update config/field_semantics.yaml with MANUAL_OVERRIDE status")
print("  2. Document rationale: 73.9% → {:.1f}% flagging rate".format(flagging_rate))
print("  3. Set re-derivation trigger: n≥5 Enterprise Discovery clean won deals")
print("  4. Proceed to Slack validation")
