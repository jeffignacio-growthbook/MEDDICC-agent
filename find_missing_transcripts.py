"""Find calls with no transcript row."""
import sys
from pathlib import Path

# Add scripts to path
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))

from supabase_client import create_resilient_supabase_client
import os

sb = create_resilient_supabase_client(
    url=os.environ['SUPABASE_URL'],
    key=os.environ['SUPABASE_SERVICE_KEY']
)

# Get all fireflies call_ids from calls table
all_calls = sb.table('calls') \
    .select('call_id, call_date, company_name') \
    .eq('source', 'fireflies') \
    .execute()

print(f"Total fireflies calls: {len(all_calls.data)}")

# Get all call_ids that have transcript rows
transcripts = sb.table('call_transcripts') \
    .select('call_id') \
    .execute()

transcript_ids = {r['call_id'] for r in transcripts.data}
print(f"Total transcript rows: {len(transcript_ids)}")

# Find missing
missing = [c for c in all_calls.data if c['call_id'] not in transcript_ids]
print(f"Calls missing transcript rows: {len(missing)}")
print()

if missing:
    print("Sample missing transcripts:")
    for call in missing[:10]:
        company = call.get('company_name') or 'N/A'
        print(f"  {call['call_id']}: {call['call_date']} | {company[:40] if company != 'N/A' else company}")
