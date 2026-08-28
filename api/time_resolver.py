"""
Fiscal time window resolver for CRO Slack Agent.
Converts natural language time references to concrete start/end dates
using the fiscal calendar configuration.
"""

from datetime import date, timedelta
import sys
import yaml
from pathlib import Path

def _fiscal_config() -> dict:
    """Load fiscal configuration from client.yaml."""
    cfg_path = Path(__file__).parent.parent / "config" / "client.yaml"
    cfg = yaml.safe_load(open(cfg_path))
    return cfg.get("fiscal", {"fy_start_month": 2})

def current_quarter_label() -> str:
    """
    Returns current fiscal quarter label, e.g. 'Q3_FY2027'.
    Uses utils.get_fiscal_quarter from scripts/.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter

    cfg = _fiscal_config()
    _, _, label = get_fiscal_quarter(
        date.today(), {"fiscal": cfg})
    return label.replace(" ", "_")

def resolve_time_window(tw: dict) -> dict:
    """
    Convert the classifier's time_window object to
    concrete start/end dates based on fiscal calendar.
    Falls back to current quarter if unclear.

    Input:
      {
        "period": "current_quarter|current_week|last_N_days|specific|fiscal_quarter",
        "start": "YYYY-MM-DD or null",
        "end":   "YYYY-MM-DD or null",
        "n":     <int or null>  # for last_N_days
        "fiscal_quarter": "FY2027 Q2" or "Q3" or null  # for named quarters
      }

    Output:
      {
        "start": "YYYY-MM-DD",
        "end":   "YYYY-MM-DD",
        "label": "Q3 FY2027" or "this week" or "last 30 days"
      }
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from utils import get_fiscal_quarter

    today = date.today()
    period = tw.get("period", "current_quarter")
    cfg_wrap = {"fiscal": _fiscal_config()}
    fiscal_cfg = _fiscal_config()
    fy_start_month = fiscal_cfg.get("fy_start_month", 2)

    if period == "fiscal_quarter" or tw.get("fiscal_quarter"):
        # Named fiscal quarter like "Q3", "Q4", or "FY2027 Q2"
        fq_str = tw.get("fiscal_quarter", "")

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
        n = tw.get("n", 30)
        return {"start": (today - timedelta(days=n)).isoformat(),
                "end": today.isoformat(),
                "label": f"last {n} days"}
    elif period == "specific" and tw.get("start"):
        return {"start": tw["start"],
                "end": tw.get("end", today.isoformat()),
                "label": "custom range"}
    else:
        # Fallback to current quarter
        s, e, label = get_fiscal_quarter(today, cfg_wrap)
        return {"start": s.isoformat(), "end": e.isoformat(),
                "label": label}
