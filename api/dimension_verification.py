"""
Dimension Coverage Verification - Mandatory Post-Generation Gate

Prevents synthesis from answering about specific dimension values
(EMEA, Mid-Market, Q3, etc.) without actually filtering for them.

This is a CODE-LEVEL GATE, not a prompt instruction.
"""
import re
from typing import Dict, List, Tuple, Optional
import yaml
from pathlib import Path

def load_known_dimensions() -> Dict[str, List[str]]:
    """
    Load known categorical dimension values from config files.

    Returns:
        {
            "region": ["NAM", "EMEA", "APAC", "LATAM", "ROW", "UNKNOWN"],
            "segment": ["Enterprise", "Mid-Market", "SMB", "Unknown"],
            ...
        }

    2026-09-12 (PENDING_WORK.md Low Priority #14): a 'pipeline' entry
    used to live here — ['New Business', 'Renewal', 'Upsell',
    'Cross-Sell'] — assuming a literal `pipeline` column held these
    values. No such column has ever existed: no migration ever created
    it on deals, deals_snapshot, or waterfall_weekly (only `pipeline_id`
    exists, which is the HubSpot pipeline *object*, e.g. "Sales
    Pipeline" — a different concept that can hold New Business AND
    Expansion deals together), and scripts/discover_properties.py's own
    comment confirms "deal_type ... don't exist in Supabase deals
    table." The real signal this repo actually uses to distinguish deal
    types (scripts/../verify_segment_scope_and_deal_type.py) is derived
    from deals.renewal_revenue being null/0 (New Business) vs >0
    (Expansion) — a 2-way split that doesn't even match the 4 fictional
    values this used to check, and can't be expressed as the single
    `['eq', col, value]` filter this whole gate is built around (it
    needs "IS NULL OR = 0", not an equality match).
    Every existing/future filter naming an unregistered column is now
    also caught structurally by check_dimension_filtered()'s column-
    validation safeguard (see its docstring) — but 'pipeline' is
    removed here outright rather than left to rely on that safeguard,
    because it could never be correctly verified even in principle
    given the real data model, not just accidentally misconfigured.
    Silently checking a fictional dimension that can never really be
    satisfied is worse than not checking it at all: a real fix needs
    either a materialized deal-type column (backed by renewal_revenue
    at ETL time) or a content-based check (verify returned rows'
    renewal_revenue values match the claimed deal type) — a real
    schema/design decision, not a same-night patch.
    """
    known_dims = {}

    # Load regions from regions.yaml
    regions_file = Path(__file__).parent.parent / 'config' / 'regions.yaml'
    if regions_file.exists():
        try:
            with open(regions_file, 'r') as f:
                regions_config = yaml.safe_load(f)
                # regions.yaml structure: region_definitions -> NAM/EMEA/etc.
                region_defs = regions_config.get('region_definitions', {})
                known_dims['region'] = list(region_defs.keys())
                # Add UNKNOWN if not in config (it's a valid DB value)
                if 'UNKNOWN' not in known_dims['region']:
                    known_dims['region'].append('UNKNOWN')
        except Exception:
            # Fallback if YAML parse fails
            known_dims['region'] = ['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN']
    else:
        # Fallback hardcoded list
        known_dims['region'] = ['NAM', 'EMEA', 'APAC', 'LATAM', 'ROW', 'UNKNOWN']

    # Known segments (hardcoded - could be loaded from config)
    known_dims['segment'] = ['Enterprise', 'Mid-Market', 'SMB', 'Unknown']

    return known_dims


def extract_dimension_mentions(question: str, known_dimensions: Dict[str, List[str]]) -> List[Tuple[str, str]]:
    """
    Extract mentions of known dimension values from question text.

    Args:
        question: User's question
        known_dimensions: Dict of dimension -> known values

    Returns:
        List of (dimension_name, value) tuples found in question

    Example:
        question = "How has EMEA pipeline moved?"
        returns = [("region", "EMEA")]
    """
    mentions = []
    question_lower = question.lower()

    for dim_name, known_values in known_dimensions.items():
        for value in known_values:
            # Case-insensitive word boundary match
            # "EMEA" should match "EMEA pipeline" but not "STEAMEA"
            pattern = r'\b' + re.escape(value.lower()) + r'\b'
            if re.search(pattern, question_lower):
                mentions.append((dim_name, value))

    return mentions


