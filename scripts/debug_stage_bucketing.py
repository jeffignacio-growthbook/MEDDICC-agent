"""
Debug: Why is stage_bucket returning 'unknown' for all stages?
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))

from field_semantics import stage_bucket, canonical_stage, STAGE_MAP

# Sample stage values that might appear in deals table
test_stages = [
    'Discovery',
    'Scoping',
    'Proposal',
    'Negotiating',
    'Closed Won',
    'Closed Lost',
    'appointmentscheduled',
    'presentationscheduled',
    '1297321623',  # numeric ID
]

print("Testing stage_bucket with various inputs:\n")
for stage in test_stages:
    canonical = canonical_stage(stage)
    bucket = stage_bucket(stage)
    print(f"  {stage:30} → canonical: {canonical:30} → bucket: {bucket}")

print("\n" + "=" * 80)
print("STAGE_MAP keys (first 10):")
print("=" * 80)
for i, key in enumerate(list(STAGE_MAP.keys())[:10]):
    print(f"  {key}")

print("\nTotal STAGE_MAP entries:", len(STAGE_MAP))
