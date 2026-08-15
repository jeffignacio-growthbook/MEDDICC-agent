#!/usr/bin/env python3
"""
Export all HubSpot deals to CSV for offline ETL processing.
Avoids hitting API rate limits by doing a one-time export.
"""
import sys
import csv
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

from hubspot_deals import get_hubspot_deals_client

def export_deals():
    """Export all deals to CSV."""
    print("Connecting to HubSpot API...")
    hubspot = get_hubspot_deals_client()

    print("Fetching ALL deals (this may take a few minutes)...")
    deals = hubspot.get_all_deals_including_closed()
    print(f"Fetched {len(deals)} deals")

    # Output file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = REPO_ROOT / f"deals_export_{timestamp}.csv"

    print(f"\nWriting to {output_file}...")

    # Get all unique property keys across all deals
    all_keys = set()
    for deal in deals:
        all_keys.update(deal.keys())

    fieldnames = sorted(all_keys)

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deals)

    print(f"✓ Exported {len(deals)} deals to {output_file}")
    print(f"\nNow run:")
    print(f"  python scripts/etl_deals.py --mode analytics --file {output_file}")

    return output_file

if __name__ == "__main__":
    export_deals()
