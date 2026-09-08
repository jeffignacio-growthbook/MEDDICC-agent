"""
Select Boundary Case Deals for Slack Validation

Pull Enterprise Discovery deals at 30-50 days (around the 35-day threshold)
to test calibration, not just obvious 100+ day stale deals.

These boundary cases actually test whether 35 days is well-calibrated.
"""

# From check_enterprise_discovery_fallback.py, Enterprise Discovery deals:
enterprise_discovery_deals = [
    # WAY OVER threshold (obvious stale - don't test threshold calibration)
    {'name': 'Rippling', 'days': 130, 'value': 0, 'activity_days_ago': 82},
    {'name': 'Comcast', 'days': 130, 'value': 350000, 'activity_days_ago': 103},
    {'name': 'DM', 'days': 116, 'value': 0, 'activity_days_ago': 111},
    {'name': 'Square', 'days': 110, 'value': 0, 'activity_days_ago': 96},
    {'name': 'Khan Academy', 'days': 102, 'value': 0, 'activity_days_ago': None},
    {'name': 'Zocdoc', 'days': 102, 'value': 150000, 'activity_days_ago': None},
    {'name': '1800Flowers', 'days': 96, 'value': 0, 'activity_days_ago': None},
    {'name': 'Solotopia', 'days': 95, 'value': 0, 'activity_days_ago': 94},
    {'name': 'RingCentral', 'days': 94, 'value': 0, 'activity_days_ago': None},
    {'name': 'Signet Jewelers Ltd.', 'days': 94, 'value': 100000, 'activity_days_ago': None},
    {'name': 'Douglas', 'days': 91, 'value': 0, 'activity_days_ago': 7},
    {'name': 'Genius Sports', 'days': 88, 'value': 150000, 'activity_days_ago': 5},
    {'name': 'Zurich Insurance Group Ltd', 'days': 87, 'value': 50000, 'activity_days_ago': 95},
    {'name': 'Decathlon', 'days': 83, 'value': 0, 'activity_days_ago': 25},
    {'name': 'Stitch Fix', 'days': 74, 'value': 150000, 'activity_days_ago': None},
    {'name': 'Wipro', 'days': 70, 'value': 0, 'activity_days_ago': 51},
    {'name': 'Brussels Airlines', 'days': 66, 'value': 200000, 'activity_days_ago': 53},
    {'name': 'The New York Times', 'days': 61, 'value': 0, 'activity_days_ago': 3},
    {'name': 'Carrefour', 'days': 61, 'value': 200000, 'activity_days_ago': 61},
    {'name': 'DocPlanner', 'days': 59, 'value': 125000, 'activity_days_ago': 26},
    {'name': 'TRT', 'days': 59, 'value': 80000, 'activity_days_ago': 40},
    {'name': 'Deel', 'days': 55, 'value': 175000, 'activity_days_ago': 19},
    {'name': 'GitLab Inc.', 'days': 54, 'value': 250000, 'activity_days_ago': None},
    {'name': 'Amazon', 'days': 53, 'value': 0, 'activity_days_ago': 33},

    # BOUNDARY CASES (30-50 days - THESE TEST THE THRESHOLD)
    {'name': 'Hy-Vee', 'days': 44, 'value': 0, 'activity_days_ago': 13},
    {'name': 'Electronic Arts', 'days': 37, 'value': 200000, 'activity_days_ago': 12},
    {'name': 'Expedia Group', 'days': 37, 'value': 62000, 'activity_days_ago': 10},
    {'name': 'Virgin Media O2 UK Limited', 'days': 35, 'value': 100000, 'activity_days_ago': 21},
    {'name': 'Zynga', 'days': 32, 'value': 0, 'activity_days_ago': None},
    {'name': 'Guidepoint', 'days': 32, 'value': 0, 'activity_days_ago': 12},

    # NEWLY HEALTHY under 35d override (were flagged under 19d)
    {'name': 'Zurich Insurance Group', 'days': 28, 'value': 74400, 'activity_days_ago': 5},
    {'name': 'Zurich Insurance', 'days': 27, 'value': 100000, 'activity_days_ago': 27},
    {'name': 'ATrack Solutions', 'days': 25, 'value': 0, 'activity_days_ago': 25},
    {'name': 'Robinhood', 'days': 20, 'value': 150000, 'activity_days_ago': 19},

    # HEALTHY (well below threshold - control group)
    {'name': 'Royal Caribbean International', 'days': 19, 'value': 0, 'activity_days_ago': None},
    {'name': 'Salesforce', 'days': 17, 'value': 100000, 'activity_days_ago': None},
    {'name': 'Kaizen Gaming', 'days': 12, 'value': 0, 'activity_days_ago': None},
    {'name': 'Tubi', 'days': 10, 'value': 500000, 'activity_days_ago': None},
]

