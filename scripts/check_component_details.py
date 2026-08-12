#!/usr/bin/env python3
"""Quick check of component_details in Supabase analyses table."""
import os
from supabase import create_client

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_KEY')

if not url or not key:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    exit(1)

sb = create_client(url, key)

# Query latest analyses with component_details
result = sb.table('analyses')\
    .select('deal_id, company_name, component_details, analyzed_at')\
    .not_.is_('component_details', 'null')\
    .order('analyzed_at', desc=True)\
    .limit(3)\
    .execute()

if not result.data:
    print("No analyses with component_details found")
    exit(0)

print(f"Found {len(result.data)} recent analyses with component_details:\n")

for row in result.data:
    print(f"Deal ID: {row['deal_id']}")
    print(f"Company: {row['company_name']}")
    print(f"Analyzed: {row['analyzed_at']}")
    print(f"Component Details:")

    import json
    details = row['component_details']
    if isinstance(details, str):
        details = json.loads(details)

    for component, data in details.items():
        print(f"  {component.upper():<20} score={data.get('score', 0):<2} status={data.get('status', 'unknown')}")
        evidence = data.get('evidence', '')[:100]
        if evidence:
            print(f"    Evidence: {evidence}...")
    print()
