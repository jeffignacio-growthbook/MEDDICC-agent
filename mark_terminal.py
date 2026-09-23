"""Mark the 3 deferred calls as terminal unavailable."""
import sys
from pathlib import Path

# Add scripts to path
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))

from supabase_client import SupabaseWriter
from datetime import date

DEFERRED_CALLS = [
    {"call_id": "01KZS0ABVTAQT52V5GPX2HS91A", "date": "2026-08-11"},
    {"call_id": "01M0G0RMTHBW6179HQTHN8NPRH", "date": "2026-08-20"},
    {"call_id": "01M14G4EKQ80XFSD57HT1C2WT2", "date": "2026-08-28"},
]

writer = SupabaseWriter()

rows = []
for call in DEFERRED_CALLS:
    call_id = call["call_id"]
    call_date = date.fromisoformat(call["date"])
    age = (date.today() - call_date).days

    row = {
        "call_id": call_id,
        "transcript_quality": "unavailable",
        "unavailable_reason": f"terminal: no transcript ({age}d-old call, API: Transcript not found)",
        "transcript_text": None,
        "talk_time_seconds": None,
        "questions_asked": None,
        "longest_monologue_seconds": None,
    }
    rows.append(row)

print("Writing 3 terminal unavailable rows:")
for row in rows:
    print(f"  {row['call_id']}: {row['unavailable_reason']}")

writer.upsert_call_transcripts(rows)

print()
print("✅ Done. These calls will now be skipped by future backfill runs.")
