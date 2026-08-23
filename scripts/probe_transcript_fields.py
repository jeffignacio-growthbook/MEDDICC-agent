#!/usr/bin/env python3
"""
Field-inventory probe: what does the sentence/fragment payload ACTUALLY expose?

The availability probe selected only speaker_name+text (Fireflies) and read only
participant_name/spoken_sentence (Apollo), so it cannot answer whether timestamps
exist — the payload only ever contained what we asked for. This settles the
talk-ratio column-type question with real fetches:

  - Fireflies: try a per-id GraphQL query that ALSO selects start_time/end_time
    (and raw_text). Report which fields the API accepts and whether the
    time fields come back non-null. If timestamps are real, monologue-seconds is
    computable; if not, word-count talk ratio + consecutive-sentence monologue.
  - Apollo: dump the full key set of a transcript fragment from get_conversation,
    and a sample fragment, so we can see any timestamp/duration field.

Writes nothing. Needs FIREFLIES_API_KEY, APOLLO_API_KEY, SUPABASE_*.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))


def _one_call_id(sb, source):
    from supabase_client import select_all
    rows = select_all(sb, "calls", columns="call_id,call_date",
                      filters=[("eq", "source", source)])
    rows = [r for r in rows if r.get("call_id") and r.get("call_date")]
    rows.sort(key=lambda r: r["call_date"], reverse=True)   # newest first
    return [r["call_id"] for r in rows[:8]]


def probe_fireflies(call_ids):
    from fireflies_client import FirefliesClient
    c = FirefliesClient()
    print("\n" + "=" * 76)
    print("FIREFLIES sentence payload")
    print("=" * 76)
    # Candidate field sets, richest first. If the API rejects a field it returns
    # a GraphQL error; we fall back to a leaner set and report what was rejected.
    candidates = [
        "speaker_name text raw_text start_time end_time",
        "speaker_name text start_time end_time",
        "speaker_name text start_time",
        "speaker_name text",
    ]
    for cid in call_ids:
        for fields in candidates:
            q = ("query T($id:String!){ transcript(id:$id){ sentences { %s } } }"
                 % fields)
            try:
                res = c._query(q, {"id": cid})
            except Exception as e:
                print(f"  call {cid[:20]} fields[{fields}] → HTTP error "
                      f"{type(e).__name__}: {str(e)[:80]}")
                continue
            errs = res.get("errors")
            if errs:
                msg = "; ".join(e.get("message", "")[:80] for e in errs)[:160]
                print(f"  call {cid[:20]} fields[{fields}] → GraphQL rejected: {msg}")
                continue
            sents = ((res.get("data") or {}).get("transcript") or {}).get("sentences") or []
            if not sents:
                print(f"  call {cid[:20]} fields[{fields}] → 0 sentences (empty), try next call")
                break
            print(f"  ✓ ACCEPTED fields: [{fields}]  ({len(sents)} sentences)")
            print(f"    first sentence keys: {sorted(sents[0].keys())}")
            for s in sents[:3]:
                print(f"    sample: {json.dumps({k: (str(v)[:40]) for k, v in s.items()})}")
            # timestamp reality check
            st = [s.get("start_time") for s in sents[:20] if s.get("start_time") is not None]
            et = [s.get("end_time") for s in sents[:20] if s.get("end_time") is not None]
            print(f"    start_time non-null in first 20: {len(st)}  "
                  f"end_time non-null: {len(et)}"
                  + (f"  (e.g. start={st[0]} end={et[0] if et else '—'})" if st else ""))
            return
        else:
            continue
        break
    print("  (no call returned sentences)")


def probe_apollo(call_ids):
    from apollo_client import ApolloClient
    c = ApolloClient()
    print("\n" + "=" * 76)
    print("APOLLO transcript fragment payload")
    print("=" * 76)
    for cid in call_ids:
        try:
            convo = c.get_conversation(cid)
        except Exception as e:
            print(f"  call {cid[:20]} → error {type(e).__name__}: {str(e)[:80]}")
            continue
        frags = convo.get("transcript") or []
        print(f"  call {cid[:20]} → conversation keys: {sorted(convo.keys())}")
        if not frags:
            print("    0 transcript fragments, try next call")
            continue
        print(f"    {len(frags)} fragments; first fragment keys: {sorted(frags[0].keys())}")
        for f in frags[:3]:
            print(f"    sample: {json.dumps({k: (str(v)[:40]) for k, v in f.items()})}")
        # any plausible time/duration field?
        timeish = [k for k in frags[0].keys()
                   if any(t in k.lower() for t in ("time", "start", "end", "dur", "sec", "ms"))]
        print(f"    time-like fields on a fragment: {timeish or 'NONE'}")
        return
    print("  (no call returned fragments)")


def main():
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY")):
        print("cannot probe — SUPABASE_* not set"); return 2
    from api.db import get_supabase
    sb = get_supabase()
    if os.getenv("FIREFLIES_API_KEY") or os.getenv("GROWTHBOOK_FIREFLIES_API_KEY"):
        probe_fireflies(_one_call_id(sb, "fireflies"))
    if os.getenv("APOLLO_API_KEY"):
        probe_apollo(_one_call_id(sb, "apollo"))
    print("\n" + "=" * 76)
    print("Use the ACCEPTED field set above to decide talk-ratio column types:\n"
          "timestamps present → monologue seconds; text only → word-count ratio.")
    print("=" * 76)


if __name__ == "__main__":
    sys.exit(main() or 0)
