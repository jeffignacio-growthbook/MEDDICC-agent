"""
Fiscal time window resolver for CRO Slack Agent.
Converts natural language time references to concrete start/end dates
using the fiscal calendar configuration.
"""

from datetime import date, timedelta
import sys
import yaml
from pathlib import Path

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Months with numeric keys (LLM may emit month as an integer string)
_MONTH_NUMS = {str(i): i for i in range(1, 13)}

def _client_config() -> dict:
    """Load the full client.yaml config (fiscal + reporting sections)."""
    cfg_path = Path(__file__).parent.parent / "config" / "client.yaml"
    return yaml.safe_load(open(cfg_path)) or {}

def _fiscal_config() -> dict:
    """Load fiscal configuration from client.yaml."""
    return _client_config().get("fiscal", {"fy_start_month": 2})

def _today(config: dict) -> date:
    """'Today' for every period this module resolves.

    Must be today_in_reporting_tz(), never date.today() — the server runs
    UTC, but client.yaml's reporting.timezone (e.g. America/New_York) is
    what "today" means for the business. Using the server clock here
    silently disagrees with every other reporting-tz-aware caller for part
    of each evening — this was found auditing the 2026-09-10 date-window
    incidents: resolve_time_window() was the one function everything was
    supposed to route through, but it still had its own, different idea of
    "today" than the rest of the system.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from sdr_utils import today_in_reporting_tz
    return today_in_reporting_tz(config)

def _parse_month(raw) -> int | None:
    """Convert a month value (name string or integer/string number) to 1-12."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    return _MONTH_NAMES.get(s) or _MONTH_NUMS.get(s)

def _year_sanity_check(year: int, today: date) -> str | None:
    """Return an error string if year is implausible relative to today, else None.

    Catches pathological model outputs (2019, 2035) before they reach the
    anchor lookup. The window is deliberately generous — the intent is to
    catch obviously wrong values, not to second-guess valid historical or
    near-future months within normal business planning horizons.
    """
    if year < today.year - 4:
        return (
            f"NO DATA AVAILABLE — the requested year {year} is more than "
            f"4 years before today ({today.year}); no snapshot data exists "
            f"that far back. Please confirm the year and try again."
        )
    if year > today.year + 1:
        return (
            f"NO DATA AVAILABLE — the requested year {year} is more than "
            f"1 year in the future (today is {today.isoformat()}); "
            f"pipeline snapshots don't exist yet for that period."
        )
    return None

