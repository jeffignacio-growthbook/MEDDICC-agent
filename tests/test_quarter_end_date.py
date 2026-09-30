"""
quarter_end_date — unit tests for api.time_resolver.quarter_end_date.

Verifies the fiscal-quarter end-date math for the label format
produced by current_quarter_label() (e.g. 'FY2027_Q3').

All tests use a synthetic config injected via monkeypatch so the
real client.yaml is not required.

Planted-bug controls
--------------------
test_q4_wraps_into_next_calendar_year:
  Q4 of a fiscal year that starts in February ends in January of the
  NEXT calendar year. The bug would be returning Jan of the *same*
  year as the FY label (off by a year). The assertion fails if the
  year arithmetic is wrong.

test_calendar_year_fy:
  When fy_start_month=1, FY label == calendar year.  Q1 ends Mar 31
  of the same year.  The planted-bug form would return the wrong year
  (fy_year - 1 instead of fy_year).
"""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.time_resolver import quarter_end_date


def _cfg(fy_start_month: int) -> dict:
    return {"fiscal": {"fy_start_month": fy_start_month}}


# ---------------------------------------------------------------------------
# fy_start_month = 2  (Feb fiscal year, our production config)
# FY2027: Feb 2026 – Jan 2027
# Q1 = Feb–Apr 2026   Q2 = May–Jul 2026   Q3 = Aug–Oct 2026   Q4 = Nov 2026–Jan 2027
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_client_config(request):
    """Each test can opt into a specific fy_start_month via the _fy marker;
    defaults to fy_start_month=2 if not specified."""
    marker = request.node.get_closest_marker("fy_start")
    month = marker.args[0] if marker else 2
    with patch("api.time_resolver._client_config", return_value=_cfg(month)):
        yield


def test_q1_end():
    assert quarter_end_date("Q1_FY2027") == date(2026, 4, 30)


def test_q2_end():
    assert quarter_end_date("Q2_FY2027") == date(2026, 7, 31)


def test_q3_end():
    assert quarter_end_date("Q3_FY2027") == date(2026, 10, 31)


def test_q4_wraps_into_next_calendar_year():
    # Q4 FY2027 = Nov 2026 – Jan 2027. End is Jan 31, 2027 (year > fy_year - 1).
    result = quarter_end_date("Q4_FY2027")
    assert result == date(2027, 1, 31), (
        f"Q4 end should wrap into 2027, got {result} — "
        "likely off-by-year in q_end_year calculation"
    )


def test_label_with_spaces_accepted():
    assert quarter_end_date("Q3 FY2027") == date(2026, 10, 31)


def test_bad_label_raises():
    with pytest.raises(ValueError, match="Cannot parse"):
        quarter_end_date("not_a_quarter")


# ---------------------------------------------------------------------------
# fy_start_month = 1  (calendar-year fiscal, planted-bug control)
# FY2027: Jan 2027 – Dec 2027
# Q1 = Jan–Mar 2027   Q2 = Apr–Jun 2027   Q3 = Jul–Sep 2027   Q4 = Oct–Dec 2027
# ---------------------------------------------------------------------------

@pytest.mark.fy_start(1)
def test_calendar_year_fy_q1():
    result = quarter_end_date("Q1_FY2027")
    assert result == date(2027, 3, 31), (
        f"Calendar-year Q1 should end Mar 2027, got {result} — "
        "likely subtracted 1 from fy_year incorrectly when fy_start_month=1"
    )


@pytest.mark.fy_start(1)
def test_calendar_year_fy_q4():
    assert quarter_end_date("Q4_FY2027") == date(2027, 12, 31)


# ---------------------------------------------------------------------------
# fy_start_month = 11  (November-start fiscal)
# FY2027: Nov 2026 – Oct 2027
# Q1 = Nov–Jan   Q2 = Feb–Apr   Q3 = May–Jul   Q4 = Aug–Oct 2027
# ---------------------------------------------------------------------------

@pytest.mark.fy_start(11)
def test_november_fy_q1_wraps():
    # Q1: Nov 2026 – Jan 2027 → end Jan 31, 2027
    result = quarter_end_date("Q1_FY2027")
    assert result == date(2027, 1, 31)


@pytest.mark.fy_start(11)
def test_november_fy_q4():
    assert quarter_end_date("Q4_FY2027") == date(2027, 10, 31)
