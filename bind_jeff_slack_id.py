#!/usr/bin/env python3
"""Bind Jeff's Slack user ID to his persona."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))
from api.db import get_supabase

sb = get_supabase()

print("\n" + "="*80)
print("BINDING SLACK USER ID TO PERSONA")
print("="*80)

# Update slack_user_id
print("\n1. Updating slack_user_id for jeff.ignacio@growthbook.io...")
result = sb.table('user_personas').update({
    'slack_user_id': 'U07B3Q0TRGR'
}).eq('email', 'jeff.ignacio@growthbook.io').execute()

print(f"   ✓ Updated {len(result.data)} row(s)")

# Verify
print("\n2. Verifying update...")
verify = sb.table('user_personas').select(
    'name,role,role_group,slack_user_id,email'
).eq('email', 'jeff.ignacio@growthbook.io').execute()

if verify.data:
    persona = verify.data[0]
    print(f"   Name:          {persona.get('name')}")
    print(f"   Email:         {persona.get('email')}")
    print(f"   Role:          {persona.get('role')}")
    print(f"   Role Group:    {persona.get('role_group')}")
    print(f"   Slack User ID: {persona.get('slack_user_id')}")
    print("\n   ✓ Slack ID bound successfully")
else:
    print("   ✗ Persona not found")

print("\n" + "="*80 + "\n")
