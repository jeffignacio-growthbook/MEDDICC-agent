#!/usr/bin/env python3
"""
GATE 1: Tool schema completeness check.

CRITICAL GATE: Prevents handler parameter gaps from recurring.

The Gap Pattern (Pre-2026-09-10):
- query_pipeline_movement handler CODE: params.get("time_window", {})
- Router.py tool description: did NOT list time_window parameter
- Model couldn't use the parameter (schema said it didn't exist)
- Result: "last 2 weeks" questions fell back to arbitrary snapshot pairs
  (e.g., Aug 17-28 instead of requested Aug 27-Sep 10)

This test FAILS THE BUILD if:
1. A handler function reads a parameter via params.get("X") or params["X"]
2. That parameter is NOT documented in router.py's tool description
3. OR a tool description lists a parameter the handler never reads

Source of Truth: Actual params.get()/params[] calls in handler CODE
(not docstrings - docstring omissions aren't functional bugs)
vs tool descriptions in router.py's unified-routing prompt.

Coverage: Validates all handlers migrated to unified-routing
(identified by query_* naming pattern and presence in router.py).

Reuses extraction logic from test_handler_schema_completeness.py
(proven regex-based approach for params.get() detection).
"""
import re
import sys
from pathlib import Path
from typing import Dict, Set, List, Tuple

# Setup paths
REPO_ROOT = Path(__file__).parent.parent

# Known parameters that are infrastructure (not exposed to model)
INFRASTRUCTURE_PARAMS = {
    "sb",  # Supabase client - always injected by router
}

# Parameters computed by router from conversation context (not in tool schemas)
# These are INTERNAL - model can't specify them, router computes them
COMPUTED_PARAMS = {
    "company",  # Extracted from entity_registry
    "company_names",  # Extracted from entity_registry
    "companies",  # Extracted from entity_registry
    "pipeline_id",  # Resolved from pipeline_filter by handler, not user input

    # NOTE: deal_ids removed - it IS documented in some tool schemas
    # (query_deals_at_risk, query_win_loss) even though often computed
}

# Known parameter aliases (different names for same semantic param)
PARAM_ALIASES = {
    "rep_email": "owner_email",  # rep_email accepted as alias
    "owner": "owner_email",  # owner accepted as alias
}


def extract_handler_params_from_code(handlers_file: Path) -> Dict[str, Set[str]]:
    """
    Extract params.get() and params[] calls from each handler function.

    Reuses proven extraction logic from test_handler_schema_completeness.py.
    Also detects helper function calls that read params (_resolve_tw, _resolve_owner_email).

    Returns: {
        "query_pipeline_movement": {"view", "fiscal_quarter", "time_window", ...},
        ...
    }
    """
    content = handlers_file.read_text()

    # Helper functions that read specific params
    # _resolve_tw reads: time_window
    # _resolve_owner_email reads: owner_email (also rep_email, sdr_email as aliases)
    HELPER_FUNCTION_PARAMS = {
        "_resolve_tw": {"time_window"},
        "_resolve_owner_email": {"owner_email"},  # Covers rep_email, sdr_email aliases
    }

    # Find all async def functions that take params
    # Match: async def query_xxx(params: dict, sb) -> dict:
    handler_pattern = r'async def (query_\w+)\([^)]*params[^)]*\).*?(?=\nasync def |\nclass |\nif __name__|\Z)'
    handlers = {}

    for match in re.finditer(handler_pattern, content, re.DOTALL):
        handler_name = match.group(1)
        handler_body = match.group(0)

        # Extract all params.get("X") and params["X"] calls
        param_gets = re.findall(r'params\.get\(["\'](\w+)["\']', handler_body)
        param_brackets = re.findall(r'params\[["\'](\w+)["\']\]', handler_body)

        all_params = set(param_gets + param_brackets)

        # Check for helper function calls that read params
        for helper_func, helper_params in HELPER_FUNCTION_PARAMS.items():
            # Pattern: helper_func(params, ...) or helper_func(params)
            if re.search(rf'{helper_func}\s*\(\s*params', handler_body):
                all_params.update(helper_params)

        # Remove infrastructure params
        all_params = all_params - INFRASTRUCTURE_PARAMS

        if all_params:
            handlers[handler_name] = all_params

    return handlers


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

        # Parse parameter names from function signature in description
        # e.g., "owner_email, stage_filter, pipeline_filter" -> ["owner_email", "stage_filter", "pipeline_filter"]
        documented_params = []
        if params_str.strip():
            documented_params = [p.strip() for p in params_str.split(",")]

        tools[tool_name] = {
            "documented_params": documented_params,
            "description_location": f"line {i}",
        }

    return tools


