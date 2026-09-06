"""
Utils module - re-exports from parent utils.py to resolve naming conflict.
"""
import sys
from pathlib import Path

# Add parent scripts directory to path to import from utils.py
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import from the utils.py file (not this module)
import importlib.util
spec = importlib.util.spec_from_file_location("fiscal_utils",
    Path(__file__).parent.parent / "utils.py")
fiscal_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fiscal_utils)

# Re-export all functions from utils.py
load_client_config = fiscal_utils.load_client_config
get_pipeline_config = fiscal_utils.get_pipeline_config
get_stage_order = fiscal_utils.get_stage_order
get_value_field = fiscal_utils.get_value_field
get_value_properties = fiscal_utils.get_value_properties
compute_deal_value = fiscal_utils.compute_deal_value
is_won_stage = fiscal_utils.is_won_stage
is_lost_stage = fiscal_utils.is_lost_stage
get_segment = fiscal_utils.get_segment
slugify = fiscal_utils.slugify
get_fiscal_quarter = fiscal_utils.get_fiscal_quarter
build_semantic_context = fiscal_utils.build_semantic_context

__all__ = [
    'load_client_config',
    'get_pipeline_config',
    'get_stage_order',
    'get_value_field',
    'get_value_properties',
    'compute_deal_value',
    'is_won_stage',
    'is_lost_stage',
    'get_segment',
    'slugify',
    'get_fiscal_quarter',
    'build_semantic_context'
]
