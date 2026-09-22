#!/usr/bin/env python3
"""
Backfill call transcripts into the substrate (STORE_AND_BACKFILL_TRANSCRIPTS,
Phase 4). Iterate existing `calls`, fetch each transcript through the
source-agnostic transcript_store, and upsert into call_transcripts.

Discipline (from the spec):
  - DRY RUN reports per-source counts BEFORE any write (--dry-run).
  - Resumable + idempotent: skips call_ids already in call_transcripts, so a
    re-run continues where it stopped; the table itself is the checkpoint.
  - Batched writes (not row-by-row — an earlier row-by-row job here hit
    connection limits).
  - Retry with backoff on transient fetch failure; a call that still fails is
    recorded 'unavailable' with a reason and the run continues.
  - No source branching in this loop — transcript_store handles the source
    difference; we iterate the configured source priority.
  - Progress printed incrementally.

Needs SUPABASE_URL + SUPABASE_SERVICE_KEY, and the source API keys
(FIREFLIES_API_KEY / APOLLO_API_KEY). Requires migration 041 applied.

Usage:
  python scripts/backfill_transcripts.py --dry-run          # report, no writes
  python scripts/backfill_transcripts.py                    # write
  python scripts/backfill_transcripts.py --source apollo --limit 20
"""
import argparse
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in ("", "scripts", "api"):
    sys.path.insert(0, str(REPO / p) if p else str(REPO))

# Line-buffer stdout so incremental progress survives a kill (CI block-buffers
# stdout by default; a SIGTERM'd run otherwise flushes nothing — a long backfill
# then looks like it did nothing even though batched writes persisted).
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


def _sources():
    """Configured source priority (fireflies, apollo), from client.yaml."""
    try:
        from adapters import get_source_priority
        pri = get_source_priority()
        if pri:
            return pri
    except Exception:
        pass
    return ["fireflies", "apollo"]


def _done_transcript_ids(client):
    """call_ids that are DONE (resume skips them): rows with text, or TERMINAL
    empties (old calls that will never have a transcript). A RETRY/pending empty
    is re-attempted. is_done() in transcript_store is the shared authority."""
    from supabase_client import select_all
    from transcript_store import is_done
    try:
        rows = select_all(client, "call_transcripts",
                          columns="call_id,transcript_quality,unavailable_reason")
    except Exception as e:
        # Table not applied yet — treat as none done so a dry-run still reports.
        print(f"  ⚠️  could not read call_transcripts ({type(e).__name__}) — "
              "assuming none done (is migration 041/042 applied?)")
        return set()
    return {r["call_id"] for r in rows if r.get("call_id")
            and is_done(r.get("transcript_quality"), r.get("unavailable_reason"))}


def _calls_for_source(client, source, newest_first=False):
    from supabase_client import select_all
    rows = select_all(client, "calls", columns="call_id,source,company_name,call_date",
                      filters=[("eq", "source", source)])
    # deterministic order → stable, resumable progress. newest_first (the
    # nightly self-heal) spends a capped budget on the calls coaching reads
    # soonest; ties broken by call_id so the order is still deterministic.
    rows = [r for r in rows if r.get("call_id")]
    rows.sort(key=lambda r: str(r["call_id"]))
    if newest_first:
        rows.sort(key=lambda r: str(r.get("call_date") or ""), reverse=True)
    return rows


def format_backfill_report(grand, dry_run, limit, max_consecutive_deferrals):
    """Markdown per-source report for $GITHUB_STEP_SUMMARY: every state with
    its real count, plus the backlog left for the next run, so a capped or
    tripped run is visible on the run page."""
    lines = [f"### Transcript self-heal / backfill{' (DRY RUN)' if dry_run else ''}", "",
             f"Cap: {limit if limit else 'none'} calls per source per run; circuit breaker after "
             f"{max_consecutive_deferrals} consecutive deferrals.", "",
             "| source | pending before | attempted | text | unavailable | deferred | written | pending after | stopped early |",
             "|---|---|---|---|---|---|---|---|---|"]
    for src, s in grand.items():
        written = s["with_text"] + s["unavailable"] if dry_run else s["written"]
        # still pending = not resolved (retryable-empty rows stay pending)
        after = s["pending"] - s["resolved"]
        lines.append(f"| {src} | {s['pending']} | {s['attempted']} | {s['with_text']} | "
                     f"{s['unavailable']} | {s['deferred']} | {written} | {after} | "
                     f"{s['stopped'] or 'no'} |")
    lines.append("")
    for src, s in grand.items():
        for reason, n in s["reasons"].most_common(6):
            lines.append(f"- {src} ×{n}: `{reason}`")
    return "\n".join(lines)