print("=" * 80)
print("BOUNDARY CASE SELECTION FOR SLACK VALIDATION")
print("=" * 80)

print("\nObjective: Test threshold calibration with deals NEAR 35-day line,")
print("not just obvious 100+ day stale deals.\n")

# Categorize by distance from threshold
obvious_stale = [d for d in enterprise_discovery_deals if d['days'] > 60]
boundary_flagged = [d for d in enterprise_discovery_deals if 35 < d['days'] <= 60]
boundary_healthy = [d for d in enterprise_discovery_deals if 25 <= d['days'] <= 35]
clearly_healthy = [d for d in enterprise_discovery_deals if d['days'] < 25]

print("=" * 80)
print("DEAL CATEGORIES")
print("=" * 80)

print(f"\nObvious stale (>60 days): {len(obvious_stale)} deals")
print(f"  Don't test threshold - everyone agrees these are stale")

print(f"\nBoundary flagged (35-60 days): {len(boundary_flagged)} deals")
print(f"  Recently crossed threshold - THESE TEST if 35d is too low")

print(f"\nBoundary healthy (25-35 days): {len(boundary_healthy)} deals")
print(f"  Just under threshold - THESE TEST if 35d is too high")

print(f"\nClearly healthy (<25 days): {len(clearly_healthy)} deals")
print(f"  Control group - everyone agrees these are normal")

# Select validation sample
print("\n" + "=" * 80)
print("RECOMMENDED VALIDATION SAMPLE")
print("=" * 80)

print("\n1. Include ONE obvious stale deal (proves system works):")
obvious_sample = sorted(obvious_stale, key=lambda x: -x['days'])[:1]
for deal in obvious_sample:
    act = f"{deal['activity_days_ago']}d ago" if deal['activity_days_ago'] else "no data"
    print(f"   - {deal['name']}: {deal['days']}d, ${deal['value']:,}, activity {act}")

print("\n2. Include ALL boundary flagged deals (test if 35d too low):")
for deal in sorted(boundary_flagged, key=lambda x: -x['days']):
    act = f"{deal['activity_days_ago']}d ago" if deal['activity_days_ago'] else "no data"
    print(f"   - {deal['name']}: {deal['days']}d, ${deal['value']:,}, activity {act}")

print("\n3. Include ALL boundary healthy deals (test if 35d too high):")
for deal in sorted(boundary_healthy, key=lambda x: -x['days']):
    act = f"{deal['activity_days_ago']}d ago" if deal['activity_days_ago'] else "no data"
    print(f"   - {deal['name']}: {deal['days']}d, ${deal['value']:,}, activity {act}")

print("\n4. Include ONE clearly healthy deal (control):")
healthy_sample = [d for d in clearly_healthy if d['value'] > 0][:1]
for deal in healthy_sample:
    act = f"{deal['activity_days_ago']}d ago" if deal['activity_days_ago'] else "no data"
    print(f"   - {deal['name']}: {deal['days']}d, ${deal['value']:,}, activity {act}")

# Generate sample
full_sample = obvious_sample + boundary_flagged + boundary_healthy + healthy_sample

print("\n" + "=" * 80)
print(f"FULL VALIDATION SAMPLE (n={len(full_sample)})")
print("=" * 80)

print("\nDeals to review with sales team:\n")
for i, deal in enumerate(full_sample, 1):
    act = f"{deal['activity_days_ago']}d ago" if deal['activity_days_ago'] else "no data"

    # Classification
    if deal['days'] > 35:
        if deal['activity_days_ago'] and deal['activity_days_ago'] > 14:
            classification = "CRITICAL"
        elif deal['activity_days_ago'] and deal['activity_days_ago'] <= 14:
            classification = "WARN"
        else:
            classification = "no_signal_at_risk"
    else:
        classification = "HEALTHY"

    print(f"{i:2}. {deal['name']} ({classification})")
    print(f"    Time in Discovery: {deal['days']} days")
    print(f"    Deal value: ${deal['value']:,}")
    print(f"    Last activity: {act}")
    print()

print("=" * 80)
print("KEY INSIGHT")
print("=" * 80)

print("""
The boundary cases (deals at 30-50 days) are where sales team gut-check
actually tests threshold calibration.

If they say deals at 35-45 days are "normal, actively working":
→ 35-day threshold is TOO LOW (consider raising to 45-60d)

If they say deals at 30-35 days are "concerning, should be flagged":
→ 35-day threshold is TOO HIGH (consider lowering to 25-30d)

If they agree with system classification on boundary cases:
→ 35-day threshold is WELL-CALIBRATED

The 100+ day deals (Comcast, Rippling) don't test this - everyone agrees
they're stale regardless of threshold.
""")
