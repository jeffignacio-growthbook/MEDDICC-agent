"""Check the 3 deferred Fireflies calls."""
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

# Get all fireflies calls that are NOT done (retry or missing)
from transcript_store import is_done

# Get all call_transcripts rows for fireflies
all_transcripts = sb.table('call_transcripts') \
    .select('call_id, transcript_quality, unavailable_reason') \
    .execute()

# Filter for not done
not_done_ids = []
for row in all_transcripts.data:
    quality = row.get('transcript_quality')
    reason = row.get('unavailable_reason')
    if not is_done(quality, reason):
        not_done_ids.append(row['call_id'])

print(f"Found {len(not_done_ids)} not-done transcript rows total")
print()

# Get call metadata for fireflies calls that are not done
if not_done_ids:
    calls = sb.table('calls') \
        .select('call_id, source, company_name, call_date') \
        .in_('call_id', not_done_ids[:10]) \
        .eq('source', 'fireflies') \
        .execute()

    print(f"Fireflies calls pending retry:")
    for call in calls.data:
        # Get the transcript row for this call
        trans = next((r for r in all_transcripts.data if r['call_id'] == call['call_id']), None)
        if trans:
            print(f"  {call['call_id']}: {call['call_date']} | {trans.get('unavailable_reason', 'N/A')[:80]}")