def backfill(dry_run=True, only_source=None, limit=None, batch=25,
             newest_first=False, max_consecutive_deferrals=None, fetch_retries=6):
    from supabase_client import SupabaseWriter
    from transcript_store import fetch_utterances, build_transcript_row, UNAVAILABLE, is_done

    writer = SupabaseWriter()
    client = writer.client
    already = _done_transcript_ids(client)
    clients = {}
    sources = [s for s in _sources() if (only_source is None or s == only_source)]
    # Fireflies rate-limits a fast sequential sweep; throttle it. Apollo did 553
    # clean with no throttle. Override via TRANSCRIPT_THROTTLE_SECONDS.
    throttle = {"fireflies": float(os.getenv("TRANSCRIPT_THROTTLE_SECONDS", "1.0")),
                "apollo": 0.0, "gong": 0.0}

    print("=" * 78)
    print(f"TRANSCRIPT BACKFILL — {'DRY RUN (no writes)' if dry_run else 'WRITING'}")
    print(f"sources: {sources}  |  already stored: {len(already)}"
          + (f"  |  limit/source: {limit}" if limit else ""))
    print("=" * 78)

    grand = {}
    for source in sources:
        calls = _calls_for_source(client, source, newest_first=newest_first)
        todo = [c for c in calls if str(c["call_id"]) not in already]
        pending_count = len(todo)
        if limit:
            todo = todo[:limit]
        stats = {"calls": len(calls), "already": len(calls) - pending_count,
                 "pending": pending_count, "stopped": "", "resolved": 0,
                 "attempted": 0, "with_text": 0, "unavailable": 0,
                 "deferred": 0, "written": 0, "chars": [], "reasons": Counter()}
        consecutive_deferrals = 0
        print(f"\n[{source}] {len(calls)} calls, {stats['already']} done, "
              f"{len(todo)} to process  (throttle={throttle.get(source, 0.0)}s)")

        pending = []
        for i, c in enumerate(todo, 1):
            cid = str(c["call_id"])
            utts, err, extra = fetch_utterances(source, cid, clients, retries=fetch_retries,
                                                throttle=throttle.get(source, 0.0))
            stats["attempted"] += 1
            if err:
                # Transient fetch failure (e.g. rate limit that outlasted the
                # backoff). Do NOT write a row — leaving the call absent means a
                # later run RE-ATTEMPTS it, instead of recording a false
                # 'unavailable' that resume would skip forever.
                stats["deferred"] += 1
                stats["reasons"][("defer: " + err)[:48]] += 1
                consecutive_deferrals += 1
                if (max_consecutive_deferrals
                        and consecutive_deferrals >= max_consecutive_deferrals):
                    # Rate limit / outage: every further call would burn the
                    # full backoff budget. Stop this source; the rest stays
                    # pending for the next run.
                    stats["stopped"] = (f"circuit breaker: {consecutive_deferrals} "
                                        f"consecutive deferrals ({err[:60]})")
                    print(f"    ⛔ {source}: {stats['stopped']} — stopping this source")
                    break
            else:
                consecutive_deferrals = 0
                row = build_transcript_row(source, cid, utts, error=None,
                                           call_date=c.get("call_date"), extra=extra)
                if is_done(row["transcript_quality"], row["unavailable_reason"]):
                    stats["resolved"] += 1      # text, or terminal empty
                if row["transcript_quality"] == UNAVAILABLE:
                    stats["unavailable"] += 1   # genuine no-content
                    stats["reasons"][(row["unavailable_reason"] or "")[:48]] += 1
                else:
                    stats["with_text"] += 1
                    stats["chars"].append(row["char_count"])
                pending.append(row)

            if not dry_run and len(pending) >= batch:
                stats["written"] += writer.bulk_upsert_transcripts(pending)
                pending = []
            if i % 25 == 0 or i == len(todo):
                print(f"    {i}/{len(todo)}  text={stats['with_text']} "
                      f"no_content={stats['unavailable']} deferred={stats['deferred']}"
                      + ("" if dry_run else f" written={stats['written']}"))

        if not dry_run and pending:
            stats["written"] += writer.bulk_upsert_transcripts(pending)

        # per-source report
        chars = sorted(stats["chars"])
        if chars:
            total_kb = sum(chars) / 1024
            print(f"  → text {stats['with_text']}/{stats['attempted']}  "
                  f"no_content {stats['unavailable']}  deferred {stats['deferred']}  "
                  f"chars: min={chars[0]} median={int(statistics.median(chars))} "
                  f"max={chars[-1]}  est_store={total_kb:.0f}KB")
        else:
            print(f"  → text 0/{stats['attempted']}  deferred {stats['deferred']}")
        for reason, n in stats["reasons"].most_common(6):
            print(f"     ×{n}: {reason}")
        grand[source] = stats

    print("\n" + "=" * 78)
    verb = "WOULD WRITE" if dry_run else "WROTE"
    for source, s in grand.items():
        n = s["with_text"] + s["unavailable"] if dry_run else s["written"]
        tail = (f"  |  {s['deferred']} DEFERRED (transient — re-run to retry)"
                if s["deferred"] else "")
        print(f"  {source:10} {verb} {n} rows "
              f"({s['with_text']} with text, {s['unavailable']} no-content){tail}")
    if dry_run:
        print("\nDRY RUN — nothing written. Re-run without --dry-run to backfill.")
    elif any(s["deferred"] for s in grand.values()):
        print("\nSome calls DEFERRED (transient failures, no row written) — "
              "re-run to retry them; done rows are skipped.")
    print("=" * 78)
    return grand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report per-source counts, write nothing")
    ap.add_argument("--source", default=None, help="only this source")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap calls processed per source per run")
    ap.add_argument("--newest-first", action="store_true",
                    help="process the most recent calls first (nightly self-heal)")
    ap.add_argument("--max-consecutive-deferrals", type=int, default=None,
                    help="stop a source after this many deferrals in a row "
                         "(rate limit / outage circuit breaker)")
    ap.add_argument("--fetch-retries", type=int, default=6,
                    help="per-call fetch attempts (fewer = shorter worst-case backoff)")
    args = ap.parse_args()
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY")):
        print("cannot run — SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 2
    grand = backfill(dry_run=args.dry_run, only_source=args.source, limit=args.limit,
                     newest_first=args.newest_first,
                     max_consecutive_deferrals=args.max_consecutive_deferrals,
                     fetch_retries=args.fetch_retries)
    report = format_backfill_report(grand, args.dry_run, args.limit,
                                    args.max_consecutive_deferrals)
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
