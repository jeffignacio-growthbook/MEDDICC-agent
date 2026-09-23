"""Identify the 3 deferred Fireflies calls using backfill logic."""
import sys
from pathlib import Path

# Add scripts to path
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))

from supabase_client import SupabaseWriter, select_all
from transcript_store import is_done
import os

writer = SupabaseWriter()
client = writer.client

# Get all done call_ids (same logic as backfill)
rows = select_all(client, "call_transcripts",
                  columns="call_id,transcript_quality,unavailable_reason")

done_ids = {r["call_id"] for r in rows if r.get("call_id")
            and is_done(r.get("transcript_quality"), r.get("unavailable_reason"))}

print(f"Total done transcript IDs: {len(done_ids)}")

# Get all fireflies calls (same logic as backfill)
calls = select_all(client, "calls", columns="call_id,source,company_name,call_date",
                   filters=[("eq", "source", "fireflies")])

# Sort same way as backfill
calls = [c for c in calls if c.get("call_id")]
calls.sort(key=lambda r: str(r["call_id"]))

print(f"Total fireflies calls: {len(calls)}")

# Find not done
not_done = [c for c in calls if str(c["call_id"]) not in done_ids]
print(f"Not done (pending): {len(not_done)}")
print()

if not_done:
    print("First 10 pending calls (in backfill order):")
    for call in not_done[:10]:
        company = call.get('company_name') or 'N/A'
        print(f"  {call['call_id']}: {call['call_date']} | {company[:40] if company != 'N/A' else company}")
