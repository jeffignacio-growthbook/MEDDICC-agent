#!/usr/bin/env python3
"""Check what analyses exist in Supabase."""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))

# Load .env if it exists
from dotenv import load_dotenv
load_dotenv()

from supabase_client import SupabaseWriter

writer = SupabaseWriter()
sb = writer.client

# Get all analyses
result = sb.table('analyses').select('*').order('analyzed_at', desc=False).execute()
print(f'Total analyses: {len(result.data)}')
print()

for row in result.data:
    print(f"Deal ID: {row.get('deal_id')}")
    print(f"  Company: {row.get('company_name')}")
    print(f"  Analyzed at: {row.get('analyzed_at')}")
    print(f"  Overall score: {row.get('overall_score')}")
    print(f"  Output file: {row.get('output_file')}")
    print(f"  Stage: {row.get('stage_at_analysis')}")
    print()