def validate_tool_schema_completeness() -> Tuple[List[Tuple], List[Tuple], int]:
    """
    Validate that tool schemas match actual handler code usage.

    Returns: (missing_params, extra_params, handlers_checked)
        missing_params: [(handler, param, location), ...] - params in code but not documented
        extra_params: [(handler, param, location), ...] - params documented but not in code
        handlers_checked: number of handlers validated
    """
    handlers_file = REPO_ROOT / "api" / "handlers.py"
    handler_params = extract_handler_params_from_code(handlers_file)
    tool_descriptions = extract_tool_descriptions_from_router()

    missing_params = []
    extra_params = []
    handlers_checked = 0

    # Check each handler that has a tool description
    for handler_name in handler_params.keys():
        if handler_name not in tool_descriptions:
            # Handler exists but not yet migrated to unified-routing
            continue

        handlers_checked += 1

        code_params = handler_params[handler_name].copy()
        tool_info = tool_descriptions[handler_name]
        documented_params = set(tool_info["documented_params"])

        # Remove computed params (not in tool schemas)
        code_params = code_params - COMPUTED_PARAMS

        # Apply aliases (e.g., owner_email covers rep_email, owner)
        for alias, canonical in PARAM_ALIASES.items():
            if canonical in documented_params and alias in code_params:
                code_params.remove(alias)

        # Check for missing params (in code but not documented)
        for param in code_params:
            if param not in documented_params:
                # Check if it's an alias of a documented param
                canonical = PARAM_ALIASES.get(param)
                if canonical and canonical in documented_params:
                    continue

                missing_params.append((
                    handler_name,
                    param,
                    f"handlers.py (used in code)",
                    tool_info["description_location"]
                ))

        # Check for extra params (documented but not in code)
        for param in documented_params:
            # Check if param or any of its aliases exist in code
            param_exists = param in code_params
            aliases_exist = any(
                alias in code_params
                for alias, canonical in PARAM_ALIASES.items()
                if canonical == param
            )

            if not param_exists and not aliases_exist:
                extra_params.append((
                    handler_name,
                    param,
                    f"handlers.py (not used in code)",
                    tool_info["description_location"]
                ))

    return missing_params, extra_params, handlers_checked


def test_tool_schema_completeness():
    """
    CRITICAL CI GATE: Fail if tool schemas don't match handler code.

    This prevents the "time_window" gap pattern: handler code reading a
    parameter that's not documented in the tool schema, making it invisible
    to the model.
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
        print("\nThese parameters are READ in handler CODE but NOT documented")
        print("in router.py tool descriptions (model can't use them):\n")

        by_handler = {}
        for handler, param, handler_loc, tool_loc in missing:
            if handler not in by_handler:
                by_handler[handler] = []
            by_handler[handler].append((param, handler_loc, tool_loc))

        for handler in sorted(by_handler.keys()):
            print(f"\n{handler}:")
            for param, handler_loc, tool_loc in by_handler[handler]:
                print(f"  - Parameter: '{param}'")
                print(f"    Used in:  {handler_loc}")
                print(f"    Tool doc: {tool_loc}")

    if extra:
        has_gaps = True
        print("\n" + "=" * 80)
        print("❌ EXTRA PARAMETERS DETECTED")
        print("=" * 80)
        print("\nThese parameters are documented in router.py but NEVER READ")
        print("in handler code (dead schema entries):\n")

        by_handler = {}
        for handler, param, handler_loc, tool_loc in extra:
            if handler not in by_handler:
                by_handler[handler] = []
            by_handler[handler].append((param, handler_loc, tool_loc))

        for handler in sorted(by_handler.keys()):
            print(f"\n{handler}:")
            for param, handler_loc, tool_loc in by_handler[handler]:
                print(f"  - Parameter: '{param}'")
                print(f"    Not used in: {handler_loc}")
                print(f"    Tool doc:    {tool_loc}")

    if has_gaps:
        print("\n" + "=" * 80)
        print("This is the SAME GAP PATTERN as the 'time_window' incident:")
        print("  - query_pipeline_movement CODE: params.get('time_window', {})")
        print("  - Router.py tool description: did NOT list time_window")
        print("  - Model couldn't use the parameter")
        print("  - Result: time-based queries used wrong snapshot pairs")
        print("")
        print("FIX: Add missing parameters to router.py tool descriptions,")
        print("     or remove extra (unused) parameters from tool descriptions.")
        print("=" * 80)

        raise AssertionError(
            f"Found {len(missing)} missing and {len(extra)} extra parameter(s)"
        )

    print("\n✅ All tool schemas complete")
    print(f"   Validated {checked} unified-routing handlers")
    print(f"   All params in code are documented in router.py")
    print(f"   All params in router.py are used in code")
    print("=" * 80)


if __name__ == "__main__":
    test_tool_schema_completeness()
