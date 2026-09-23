"""Verify the 3 deferred calls against Fireflies API."""
import sys
from pathlib import Path

# Add scripts to path
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))

DEFERRED_CALLS = [
    {"call_id": "01KZS0ABVTAQT52V5GPX2HS91A", "date": "2026-08-11"},  # 42 days old
    {"call_id": "01M0G0RMTHBW6179HQTHN8NPRH", "date": "2026-08-20"},  # 33 days old
    {"call_id": "01M14G4EKQ80XFSD57HT1C2WT2", "date": "2026-08-28"},  # 25 days old
]

print("=" * 80)
print("VERIFYING 3 DEFERRED FIREFLIES CALLS")
print("=" * 80)
print()

from fireflies_client import FirefliesClient
client = FirefliesClient()

for i, call in enumerate(DEFERRED_CALLS, 1):
    call_id = call["call_id"]
    date = call["date"]

    print(f"{i}. call_id={call_id}, date={date}")

    # Same query as transcript_store.py _fetch_fireflies()
    q = ("query T($id:String!){ transcript(id:$id){ sentences "
         "{ speaker_name text raw_text start_time end_time } } }")

    try:
        res = client._query(q, {"id": call_id})

        if res.get("errors"):
            msg = "; ".join(e.get("message", "")[:80] for e in res["errors"])
            print(f"   ❌ GraphQL Error: {msg}")
            print(f"   → Should be marked TERMINAL (old call, API confirms not found)")
        else:
            sents = ((res.get("data") or {}).get("transcript") or {}).get("sentences") or []
            if not sents:
                print(f"   ✅ API returned 0 sentences (empty but valid response)")
                print(f"   → Should be marked TERMINAL (empty transcript, not processing)")
            else:
                with_text = [s for s in sents if (s.get("text") or s.get("raw_text") or "").strip()]
                total_chars = sum(len((s.get("text") or s.get("raw_text") or "").strip()) for s in with_text)
                print(f"   🎉 HAS CONTENT: {len(sents)} sentences, {len(with_text)} with text, {total_chars} chars")
                print(f"   → Misclassified! Should write this transcript")
    except Exception as e:
        print(f"   ⚠️  ERROR: {type(e).__name__}: {str(e)[:200]}")

    print()

print("=" * 80)
print("RECOMMENDATION")
print("=" * 80)
print("If all 3 show 'GraphQL Error: Transcript not found' or empty:")
print("  → These are genuinely unavailable, mark as terminal")
print("  → Write terminal rows so backfill stops retrying them")
print()