def check_dimension_filtered(dimension: str, value: str, queries_run: list,
                              sb=None) -> bool:
    """
    Check if any query filtered for the specific dimension value.

    Args:
        dimension: Column name (e.g., "region")
        value: Value to check (e.g., "EMEA")
        queries_run: List of query dicts with tool/params/rows
        sb: optional live Supabase client. When provided, a claimed
            filter is only trusted if `dimension` is an actual,
            registered-queryable column for the query's target table.

    Returns:
        True if dimension=value filter found in any query

    2026-09-12 (PENDING_WORK.md Low Priority #14): queries_run records
    what a query REQUESTED, never what actually reached Postgres.
    api/tools.py's filter_table() silently DROPS any filter naming a
    column that isn't registered as queryable for that table
    (_validate_filters()) — it never errors, so the caller has no way
    to tell a dropped filter from an applied one just by looking at
    queries_run. Before this fix, that gap meant a filter on a
    nonexistent column (the removed 'pipeline' dimension — see
    load_known_dimensions() — is the exact incident this closes) could
    report "verified" even though the underlying data was never
    actually filtered by it, and a confidently wrong-scoped answer
    shipped with no warning at all.
    When `sb` is given, this cross-checks the claimed column against
    the same data_dictionary-backed valid-column set filter_table()
    itself validates against (api.tools._VALID_COLUMNS) before trusting
    a match — a filter on a column filter_table() would silently drop
    can never count as satisfying verification, for ANY dimension, not
    just the one this was found on. `sb=None` (the default — used by a
    few standalone/offline scripts with no live client) skips this
    extra check and falls back to the original queries_run-only
    behavior; a failure loading column metadata (offline test double,
    transient DB issue) degrades the same way rather than crashing the
    whole verification gate.
    """
    valid_columns_by_table = {}
    if sb is not None:
        try:
            from api import tools as T
            T._init_valid_columns(sb)
            valid_columns_by_table = T._VALID_COLUMNS
        except Exception:
            valid_columns_by_table = {}

    for query in queries_run:
        tool = query.get('tool', '')
        params = query.get('params', {})

        if tool in ('filter_table', 'compare_periods', 'aggregate_results'):
            table = params.get('table')
            if table:
                valid_cols = valid_columns_by_table.get(table) or set()
                if valid_cols and dimension not in valid_cols:
                    # filter_table() would silently drop a filter on
                    # this column for this table — never treat it as
                    # having satisfied verification, no matter what
                    # queries_run claims was requested.
                    continue

            filters = params.get('filters', [])

            # Check filters for [operator, column, value] format
            for f in filters:
                if len(f) >= 3:
                    op, col, val = f[0], f[1], f[2]

                    # Match: column matches dimension AND value matches (case-insensitive)
                    if col == dimension and str(val).lower() == value.lower():
                        return True

    return False


def verify_dimension_coverage(question: str, queries_run: list,
                             accumulated_data: dict, sb=None) -> dict:
    """
    MANDATORY GATE: Verify dimension values mentioned in question were queried.

    This is the post-generation check that prevents answering about EMEA
    without actually filtering for EMEA.

    Args:
        question: User's question
        queries_run: List of queries executed this turn
        accumulated_data: Data retrieved (for row count checks)
        sb: optional live Supabase client, passed through to
            check_dimension_filtered() so a filter on a column that
            isn't actually queryable can never falsely "verify" — see
            that function's docstring. Optional and defaults to None
            for callers without a live client (offline scripts/tests).

    Returns:
        {
            "verified": bool,
            "missing_filters": [(dimension, value), ...],
            "required_query": {
                "tool": "filter_table",
                "table": "waterfall_weekly",  # inferred from existing queries
                "filters": [...],  # missing filters to add
            } or None
        }
    """
    # Load known dimensions
    known_dimensions = load_known_dimensions()

    # Extract dimension mentions from question
    mentions = extract_dimension_mentions(question, known_dimensions)

    if not mentions:
        # No known dimensions mentioned - verification passes
        return {"verified": True, "missing_filters": [], "required_query": None}

    # Check each mention was actually filtered for
    missing_filters = []

    for dim_name, value in mentions:
        if not check_dimension_filtered(dim_name, value, queries_run, sb=sb):
            missing_filters.append((dim_name, value))

    if not missing_filters:
        # All dimensions were filtered - verification passes
        return {"verified": True, "missing_filters": [], "required_query": None}

    # VERIFICATION FAILED - construct required query
    # Infer table from existing queries (most common table queried)
    tables_queried = []
    for q in queries_run:
        if q.get('tool') == 'filter_table':
            tables_queried.append(q['params'].get('table'))

    # Default to waterfall_weekly if we queried it, else first table
    inferred_table = 'waterfall_weekly' if 'waterfall_weekly' in tables_queried else (tables_queried[0] if tables_queried else 'deals')

    # Get base filters from first query (time filters, etc.)
    base_filters = []
    if queries_run and queries_run[0].get('tool') == 'filter_table':
        base_filters = queries_run[0]['params'].get('filters', [])

    # Add missing dimension filters
    required_filters = base_filters.copy()
    for dim_name, value in missing_filters:
        # Add eq filter for missing dimension
        required_filters.append(['eq', dim_name, value])

    required_query = {
        "tool": "filter_table",
        "table": inferred_table,
        "filters": required_filters,
        "reason": f"Question mentioned {', '.join(f'{v} ({d})' for d, v in missing_filters)} but query never filtered for it"
    }

    return {
        "verified": False,
        "missing_filters": missing_filters,
        "required_query": required_query
    }


def format_verification_error(missing_filters: List[Tuple[str, str]],
                             required_query: dict) -> str:
    """
    Format verification failure into user-facing error message.

    This should NEVER be shown to users in production - the system
    should automatically retry with the required query instead.

    But if retry fails or is disabled, show this diagnostic.
    """
    dims = ', '.join(f"{value} ({dim})" for dim, value in missing_filters)

    return (
        f"⚠️ Verification failed: Question asked about {dims} but "
        f"query never filtered for it. Retrieved data may be unfiltered. "
        f"Required query: {required_query['tool']} with filters {required_query['filters']}"
    )
