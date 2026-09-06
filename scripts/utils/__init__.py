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

# Re-export get_fiscal_quarter
get_fiscal_quarter = fiscal_utils.get_fiscal_quarter

__all__ = ['get_fiscal_quarter']