def current_quarter_label() -> str:
    """
    Returns current fiscal quarter label, e.g. 'Q3_FY2027'.
    Uses utils.get_fiscal_quarter from scripts/.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter

    config = _client_config()
    _, _, label = get_fiscal_quarter(
        _today(config), {"fiscal": config.get("fiscal", {})})
    return label.replace(" ", "_")

def resolve_time_window(tw: dict) -> dict:
    """
    Convert the classifier's time_window object to
    concrete start/end dates based on fiscal calendar.
    Falls back to current quarter if unclear.

    Input:
      {
        "period": "current_quarter|current_month|previous_month|current_week|last_N_days|specific|specific_month|fiscal_quarter",
        "start": "YYYY-MM-DD or null",
        "end":   "YYYY-MM-DD or null",
        "n":     <int or null>  # for last_N_days
        "month": "January" (or "1") or null  # for specific_month
        "year":  <int or null>               # for specific_month: literal 4-digit year from question
        "fiscal_quarter": "FY2027 Q2" or "Q3" or null  # for named quarters
      }

    Output:
      {
        "start": "YYYY-MM-DD",
        "end":   "YYYY-MM-DD",
        "label": "Q3 FY2027" or "this week" or "last 30 days"
      }

    Note on None-passthrough: every tw.get() that has a default uses
    `tw.get(key) or default` rather than `tw.get(key, default)`.
    dict.get(key, default) ignores the default when the key IS present
    with value None — which is exactly what the LLM emits for optional
    fields ("n": null, "fiscal_quarter": null, etc.). The `or` form
    treats None the same as a missing key.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter

    # Handle None from classifier (when time_window is explicitly null in JSON)
    if tw is None:
        tw = {}

    config = _client_config()
    today = _today(config)
    # Use `or` fallback — dict.get(key, default) won't use the default when
    # the LLM emits the key explicitly as null (value is None, key is present).
    period = tw.get("period") or "current_quarter"
    fiscal_cfg = config.get("fiscal", {"fy_start_month": 2})
    cfg_wrap = {"fiscal": fiscal_cfg}
    fy_start_month = fiscal_cfg.get("fy_start_month", 2)

    if period == "fiscal_quarter" or tw.get("fiscal_quarter"):
        # Named fiscal quarter like "Q3", "Q4", or "FY2027 Q2"
        # `or ""` handles "fiscal_quarter": null without crashing on .upper()
        fq_str = tw.get("fiscal_quarter") or ""

        # Parse quarter number and optional fiscal year
        import re
        match = re.search(r'Q([1-4])', fq_str.upper())
        if not match:
            # Fallback to current quarter if can't parse
            s, e, label = get_fiscal_quarter(today, cfg_wrap)
            return {"start": s.isoformat(), "end": e.isoformat(), "label": label}

        quarter_num = int(match.group(1))

        # Extract fiscal year if present (e.g., "FY2027 Q2")
        fy_match = re.search(r'FY(\d{4})', fq_str.upper())
        if fy_match:
            fiscal_year = int(fy_match.group(1))
        else:
            # Infer fiscal year from today's date
            _, _, current_label = get_fiscal_quarter(today, cfg_wrap)
            # current_label format: "FY2027 Q3"
            fy_part = current_label.split()[0]  # Get first part (FY2027)
            current_fy = int(fy_part.replace("FY", ""))
            fiscal_year = current_fy

        # Calculate quarter start/end dates
        # Q1 starts at fy_start_month, Q2 is +3 months, Q3 is +6, Q4 is +9
        quarter_offset_months = (quarter_num - 1) * 3
        start_month = fy_start_month + quarter_offset_months

        # Handle month overflow (e.g., Feb + 9 = Nov, Feb + 12 = next Feb)
        if start_month > 12:
            start_month -= 12
            start_year = fiscal_year
        else:
            # FY starts in Feb, so Q1 Feb-Apr is in calendar year FY-1
            # FY2027 Q1 = Feb-Apr 2026
            start_year = fiscal_year - 1

        # Q4 wraps into next calendar year (e.g., FY2027 Q4 = Nov 2026 - Jan 2027)
        if quarter_num == 4:
            start_year = fiscal_year - 1

        # Calculate end month (start + 3 months, minus 1 day)
        end_month = start_month + 2
        end_year = start_year
        if end_month > 12:
            end_month -= 12
            end_year += 1

        from calendar import monthrange
        start_date = date(start_year, start_month, 1)
        last_day = monthrange(end_year, end_month)[1]
        end_date = date(end_year, end_month, last_day)

        label = f"Q{quarter_num} FY{fiscal_year}"
        return {"start": start_date.isoformat(), "end": end_date.isoformat(), "label": label}

    elif period == "current_quarter":
        s, e, label = get_fiscal_quarter(today, cfg_wrap)
        return {"start": s.isoformat(), "end": e.isoformat(),
                "label": label}
    elif period == "current_month":
        from calendar import monthrange
        first = date(today.year, today.month, 1)
        last_day = monthrange(today.year, today.month)[1]
        last = date(today.year, today.month, last_day)
        return {
            "start": first.isoformat(),
            "end":   last.isoformat(),
            "label": today.strftime("%B %Y")  # e.g. "August 2026"
        }
    elif period == "previous_month":
        from dateutil.relativedelta import relativedelta
        first = (today.replace(day=1) - relativedelta(months=1))
        from calendar import monthrange
        last_day = monthrange(first.year, first.month)[1]
        last = date(first.year, first.month, last_day)
        return {
            "start": first.isoformat(),
            "end":   last.isoformat(),
            "label": first.strftime("%B %Y")
        }
    elif period == "current_week":
        monday = today - timedelta(days=today.weekday())
        return {"start": monday.isoformat(),
                "end": today.isoformat(), "label": "this week"}
    elif period == "last_N_days":
        # `or 30` handles "n": null — dict.get("n", 30) would silently
        # return None and crash on timedelta(days=None).
        n = tw.get("n") or 30
        return {"start": (today - timedelta(days=n)).isoformat(),
                "end": today.isoformat(),
                "label": f"last {n} days"}
    elif period == "specific_month":
        # Primary fix for the month+year off-by-one-year class of bug:
        # The LLM emits the month name/number and the literal 4-digit year
        # the user stated; Python constructs the date range deterministically.
        # The model never resolves or anchors a year — it only transcribes
        # the literal digits from the question text.
        from calendar import monthrange
        month_num = _parse_month(tw.get("month"))
        year = tw.get("year")

        if month_num and year:
            year = int(year)
            sanity_err = _year_sanity_check(year, today)
            if sanity_err:
                # Surface a clear, explicit error rather than silently using
                # a bad year — same pattern as resolve_snapshot_anchors.
                return {"start": None, "end": None,
                        "label": sanity_err, "_error": sanity_err}
            last_day = monthrange(year, month_num)[1]
            start_date = date(year, month_num, 1)
            # Clip end to today: we can't report on the future
            end_date = min(date(year, month_num, last_day), today)
            raw_month = tw.get("month") or ""
            label_month = raw_month if raw_month else date(year, month_num, 1).strftime("%B")
            label = f"{label_month} {year}"
            return {"start": start_date.isoformat(), "end": end_date.isoformat(), "label": label}
        # Unparseable month/year — fall through to current quarter
        s, e, label = get_fiscal_quarter(today, cfg_wrap)
        return {"start": s.isoformat(), "end": e.isoformat(), "label": label}
    elif period in ("specific", "custom") and tw.get("start"):
        # `or today.isoformat()` handles "end": null — dict.get("end", default)
        # ignores the default when the key is present with value None, which is
        # exactly what the LLM emits for "to today" or an open-ended range.
        end_val = tw.get("end") or today.isoformat()
        return {"start": tw["start"],
                "end": end_val,
                "label": "custom range"}
    else:
        # Fallback to current quarter
        s, e, label = get_fiscal_quarter(today, cfg_wrap)
        return {"start": s.isoformat(), "end": e.isoformat(),
                "label": label}
