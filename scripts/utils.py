"""
Shared utility functions for MEDDICC agent.

This module provides common functionality used across ETL and analysis scripts.
"""

import re
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional


# ============================================================================
# PIPELINE CONFIGURATION HELPERS
# ============================================================================

def load_client_config() -> Dict[str, Any]:
    """
    Load full client configuration from config/client.yaml.

    Returns:
        dict: Full configuration dictionary
    """
    config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        return yaml.safe_load(f)


def get_pipeline_config(config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Load pipeline configuration from config/client.yaml.

    Args:
        config: Optional pre-loaded config dict (loaded if not provided)

    Returns:
        dict: Pipeline configuration with 'pipelines' key containing stage details
    """
    if config is None:
        config = load_client_config()

    return config.get('pipeline', {})


def get_stage_order(stage_id: str, pipeline_config: Optional[Dict] = None) -> Optional[int]:
    """
    Get the order value for a stage ID.

    Args:
        stage_id: HubSpot stage ID
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        int: Stage order value, or None if not found
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    for pipeline in pipeline_config.get('pipelines', []):
        for stage in pipeline.get('stages', []):
            if stage.get('id') == stage_id:
                return stage.get('order')

    return None


def get_value_field(pipeline_config: Optional[Dict] = None):
    """
    Get the deal value field configuration (string or dict).

    Args:
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        str or dict: Field name ('incremental_arr') or computed config dict
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    return pipeline_config.get('value_field', 'amount')


def get_value_properties(config: Optional[Dict] = None) -> list:
    """
    HubSpot property names the ETL must fetch to compute deal value.
    String field -> [field]; computed -> its components.

    Args:
        config: Optional full config dict (loaded if not provided)

    Returns:
        list: Property names to fetch from HubSpot
    """
    if config is None:
        from pathlib import Path
        import yaml
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
        else:
            config = {}

    vf = config.get('pipeline', {}).get('value_field', 'amount')
    if isinstance(vf, dict):
        return list(vf.get('components', []))
    return [vf]


def compute_deal_value(properties: dict, config: Optional[Dict] = None) -> float:
    """
    NULL-safe deal value from a HubSpot properties dict.
    Blanks/None/'' -> 0. Works for both config shapes.

    Args:
        properties: HubSpot deal properties dict
        config: Optional full config dict (loaded if not provided)

    Returns:
        float: Computed deal value
    """
    if config is None:
        from pathlib import Path
        import yaml
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
        else:
            config = {}

    vf = config.get('pipeline', {}).get('value_field', 'amount')
    names = (vf.get('components', []) if isinstance(vf, dict) else [vf])

    total = 0.0
    for n in names:
        raw = properties.get(n)
        try:
            # Strip $ and , from value strings, handle None/empty/null
            if raw not in (None, '', 'null'):
                clean = str(raw).replace('$', '').replace(',', '').strip()
                if clean:
                    total += float(clean)
        except (ValueError, TypeError):
            pass

    return total


def is_won_stage(stage_id: str, pipeline_config: Optional[Dict] = None) -> bool:
    """
    Check if a stage ID is a won stage.

    Args:
        stage_id: HubSpot stage ID
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        bool: True if stage is marked as won
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    for pipeline in pipeline_config.get('pipelines', []):
        for stage in pipeline.get('stages', []):
            if stage.get('id') == stage_id:
                return stage.get('is_won', False)

    return False


def is_lost_stage(stage_id: str, pipeline_config: Optional[Dict] = None) -> bool:
    """
    Check if a stage ID is a lost stage.

    Args:
        stage_id: HubSpot stage ID
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        bool: True if stage is marked as lost
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    for pipeline in pipeline_config.get('pipelines', []):
        for stage in pipeline.get('stages', []):
            if stage.get('id') == stage_id:
                return stage.get('is_lost', False)

    return False


def get_segment(employee_count: Optional[int], config: Optional[Dict] = None) -> tuple:
    """
    Return (segment_name, expected_cycle_days) for an employee count.

    Maps employee count to configured segmentation bands (SMB, Mid-Market,
    Enterprise). Returns 'Unknown' for None/missing employee counts.

    Args:
        employee_count: Number of employees (from Company.numberofemployees)
        config: Optional full config dict (loaded if not provided)

    Returns:
        tuple: (segment_name, expected_cycle_days)
            e.g. ('SMB', 33), ('Enterprise', 132), ('Unknown', None)

    Examples:
        get_segment(100) -> ('SMB', 33)
        get_segment(500) -> ('Mid-Market', 84)
        get_segment(5000) -> ('Enterprise', 132)
        get_segment(None) -> ('Unknown', None)
    """
    if config is None:
        config = load_client_config()

    bands = config.get('segmentation', {}).get('bands', [])

    # Handle None/missing employee count -> Unknown
    if employee_count is None:
        unknown = next((b for b in bands if b['name'] == 'Unknown'), None)
        return ('Unknown', unknown.get('expected_cycle_days') if unknown else None)

    # Find matching band
    for band in bands:
        lo = band.get('min', 0)
        hi = band.get('max', float('inf'))
        if lo <= employee_count <= hi:
            return (band['name'], band.get('expected_cycle_days'))

    # No match found -> Unknown
    return ('Unknown', None)


# ============================================================================
# STRING UTILITIES
# ============================================================================

def slugify(name: str) -> str:
    """
    Convert company name to slug (e.g., 'Skyscanner + GrowthBook' -> 'skyscanner').

    CRITICAL: This logic must be identical across etl_calls.py, etl_deals.py,
    and run_nightly.py to ensure cache files match correctly.

    Args:
        name: Company name from HubSpot deal or call transcript

    Returns:
        str: Slugified company name for cache file naming

    Examples:
        'Acme Corp' -> 'acme-corp'
        'Scale AI' -> 'scale-ai'
        'Notion Labs Inc' -> 'notion-labs-inc'
        'Skyscanner + GrowthBook' -> 'skyscanner'
        'GrowthBook <> ClickHouse' -> 'clickhouse'
    """
    if not name:
        return ''

    # Split on connector symbols (-, +, <>, &, /) and "and"
    # This handles: "Skyscanner - GrowthBook", "Client + GrowthBook", etc.
    parts = re.split(r'\s*[-–—]\s+', name, maxsplit=1)
    company_part = parts[0]

    # Remove "GrowthBook" (case-insensitive) from anywhere in the name
    # Handles: "GrowthBook + Client" or "Client + GrowthBook"
    company_part = re.sub(r'growthbook', '', company_part, flags=re.IGNORECASE)

    # Remove connector symbols that might remain
    company_part = re.sub(r'[+<>&/,]', ' ', company_part)

    # Remove common filler words
    company_part = re.sub(
        r'\b(and|the|with|vs|versus|for|at|in|of)\b',
        '', company_part, flags=re.IGNORECASE
    )

    # Normalize whitespace and lowercase
    company_part = re.sub(r'\s+', ' ', company_part).strip().lower()

    # Remove non-alphanumeric characters (except spaces)
    company_part = re.sub(r'[^a-z0-9\s]', '', company_part)

    # Convert to hyphenated slug
    slug = company_part.replace(' ', '-').strip('-')

    # Return slug if >= 3 chars (avoid single-letter slugs)
    return slug if len(slug) >= 3 else ''


def get_fiscal_quarter(as_of=None, config: Optional[Dict] = None) -> tuple:
    """
    Return (q_start_date, q_end_date, label) for the fiscal quarter
    containing as_of, from fiscal.fy_start_month.

    fy_start_month=2 => Feb-Apr, May-Jul, Aug-Oct, Nov-Jan
    FY label is the year of the FY END (May 2026 sits in FY2027 Q2)

    Args:
        as_of: Date to find quarter for (default: today)
        config: Optional full config dict (loaded if not provided)

    Returns:
        tuple: (start_date, end_date, label) e.g. (date(2026,5,1), date(2026,7,31), "FY2027 Q2")
    """
    from datetime import date
    from dateutil.relativedelta import relativedelta

    if as_of is None:
        as_of = date.today()

    if config is None:
        from pathlib import Path
        import yaml
        config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
        else:
            config = {}

    fy_start_month = config.get('fiscal', {}).get('fy_start_month', 1)

    # Find which quarter this date falls in
    # Quarters are 3 months each starting from fy_start_month
    year = as_of.year
    month = as_of.month

    # Calculate months since FY start
    if month >= fy_start_month:
        # Same fiscal year
        fy_year = year + 1  # FY label is END year
        months_into_fy = month - fy_start_month
    else:
        # Previous fiscal year
        fy_year = year
        months_into_fy = (12 - fy_start_month) + month

    # Which quarter (0-3)?
    quarter_num = months_into_fy // 3 + 1  # 1-4

    # Calculate quarter start
    q_start_month = fy_start_month + ((quarter_num - 1) * 3)
    if q_start_month > 12:
        q_start_month -= 12
        q_start_year = fy_year
    else:
        q_start_year = fy_year - 1

    q_start = date(q_start_year, q_start_month, 1)

    # Quarter end is last day of 3rd month
    q_end = q_start + relativedelta(months=3) - relativedelta(days=1)

    label = f"FY{fy_year} Q{quarter_num}"

    return (q_start, q_end, label)
