#!/usr/bin/env python3
"""
Generate handlers from high-frequency entity-scope patterns via GitHub PR.

Task G.8.5: When patterns repeat frequently, generate dedicated handlers
with proper validation gates and human review.

Usage:
    python scripts/generate_handler_from_pattern.py --dry-run
    python scripts/generate_handler_from_pattern.py --create-pr

Four validation gates (matching handler_generator.py):
    1. Safety: Read-only, no dangerous imports, valid syntax
    2. Execution: Test against real Supabase data
    3. Answer quality: Haiku validates result answers the questions
    4. Confidence: Generated handler confidence >= 0.6

Max 3 handlers per run. Never auto-merges. Requires human review.
"""

import os
import sys
import ast
import json
import argparse
from pathlib import Path
from datetime import datetime, date
from collections import Counter

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

GENERATOR_MODEL = "claude-sonnet-4-5-20250929"
VALIDATION_MODEL = "claude-haiku-4-5-20251001"

# Minimum frequency threshold for handler generation
MIN_FREQUENCY = 10
MIN_QUALITY = 0.7
MAX_HANDLERS_PER_RUN = 3

HANDLER_GENERATION_PROMPT = """Generate a new entity-scoped handler for a RevOps agent.

HIGH-FREQUENCY PATTERN:
Question: "{question}"
Frequency: {frequency}x (avg quality: {avg_quality:.2f})
Current routing: {current_handler}

EXISTING HANDLER PATTERN (follow exactly):
async def query_X(params: dict, sb) -> dict:
    \"\"\"Brief description of what this returns.\"\"\"
    deal_ids = params.get("deal_ids", [])
    if not deal_ids:
        return {{"error": "No deal_ids provided"}}

    from supabase_client import select_all
    rows = select_all(sb, "table_name",
        columns="col1,col2",
        filters=[("in", "deal_id", deal_ids)])

    return {{"result_key": rows, "count": len(rows)}}

AVAILABLE SUPABASE TABLES:
{schema_context}

CONSTRAINTS (CRITICAL):
- ONLY use select_all() for reads — no writes, deletes, updates
- Import only: select_all from supabase_client, Counter from collections
- Filter by deal_ids using: filters=[("in", "deal_id", deal_ids)]
- Return dict with clear keys (not "rows")
- Function name: query_<descriptive_action> (lowercase, underscores)
- Must accept (params: dict, sb) and be async
- Handle empty deal_ids gracefully
- Keep under 60 lines

Generate JSON (no markdown):
{{
  "handler_name": "query_calls_for_deals",
  "handler_code": "async def query_...",
  "description": "call transcripts for specific deals",
  "evaluator_key": "calls",
  "confidence": 0.0-1.0,
  "explanation": "why this handler answers the pattern"
}}"""

VALIDATION_PROMPT = """A handler was generated for this pattern:
Question: "{question}"
Frequency: {frequency}x

Handler returned this when tested:
{result_sample}

Does this result answer the question pattern?
Score 0-1 and explain.

JSON response:
{{
  "score": 0.0-1.0,
  "answers_question": true/false,
  "missing": "what's missing (if score < 0.8)",
  "ready_for_pr": true/false
}}"""


