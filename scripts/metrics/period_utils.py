#!/usr/bin/env python3
"""
Period construction utilities for parameterized metrics.

All period types (all_time, rolling, quarter, custom) reduce to
{start, end} date ranges. These helpers construct those ranges.
"""

from datetime import datetime, timedelta
from typing import Optional


def period_all_time() -> dict:
    """
    All-time period (no date filter).

    Returns:
        {"start": None, "end": None}
    """
    return {"start": None, "end": None}


def period_rolling(months: int, as_of: Optional[str] = None) -> dict:
    """
    Rolling N-month window from as_of date.

    Args:
        months: Number of months to look back
        as_of: End date as "YYYY-MM-DD" (default: today)

    Returns:
        {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}

    Example:
        period_rolling(12) → last 12 months from today
        period_rolling(6, as_of="2026-08-01") → 6 months before Aug 1
    """
    if as_of:
        end_date = datetime.fromisoformat(as_of)
    else:
        end_date = datetime.now()

    start_date = end_date - timedelta(days=months * 30)

    return {
        "start": start_date.strftime("%Y-%m-%d"),
        "end": end_date.strftime("%Y-%m-%d")
    }


def period_quarter(quarter: str) -> dict:
    """
    Fiscal quarter date range.

    Supports two formats:
    - Calendar: "Q1 2026", "Q2 2026", etc. (Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec)
    - Fiscal: "FY2027 Q3", "FY2027 Q4", etc. (based on Feb 1 fiscal year start)

    Args:
        quarter: Quarter string in format "Q1 2026" or "FY2027 Q3"

    Returns:
        {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}

    Examples:
        period_quarter("Q1 2026") → Jan 1 - Mar 31, 2026
        period_quarter("Q2 2026") → Apr 1 - Jun 30, 2026
        period_quarter("FY2027 Q3") → Aug 1 - Oct 31, 2026
    """
    quarter = quarter.strip()

    # Fiscal year format: "FY2027 Q3"
    if quarter.startswith("FY"):
        # Parse fiscal year and quarter number
        parts = quarter.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid fiscal quarter format: {quarter}")

        fy_year = int(parts[0][2:])  # "FY2027" → 2027
        q_num = int(parts[1][1:])     # "Q3" → 3

        if q_num not in [1, 2, 3, 4]:
            raise ValueError(f"Quarter must be 1-4, got: {q_num}")

        # Fiscal year starts Feb 1
        # FY2027 Q1 = Feb 1 - Apr 30, 2026
        # FY2027 Q2 = May 1 - Jul 31, 2026
        # FY2027 Q3 = Aug 1 - Oct 31, 2026
        # FY2027 Q4 = Nov 1 - Jan 31, 2027

        # Fiscal Q1 starts in prior calendar year
        base_year = fy_year - 1

        quarter_starts = {
            1: (base_year, 2, 1),   # Feb 1
            2: (base_year, 5, 1),   # May 1
            3: (base_year, 8, 1),   # Aug 1
            4: (base_year, 11, 1),  # Nov 1
        }

        quarter_ends = {
            1: (base_year, 4, 30),   # Apr 30
            2: (base_year, 7, 31),   # Jul 31
            3: (base_year, 10, 31),  # Oct 31
            4: (fy_year, 1, 31),     # Jan 31 (next calendar year)
        }

        start_year, start_month, start_day = quarter_starts[q_num]
        end_year, end_month, end_day = quarter_ends[q_num]

        start_date = f"{start_year:04d}-{start_month:02d}-{start_day:02d}"
        end_date = f"{end_year:04d}-{end_month:02d}-{end_day:02d}"

        return {"start": start_date, "end": end_date}

    # Calendar quarter format: "Q1 2026"
    else:
        parts = quarter.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid calendar quarter format: {quarter}")

        q_part = parts[0]
        year = int(parts[1])

        if not q_part.startswith("Q"):
            raise ValueError(f"Quarter must start with 'Q', got: {q_part}")

        q_num = int(q_part[1:])

        if q_num not in [1, 2, 3, 4]:
            raise ValueError(f"Quarter must be 1-4, got: {q_num}")

        # Calendar quarters: Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec
        quarter_starts = {
            1: (year, 1, 1),
            2: (year, 4, 1),
            3: (year, 7, 1),
            4: (year, 10, 1),
        }

        quarter_ends = {
            1: (year, 3, 31),
            2: (year, 6, 30),
            3: (year, 9, 30),
            4: (year, 12, 31),
        }

        start_year, start_month, start_day = quarter_starts[q_num]
        end_year, end_month, end_day = quarter_ends[q_num]

        start_date = f"{start_year:04d}-{start_month:02d}-{start_day:02d}"
        end_date = f"{end_year:04d}-{end_month:02d}-{end_day:02d}"

        return {"start": start_date, "end": end_date}


def period_custom(start: str, end: str) -> dict:
    """
    Custom date range.

    Args:
        start: Start date as "YYYY-MM-DD"
        end: End date as "YYYY-MM-DD"

    Returns:
        {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}

    Example:
        period_custom("2026-01-15", "2026-03-20")
    """
    # Validate date format
    datetime.fromisoformat(start)
    datetime.fromisoformat(end)

    return {"start": start, "end": end}


def format_period(period: Optional[dict]) -> str:
    """
    Format period for display.

    Args:
        period: {"start": date, "end": date} or None

    Returns:
        Human-readable string

    Examples:
        None → "all-time"
        {"start": None, "end": None} → "all-time"
        {"start": "2026-01-01", "end": "2026-03-31"} → "Jan 1, 2026 - Mar 31, 2026"
    """
    if not period or (period.get("start") is None and period.get("end") is None):
        return "all-time"

    start = period.get("start")
    end = period.get("end")

    if start and end:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        return f"{start_dt.strftime('%b %d, %Y')} - {end_dt.strftime('%b %d, %Y')}"
    elif start:
        start_dt = datetime.fromisoformat(start)
        return f"from {start_dt.strftime('%b %d, %Y')}"
    elif end:
        end_dt = datetime.fromisoformat(end)
        return f"through {end_dt.strftime('%b %d, %Y')}"

    return "custom period"
