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

STEP 3 (evidence, not just code-reading) — for EVERY terminal row, not
just the top 10, compute real age-as-of-today from call_date and report
the full age distribution, so we know whether any terminal call is
suspiciously recent (age <= STILL_PROCESSING_DAYS, which would mean the
age gate itself is being bypassed or miscomputed) vs whether all 90 are
genuinely old (which would mean the 3-day cutoff, not the fetch logic,
is what needs re-examining).

Needs SUPABASE_URL + SUPABASE_SERVICE_KEY + APOLLO_API_KEY +
FIREFLIES_API_KEY.
"""
import sys
from pathlib import Path
from datetime import date, datetime

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


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
        # Apollo.io (video meetings) doesn't have a dedicated /me endpoint;
        # page 1 of conversations carries no account name either, so the
        # most direct live identity signal is the workspace-scoped users
        # endpoint if present, falling back to a conversations call
        # succeeding at all (proves the key is valid + scoped) plus the
        # topic/participant domains actually seen.
        resp = apollo._get("/users/search", params={"page": 1, "per_page": 1})
        print(f"  Apollo /users/search succeeded — key is valid and scoped. "
              f"Sample response keys: {list(resp.keys())}")
    except Exception as e:
        print(f"  Apollo /users/search failed ({type(e).__name__}: {e}); "
              f"falling back to a conversations call to prove key validity + inspect real domains")
    try:
        convos = apollo.get_conversations(page=1, per_page=5)
        domains = set()
        for c in convos.get("conversations", []):
            for p in (c.get("participants") or []):
                em = (p.get("email") or "")
                if "@" in em:
                    domains.add(em.split("@", 1)[1].lower())
        print(f"  Apollo: live conversations fetched OK. Real participant domains seen: {sorted(domains)}")
    except Exception as e:
        print(f"  ❌ Apollo conversations call failed: {type(e).__name__}: {e}")

    from fireflies_client import FirefliesClient
    ff = FirefliesClient()
    try:
        res = ff._query("query { user { name email user_id } }")
        user = (res.get("data") or {}).get("user") or {}
        print(f"  Fireflies /graphql `user` query: name={user.get('name')!r} "
              f"email={user.get('email')!r} user_id={user.get('user_id')!r}")
        if res.get("errors"):
            print(f"    (errors in response: {res['errors']})")
    except Exception as e:
        print(f"  ❌ Fireflies user query failed: {type(e).__name__}: {e}")

    print("\n" + "=" * 100)
    print("STEP 2/3: Pull REAL terminal-empty call_transcripts rows, age distribution, live re-fetch top 10")
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
            enriched.append({**r, "call_date": None, "age_days": None,
                              "source": (c or {}).get("source"),
                              "company_name": (c or {}).get("company_name")})
            continue
        try:
            age = (today - date.fromisoformat(str(c["call_date"])[:10])).days
        except Exception:
            age = None
        enriched.append({**r, "call_date": c["call_date"], "age_days": age,
                          "source": c.get("source"), "company_name": c.get("company_name")})

    with_age = [e for e in enriched if e["age_days"] is not None]
    print(f"\nTerminal rows with a resolvable call_date: {len(with_age)}/{len(enriched)}")

    suspicious = [e for e in with_age if e["age_days"] <= STILL_PROCESSING_DAYS]
    print(f"Terminal rows with age <= STILL_PROCESSING_DAYS ({STILL_PROCESSING_DAYS}d) — "
          f"SHOULD be impossible under current code, would indicate a real bug: {len(suspicious)}")
    for e in suspicious:
        print(f"    call_id={e['call_id']} source={e['source']} company={e['company_name']} "
              f"call_date={e['call_date']} age={e['age_days']}d reason={e['unavailable_reason']!r}")

    ages = sorted(e["age_days"] for e in with_age)
    if ages:
        print(f"\nAge distribution (days): min={ages[0]} p25={ages[len(ages)//4]} "
              f"median={ages[len(ages)//2]} p75={ages[3*len(ages)//4]} max={ages[-1]}")

    # 10 most recent (smallest age) terminal calls — the decisive live test.
    most_recent = sorted(with_age, key=lambda e: e["age_days"])[:10]
    print(f"\n{'='*100}\nLIVE RE-FETCH of the 10 MOST RECENT terminal-empty calls (right now, real API):\n{'='*100}")

    clients = {}
    results = []
    for e in most_recent:
        cid, source = e["call_id"], (e["source"] or "").lower()
        utts, err, extra = fetch_utterances(source, cid, clients, retries=3, backoff=1.0)
        text_len = sum(len((u.get("text") or "")) for u in (utts or []))
        outcome = ("REAL TEXT NOW AVAILABLE" if text_len > 0
                   else f"still empty (err={err!r})")
        results.append({**e, "live_text_chars": text_len, "live_outcome": outcome})
        print(f"\n  call_id={cid}  source={source}  company={e['company_name']}")
        print(f"    call_date={e['call_date']}  age={e['age_days']}d  "
              f"stored_reason={e['unavailable_reason']!r}")
        print(f"    LIVE FETCH NOW: {outcome}"
              + (f" ({text_len} chars)" if text_len > 0 else ""))

    recovered = [r for r in results if r["live_text_chars"] > 0]
    print(f"\n{'='*100}\nSUMMARY: {len(recovered)}/{len(results)} of the 10 most-recent terminal calls "
          f"now return real transcript text on live re-fetch.\n{'='*100}")

    print("\nDONE")


if __name__ == "__main__":
    main()
