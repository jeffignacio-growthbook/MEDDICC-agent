#!/usr/bin/env python3
"""
CI-enforced handler parameter completeness check.

CRITICAL GATE: Prevents the pipeline_filter bug pattern from recurring.

The Bug Pattern:
- Handler code reads params.get("pipeline_filter")
- Classifier schema never declares pipeline_filter
- Result: parameter silently stays None forever
- Handler's filtering code never executes
- Production gets wrong answer

This test FAILS THE BUILD if:
1. A handler reads a parameter via params.get("X")
2. That parameter is NOT in the classifier schema
3. AND it's NOT in the known exceptions list

Known Exceptions (Intentional Omissions):
- Internal params: deal_ids, owner_email, company, company_names
  → Computed by router from conversation context, not user-facing
- Pass-through params: question
  → Original user question, always available
- Legacy params: being phased out, handlers gracefully handle None

This is a STRUCTURAL GATE, not a one-off audit. It runs on every PR.
"""
import pytest
import re
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Parameters that handlers read but are INTENTIONALLY not in classifier schema
# These are computed by router or passed through from conversation context
KNOWN_INTERNAL_PARAMS = {
    # Computed by router from conversation/history
    "deal_ids",  # Extracted from entity_registry, conversation context
    "owner_email",  # Resolved from owner name via dimension resolver
    "company",  # Extracted from entity_registry
    "company_names",  # Extracted from entity_registry
    "companies",  # Extracted from entity_registry (plural variant)

    # Pass-through from conversation
    "question",  # Original user question, always available

    # Computed/resolved by primitives
    "fiscal_quarter",  # Computed from time_window by time_resolver
    "close_date_scope",  # Legacy, derived from time_window

    # Submission/correction params (not query params)
    "reason",  # For submit_score_correction
    "correction_reason",  # For submit_score_correction
    "submitted_by",  # For submit_score_correction
    "proposed_score",  # For submit_score_correction

    # Target-setting params (not query params)
    "role",  # For set_target
    "target_value",  # For set_target
    "metric",  # For set_target
    "entity_name",  # For set_target
    "period_label",  # For set_target

    # Bulk query internal params
    # (These handlers are called internally with pre-resolved params,
    # not directly from classifier - they're helper functions for dynamic_query)
}

# These are REAL PARAMETERS that SHOULD be in schema but currently aren't
# If this list is non-empty, the test FAILS and these need to be added
KNOWN_REAL_GAPS = {
    # Add parameters here that are confirmed gaps needing schema addition
    # Example: "pipeline_filter",  # TODO: Add to classifier schema
}


def extract_handler_params(handlers_file: Path) -> dict:
    """Extract params.get() calls from each handler function."""
    content = handlers_file.read_text()

    # Find all async def functions that take params
    handler_pattern = r'async def (\w+)\([^)]*params[^)]*\).*?(?=\nasync def |\nclass |\nif __name__|\Z)'
    handlers = {}

    for match in re.finditer(handler_pattern, content, re.DOTALL):
        handler_name = match.group(1)
        handler_body = match.group(0)

        # Extract all params.get("X") and params["X"] calls
        param_gets = re.findall(r'params\.get\(["\'](\w+)["\']', handler_body)
        param_brackets = re.findall(r'params\[["\'](\w+)["\']\]', handler_body)

        all_params = list(set(param_gets + param_brackets))

        if all_params:
            handlers[handler_name] = sorted(all_params)

    return handlers


def extract_schema_params_from_router_prompt() -> set:
    """
    Extract parameter names from router.py's classification prompt.

    The schema is defined as a JSON structure in the prompt that the
    classifier model is instructed to return. This is the source of truth
    for what parameters can be extracted from user questions.

    Format in prompt (around line 877-905):
      "params": {{
        "time_window": {{ ... }},
        "company": "<description>",
        "pipeline_filter": "...",
        ...
      }}
    """
    router_file = REPO_ROOT / "api" / "router.py"

    if not router_file.exists():
        pytest.fail(f"router.py not found at {router_file}")

    content = router_file.read_text()

    # Find the params schema section in the classification prompt
    # It's between '"params": {{' and the closing '}}'
    # The double {{ }} are f-string escaping, actual JSON has single {}

    # Find the start of params schema
    params_start = content.find('"params": {{')
    if params_start == -1:
        pytest.fail("Could not find params schema in router.py classification prompt")

    # Find the matching closing braces
    # Count braces to find the right one (skip nested time_window object)
    brace_count = 0
    params_content_start = params_start + len('"params": ')
    i = params_content_start

    # Skip opening {{
    while i < len(content) and content[i] in ' {':
        if content[i] == '{':
            brace_count += 1
        i += 1

    # Find matching closing braces
    start = i
    while i < len(content) and brace_count > 0:
        if content[i] == '{':
            brace_count += 1
        elif content[i] == '}':
            brace_count -= 1
        i += 1

    params_section = content[start:i-1]

    # Extract parameter names from lines like:
    # "param_name": "description"  or  "param_name": {{ ... }}
    schema_params = set()

    for line in params_section.split('\n'):
        line = line.strip()
        if line.startswith('"') and '":' in line:
            # Extract param name from "param_name": ...
            match = re.match(r'"(\w+)":', line)
            if match:
                schema_params.add(match.group(1))

    return schema_params


