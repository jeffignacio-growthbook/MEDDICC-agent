#!/usr/bin/env python3
"""Check ALL deals in renewal-arr.csv for pipeline distribution."""
from dotenv import load_dotenv
load_dotenv()

import os
import csv
import requests
from collections import Counter
import time

csv_path = "/Users/jeffignacio/Downloads/HubSpot Custom Report Renewal Aug 28 2026/renewal-arr.csv"

# Read all deal IDs from CSV
deal_ids = []
with open(csv_path, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        deal_ids.append(row['Deal ID'])

print(f"Checking all {len(deal_ids)} deals from CSV...")
print("=" * 70)

api_key = os.getenv("HUBSPOT_API_KEY")
headers = {"Authorization": f"Bearer {api_key}"}

pipeline_counts = Counter()
renewal_deals_in_csv = []
default_deals_in_csv = []

for i, deal_id in enumerate(deal_ids):
    if (i + 1) % 50 == 0:
        print(f"  Checked {i + 1}/{len(deal_ids)} deals...")

    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {"properties": "pipeline,dealname"}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        pipeline = data.get("properties", {}).get("pipeline", "unknown")
        pipeline_counts[pipeline] += 1

        if pipeline == "866608541":
            renewal_deals_in_csv.append(deal_id)
        elif pipeline == "default":
            default_deals_in_csv.append(deal_id)

    # Rate limit: ~10 requests/second
    time.sleep(0.11)

print(f"  Checked {len(deal_ids)}/{len(deal_ids)} deals...")
print("\n" + "=" * 70)
print("Pipeline distribution in CSV:")
for pipeline, count in pipeline_counts.most_common():
    pct = (count / len(deal_ids)) * 100
    pipeline_name = "RENEWAL" if pipeline == "866608541" else "DEFAULT" if pipeline == "default" else pipeline
    print(f"  {pipeline_name:20} ({pipeline:12}): {count:3} deals ({pct:5.1f}%)")

print("\n" + "=" * 70)
print(f"Renewal pipeline deals in CSV: {len(renewal_deals_in_csv)}")
print(f"Default pipeline deals in CSV: {len(default_deals_in_csv)}")

# Write renewal deal IDs to file for comparison
with open("/tmp/csv_renewal_deals.txt", "w") as f:
    for deal_id in renewal_deals_in_csv:
        f.write(f"{deal_id}\n")

print(f"\nWrote {len(renewal_deals_in_csv)} renewal deal IDs to /tmp/csv_renewal_deals.txt")
