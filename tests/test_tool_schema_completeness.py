#!/usr/bin/env python3
"""
GATE 1: Tool schema completeness check.

CRITICAL GATE: Prevents handler parameter gaps from recurring.

The Gap Pattern (Pre-2026-09-10):
- query_pipeline_movement handler accepted 'time_window' parameter
- Router.py tool description did NOT list 'time_window'
- Model couldn't use the parameter (schema said it didn't exist)
- Result: "last 2 weeks" questions fell back to arbitrary snapshot pairs
  (e.g., Aug 17-28 instead of requested Aug 27-Sep 10)

This test FAILS THE BUILD if:
1. A handler function accepts a parameter
2. That parameter is NOT documented in the router.py tool description
3. OR a tool description lists a parameter the handler doesn't accept

Source of Truth: Handler function signatures in api/handlers.py vs
tool descriptions in api/router.py's unified-routing prompt.

Coverage: Validates all handlers that have been migrated to unified-routing
(identified by their query_* naming pattern and presence in router.py).
"""
import re
import sys
import inspect
from pathlib import Path
from typing import Dict, Set, List, Tuple

# Setup paths
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "api"))

# Import handlers module to inspect functions
import handlers

# Known parameters that are infrastructure (not exposed to model)
INFRASTRUCTURE_PARAMS = {
    "sb",  # Supabase client - always injected by router
    "params",  # Dict wrapper for all params in some handlers
}

# Known parameters that are documented differently
PARAM_ALIASES = {
    "rep_email": "owner_email",  # rep_email is accepted as alias
}


def extract_tool_descriptions_from_router() -> Dict[str, Dict]:
    """
    Parse router.py to extract tool descriptions and their parameters.

    Returns: {
        "query_pipeline_movement": {
            "documented_params": ["view", "fiscal_quarter", "time_window", ...],
            "description_location": "line 1245",
        },
        ...
    }
    """
    router_path = REPO_ROOT / "api" / "router.py"
    content = router_path.read_text()

    tools = {}

    # Pattern: query_xxx(...) in tool descriptions
    # These appear in the "TOOLS YOU CAN CALL:" section
    tool_pattern = r'(query_\w+)\((.*?)\)'

    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        match = re.search(tool_pattern, line)
        if not match:
            continue

        tool_name = match.group(1)
        params_str = match.group(2)

        # Parse parameter names from the function signature in the description
        # e.g., "owner_email, stage_filter, pipeline_filter" -> ["owner_email", "stage_filter", "pipeline_filter"]
        documented_params = []
        if params_str.strip():
            documented_params = [p.strip() for p in params_str.split(",")]

        tools[tool_name] = {
            "documented_params": documented_params,
            "description_location": f"line {i}",
        }

    return tools


def extract_handler_signatures() -> Dict[str, Dict]:
    """
    Inspect api/handlers.py to extract actual function signatures.

    Returns: {
        "query_pipeline_movement": {
            "actual_params": ["params", "sb"],
            "source": "api/handlers.py:5003",
        },
        ...
    }

    Note: Most handlers use params: dict pattern, so we need to parse docstrings
    to find the actual semantic parameters extracted from params dict.
    """
    handler_funcs = {}

    # Get all functions from handlers module that match query_* pattern
    for name, obj in inspect.getmembers(handlers):
        if not name.startswith("query_"):
            continue
        if not inspect.isfunction(obj) and not inspect.iscoroutinefunction(obj):
            continue

        # Get function signature
        sig = inspect.signature(obj)
        actual_params = list(sig.parameters.keys())

        # Get source location
        try:
            source_file = inspect.getsourcefile(obj)
            source_lines = inspect.getsourcelines(obj)
            line_no = source_lines[1]
            location = f"{Path(source_file).name}:{line_no}"
        except:
            location = "unknown"

        # Parse docstring to find params documented there
        docstring_params = []
        if obj.__doc__:
            # Look for "params:" section or "Args:" section
            doc_lines = obj.__doc__.split("\n")
            in_params_section = False
            params_indent = None

            for line in doc_lines:
                stripped = line.strip()

                # Detect params section start
                if stripped == "params:" or stripped == "Args:" or stripped.startswith("Parameters:"):
                    in_params_section = True
                    # Record the indentation level of the params: line
                    params_indent = len(line) - len(line.lstrip())
                    continue

                # Detect section end: a non-empty line at same or less indentation than params:
                if in_params_section and line.strip():
                    current_indent = len(line) - len(line.lstrip())
                    # If we hit a line at same or lesser indentation than "params:", section ends
                    if current_indent <= params_indent:
                        in_params_section = False

                # Extract parameter names from docstring
                if in_params_section and stripped:
                    # Pattern: "  param_name : description" or "  param_name: description"
                    # Allow for various whitespace between param and colon
                    param_match = re.match(r'(\w+)\s*:', stripped)
                    if param_match:
                        docstring_params.append(param_match.group(1))

        handler_funcs[name] = {
            "actual_params": actual_params,
            "docstring_params": docstring_params,
            "source": location,
        }

    return handler_funcs


