#!/usr/bin/env python3
"""
One-off diagnostic: root-cause the "90 of 286 terminal empty" transcript
backfill result Jeff flagged as suspicious (2026-09-22).

READ-ONLY except for the live re-fetch calls to Apollo/Fireflies, which
are themselves read-only GET/GraphQL queries — no writes to Supabase or
either transcript source.

STEP 1 — confirm the ingestion code's actual API keys resolve to
GrowthBook's real Apollo/Fireflies accounts (not a personal/test
account), using the SAME client classes production uses
(scripts/apollo_client.py, scripts/fireflies_client.py), not a separate
credential.

STEP 2 — pull the REAL current set of call_transcripts rows classified
TERMINAL (unavailable_reason LIKE 'terminal:%'), joined to calls.call_date
for age. Take the 10 most recent by call_date. Live re-fetch each one,
right now, through transcript_store.fetch_utterances() — the exact
function backfill_transcripts.py itself calls — and report what comes
back today: real text, still empty/404, or something else.

STEP 3 — for EVERY terminal row (not just the top 10), compute real
age-as-of-today, AND pull the RAW source payload directly (not just
normalised utterances) for every one: Fireflies duration + meeting_
attendees count + whether the `transcript` object itself is null vs
present-with-empty-sentences; Apollo's full conversation object (state,
duration, participant count). This is the real evidence for what these
calls actually are, if Step 2's live re-fetch shows they are NOT simply
still processing.

Needs SUPABASE_URL + SUPABASE_SERVICE_KEY + APOLLO_API_KEY +
FIREFLIES_API_KEY.
"""
import sys
from pathlib import Path
from datetime import date, datetime
from collections import Counter

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _raw_fireflies_inspect(client, call_id):
    """Full raw payload for one Fireflies transcript id: duration,
    attendee count, sentence count, and whether the transcript object
    itself is null (id doesn't exist / was deleted) vs present-but-empty."""
    q = """query T($id:String!){ transcript(id:$id){
        title duration
        meeting_attendees { displayName email }
        sentences { text }
    } }"""
    res = client._query(q, {"id": call_id})
    if res.get("errors"):
        return {"raw_errors": [e.get("message", "")[:120] for e in res["errors"]]}
    t = (res.get("data") or {}).get("transcript")
    if t is None:
        return {"transcript_object": None}
    return {
        "transcript_object": "present",
        "title": t.get("title"),
        "duration_seconds": t.get("duration"),
        "attendee_count": len(t.get("meeting_attendees") or []),
        "attendees": [a.get("displayName") for a in (t.get("meeting_attendees") or [])],
        "sentence_count": len(t.get("sentences") or []),
    }


def _raw_apollo_inspect(client, call_id):
    """Full raw conversation object for one Apollo id: state, duration,
    participant count — whatever Apollo itself says happened to this
    recording, not just whether utterances came back."""
    try:
        convo = client.get_conversation(call_id)
    except Exception as e:
        return {"fetch_error": f"{type(e).__name__}: {str(e)[:160]}"}
    c = convo.get("conversation", convo)
    return {
        "state": c.get("state"),
        "duration": c.get("duration") or c.get("duration_seconds"),
        "participant_count": len(c.get("participants") or []),
        "topic": c.get("topic"),
        "top_level_keys": sorted(convo.keys()),
    }


