"""Spot-check terminal empty calls against live APIs."""
import sys
from pathlib import Path

# Add scripts to path
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts"))

# Sample terminal empty calls from database
SAMPLES = [
    {"call_id": "01KS2Z6CGYBD3PG65SCD57JZVA", "source": "fireflies", "date": "2026-05-21", "reason": "terminal: no transcript (124d-old call, none will appear)"},
    {"call_id": "01KS88YZ2J5V55HGC4EB90N348", "source": "fireflies", "date": "2026-05-22", "reason": "terminal: no transcript (123d-old call, none will appear)"},
    {"call_id": "698a5d42e4246200014a80f4", "source": "apollo", "date": "2026-02-09", "reason": "terminal: no transcript (225d-old call, none will appear)"},
    {"call_id": "69a9bf70d2ccb600017fd675", "source": "apollo", "date": "2026-03-05", "reason": "terminal: no transcript (201d-old call, none will appear)"},
    {"call_id": "6a9749c4620c05000185cde9", "source": "apollo", "date": "2026-09-01", "reason": "terminal: no transcript (21d-old call, none will appear)"},
]

print("=" * 80)
print("TERMINAL EMPTY SPOT-CHECK")
print("Testing 5 calls classified as 'terminal empty' against live APIs")
print("=" * 80)
print()

clients = {}

for i, sample in enumerate(SAMPLES, 1):
    call_id = sample["call_id"]
    source = sample["source"]
    date = sample["date"]
    reason = sample["reason"]

    print(f"{i}. call_id={call_id}")
    print(f"   source={source}, date={date}")
    print(f"   classified: {reason}")
    print()

    try:
        if source == "fireflies":
            from fireflies_client import FirefliesClient
            if "fireflies" not in clients:
                clients["fireflies"] = FirefliesClient()
            client = clients["fireflies"]

            # Same query as transcript_store.py _fetch_fireflies()
            q = ("query T($id:String!){ transcript(id:$id){ sentences "
                 "{ speaker_name text raw_text start_time end_time } } }")
            res = client._query(q, {"id": call_id})

            if res.get("errors"):
                msg = "; ".join(e.get("message", "")[:80] for e in res["errors"])
                print(f"   ❌ GraphQL Error: {msg}")
            else:
                sents = ((res.get("data") or {}).get("transcript") or {}).get("sentences") or []
                if not sents:
                    print(f"   ✅ CONFIRMED EMPTY: API returned 0 sentences")
                else:
                    # Count actual text content
                    with_text = [s for s in sents if (s.get("text") or s.get("raw_text") or "").strip()]
                    total_chars = sum(len((s.get("text") or s.get("raw_text") or "").strip()) for s in with_text)
                    print(f"   🚨 HAS CONTENT: API returned {len(sents)} sentences, {len(with_text)} with text, {total_chars} total chars")
                    # Sample first utterance
                    if with_text:
                        first = with_text[0]
                        speaker = first.get("speaker_name", "Unknown")
                        text = (first.get("text") or first.get("raw_text") or "")[:100]
                        print(f"   Sample: [{speaker}] {text}...")

        elif source == "apollo":
            from apollo_client import ApolloClient
            if "apollo" not in clients:
                clients["apollo"] = ApolloClient()
            client = clients["apollo"]

            # Same method as transcript_store.py _fetch_apollo()
            convo = client.get_conversation(call_id)
            transcript = convo.get("transcript") or []

            if not transcript:
                print(f"   ✅ CONFIRMED EMPTY: API returned 0 transcript fragments")
            else:
                # Count actual text content
                with_text = [f for f in transcript if (f.get("spoken_sentence") or f.get("text") or "").strip()]
                total_chars = sum(len((f.get("spoken_sentence") or f.get("text") or "").strip()) for f in with_text)
                print(f"   🚨 HAS CONTENT: API returned {len(transcript)} fragments, {len(with_text)} with text, {total_chars} total chars")
                # Sample first utterance
                if with_text:
                    first = with_text[0]
                    speaker = first.get("participant_name") or first.get("speaker") or "Unknown"
                    text = (first.get("spoken_sentence") or first.get("text") or "")[:100]
                    print(f"   Sample: [{speaker}] {text}...")

    except Exception as e:
        print(f"   ⚠️  ERROR: {type(e).__name__}: {str(e)[:200]}")

    print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print("Check complete. Review results above for:")
print("  ✅ CONFIRMED EMPTY = classification correct, no text at source")
print("  🚨 HAS CONTENT = classification WRONG, real transcript exists")
print()