def _extract_json(text: str) -> dict | None:
    """Extract JSON from Claude response, handling markdown fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except:
        pass

    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            try:
                return json.loads(block)
            except:
                continue
    return None


def find_handler_candidates(sb, min_freq=MIN_FREQUENCY, min_quality=MIN_QUALITY):
    """Find high-frequency patterns suitable for handler generation."""
    result = sb.table("entity_scope_patterns")\
        .select("*")\
        .gte("quality_score", min_quality)\
        .execute()

    patterns = result.data
    if not patterns:
        return []

    # Group by normalized question
    pattern_groups = {}
    for p in patterns:
        normalized = p["question"].lower().strip()
        pattern_groups.setdefault(normalized, []).append(p)

    # Find high-frequency patterns
    candidates = []
    for question, instances in pattern_groups.items():
        if len(instances) >= min_freq:
            handler_counter = Counter(p["handler_name"] for p in instances)
            most_common = handler_counter.most_common(1)[0]

            candidates.append({
                "question": question,
                "frequency": len(instances),
                "avg_quality": sum(p["quality_score"] for p in instances) / len(instances),
                "avg_entities": sum(p["entity_count"] for p in instances) / len(instances),
                "current_handler": most_common[0],
                "latest": max(p["asked_at"] for p in instances)
            })

    candidates.sort(key=lambda x: x["frequency"], reverse=True)
    return candidates


def generate_handler(pattern_data: dict, schema_context: str, client) -> dict | None:
    """Use Claude Sonnet to generate handler from pattern."""
    resp = client.messages.create(
        model=GENERATOR_MODEL,
        max_tokens=2000,
        system="Respond with valid JSON only. No markdown fences.",
        messages=[{"role": "user", "content":
            HANDLER_GENERATION_PROMPT.format(
                question=pattern_data["question"],
                frequency=pattern_data["frequency"],
                avg_quality=pattern_data["avg_quality"],
                current_handler=pattern_data["current_handler"],
                schema_context=schema_context
            )
        }]
    )

    parsed = _extract_json(resp.content[0].text)
    if parsed is None:
        print(f"  Generation failed: could not parse JSON")
    return parsed


def validate_handler_code(code: str) -> tuple[bool, str]:
    """
    Gate 1: Safety validation - check code is safe to execute.
    Returns (is_safe, reason).
    """
    FORBIDDEN = [
        "import os", "import subprocess", "import sys",
        "__import__", "exec(", "eval(", "open(",
        ".delete(", ".update(", ".insert(", ".upsert(",
        "DROP ", "DELETE ", "UPDATE ", "INSERT ",
    ]

    code_upper = code.upper()
    for forbidden in FORBIDDEN:
        if forbidden.upper() in code_upper:
            return False, f"Forbidden pattern: {forbidden}"

    # Syntax check
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    # Must be async query function
    if "async def query_" not in code:
        return False, "Must be async def query_*"

    return True, "OK"


async def test_handler(code: str, handler_name: str, sb) -> dict:
    """
    Gate 2: Execute handler against real Supabase data.
    Returns {"success": bool, "result": dict, "error": str}
    """
    from api.time_resolver import resolve_time_window

    namespace = {}
    try:
        exec(
            "from supabase_client import select_all\n"
            "from collections import Counter\n"
            + code,
            namespace
        )
    except Exception as e:
        return {"success": False, "result": {}, "error": f"Exec failed: {e}"}

    handler_fn = namespace.get(handler_name)
    if not handler_fn:
        return {"success": False, "result": {},
                "error": f"Handler {handler_name} not found in namespace"}

    # Test with sample deal_ids from database
    try:
        deals_result = sb.table("deals").select("deal_id").limit(5).execute()
        sample_deal_ids = [d["deal_id"] for d in deals_result.data]

        if not sample_deal_ids:
            return {"success": False, "result": {},
                    "error": "No sample deal_ids available for testing"}

        tw = resolve_time_window({"period": "current_quarter"})
        result = await handler_fn(
            {"deal_ids": sample_deal_ids, "time_window": tw}, sb)

        return {"success": True, "result": result, "error": None}
    except Exception as e:
        return {"success": False, "result": {}, "error": str(e)}


def validate_answer_quality(pattern_data: dict, result: dict, client) -> dict:
    """
    Gate 3: Ask Haiku if result actually answers the question pattern.
    Returns validation assessment.
    """
    result_sample = json.dumps(result, default=str)[:1000]

    resp = client.messages.create(
        model=VALIDATION_MODEL,
        max_tokens=200,
        system="Respond with valid JSON only.",
        messages=[{"role": "user", "content":
            VALIDATION_PROMPT.format(
                question=pattern_data["question"],
                frequency=pattern_data["frequency"],
                result_sample=result_sample
            )
        }]
    )

    parsed = _extract_json(resp.content[0].text)
    return parsed if parsed else {"score": 0.5, "ready_for_pr": False}


def create_github_pr(handler_name: str, handler_code: str,
                     description: str, evaluator_key: str,
                     pattern_data: dict):
    """
    Create GitHub PR via GitHubMemory (no local git operations).

    Only appends handler to api/handlers.py. HANDLER_DESCRIPTIONS
    must be added manually (too risky for auto-edit).

    Returns PR URL or None.
    """
    from github_memory import GitHubMemory

    branch = (f"auto-handler-pattern-{handler_name}-"
              f"{datetime.now().strftime('%Y%m%d%H%M%S')}")

    pr_title = (f"Auto-generated handler: {handler_name} "
                f"(pattern: {pattern_data['frequency']}x)")

    handlers_path = REPO_ROOT / "api" / "handlers.py"
    existing_code = handlers_path.read_text()
    new_code = existing_code.rstrip("\n") + f"\n\n\n{handler_code}\n"

    print(f"\nManual additions needed after merge:")
    print(f'  HANDLER_DESCRIPTIONS: "{handler_name}": "{description}",')

    pr_body = f"""## Auto-generated handler: `{handler_name}`

**Generated by:** generate_handler_from_pattern.py (Task G.8.5)
**Date:** {date.today()}
**Pattern frequency:** {pattern_data['frequency']}x (avg quality: {pattern_data['avg_quality']:.2f})

### Pattern this handler addresses
- **Question:** "{pattern_data['question']}"
- **Previously routed to:** {pattern_data['current_handler']}
- **Occurrences:** {pattern_data['frequency']} times

### What was added
- `{handler_name}()` appended to `api/handlers.py`

### Still needs manual addition
- HANDLER_DESCRIPTIONS entry in `api/router.py`:
  ```python
  "{handler_name}": "{description}",
  ```

### Validation gates passed
- ✅ Safety check (read-only, no dangerous imports)
- ✅ Syntax check (valid Python, async def query_*)
- ✅ Execution test (ran against real Supabase data)
- ✅ Answer quality (Haiku confirmed result answers question)

### Human review checklist
- [ ] Handler code is read-only (verify no writes/deletes)
- [ ] Return dict makes sense for the question pattern
- [ ] HANDLER_DESCRIPTIONS entry added to router.py
- [ ] Tested locally with real entity-scoped questions
- [ ] Quality improvement vs current handler verified

