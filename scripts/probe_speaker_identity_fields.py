#!/usr/bin/env python3
"""
RAW API identity probe (rep-coaching Criterion C investigation).

Answers directly, against the live Fireflies/Apollo APIs (not just what
this codebase currently extracts from them): does either platform expose
a participant/speaker list that ties an ACTUAL DIARIZED SPEAKER to an
email or account-level identity — separate from calls.participant_emails,
which is confirmed (by reading scripts/enrichment/fireflies_participants.py)
to come from Fireflies' meeting_attendees (a CALENDAR-INVITE list, not an
attendance list) and (by reading scripts/adapters/apollo_adapter.py) from
Apollo's host/participants/transcript-entry fields, none of which are the
same array used for the transcript.speakers key.

FIREFLIES: tries progressively richer GraphQL field sets on both
`sentences` (does a per-utterance speaker_id/email field exist?) and a
top-level `speakers` field (does Fireflies expose a resolved-speaker
roster separate from meeting_attendees, and does it carry email?).
Also diffs meeting_attendees' email-implied names against the sentence
speaker_name set, to directly see how many actual speakers are absent
from the calendar-invite list at the API level (not just in what's
already stored).

APOLLO: dumps the FULL top-level key set of a live get_conversation()
detail response (not just the transcript fragment keys already probed
in probe_transcript_fields.py), looking specifically for a
participants/participants_info array with a per-participant id — and
whether that id matches the participant_id values appearing in the
SAME conversation's transcript fragments.

WRITES NOTHING. Needs FIREFLIES_API_KEY (or falls back to the
hardcoded default already in fireflies_client.py), APOLLO_API_KEY,
SUPABASE_URL, SUPABASE_SERVICE_KEY. Either source is skipped cleanly
(not fatal) if its key isn't set.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def _http_error_detail(e):
    """A GraphQL schema-validation error (e.g. querying a field that
    doesn't exist) can come back as HTTP 400 BEFORE the JSON body is
    parsed, so fireflies_client._query's raise_for_status() raises
    before we ever see the actual message. Reach into the response body
    if one is attached, so 'field doesn't exist' is distinguishable from
    a real outage."""
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            body = resp.json()
            errs = body.get("errors") or []
            if errs:
                return errs[0].get("message", "")[:150]
            return str(body)[:150]
        except Exception:
            return (resp.text or "")[:150]
    return str(e)[:150]


def _recent_call_ids(sb, source, n=5):
    from supabase_client import select_all
    rows = select_all(sb, "calls", columns="call_id,call_date",
                      filters=[("eq", "source", source)])
    rows = [r for r in rows if r.get("call_id") and r.get("call_date")]
    rows.sort(key=lambda r: r["call_date"], reverse=True)
    return [r["call_id"] for r in rows[:n]]


def probe_fireflies_identity(client, call_ids):
    print("\n" + "=" * 100)
    print("FIREFLIES — identity fields on sentences, and a top-level 'speakers' roster")
    print("=" * 100)

    sentence_field_candidates = [
        "speaker_name speaker_id email text",
        "speaker_name speaker_id text",
        "speaker_name email text",
    ]
    for cid in call_ids:
        found_any = False
        for fields in sentence_field_candidates:
            q = ("query T($id:String!){ transcript(id:$id){ sentences { %s } } }"
                 % fields)
            try:
                res = client._query(q, {"id": cid})
            except Exception as e:
                print(f"  call {cid[:20]} sentences[{fields}] -> HTTP/GraphQL "
                      f"REJECTED (pre-execution validation error): "
                      f"{_http_error_detail(e)}")
                continue
            errs = res.get("errors")
            if errs:
                print(f"  call {cid[:20]} sentences[{fields}] -> REJECTED: "
                      f"{errs[0].get('message','')[:100]}")
                continue
            sents = ((res.get("data") or {}).get("transcript") or {}).get("sentences") or []
            if sents:
                print(f"  call {cid[:20]} sentences[{fields}] -> ACCEPTED, "
                      f"keys={sorted(sents[0].keys())}")
                found_any = True
                break
        if found_any:
            break
    else:
        print("  (no call returned sentences with any candidate field set)")

    # Top-level 'speakers' roster — separate from meeting_attendees.
    # Tried WITH the speakers{id name} sub-selection first; if the field
    # itself doesn't exist in the schema, that alone must not also blank
    # out the meeting_attendees-vs-sentences comparison below, so this
    # falls back to a query without it rather than bundling both into one
    # all-or-nothing request.
    print()
    speakers_field_exists = None  # None = untested, True/False once known
    for cid in call_ids:
        q_with_speakers = ("query T($id:String!){ transcript(id:$id){ "
             "speakers { id name } "
             "meeting_attendees { displayName email } "
             "sentences { speaker_name } } }")
        q_without_speakers = ("query T($id:String!){ transcript(id:$id){ "
             "meeting_attendees { displayName email } "
             "sentences { speaker_name } } }")

        t = None
        speakers = []
        if speakers_field_exists is not False:
            try:
                res = client._query(q_with_speakers, {"id": cid})
                errs = res.get("errors")
                if errs:
                    raise RuntimeError(errs[0].get("message", ""))
                t = (res.get("data") or {}).get("transcript") or {}
                speakers = t.get("speakers") or []
                speakers_field_exists = True
            except Exception as e:
                if speakers_field_exists is None:
                    print(f"  top-level 'speakers{{id name}}' field -> REJECTED: "
                          f"{_http_error_detail(e)}")
                speakers_field_exists = False
                t = None

        if t is None:
            try:
                res = client._query(q_without_speakers, {"id": cid})
            except Exception as e:
                print(f"  call {cid[:20]} -> HTTP/GraphQL REJECTED: "
                      f"{_http_error_detail(e)}")
                continue
            errs = res.get("errors")
            if errs:
                print(f"  call {cid[:20]} -> REJECTED: {errs[0].get('message','')[:120]}")
                continue
            t = (res.get("data") or {}).get("transcript") or {}
        attendees = t.get("meeting_attendees") or []
        sentence_names = sorted({s.get("speaker_name") for s in (t.get("sentences") or [])
                                  if s.get("speaker_name")})
        if not sentence_names:
            continue
        print(f"  call {cid[:20]}:")
        print(f"    top-level 'speakers' field -> {speakers if speakers else 'FIELD REJECTED OR EMPTY'}")
        print(f"    meeting_attendees (calendar invite list): "
              f"{[a.get('displayName') for a in attendees]}")
        print(f"    actual sentence speaker_name set (who really spoke): {sentence_names}")
        attendee_names = {(a.get("displayName") or "").strip().lower() for a in attendees}
        missing_from_invite = [n for n in sentence_names
                               if n.strip().lower() not in attendee_names]
        print(f"    speakers who spoke but are NOT in meeting_attendees: "
              f"{missing_from_invite or 'none'}")
        return
    print("  (no call yielded a usable comparison)")


def probe_apollo_identity(client, call_ids):
    print("\n" + "=" * 100)
    print("APOLLO — full get_conversation() detail keys, participants array, "
          "and id<->participant_id correlation")
    print("=" * 100)
    for cid in call_ids:
        try:
            convo = client.get_conversation(cid)
        except Exception as e:
            print(f"  call {cid[:20]} -> error {type(e).__name__}: {str(e)[:100]}")
            continue

        print(f"  call {cid[:20]}:")
        print(f"    ALL top-level keys: {sorted(convo.keys())}")
        print(f"    host: {convo.get('host')!r}  host_id: {convo.get('host_id')!r}")
        accounts = convo.get("accounts")
        print(f"    accounts field: type={type(accounts).__name__}  "
              f"value={json.dumps(accounts)[:300] if accounts is not None else None}")

        participants_key = None
        for k in ("participants_info", "participants", "attendees"):
            if k in convo:
                participants_key = k
                break

        frags = convo.get("transcript") or []
        frag_participant_ids = sorted({f.get("participant_id") for f in frags
                                       if f.get("participant_id")})

        if participants_key:
            praw = convo.get(participants_key)
            print(f"    found '{participants_key}', type={type(praw).__name__}")
            # Apollo's shape here is unconfirmed — could be a list of
            # participant dicts, OR a dict keyed some other way. Print the
            # raw structure honestly rather than assuming a list, which is
            # exactly the bug that crashed the first run of this probe.
            if isinstance(praw, list):
                plist = praw
                print(f"    {len(plist)} entries (list)")
                if plist:
                    print(f"    first entry keys: {sorted(plist[0].keys()) if isinstance(plist[0], dict) else type(plist[0]).__name__}")
                    print(f"    first entry sample: "
                          f"{json.dumps({k: str(v)[:60] for k, v in plist[0].items()}) if isinstance(plist[0], dict) else str(plist[0])[:200]}")
                    if isinstance(plist[0], dict):
                        participant_ids_in_list = {
                            p.get("id") or p.get("participant_id") for p in plist
                            if isinstance(p, dict) and (p.get("id") or p.get("participant_id"))
                        }
                        overlap = participant_ids_in_list & set(frag_participant_ids)
                        print(f"    transcript fragment participant_ids: {frag_participant_ids}")
                        print(f"    ids present in '{participants_key}': {sorted(participant_ids_in_list)}")
                        print(f"    OVERLAP (can bridge speaker->identity via id): "
                              f"{sorted(overlap) if overlap else 'NONE — no shared id field'}")
            elif isinstance(praw, dict):
                print(f"    dict with {len(praw)} keys: {sorted(praw.keys())}")
                print(f"    RAW (truncated): {json.dumps({k: str(v)[:150] for k, v in praw.items()})}")
            else:
                print(f"    RAW value (truncated): {str(praw)[:300]}")
        else:
            print(f"    NO participants/participants_info/attendees key in the "
                  f"DETAIL response at all")
            print(f"    transcript fragment participant_ids (unresolvable to identity "
                  f"from this response): {frag_participant_ids}")

        if frags:
            return
    print("  (no call yielded transcript fragments to check)")


def main():
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY")):
        print("cannot probe — SUPABASE_* not set")
        return 2
    from api.db import get_supabase
    sb = get_supabase()

    print("=" * 100)
    print("RAW API SPEAKER-IDENTITY PROBE — writes nothing")
    print("Answers: can either platform tie a diarized speaker to an email/account,")
    print("via a field this codebase isn't currently extracting?")
    print("=" * 100)

    try:
        from fireflies_client import FirefliesClient
        ff_client = FirefliesClient()
        probe_fireflies_identity(ff_client, _recent_call_ids(sb, "fireflies", n=8))
    except Exception as e:
        print(f"\n[fireflies] probe failed: {type(e).__name__}: {e}")

    if os.getenv("APOLLO_API_KEY"):
        from apollo_client import ApolloClient
        apollo_client = ApolloClient()
        probe_apollo_identity(apollo_client, _recent_call_ids(sb, "apollo", n=8))
    else:
        print("\n[apollo] APOLLO_API_KEY not set — skipped")

    print("\n" + "=" * 100)
    print("DONE")
    print("=" * 100)


if __name__ == "__main__":
    sys.exit(main() or 0)
