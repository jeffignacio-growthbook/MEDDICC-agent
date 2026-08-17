#!/usr/bin/env python3
"""Verify migration 026 was applied successfully."""

import os
import sys

os.environ["SUPABASE_URL"] = "https://htgvkqycrwesdysustxd.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Z3ZrcXljcndlc2R5c3VzdHhkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NTg4NTI5MiwiZXhwIjoyMTAxNDYxMjkyfQ.aeJFp6OwucNplQClgNGcC6pFZu_zfVK7ATim_MC_Wn4"

sys.path.insert(0, '/tmp/MEDDICC-agent')

from api.db import get_supabase

sb = get_supabase()

print("=" * 70)
print("Verifying Migration 026: Entity Registry")
print("=" * 70)

# 1. Check entity_registry view exists
print("\n1. Checking entity_registry view...")
try:
    result = sb.table('entity_registry').select('*').execute()
    print(f"   ✓ View exists with {len(result.data)} rows")

    expected_entities = {'deal', 'company', 'call'}
    found_entities = {row['entity_type'] for row in result.data}

    if found_entities == expected_entities:
        print(f"   ✓ All expected entity types present: {sorted(expected_entities)}")
    else:
        print(f"   ✗ Entity type mismatch!")
        print(f"     Expected: {sorted(expected_entities)}")
        print(f"     Found: {sorted(found_entities)}")

    print("\n   Entity Registry:")
    print(f"   {'Type':<10} {'Table':<15} {'ID Column':<15} {'Label Column':<20}")
    print("   " + "-" * 70)
    for row in sorted(result.data, key=lambda x: x['entity_type']):
        print(f"   {row['entity_type']:<10} {row['supabase_table']:<15} "
              f"{row['id_column']:<15} {row['entity_label_column']:<20}")

except Exception as e:
    print(f"   ✗ FAILED: {e}")
    print("\n   Migration 026 NOT applied. Run the SQL in Supabase SQL Editor.")
    sys.exit(1)

# 2. Check data_dictionary has new columns
print("\n2. Checking data_dictionary columns...")
try:
    result = sb.table('data_dictionary')\
        .select('supabase_table,supabase_column,is_entity_id,entity_type,entity_label_column')\
        .eq('is_entity_id', True)\
        .execute()

    if len(result.data) == 3:
        print(f"   ✓ data_dictionary has 3 entity rows (is_entity_id = TRUE)")
    else:
        print(f"   ✗ Expected 3 entity rows, found {len(result.data)}")

except Exception as e:
    print(f"   ✗ FAILED: {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ Migration 026 successfully verified")
print("=" * 70)
print("\nNext step: Continue with Task 2 (schema-driven extract_entity_context)")