**Auto-generated — requires human review. DO NOT MERGE without verification.**
"""

    try:
        gm = GitHubMemory(REPO_ROOT)
        pr_url = gm.create_pr(
            branch_name=branch,
            title=pr_title,
            body=pr_body,
            files_to_commit={"api/handlers.py": new_code},
        )
        return pr_url
    except Exception as e:
        print(f"  PR creation failed: {e}")
        print(f"  Add handler manually from code below:")
        print(f"\n{handler_code}\n")
        return None


async def main():
    import anthropic
    from api.db import get_supabase
    from api.schema_context import get_schema_context

    parser = argparse.ArgumentParser(
        description="Generate handlers from high-frequency patterns"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without creating PRs"
    )
    parser.add_argument(
        "--create-pr",
        action="store_true",
        help="Create GitHub PRs for passing handlers"
    )
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=MIN_FREQUENCY,
        help=f"Minimum pattern frequency (default: {MIN_FREQUENCY})"
    )
    args = parser.parse_args()

    sb = get_supabase()
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    schema = get_schema_context(sb)

    print(f"\n{'='*80}")
    print("HANDLER GENERATION FROM ENTITY-SCOPE PATTERNS")
    print(f"{'='*80}\n")

    # Find candidates
    print(f"Analyzing patterns (min frequency: {args.min_frequency})...")
    candidates = find_handler_candidates(sb, args.min_frequency, MIN_QUALITY)

    if not candidates:
        print(f"\nNo patterns found with frequency >= {args.min_frequency}")
        print("Wait for more data or lower threshold with --min-frequency")
        return 0

    print(f"Found {len(candidates)} candidates:\n")
    for i, c in enumerate(candidates[:10], 1):  # Show top 10
        print(f"{i}. [{c['frequency']:3d}x] {c['question'][:60]}")
        print(f"   Quality: {c['avg_quality']:.2f} | "
              f"Current: {c['current_handler']}")

    # Process top N candidates (max 3 per run)
    handlers_created = 0
    for i, pattern_data in enumerate(candidates[:MAX_HANDLERS_PER_RUN], 1):
        print(f"\n{'='*80}")
        print(f"Processing pattern {i}/{min(len(candidates), MAX_HANDLERS_PER_RUN)}")
        print(f"Question: \"{pattern_data['question']}\"")
        print(f"Frequency: {pattern_data['frequency']}x")

        # Generate handler
        print("\nGenerating handler with Sonnet...")
        generated = generate_handler(pattern_data, schema, client)
        if not generated:
            print("  ❌ Generation failed — skipping")
            continue

        handler_name = generated["handler_name"]
        handler_code = generated["handler_code"]
        confidence = generated.get("confidence", 0)

        print(f"  Generated: {handler_name} (confidence: {confidence:.2f})")

        # Gate 4: Confidence check
        if confidence < 0.6:
            print(f"  ❌ Low confidence — skipping")
            continue

        # Gate 1: Safety validation
        print("\n  Gate 1: Safety validation...")
        is_safe, reason = validate_handler_code(handler_code)
        if not is_safe:
            print(f"  ❌ Safety check failed: {reason}")
            continue
        print(f"  ✅ Safety check passed")

        if args.dry_run:
            print(f"\n  DRY RUN — Handler code:")
            print(handler_code)
            continue

        # Gate 2: Execution test
        print("  Gate 2: Execution test...")
        test_result = await test_handler(handler_code, handler_name, sb)
        if not test_result["success"]:
            print(f"  ❌ Test failed: {test_result['error']}")
            continue
        print(f"  ✅ Handler executed successfully")

        # Gate 3: Answer quality validation
        print("  Gate 3: Answer quality validation...")
        validation = validate_answer_quality(
            pattern_data, test_result["result"], client)
        score = validation.get("score", 0)
        print(f"  Quality score: {score:.2f}")

        if not validation.get("ready_for_pr"):
            print(f"  ❌ Not ready for PR: "
                  f"{validation.get('missing', 'low quality')}")
            continue
        print(f"  ✅ Quality check passed")

        # Create PR
        if args.create_pr:
            print("\n  Creating GitHub PR...")
            pr_url = create_github_pr(
                handler_name=handler_name,
                handler_code=handler_code,
                description=generated["description"],
                evaluator_key=generated["evaluator_key"],
                pattern_data=pattern_data
            )
            if pr_url:
                print(f"  ✅ PR created: {pr_url}")
                handlers_created += 1
            else:
                print(f"  ⚠️  PR creation failed (see code above)")
        else:
            print(f"\n  ✅ All gates passed — run with --create-pr to create PR")
            print(f"\n  Handler code:\n{handler_code}")

    print(f"\n{'='*80}")
    if args.create_pr:
        print(f"Summary: {handlers_created} handler(s) created as PRs")
        print(f"Max per run: {MAX_HANDLERS_PER_RUN} (prevents flooding)")
    else:
        print(f"Dry run complete. Use --create-pr to generate PRs.")
    print(f"{'='*80}\n")

    return 0


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