def main():
    from supabase import create_client
    import os
    from supabase_client import select_all
    from transcript_store import fetch_utterances, TERMINAL, STILL_PROCESSING_DAYS

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    print("=" * 100)
    print("STEP 1: Confirm Apollo/Fireflies account identity via the ACTUAL ingestion client classes")
    print("=" * 100)

    from apollo_client import ApolloClient
    apollo = ApolloClient()
    try:
        resp = apollo._get("/users/search", params={"page": 1, "per_page": 1})
        print(f"  Apollo /users/search succeeded — key is valid and scoped. "
              f"Sample response keys: {list(resp.keys())}")
    except Exception as e:
        print(f"  Apollo /users/search failed ({type(e).__name__}: {e})")

    from fireflies_client import FirefliesClient
    ff = FirefliesClient()
    try:
        res = ff._query("query { user { name email user_id } }")
        user = (res.get("data") or {}).get("user") or {}
        print(f"  Fireflies /graphql `user` query: name={user.get('name')!r} "
              f"email={user.get('email')!r} user_id={user.get('user_id')!r}")
    except Exception as e:
        print(f"  ❌ Fireflies user query failed: {type(e).__name__}: {e}")

    print("\n" + "=" * 100)
    print("STEP 2/3: Real terminal-empty set, age distribution, live re-fetch, RAW source inspection")
    print("=" * 100)

    ct_rows = select_all(sb, "call_transcripts",
                          columns="call_id,transcript_quality,unavailable_reason")
    terminal_rows = [r for r in ct_rows
                     if (r.get("unavailable_reason") or "").startswith(TERMINAL)]
    print(f"Total call_transcripts rows: {len(ct_rows)}")
    print(f"TERMINAL rows (real, current count): {len(terminal_rows)}")

    calls_rows = select_all(sb, "calls", columns="call_id,source,company_name,call_date")
    calls_by_id = {str(c["call_id"]): c for c in calls_rows if c.get("call_id")}

    today = date.today()
    enriched = []
    for r in terminal_rows:
        cid = str(r["call_id"])
        c = calls_by_id.get(cid)
        if not c or not c.get("call_date"):
            enriched.append({**r, "call_id": cid, "call_date": None, "age_days": None,
                              "source": (c or {}).get("source"),
                              "company_name": (c or {}).get("company_name")})
            continue
        try:
            age = (today - date.fromisoformat(str(c["call_date"])[:10])).days
        except Exception:
            age = None
        enriched.append({**r, "call_id": cid, "call_date": c["call_date"], "age_days": age,
                          "source": c.get("source"), "company_name": c.get("company_name")})

    with_age = [e for e in enriched if e["age_days"] is not None]
    print(f"\nTerminal rows with a resolvable call_date: {len(with_age)}/{len(enriched)}")

    suspicious = [e for e in with_age if e["age_days"] <= STILL_PROCESSING_DAYS]
    print(f"Terminal rows with age <= STILL_PROCESSING_DAYS ({STILL_PROCESSING_DAYS}d): {len(suspicious)}")

    ages = sorted(e["age_days"] for e in with_age)
    if ages:
        print(f"Age distribution (days): min={ages[0]} p25={ages[len(ages)//4]} "
              f"median={ages[len(ages)//2]} p75={ages[3*len(ages)//4]} max={ages[-1]}")

    most_recent = sorted(with_age, key=lambda e: e["age_days"])[:10]
    print(f"\n{'='*100}\nLIVE RE-FETCH (via fetch_utterances, same as production) of 10 MOST RECENT:\n{'='*100}")

    clients = {}
    for e in most_recent:
        cid, source = e["call_id"], (e["source"] or "").lower()
        utts, err, extra = fetch_utterances(source, cid, clients, retries=3, backoff=1.0)
        text_len = sum(len((u.get("text") or "")) for u in (utts or []))
        e["live_text_chars"] = text_len
        print(f"  call_id={cid}  source={source}  age={e['age_days']}d  "
              f"LIVE: {'REAL TEXT (' + str(text_len) + ' chars)' if text_len else f'still empty (err={err!r})'}")

    print(f"\n{'='*100}\nRAW SOURCE INSPECTION — ALL {len(with_age)} terminal calls "
          f"(duration/attendees/state, not just utterance count):\n{'='*100}")

    raw_results = []
    for e in with_age:
        cid, source = e["call_id"], (e["source"] or "").lower()
        if source == "fireflies":
            raw = _raw_fireflies_inspect(ff, cid)
        elif source == "apollo":
            raw = _raw_apollo_inspect(apollo, cid)
        else:
            raw = {"skipped": f"unhandled source {source!r}"}
        raw_results.append({**e, "raw": raw})

    # Classify what these calls actually are, from real evidence.
    zero_duration = [r for r in raw_results if r["raw"].get("duration_seconds") == 0
                      or r["raw"].get("duration") == 0]
    one_or_no_attendee = [r for r in raw_results
                           if isinstance(r["raw"].get("attendee_count"), int)
                           and r["raw"]["attendee_count"] <= 1]
    one_or_no_participant = [r for r in raw_results
                              if isinstance(r["raw"].get("participant_count"), int)
                              and r["raw"]["participant_count"] <= 1]
    null_transcript_obj = [r for r in raw_results
                            if r["raw"].get("transcript_object") is None
                            and "transcript_object" in r["raw"]]
    apollo_states = Counter(r["raw"].get("state") for r in raw_results
                             if r["source"] == "apollo")
    fetch_errors = [r for r in raw_results if "fetch_error" in r["raw"] or "raw_errors" in r["raw"]]

    print(f"\nZero-duration recordings: {len(zero_duration)}/{len(raw_results)}")
    print(f"Fireflies: <=1 meeting attendee: {len(one_or_no_attendee)}")
    print(f"Apollo: <=1 participant: {len(one_or_no_participant)}")
    print(f"Fireflies: transcript object itself is NULL (id has no transcript record at all "
          f"at the source, distinct from 'exists but empty'): {len(null_transcript_obj)}")
    print(f"Apollo conversation `state` values seen: {dict(apollo_states)}")
    print(f"Raw fetch errors/GraphQL errors during inspection: {len(fetch_errors)}")

    print(f"\nPer-call raw detail:")
    for r in raw_results:
        print(f"  call_id={r['call_id']}  source={r['source']}  company={r['company_name']}  "
              f"call_date={r['call_date']}  age={r['age_days']}d")
        print(f"    raw={r['raw']}")

    print("\nDONE")


if __name__ == "__main__":
    main()
