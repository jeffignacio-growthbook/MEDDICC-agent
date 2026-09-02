#!/usr/bin/env python3
"""Check RLS policies on rep_targets table."""
import psycopg2
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

conn_string = os.getenv('SUPABASE_DB_URL')
if conn_string:
    conn_string = conn_string.strip('"').replace('\\!', '!')

conn = psycopg2.connect(conn_string)
cur = conn.cursor()

print('1. RLS Status:')
print('=' * 80)
cur.execute("SELECT relname, relrowsecurity FROM pg_class WHERE relname = 'rep_targets'")
rls = cur.fetchone()
if rls:
    print(f'Table: {rls[0]}')
    print(f'RLS Enabled: {rls[1]}')
else:
    print('Table not found')
print()

print('2. RLS Policies:')
print('=' * 80)
cur.execute("""
    SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual
    FROM pg_policies
    WHERE tablename = 'rep_targets'
""")
policies = cur.fetchall()
if policies:
    for p in policies:
        print(f'Policy: {p[2]}')
        print(f'  Schema: {p[0]}')
        print(f'  Permissive: {p[3]}')
        print(f'  Roles: {p[4]}')
        print(f'  Command: {p[5]}')
        print(f'  Qualifier: {p[6]}')
        print()
else:
    print('No RLS policies on rep_targets')
print()

cur.close()
conn.close()