def test_handler_schema_completeness():
    """
    CRITICAL CI GATE: Fail if handler reads param not in classifier schema.

    This prevents the pipeline_filter bug pattern: handler expects a
    parameter but classifier never sets it, so it silently stays None.
    """
    handlers_file = REPO_ROOT / "api" / "handlers.py"

    if not handlers_file.exists():
        pytest.fail(f"handlers.py not found at {handlers_file}")

    # Extract handler params
    handler_params = extract_handler_params(handlers_file)

    # Extract schema params
    schema_params = extract_schema_params_from_router_prompt()

    # Find real gaps (params that should be in schema but aren't)
    real_gaps = []

    for handler_name, params in sorted(handler_params.items()):
        for param in params:
            # Skip if intentionally omitted (internal param)
            if param in KNOWN_INTERNAL_PARAMS:
                continue

            # Skip if in schema
            if param in schema_params:
                continue

            # This is a REAL GAP
            real_gaps.append((handler_name, param))

    # Build error message
    if real_gaps:
        error_lines = [
            "",
            "=" * 80,
            "HANDLER PARAMETER SCHEMA GAPS DETECTED",
            "=" * 80,
            "",
            "The following handlers read parameters that are NOT in the classifier schema:",
            ""
        ]

        by_handler = {}
        for handler, param in real_gaps:
            if handler not in by_handler:
                by_handler[handler] = []
            by_handler[handler].append(param)

        for handler, params in sorted(by_handler.items()):
            error_lines.append(f"  ❌ {handler}: {params}")

        error_lines.extend([
            "",
            "This is the SAME BUG PATTERN as the pipeline_filter incident:",
            "  - Handler code reads params.get('X')",
            "  - Classifier schema never declares X",
            "  - Result: X silently stays None forever",
            "  - Handler's code path never executes",
            "  - Production gets wrong answer",
            "",
            "FIX: Add these parameters to the classifier schema in api/table_classifier.py",
            "",
            "If a parameter is INTENTIONALLY omitted (internal/computed param),",
            "add it to KNOWN_INTERNAL_PARAMS in this test file.",
            "",
            "=" * 80,
        ])

        pytest.fail("\n".join(error_lines))

    print(f"✅ Handler schema completeness check PASSED")
    print(f"   Checked {len(handler_params)} handlers")
    print(f"   Found {len(schema_params)} parameters in classifier schema")
    print(f"   No real gaps detected")


def test_known_real_gaps_documented():
    """
    Fail if KNOWN_REAL_GAPS list is non-empty.

    If you know about a real gap but can't fix it immediately, you can
    temporarily add it to KNOWN_REAL_GAPS to unblock CI. But this test
    FAILS to ensure it doesn't stay there forever - the gap must be fixed.
    """
    if KNOWN_REAL_GAPS:
        error_lines = [
            "",
            "=" * 80,
            "KNOWN REAL GAPS LIST IS NON-EMPTY",
            "=" * 80,
            "",
            "The following parameters are documented as real gaps but haven't",
            "been added to the classifier schema yet:",
            ""
        ]

        for param in sorted(KNOWN_REAL_GAPS):
            error_lines.append(f"  - {param}")

        error_lines.extend([
            "",
            "This test FAILS to prevent these gaps from staying unfixed indefinitely.",
            "",
            "FIX: Add these parameters to the classifier schema, then remove them",
            "from KNOWN_REAL_GAPS in this test file.",
            "",
            "=" * 80,
        ])

        pytest.fail("\n".join(error_lines))


if __name__ == "__main__":
    # Allow running directly for quick local check
    pytest.main([__file__, "-v"])
