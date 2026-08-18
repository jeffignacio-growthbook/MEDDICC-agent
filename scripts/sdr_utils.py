"""
SDR utility functions for the MEDDICC agent.

This module provides shared data-handling and timezone utilities
used across ETL scripts, adapters, and API handlers.

Timezone functions are in this module (not utils.py) to keep the
nightly agent's existing utils.py stable. Import from here for
all SDR and CRO agent work.
"""

from __future__ import annotations
from datetime import date, datetime, timezone as _tz, timedelta
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Module-level config cache to avoid re-reading client.yaml on every call
_config_cache = None
_config_cache_ts = None


# ── Timezone utilities ────────────────────────────────────────────

def get_reporting_tz(config: dict = None):
    """Return the configured reporting timezone as a ZoneInfo object.

    Resolution order:
      1. reporting.timezone in client.yaml
      2. organization.timezone in client.yaml
      3. UTC (silent fallback — never raises)

    Uses zoneinfo.ZoneInfo (Python 3.9+ stdlib — no pip install needed).
    Returns UTC on unrecognized IANA names rather than raising.

    Examples:
        get_reporting_tz()
            -> ZoneInfo('America/New_York')  # from config
        get_reporting_tz({"reporting": {"timezone": "Europe/London"}})
            -> ZoneInfo('Europe/London')
        get_reporting_tz({"reporting": {"timezone": "Bad/Zone"}})
            -> ZoneInfo('UTC')              # safe fallback
    """
    from zoneinfo import ZoneInfo

    global _config_cache, _config_cache_ts

    # Use provided config or load from cache
    if config is None:
        # Check if cache is still fresh (5 min TTL)
        import time
        now = time.time()
        if _config_cache is None or _config_cache_ts is None or (now - _config_cache_ts > 300):
            from utils import load_client_config
            _config_cache = load_client_config()
            _config_cache_ts = now
        config = _config_cache

    # Try reporting.timezone first
    tz_name = None
    if config and "reporting" in config and "timezone" in config["reporting"]:
        tz_name = config["reporting"]["timezone"]
    elif config and "organization" in config and "timezone" in config["organization"]:
        tz_name = config["organization"]["timezone"]

    # Fallback to UTC if no config or bad IANA name
    if not tz_name:
        return ZoneInfo("UTC")

    try:
        return ZoneInfo(tz_name)
    except Exception as e:
        logger.warning(f"[TIMEZONE] unrecognized IANA name '{tz_name}', falling back to UTC: {e}")
        return ZoneInfo("UTC")


def utc_to_reporting_date(ts, config: dict = None) -> Optional[date]:
    """Convert a UTC timestamp to a date in the reporting timezone.

    This is the canonical function for turning any timestamp into a
    reporting date for metric attribution. Use this everywhere a
    timestamp becomes a date (day/week/quarter bucketing).

    Args:
        ts: Any of: datetime (aware or naive — assumed UTC if naive),
            str (ISO 8601, handles Z suffix), int/float (Unix epoch seconds).
            None returns None.
        config: Optional config dict. Loaded from client.yaml if None.

    Returns:
        date in the reporting timezone, or None if ts is None or
        unparseable.

    Examples:
        # 11 PM UTC March 31 — Eastern team (UTC-4 in summer):
        utc_to_reporting_date("2026-03-31T23:00:00Z", eastern_cfg)
            -> date(2026, 3, 31)   # 7 PM Eastern, still March 31

        # Same timestamp — IST team (UTC+5:30):
        utc_to_reporting_date("2026-03-31T23:00:00Z", ist_cfg)
            -> date(2026, 4, 1)    # 4:30 AM IST, already April 1
    """
    if ts is None or ts == "":
        return None

    reporting_tz = get_reporting_tz(config)

    # Convert to datetime if needed
    dt_utc = None

    if isinstance(ts, datetime):
        dt_utc = ts
        # If naive, assume UTC
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=_tz.utc)

    elif isinstance(ts, str):
        if not ts.strip():
            return None
        try:
            # Handle Z suffix and ISO 8601
            ts_clean = ts.replace('Z', '+00:00')
            dt_utc = datetime.fromisoformat(ts_clean)
            # If naive after parsing, assume UTC
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=_tz.utc)
        except Exception as e:
            logger.warning(f"[TIMEZONE] could not parse date string '{ts}': {e}")
            return None

    elif isinstance(ts, (int, float)):
        try:
            dt_utc = datetime.fromtimestamp(ts, tz=_tz.utc)
        except Exception as e:
            logger.warning(f"[TIMEZONE] could not parse epoch timestamp {ts}: {e}")
            return None

    else:
        logger.warning(f"[TIMEZONE] unsupported timestamp type: {type(ts)}")
        return None

    # Convert to reporting timezone and extract date
    if dt_utc is None:
        return None

    dt_reporting = dt_utc.astimezone(reporting_tz)
    return dt_reporting.date()


