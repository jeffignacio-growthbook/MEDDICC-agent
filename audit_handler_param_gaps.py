#!/usr/bin/env python3
"""
Systematic audit: Find handler parameters that exist in handler code but
not in the classifier's params schema.

This is the exact failure mode that caused the pipeline_filter bug:
- query_pipeline handler reads params.get("pipeline_filter")
- Classifier schema didn't define pipeline_filter
- Result: pipeline_filter was ALWAYS None, filtering code never executed
- Bug went undetected because both CI and local tests passed

This audit prevents the same gap from recurring elsewhere.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

print("=" * 80)
print("HANDLER PARAMETER GAP AUDIT")
print("=" * 80)
print()
print("Checking: Does every handler-expected param exist in classifier schema?")
print()


def extract_handler_params(handlers_file: Path) -> dict:
    """Extract params.get() calls from each handler function."""
    content = handlers_file.read_text()

    # Find all async def functions
    handler_pattern = r'async def (\w+)\(.*?params.*?\).*?(?=\nasync def |\nclass |\Z)'
    handlers = {}

    for match in re.finditer(handler_pattern, content, re.DOTALL):
        handler_name = match.group(1)
        handler_body = match.group(0)

        # Extract all params.get("X") calls
        param_gets = re.findall(r'params\.get\(["\'](\w+)["\']', handler_body)

        if param_gets:
            handlers[handler_name] = list(set(param_gets))

    return handlers


def extract_schema_params(router_file: Path) -> set:
    """Extract all parameter names defined in the classifier's params schema."""
    content = router_file.read_text()

    # Find the params schema section - use single braces since string has {{}}
    # for f-string escaping
    schema_match = re.search(
        r'"params":\s*\{\{([^\}]+)\}\},',
        content,
        re.DOTALL
    )

    if not schema_match:
        print("❌ ERROR: Could not find params schema in router.py")
        sys.exit(1)

    schema_content = schema_match.group(1)

    # Extract parameter names - top-level keys in the JSON structure
    # Format: "param_name": "value" or "param_name": { (nested object)
    # Need to be careful not to match nested keys inside time_window

    # Split into lines and extract just the top-level param names
    param_names = []
    for line in schema_content.split('\n'):
        # Match lines like: "param_name": ...
        # But not inside nested objects (indentation check)
        line_stripped = line.lstrip()
        if line_stripped.startswith('"') and '":' in line_stripped:
            # Count leading spaces - top level params have 4 spaces
            spaces = len(line) - len(line_stripped)
            if spaces == 4:  # Top-level param
                param_name = re.match(r'"(\w+)":', line_stripped)
                if param_name:
                    param_names.append(param_name.group(1))

    return set(param_names)


def main():
    handlers_file = REPO_ROOT / "api" / "handlers.py"
    router_file = REPO_ROOT / "api" / "router.py"

    if not handlers_file.exists():
        print(f"❌ ERROR: {handlers_file} not found")
        sys.exit(1)

    if not router_file.exists():
        print(f"❌ ERROR: {router_file} not found")
        sys.exit(1)

    print("Files:")
    print(f"  Handlers: {handlers_file}")
    print(f"  Router:   {router_file}")
    print()

    # Extract handler params
    print("Extracting params from handlers...")
    handler_params = extract_handler_params(handlers_file)

    print(f"Found {len(handler_params)} handlers with params.get() calls")
    print()

    # Extract schema params
    print("Extracting params from classifier schema...")
    schema_params = extract_schema_params(router_file)

    print(f"Found {len(schema_params)} parameters in classifier schema:")
    print(f"  {sorted(schema_params)}")
    print()

    # Find gaps
    print("=" * 80)
    print("AUDIT RESULTS")
    print("=" * 80)
    print()

    gaps_found = []

    for handler_name, params in sorted(handler_params.items()):
        missing = [p for p in params if p not in schema_params]

        if missing:
            print(f"❌ {handler_name}:")
            print(f"   Handler reads: {params}")
            print(f"   Missing from schema: {missing}")
            print()
            gaps_found.append((handler_name, missing))

    if not gaps_found:
        print("✅ No gaps found - all handler params exist in classifier schema")
    else:
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print()
        print(f"Found {len(gaps_found)} handlers with parameter gaps:")
        print()

        for handler_name, missing in gaps_found:
            print(f"  {handler_name}: {missing}")

        print()
        print("These parameters should be added to the classifier schema")
        print("in api/router.py (around line 877-903) to prevent the same")
        print("'handler expects it but classifier never sets it' bug that")
        print("affected pipeline_filter.")

    print()
    print("=" * 80)
    print("KNOWN SAFE CASES (not gaps)")
    print("=" * 80)
    print()
    print("Some params are intentionally not in the schema:")
    print("  - Internal params set by router before calling handler")
    print("  - Computed params derived from other fields")
    print("  - Legacy params being phased out")
    print()
    print("If a param appears in the gap list above, check:")
    print("  1. Is it user-facing? (should be in schema)")
    print("  2. Is it internal/computed? (intentionally omitted)")
    print("  3. Is it legacy/unused? (can be removed from handler)")


if __name__ == "__main__":
    main()
