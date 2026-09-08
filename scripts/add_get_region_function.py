#!/usr/bin/env python3
"""
Add get_region() function to field_semantics.py.

Implements region classification with explicit UNKNOWN handling.
"""

import sys
from pathlib import Path
import yaml

# Read regions.yaml to generate the function
regions_yaml = Path(__file__).parent.parent / 'config' / 'regions.yaml'
with open(regions_yaml) as f:
    regions_config = yaml.safe_load(f)

region_defs = regions_config['region_definitions']

# Generate country -> region mapping
country_to_region = {}
for region, config in region_defs.items():
    if region == 'ROW':
        continue
    countries = config.get('countries', [])
    for country in countries:
        country_to_region[country] = region

print("Generated country -> region mapping:")
print(f"  Total countries: {len(country_to_region)}")
print(f"  Regions: {set(country_to_region.values())}")
print()

# Generate the function code
function_code = '''
# ============================================================================
# REGION CLASSIFICATION
# ============================================================================
# Maps company geography to sales regions (NAM, EMEA, APAC, LATAM, ROW).
# Data source: HubSpot Company.country property (90.9% coverage)
# See config/regions.yaml for full country mappings.
# ============================================================================

# Country -> Region mapping (generated from config/regions.yaml)
_COUNTRY_TO_REGION = {
'''

# Add country mappings (sorted for readability)
for country in sorted(country_to_region.keys()):
    region = country_to_region[country]
    function_code += f'    "{country}": "{region}",\n'

function_code += '''}

def get_region(deal: dict) -> str:
    """
    Get region for a deal using company geography.

    Primary classification: Use company_country from HubSpot (90.9% coverage)
    Fallback: Return UNKNOWN for deals with no geography (9.1%)

    Args:
        deal: Deal dict with company_country field

    Returns:
        "NAM" | "EMEA" | "APAC" | "LATAM" | "ROW" | "UNKNOWN"

    Examples:
        get_region({"company_country": "United Kingdom"}) -> "EMEA"
        get_region({"company_country": "United States"}) -> "NAM"
        get_region({"company_country": "India"}) -> "APAC"
        get_region({"company_country": None}) -> "UNKNOWN"

    Note:
        UNKNOWN is returned explicitly for 172 deals (9.1%) with no Company.country.
        These deals are NOT defaulted to NAM or ROW - they must be surfaced
        explicitly in reporting (same pattern as no_signal_at_risk).

        Region classification is based on REAL company geography from HubSpot,
        not owner assumption. For 90.9% of deals, this is accurate.
    """
    company_country = deal.get('company_country')

    # Explicit UNKNOWN handling - NOT defaulted to NAM/ROW
    if not company_country:
        return "UNKNOWN"

    # Map country to region
    region = _COUNTRY_TO_REGION.get(company_country, "ROW")

    return region
'''

print("Function code generated:")
print()
print(function_code)
print()
print("=" * 80)
print("NEXT STEP: Add this function to api/field_semantics.py")
print("=" * 80)
print()
print("Location: End of file, after existing functions")
print()
print("Then verify with:")
print("  python -c 'from api.field_semantics import get_region; print(get_region({\"company_country\": \"United Kingdom\"}))'")
