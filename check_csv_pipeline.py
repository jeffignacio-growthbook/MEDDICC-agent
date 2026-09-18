#!/usr/bin/env python3
"""Check which pipeline the renewal-arr.csv deals are actually in."""
from dotenv import load_dotenv
load_dotenv()

import os
import csv
import requests
from collections import Counter

csv_path = "/Users/jeffignacio/Downloads/HubSpot Custom Report Renewal Aug 28 2026/renewal-arr.csv"

# Read all deal IDs from CSV
deal_ids = []
with open(csv_path, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        deal_ids.append(row['Deal ID'])

print(f"Found {len(deal_ids)} deals in CSV")
print(f"Sampling first 50 to check pipeline distribution...")
print("=" * 70)

api_key = os.getenv("HUBSPOT_API_KEY")
headers = {"Authorization": f"Bearer {api_key}"}

pipeline_counts = Counter()
sample_size = min(50, len(deal_ids))

for i, deal_id in enumerate(deal_ids[:sample_size]):
    url = f"https://api.hubapi.com/crm/v3/objects/deals/{deal_id}"
    params = {"properties": "pipeline,dealname,dealstage"}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        pipeline = data.get("properties", {}).get("pipeline", "unknown")
        pipeline_counts[pipeline] += 1

        if i < 5:  # Show first 5 in detail
            name = data.get("properties", {}).get("dealname", "N/A")
            stage = data.get("properties", {}).get("dealstage", "N/A")
            print(f"{deal_id} | {pipeline} | {name[:40]}")

print("\n" + "=" * 70)
print(f"Pipeline distribution (sample of {sample_size} deals):")
for pipeline, count in pipeline_counts.most_common():
    pct = (count / sample_size) * 100
    pipeline_name = "RENEWAL" if pipeline == "866608541" else "DEFAULT" if pipeline == "default" else pipeline
    print(f"  {pipeline_name:20} ({pipeline:12}): {count:3} deals ({pct:5.1f}%)")

print("\n" + "=" * 70)
if "866608541" in pipeline_counts:
    renewal_pct = (pipeline_counts["866608541"] / sample_size) * 100
    estimated_renewal = int((len(deal_ids) * renewal_pct) / 100)
    print(f"Estimated renewal pipeline deals in full CSV: ~{estimated_renewal} of {len(deal_ids)}")
else:
    print("WARNING: No renewal pipeline (866608541) deals found in sample")
