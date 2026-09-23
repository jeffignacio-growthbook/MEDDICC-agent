"""
Incremental deal sync: checkpoint storage and the rules for moving it.

Design: 2026-09-23 audit, PENDING_WORK "Incremental deal sync". The
checkpoint is the transcript-ETL lesson (TRANSCRIPT_GAP_INVESTIGATION
2026-09-22). There, a "since" cutoff was taken from data written before the
real write succeeded (§4), and a strict `>` on the max value seen dropped
late arrivals for good (cause C). So:

  - The checkpoint lives in Supabase deal_sync_checkpoints (migration 069). It
    changes only through CheckpointStore.advance(), which the sync calls
    after a fully successful run and never on a partial one.
  - It is an epoch-millisecond hs_lastmodifieddate value from HubSpot's own
    clock, never the runner's "now" and never an ISO string. deals/search
    returns HTTP 400 for an ISO string with no timezone.
"""

import time
from datetime import datetime

JOB_DEALS = "deals"

# Each run re-reads this much before the checkpoint. It covers HubSpot search
# index lag, a calculated property landing seconds after its
# hs_lastmodifieddate stamp (seen live: +2.5s, no re-bump), runner/HubSpot
# clock skew, and deals edited while a run is fetching. It must exceed the
# longest fetch: incremental runs take seconds, the full sync 8-12 min.
OVERLAP_MS = 30 * 60 * 1000
# Inclusive, so a deal stamped exactly on the window start is read. A strict
# `>` on the max value seen is transcript-ETL cause C.
WINDOW_OPERATOR = "GTE"
# Above this, don't page an incremental backlog; exit 1 and let the full
# sync (which resets the checkpoint) handle it.
MAX_INCREMENTAL_DEALS = 9000
# Company edits don't touch a deal's hs_lastmodifieddate, so each run also
# re-reads the deals of companies modified in the window. Above this many
# changed companies (e.g. a bulk enrichment), skip that pass visibly; the
# full sync refreshes every deal's company fields anyway.
MAX_COMPANY_PASS = 2000


class SyncBlocked(Exception):
    """The incremental run must not proceed (no checkpoint, backlog too big)."""


def hs_ms(value):
    """hs_lastmodifieddate (ISO '...Z' as search returns it, or epoch-ms
    digits) as int epoch ms; None if absent or unparseable."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def window_filters(checkpoint_ms):
    """(window_start_ms, filters) for deals modified since checkpoint - overlap."""
    start = checkpoint_ms - OVERLAP_MS
    return start, [{"propertyName": "hs_lastmodifieddate", "operator": WINDOW_OPERATOR,
                    "value": str(start)}]


def company_pass(hubspot, filters, already_ids):
    """Deals of companies modified in the window, not already fetched.
    Returns (extra deals, status line). A failed read raises: the run fails
    and the checkpoint stays put. Too many changed companies is not a failure
    (the full sync covers it) but is reported."""
    n = hubspot.count_objects('companies', filters)
    if n > MAX_COMPANY_PASS:
        return [], (f"skipped: {n} companies modified (> {MAX_COMPANY_PASS}); "
                    f"company fields refresh on the next full sync")
    companies = hubspot.search_objects_keyset('companies', filters, ['hs_object_id'])
    assoc = hubspot.batch_get_company_deal_associations([c['id'] for c in companies])
    wanted = sorted({d for deals in assoc.values() for d in deals} - set(already_ids), key=int)
    extra = hubspot.batch_read_deals(wanted) if wanted else []
    return extra, (f"{len(companies)} companies modified -> {len(extra)} more deals re-read")


def fetch_incremental(hubspot, store):
    """Deals modified since (checkpoint - overlap), keyset-paged, plus the
    deals of companies modified in the same window.
    Returns dict(deals, checkpoint, window_start_ms, fetch_start_ms,
    company_status). Raises SyncBlocked instead of guessing when it can't be
    done safely."""
    checkpoint = store.get(JOB_DEALS)
    if checkpoint is None:
        raise SyncBlocked("no checkpoint yet: run the full sync once "
                          "(etl_deals.py --mode analytics) to set it")
    start, filters = window_filters(checkpoint)
    backlog = hubspot.count_deals(filters)
    if backlog > MAX_INCREMENTAL_DEALS:
        raise SyncBlocked(f"{backlog} deals modified since the checkpoint window "
                          f"(> {MAX_INCREMENTAL_DEALS}): run the full sync instead")
    # Taken before both searches, so the watermark cap covers the company
    # pass as well as the deal window.
    fetch_start_ms = int(time.time() * 1000)
    deals = hubspot.search_deals_keyset(extra_filters=filters)
    extra, company_status = company_pass(hubspot, filters, {d['id'] for d in deals})
    return {"deals": deals + extra, "checkpoint": checkpoint, "window_start_ms": start,
            "fetch_start_ms": fetch_start_ms, "company_status": company_status}


def next_watermark(stored_ms, deals, fetch_start_ms):
    """The checkpoint a fully successful run may advance to:
    min(max hs_lastmodifieddate seen, fetch start), never below stored_ms.
    Capping at fetch start means a deal stamped after the fetch began (or a
    clock-skewed future stamp) can't pull the checkpoint past work this run
    didn't see. Returns stored_ms if the run saw nothing newer."""
    seen = [m for m in (hs_ms((d.get("properties") or {}).get("hs_lastmodifieddate"))
                        for d in deals) if m is not None]
    if not seen:
        return stored_ms
    candidate = min(max(seen), fetch_start_ms)
    return candidate if stored_ms is None else max(stored_ms, candidate)

# Epoch ms for 2001-09-09 .. 2286-11-20. A 10-digit value is epoch seconds
# and would put the window ~55 years back; refuse it instead.
_MIN_MS, _MAX_MS = 10**12, 10**13


def _valid_ms(value):
    return (isinstance(value, int) and not isinstance(value, bool)
            and _MIN_MS <= value < _MAX_MS)


class CheckpointStore:
    """The per-job sync checkpoint (epoch ms) in Supabase deal_sync_checkpoints."""

    TABLE = "deal_sync_checkpoints"

    def __init__(self, sb):
        self.sb = sb

    def get(self, job):
        """The stored watermark in epoch ms, or None if there isn't one."""
        rows = (self.sb.table(self.TABLE).select("job,watermark_ms")
                .eq("job", job).execute().data)
        if not rows:
            return None
        value = rows[0].get("watermark_ms")
        return int(value) if value is not None else None

    def advance(self, job, watermark_ms, *, run_id, fetched, upserted):
        """Store a new watermark. Call only after a fully successful run.
        Raises ValueError on anything that isn't epoch milliseconds."""
        if not _valid_ms(watermark_ms):
            raise ValueError(f"checkpoint must be epoch milliseconds (int), got {watermark_ms!r}")
        self.sb.table(self.TABLE).upsert({
            "job": job,
            "watermark_ms": watermark_ms,
            "run_id": str(run_id),
            "fetched": int(fetched),
            "upserted": int(upserted),
        }, on_conflict="job").execute()