def today_in_reporting_tz(config: dict = None) -> date:
    """Return today's date in the reporting timezone.

    Use instead of date.today() everywhere a 'current date' is
    needed for reporting. date.today() uses the server wall clock —
    on a UTC server serving a US West Coast team this returns the
    wrong date for 8 hours every evening.

    Examples:
        # At 11 PM UTC on March 31:
        date.today()                    -> date(2026, 4, 1)  # WRONG (server UTC)
        today_in_reporting_tz(pac_cfg)  -> date(2026, 3, 31) # correct (Pacific)
    """
    reporting_tz = get_reporting_tz(config)
    now_utc = datetime.now(_tz.utc)
    now_reporting = now_utc.astimezone(reporting_tz)
    return now_reporting.date()


def reporting_day_window(
    d: date, config: dict = None
) -> Tuple[datetime, datetime]:
    """Return (start_utc, end_utc) covering a full reporting-timezone day.

    Converts a reporting-timezone date into the UTC window that covers
    it. Use when building date filters for external APIs (Apollo,
    HubSpot, Salesloft) that accept UTC timestamps.

    Args:
        d: A date in the reporting timezone.
        config: Optional config dict.

    Returns:
        (start_utc, end_utc) as timezone-aware UTC datetimes.
        The window is [start, end) — end is exclusive (midnight next day).

    Example:
        # America/New_York, March 31 (UTC-4 in summer)
        reporting_day_window(date(2026, 3, 31), eastern_cfg)
            -> (datetime(2026,3,31, 4,0, tzinfo=UTC),   # midnight ET
                datetime(2026,4,1,  4,0, tzinfo=UTC))   # midnight next day ET
    """
    reporting_tz = get_reporting_tz(config)

    # Start of day in reporting timezone
    start_reporting = datetime.combine(d, datetime.min.time())
    start_reporting = start_reporting.replace(tzinfo=reporting_tz)

    # End of day (midnight next day) in reporting timezone
    end_reporting = start_reporting + timedelta(days=1)

    # Convert both to UTC
    start_utc = start_reporting.astimezone(_tz.utc)
    end_utc = end_reporting.astimezone(_tz.utc)

    return (start_utc, end_utc)


def quarter_window_utc(
    as_of: date = None, config: dict = None
) -> Tuple[datetime, datetime, str]:
    """Return (start_utc, end_utc, label) for the current fiscal quarter.

    Quarter boundaries are computed in the reporting timezone, then
    converted to UTC. Use when building API filters for external tools.

    Returns:
        (start_utc, end_utc, label) where start/end are aware UTC
        datetimes and label is e.g. "FY2027 Q3".

    Example:
        quarter_window_utc(config=eastern_cfg)
            -> (datetime(2026,8,1,4,0,tzinfo=UTC),
                datetime(2026,11,1,4,0,tzinfo=UTC),
                "FY2027 Q3")
    """
    from utils import get_fiscal_quarter

    if config is None:
        from utils import load_client_config
        config = load_client_config()

    if as_of is None:
        as_of = today_in_reporting_tz(config)

    # Get fiscal quarter in reporting timezone
    start_date, end_date, label = get_fiscal_quarter(as_of, {"fiscal": config.get("fiscal", {})})

    # Convert start and end dates to UTC windows
    start_utc, _ = reporting_day_window(start_date, config)
    _, end_utc = reporting_day_window(end_date, config)

    return (start_utc, end_utc, label)


def api_date_filters(
    since: date,
    until: date,
    config: dict = None,
    tool: str = "iso"
) -> dict | tuple:
    """Convert reporting-timezone dates to the UTC format each tool expects.

    Args:
        since: Start date in reporting timezone (inclusive).
        until: End date in reporting timezone (inclusive — covers
               through end of this day in reporting tz).
        config: Optional config dict.
        tool: Output format:
              "iso"     -> {"min": "2026-07-01T04:00:00Z",
                            "max": "2026-10-01T04:00:00Z"}
                           Apollo analytics smart_datetime_range format.
              "iso_str" -> ("2026-07-01T04:00:00Z", "2026-10-01T04:00:00Z")
                           Salesloft, Outreach filter params.
              "epoch"   -> (1751342400, 1756684800)
                           Aircall (uses Unix timestamps).

    The until boundary covers through 23:59:59 in reporting tz
    (i.e. midnight of the following day in UTC) — inclusive of the
    full final day.
    """
    # Get UTC windows for since and until dates
    start_utc, _ = reporting_day_window(since, config)
    _, end_utc = reporting_day_window(until, config)

    if tool == "iso":
        # Apollo analytics format
        return {
            "min": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "max": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
    elif tool == "iso_str":
        # Salesloft/Outreach format
        return (
            start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    elif tool == "epoch":
        # Aircall format (Unix timestamps)
        return (
            int(start_utc.timestamp()),
            int(end_utc.timestamp())
        )
    else:
        logger.warning(f"[API_FILTERS] unknown tool format '{tool}', defaulting to iso")
        return {
            "min": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "max": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
