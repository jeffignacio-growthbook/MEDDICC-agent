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

def get_pipeline_config() -> Dict[str, Any]:
    """
    Load pipeline configuration from config/client.yaml.

    Returns:
        dict: Pipeline configuration with 'pipelines' key containing stage details
    """
    config_path = Path(__file__).parent.parent / 'config' / 'client.yaml'
    if not config_path.exists():
        return {'pipelines': []}

    with open(config_path) as f:
        config = yaml.safe_load(f)

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


def get_value_field(pipeline_config: Optional[Dict] = None) -> str:
    """
    Get the deal value field name (amount or incremental_arr).

    Args:
        pipeline_config: Optional pipeline config dict (loaded if not provided)

    Returns:
        str: Field name ('incremental_arr' or 'amount')
    """
    if pipeline_config is None:
        pipeline_config = get_pipeline_config()

    return pipeline_config.get('value_field', 'amount')


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