def validate_tool_schema_completeness() -> Tuple[List[Tuple], List[Tuple], int]:
    """
    Validate that tool schemas match handler signatures.

    Returns: (missing_params, extra_params, handlers_checked)
        missing_params: [(handler, param, location), ...] - params in handler but not documented
        extra_params: [(handler, param, location), ...] - params documented but not in handler
        handlers_checked: number of handlers validated
    """
    tool_descriptions = extract_tool_descriptions_from_router()
    handler_signatures = extract_handler_signatures()

    missing_params = []
    extra_params = []
    handlers_checked = 0

    # Check each handler that has a tool description
    for handler_name in handler_signatures.keys():
        if handler_name not in tool_descriptions:
            # Handler exists but not yet migrated to unified-routing
            continue

        handlers_checked += 1

        handler_info = handler_signatures[handler_name]
        tool_info = tool_descriptions[handler_name]

        # Get semantic params from handler (prefer docstring params over signature params)
        # Most handlers use params: dict, so docstring is source of truth
        handler_params = set(handler_info["docstring_params"]) if handler_info["docstring_params"] else set(handler_info["actual_params"])

        # Remove infrastructure params
        handler_params = handler_params - INFRASTRUCTURE_PARAMS

        # Get documented params from tool description
        documented_params = set(tool_info["documented_params"])

        # Apply aliases (e.g., owner_email covers rep_email)
        for alias, canonical in PARAM_ALIASES.items():
            if canonical in documented_params and alias in handler_params:
                handler_params.remove(alias)

        # Check for missing params (in handler but not documented)
        for param in handler_params:
            if param not in documented_params:
                missing_params.append((
                    handler_name,
                    param,
                    handler_info["source"],
                    tool_info["description_location"]
                ))

        # Check for extra params (documented but not in handler)
        for param in documented_params:
            # Skip if it's a known alias
            if param in PARAM_ALIASES.values():
                # Check if the handler accepts either the canonical or any alias
                aliases_for_param = [k for k, v in PARAM_ALIASES.items() if v == param]
                if param not in handler_params and not any(a in handler_params for a in aliases_for_param):
                    extra_params.append((
                        handler_name,
                        param,
                        handler_info["source"],
                        tool_info["description_location"]
                    ))
            elif param not in handler_params:
                extra_params.append((
                    handler_name,
                    param,
                    handler_info["source"],
                    tool_info["description_location"]
                ))

    return missing_params, extra_params, handlers_checked


def test_tool_schema_completeness():
    """
    CRITICAL CI GATE: Fail if tool schemas don't match handler signatures.

    This prevents the "time_window" gap pattern: handler accepting a parameter
    that's not documented in the tool schema, making it invisible to the model.
    """
    print("\n" + "=" * 80)
    print("GATE 1: Tool Schema Completeness Check")
    print("=" * 80)

    missing, extra, checked = validate_tool_schema_completeness()

    # Report coverage
    print(f"\n📊 Coverage: {checked} unified-routing handlers validated")

    # Report gaps
    has_gaps = False

    if missing:
        has_gaps = True
        print("\n" + "=" * 80)
        print("❌ MISSING PARAMETERS DETECTED")
        print("=" * 80)
        print("\nThese parameters exist in handler functions but are NOT documented")
        print("in router.py tool descriptions:\n")

        by_handler = {}
        for handler, param, handler_loc, tool_loc in missing:
            if handler not in by_handler:
                by_handler[handler] = []
            by_handler[handler].append((param, handler_loc, tool_loc))

        for handler in sorted(by_handler.keys()):
            print(f"\n{handler}:")
            for param, handler_loc, tool_loc in by_handler[handler]:
                print(f"  - Parameter: '{param}'")
                print(f"    Handler:  {handler_loc}")
                print(f"    Tool doc: {tool_loc}")

    if extra:
        has_gaps = True
        print("\n" + "=" * 80)
        print("❌ EXTRA PARAMETERS DETECTED")
        print("=" * 80)
        print("\nThese parameters are documented in router.py but DON'T exist")
        print("in handler functions:\n")

        by_handler = {}
        for handler, param, handler_loc, tool_loc in extra:
            if handler not in by_handler:
                by_handler[handler] = []
            by_handler[handler].append((param, handler_loc, tool_loc))

        for handler in sorted(by_handler.keys()):
            print(f"\n{handler}:")
            for param, handler_loc, tool_loc in by_handler[handler]:
                print(f"  - Parameter: '{param}'")
                print(f"    Handler:  {handler_loc}")
                print(f"    Tool doc: {tool_loc}")

    if has_gaps:
        print("\n" + "=" * 80)
        print("This is the SAME GAP PATTERN as the 'time_window' incident:")
        print("  - query_pipeline_movement accepted 'time_window' parameter")
        print("  - Router.py tool description did NOT list it")
        print("  - Model couldn't use the parameter")
        print("  - Result: time-based queries used wrong snapshot pairs")
        print("")
        print("FIX: Add missing parameters to router.py tool descriptions,")
        print("     or remove extra parameters from tool descriptions.")
        print("=" * 80)

        raise AssertionError(
            f"Found {len(missing)} missing and {len(extra)} extra parameter(s)"
        )

    print("\n✅ All tool schemas complete")
    print(f"   Validated {checked} unified-routing handlers")
    print("=" * 80)


if __name__ == "__main__":
    test_tool_schema_completeness()
