#!/usr/bin/env python3
"""Run ETL in history mode with environment variables loaded."""
from dotenv import load_dotenv
load_dotenv()

import subprocess
import os
import sys

# Verify env vars
print(f"HUBSPOT_API_KEY: {'✓' if os.getenv('HUBSPOT_API_KEY') else '✗'}")
print(f"SUPABASE_URL: {'✓' if os.getenv('SUPABASE_URL') else '✗'}")
print()

# Run ETL
result = subprocess.run(
    ['python3', 'scripts/etl_deals.py', '--mode', 'history'],
    env=os.environ.copy()
)
sys.exit(result.returncode)
