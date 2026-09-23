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

JOB_DEALS = "deals"

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
