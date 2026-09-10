"""
Structural gate: resolve_time_window() (api/time_resolver.py) must be the
ONLY place any live-query code path in api/ converts a notion of "today" or
a relative time span into concrete dates.

Why this exists: the 2026-09-10 incident was the SAME bug written three
separate times, discovered one at a time across three follow-up questions:

  1. api/handlers.py's query_pipeline_movement checked a time_window shape
     ("type"=="relative_days") that resolve_time_window() never produced,
     so it silently fell back to comparing whichever two snapshots existed.
  2. The classifier's time_window JSON schema had no "n" field, so
     resolve_time_window()'s last_N_days branch could never be told "14" —
     it silently defaulted to 30.
  3. dynamic_query_loop's deals_snapshot "changed stage" comparisons needed
     a SECOND date the single resolved range didn't provide, so the model
     invented one from scratch (off by ~64 days).
  4. Auditing all of the above turned up a fourth, one-layer-deeper version
     of the exact same class: resolve_time_window() itself called
     date.today() (server UTC) while the rest of the system (and
     client.yaml's reporting.timezone) used today_in_reporting_tz() — so
     "today" could itself disagree by a day near midnight UTC.

Each was found only because someone asked a live follow-up question that
happened to expose it. This test removes the need for a fifth follow-up:
it greps for the two ways a parallel implementation gets written (a bare
date.today()/datetime.today() call, or timedelta(days=...) arithmetic
against "now") and fails the moment one appears anywhere in api/ outside
api/time_resolver.py itself, unless it's on a line explicitly marked
"ALLOW-RAW-DATE-MATH: <reason>" — a deliberate, reviewed exception (cache
TTLs in minutes/hours are unaffected; this only looks at day-granularity
date math), not a fifth accidental one.

Scope: api/ only — the live Slack Q&A path this bug class lives in.
scripts/ is batch ETL/admin tooling driven by config or CLI flags, not by
parsing a user's relative time phrase, and is out of scope for this gate.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).parent.parent
API_DIR = REPO_ROOT / "api"

# The canonical implementation itself — the only file allowed to define
# what "today" and "last N days" mean.
EXEMPT_FILES = {API_DIR / "time_resolver.py"}

BARE_TODAY_PATTERN = re.compile(r'\bdate\.today\(\)|\bdatetime\.today\(\)')
TIMEDELTA_DAYS_PATTERN = re.compile(r'timedelta\(\s*days\s*=')
ALLOW_MARKER = "ALLOW-RAW-DATE-MATH"


def _api_python_files():
    for path in sorted(API_DIR.rglob("*.py")):
        if path in EXEMPT_FILES:
            continue
        yield path


def _lines(path):
    return path.read_text().splitlines()


def find_bare_today_calls():
    """Any date.today()/datetime.today() outside time_resolver.py that
    isn't itself just a comment explaining the fix (checked by requiring
    the match not be inside a line that's ALSO just a '#' comment line
    mentioning it deliberately)."""
    violations = []
    for path in _api_python_files():
        for i, line in enumerate(_lines(path), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # explanatory comments referencing the old bug are fine
            if BARE_TODAY_PATTERN.search(line):
                violations.append((path, i, line.strip()))
    return violations


MARKER_LOOKBACK_LINES = 8


def find_unrouted_date_math():
    """Any timedelta(days=...) outside time_resolver.py without an
    ALLOW-RAW-DATE-MATH marker on the same line or within the
    MARKER_LOOKBACK_LINES lines above it.

    Deliberately loose (a plain "is the marker text nearby" scan, not a
    parse of which comment block "belongs" to which statement): this is a
    repo-hygiene gate, not a formal verifier, and a human reviewing the
    diff that adds a marker is the real check that it's justified and
    actually near its target line. No proximity-to-resolve_time_window()
    exemption on purpose, though — that would be exactly the kind of
    fragile, unreviewed heuristic this test exists to replace with an
    explicit, human-written justification.
    """
    violations = []
    for path in _api_python_files():
        lines = _lines(path)
        for i, line in enumerate(lines, start=1):
            if not TIMEDELTA_DAYS_PATTERN.search(line):
                continue
            window_start = max(0, i - 1 - MARKER_LOOKBACK_LINES)
            nearby = lines[window_start:i]  # up to and including this line
            if any(ALLOW_MARKER in l for l in nearby):
                continue
            violations.append((path, i, line.strip()))
    return violations


def _format(violations):
    return "\n".join(
        f"  {p.relative_to(REPO_ROOT)}:{ln}: {txt}" for p, ln, txt in violations
    )


def test_no_bare_today_outside_time_resolver():
    violations = find_bare_today_calls()
    assert not violations, (
        "date.today()/datetime.today() found outside api/time_resolver.py. "
        "The only legal source of \"today\" in this system is "
        "today_in_reporting_tz() (scripts/sdr_utils.py) — directly, or via "
        "resolve_time_window(). A server-UTC date.today() silently disagrees "
        "with that for part of every evening (client.yaml's reporting "
        "timezone is not UTC). Fix the call site instead of adding an "
        "exception — there is no legitimate reason for a new bare "
        "date.today() in this codebase.\n" + _format(violations)
    )
    print("✓ no bare date.today()/datetime.today() outside api/time_resolver.py")


def test_no_unrouted_relative_date_math():
    violations = find_unrouted_date_math()
    assert not violations, (
        "timedelta(days=...) found outside api/time_resolver.py with no "
        "'# ALLOW-RAW-DATE-MATH: <reason>' marker on the same or preceding "
        "line. Every relative-time computation must either call "
        "resolve_time_window() or carry an explicit, reviewed marker "
        "explaining why it's not a parallel implementation of it — this is "
        "exactly the bug class from 2026-09-10 (three independent "
        "reinventions of 'what does last N days mean', found one at a time "
        "over three follow-up questions). Route through resolve_time_window() "
        "or add the marker with a real justification, not to silence this "
        "test.\n" + _format(violations)
    )
    print("✓ every timedelta(days=...) site outside time_resolver.py is "
          "explicitly justified as an intentional, reviewed exception")


if __name__ == "__main__":
    test_no_bare_today_outside_time_resolver()
    test_no_unrouted_relative_date_math()
    print("\n✅ All tests passed")
