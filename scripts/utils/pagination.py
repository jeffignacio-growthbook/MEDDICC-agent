"""
Pagination Utility for Supabase Queries

PostgREST has a default 1000-row limit. For large result sets, we must paginate.

Usage:
    from scripts.utils.pagination import fetch_all_rows

    # Method 1: Pass query builder directly
    query = supabase.table('deals_snapshot') \\
        .select('*') \\
        .eq('quarter', 'Q1') \\
        .gte('close_date', '2026-01-01')

    rows = fetch_all_rows(query)

    # Method 2: Use convenience wrapper with filter dict
    rows = fetch_all_rows_by_filters(
        supabase,
        'deals_snapshot',
        'deal_id, stage_id',
        eq={'fiscal_quarter': 'FY2027 Q1', 'pipeline_id': 'default'},
        gte={'close_date': '2026-01-01'},
        lte={'close_date': '2026-03-31'}
    )
"""

from typing import List, Dict, Any, Optional


def fetch_all_rows(query_builder, page_size: int = 1000) -> List[Dict[str, Any]]:
    """
    Fetch all rows from a Supabase query, handling pagination automatically.

    Args:
        query_builder: A Supabase query builder (before .execute())
        page_size: Number of rows per page (default 1000, max for PostgREST)

    Returns:
        List of all rows across all pages

    Example:
        supabase = get_supabase()
        query = supabase.table('deals_snapshot') \\
            .select('deal_id, week_of_quarter, stage_id') \\
            .eq('fiscal_quarter', 'FY2027 Q1') \\
            .gte('close_date', '2026-01-01')

        all_rows = fetch_all_rows(query)
    """
    all_rows = []
    offset = 0

    while True:
        # Fetch one page
        result = query_builder.range(offset, offset + page_size - 1).execute()

        rows = result.data
        all_rows.extend(rows)

        # If we got fewer than page_size rows, we've reached the end
        if len(rows) < page_size:
            break

        offset += page_size

    return all_rows


def fetch_all_rows_by_filters(
    supabase,
    table: str,
    select: str,
    eq: Optional[Dict[str, Any]] = None,
    gte: Optional[Dict[str, Any]] = None,
    lte: Optional[Dict[str, Any]] = None,
    gt: Optional[Dict[str, Any]] = None,
    lt: Optional[Dict[str, Any]] = None,
    in_: Optional[Dict[str, List[Any]]] = None,
    is_: Optional[Dict[str, Any]] = None,
    page_size: int = 1000
) -> List[Dict[str, Any]]:
    """
    Fetch all rows with server-side filtering and pagination.

    This is a convenience wrapper that supports common filter types.

    Args:
        supabase: Supabase client
        table: Table name
        select: Select clause (e.g., 'deal_id, stage_id, week_of_quarter')
        eq: Dict of column: value pairs for equality filters
        gte: Dict of column: value pairs for >= filters (date ranges)
        lte: Dict of column: value pairs for <= filters (date ranges)
        gt: Dict of column: value pairs for > filters
        lt: Dict of column: value pairs for < filters
        in_: Dict of column: list pairs for IN filters (multi-value)
        is_: Dict of column: value pairs for IS filters (null checks)
        page_size: Page size (default 1000)

    Returns:
        List of all matching rows

    Example:
        # Simple equality filters
        rows = fetch_all_rows_by_filters(
            supabase,
            'deals_snapshot',
            'deal_id, week_of_quarter, stage_id',
            eq={'fiscal_quarter': 'FY2027 Q1', 'pipeline_id': 'default'}
        )

        # Date range filters
        rows = fetch_all_rows_by_filters(
            supabase,
            'deals',
            'deal_id, company_name, close_date',
            eq={'pipeline_id': 'default'},
            gte={'close_date': '2026-01-01'},
            lte={'close_date': '2026-03-31'}
        )

        # Multi-value IN filter
        rows = fetch_all_rows_by_filters(
            supabase,
            'deals',
            'deal_id, company_name',
            in_={'deal_id': ['123', '456', '789']}
        )

        # Mixed filters
        rows = fetch_all_rows_by_filters(
            supabase,
            'deals',
            '*',
            eq={'pipeline_id': 'default'},
            gte={'close_date': '2026-01-01'},
            in_={'segment': ['Enterprise', 'Mid-Market']}
        )
    """
    all_rows = []
    offset = 0

    # Apply filters once, then paginate
    while True:
        # Build query with filters
        query = supabase.table(table).select(select)

        # Apply equality filters
        if eq:
            for column, value in eq.items():
                query = query.eq(column, value)

        # Apply greater-than-or-equal filters (date ranges)
        if gte:
            for column, value in gte.items():
                query = query.gte(column, value)

        # Apply less-than-or-equal filters (date ranges)
        if lte:
            for column, value in lte.items():
                query = query.lte(column, value)

        # Apply greater-than filters
        if gt:
            for column, value in gt.items():
                query = query.gt(column, value)

        # Apply less-than filters
        if lt:
            for column, value in lt.items():
                query = query.lt(column, value)

        # Apply IN filters (multi-value)
        if in_:
            for column, values in in_.items():
                query = query.in_(column, values)

        # Apply IS filters (null checks)
        if is_:
            for column, value in is_.items():
                query = query.is_(column, value)

        # Add pagination
        result = query.range(offset, offset + page_size - 1).execute()

        rows = result.data
        all_rows.extend(rows)

        if len(rows) < page_size:
            break

        offset += page_size

    return all_rows


# Backward compatibility alias
def fetch_all_rows_by_batch(
    supabase,
    table: str,
    select: str,
    filters: Dict[str, Any],
    batch_size: int = 1000
) -> List[Dict[str, Any]]:
    """
    DEPRECATED: Use fetch_all_rows_by_filters() instead.

    Legacy wrapper that only supports .eq() filters.
    Maintained for backward compatibility with existing scripts.
    """
    return fetch_all_rows_by_filters(
        supabase,
        table,
        select,
        eq=filters,
        page_size=batch_size
    )
