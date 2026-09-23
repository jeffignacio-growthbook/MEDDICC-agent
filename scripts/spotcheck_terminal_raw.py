#!/usr/bin/env python3
"""
Step 6 spot-check: full RAW content (not just sentence/participant counts) for
3 of the 90 terminal-empty calls, fetched directly from the live source using
the same production credentials as scripts/transcript_store.py — to rule out
the raw-inspection diagnostic's own counting logic being wrong, not just to
re-confirm a Supabase row.

2 Fireflies (most-recent 5d-old call + a mid-range 124d-old call) + the 1
Apollo call with the longest duration (161s) of the 3 terminal Apollo rows —
the single best chance of hidden real content if the earlier zero-sentence
finding were somehow an artifact.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


def main():
    from fireflies_client import FirefliesClient
    from apollo_client import ApolloClient

    ff = FirefliesClient()
    apollo = ApolloClient()

    print("=" * 100)
    print("FIREFLIES — full raw query (title, duration, ALL sentence fields verbatim)")
    print("=" * 100)
    q = """query T($id:String!){ transcript(id:$id){
        title duration date
        meeting_attendees { displayName email }
        sentences { speaker_name text raw_text start_time end_time }
    } }"""
    for cid, label in [("01M2MCE3GARARD7BKA8WX3VGHT", "5d old, 'Demo Call with Sushant Singh from Vetic'"),
                        ("01KS2Z6CGYBD3PG65SCD57JZVA", "124d old, 'GrowthBook Demo for Kiosk'")]:
        print(f"\n--- {cid} ({label}) ---")
        res = ff._query(q, {"id": cid})
        print(f"RAW RESPONSE: {res}")

    print("\n" + "=" * 100)
    print("APOLLO — full raw conversation object verbatim (longest-duration terminal call)")
    print("=" * 100)
    cid = "6a9749c4620c05000185cde9"  # 161s duration, state=insights_generated
    convo = apollo.get_conversation(cid)
    print(f"\n--- {cid} (Call with Mouna Chenfouri, 161s, insights_generated) ---")
    print(f"RAW RESPONSE: {convo}")

    print("\nDONE")


if __name__ == "__main__":
    main()
