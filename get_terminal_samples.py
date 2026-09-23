"""Get sample terminal empty calls for spot-checking."""
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

# Get 5 sample terminal empty calls
result = sb.table('call_transcripts') \
    .select('call_id, transcript_quality, unavailable_reason') \
    .eq('transcript_quality', 'unavailable') \
    .like('unavailable_reason', 'terminal:%') \
    .limit(5) \
    .execute()

print(f'Found {len(result.data)} terminal empty samples:')
print()
terminal_calls = []
for row in result.data:
    print(f"  call_id={row['call_id']}")
    print(f"  reason={row['unavailable_reason']}")
    print()
    terminal_calls.append(row)

# Get call metadata for these IDs
call_ids = [row['call_id'] for row in result.data]
calls = sb.table('calls') \
    .select('call_id, source, company_name, call_date') \
    .in_('call_id', call_ids) \
    .execute()

print('=' * 80)
print('SPOT-CHECK SAMPLES (terminal empty calls):')
print('=' * 80)
for call in calls.data:
    print(f"call_id: {call['call_id']}")
    print(f"  source: {call['source']}")
    print(f"  company: {call['company_name']}")
    print(f"  date: {call['call_date']}")
    print()
