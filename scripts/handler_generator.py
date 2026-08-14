#!/usr/bin/env python3
"""
Generates new precomputed handlers from clusters of
failed questions in unanswered_queries + learning_log.

Usage:
  python scripts/handler_generator.py
  python scripts/handler_generator.py --dry-run
  python scripts/handler_generator.py --cluster "competitive_intel"

Output:
  - Generated handler code (printed or saved to file)
  - Test results against real Supabase data
  - GitHub PR creation (if --create-pr flag)

Never auto-merges. Always requires human approval.
"""

import os, sys, json, ast
from pathlib import Path
from datetime import date, timedelta

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from supabase_client import select_all

GENERATOR_MODEL  = "claude-sonnet-4-5-20250929"
VALIDATION_MODEL = "claude-haiku-4-5-20251001"

HANDLER_GENERATION_PROMPT = """You are generating a new
precomputed handler for a CRO Slack agent that answers
RevOps questions from a Supabase database.

FAILED QUESTIONS THAT NEED A NEW HANDLER:
{questions}

EXISTING HANDLER PATTERN (follow exactly):
async def query_X(params, sb) -> dict:
    \"\"\"Docstring explaining what questions this answers.\"\"\"
    tw = params["time_window"]
    rows = select_all(sb, "table_name",
        columns="col1,col2,col3",
        filters=[("eq", "col", "val")])
    return {{"key": value, "period": tw["label"]}}

AVAILABLE SUPABASE TABLES AND COLUMNS:
{schema_context}

CONSTRAINTS (CRITICAL):
- ONLY use select_all() for reads — no writes, no deletes
- Import only: select_all from supabase_client, Counter
  from collections, json
- Return dict with clear keys the synthesizer can use
- Function name must be query_<topic> (lowercase, underscores)
- Must accept (params, sb) and be async
- Must handle empty results gracefully (no crashes)
- Keep it under 60 lines

Generate:
1. The handler function (complete, runnable Python)
2. A one-line INTENT_PROMPT entry describing when to use it
3. The STRUCTURED_HANDLERS evaluator key (which return key
   indicates a valid result — not "rows")

Respond with JSON:
{{
  "handler_name": "query_competitive_intel",
  "handler_code": "async def query_...",
  "intent_entry": "query_X - description of when to use it",
  "evaluator_key": "the_key",
  "confidence": 0.0-1.0,
  "explanation": "why this handler answers those questions"
}}"""

VALIDATION_PROMPT = """A handler was generated to answer
these questions:
{questions}

The handler returned this data when run against real data:
{result_sample}

Does this result actually answer the questions?
Score 0-1 and explain what's missing if < 0.8.

Respond with JSON:
{{
  "score": 0.0-1.0,
  "answers_questions": true/false,
  "missing": "what's still not answered",
  "ready_for_pr": true/false
}}"""


def cluster_failures(sb, days: int = 7) -> list[dict]:
    """
    Read unanswered_queries from the last N days and
    cluster them by topic using keyword overlap.
    Returns list of clusters: [{topic, questions, count}]
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    unanswered = select_all(sb, "unanswered_queries",
        columns="question,reason,asked_at",
        filters=[
            ("gte", "asked_at", cutoff),
            ("neq", "asked_by", "system_assessment"),
        ])

    clusters = {}
    topic_keywords = {
        "competitive_intel": [
            "competitor", "DIY", "build", "alternative",
            "versus", "vs", "against"],
        "rep_performance": [
            "rep", "attainment", "quota", "hitting", "number"],
        "trend_analysis": [
            "trend", "improving", "getting better", "compare",
            "vs last", "month over month", "week over week"],
        "forecast": [
            "forecast", "predict", "expect", "going to"],
        "deal_context": [
            "why", "reason", "because", "how come"],
    }

    for q in unanswered:
        question = (q.get("question") or "").lower()
        assigned = False
        for topic, keywords in topic_keywords.items():
            if any(kw.lower() in question for kw in keywords):
                clusters.setdefault(topic, []).append(
                    q["question"])
                assigned = True
                break
        if not assigned:
            clusters.setdefault("other", []).append(
                q["question"])

    return [
        {"topic": topic, "questions": questions,
         "count": len(questions)}
        for topic, questions in clusters.items()
        if len(questions) >= 2  # only clusters worth fixing
    ]


def generate_handler(questions: list, schema_context: str,
                      client, tracker=None) -> dict | None:
    """
    Use Claude to generate a handler for a cluster of
    failed questions. Returns the generated handler dict
    or None if generation fails.
    """
    resp = client.messages.create(
        model=GENERATOR_MODEL,
        max_tokens=2000,
        system="Respond with valid JSON only. "
               "No markdown, no backticks.",
        messages=[{"role": "user", "content":
            HANDLER_GENERATION_PROMPT.format(
                questions=json.dumps(questions, indent=2),
                schema_context=schema_context,
            )
        }]
    )
    if tracker:
        tracker.record(resp, GENERATOR_MODEL, "handler_generator")
    try:
        return json.loads(resp.content[0].text)
    except Exception as e:
        print(f"  Generation failed: {e}")
        return None


def validate_handler_code(code: str) -> tuple:
    """
    Safety validation: check generated code is safe to test.
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

    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    if "async def query_" not in code:
        return False, "Must be async def query_*"

    return True, "OK"


async def test_handler(code: str, handler_name: str, sb) -> dict:
    """
    Execute the generated handler against real Supabase
    data and return the result for validation.
    Returns {"success": bool, "result": dict, "error": str}
    """
    from api.time_resolver import resolve_time_window

    namespace = {}
    exec(
        "from supabase_client import select_all\n"
        "from collections import Counter\n"
        "import json\n"
        + code,
        namespace
    )

    handler_fn = namespace.get(handler_name)
    if not handler_fn:
        return {"success": False, "result": {},
                "error": f"Handler {handler_name} not found"}

    tw = resolve_time_window({"period": "current_quarter"})
    try:
        result = await handler_fn({"time_window": tw}, sb)
        return {"success": True, "result": result, "error": None}
    except Exception as e:
        return {"success": False, "result": {}, "error": str(e)}


def validate_answer_quality(questions: list, result: dict,
                             client, tracker=None) -> dict:
    """
    Ask Claude: does this result actually answer the
    failed questions? Returns validation assessment.
    """
    result_sample = json.dumps(result, default=str)[:1000]
    resp = client.messages.create(
        model=VALIDATION_MODEL,
        max_tokens=200,
        system="Respond with valid JSON only.",
        messages=[{"role": "user", "content":
            VALIDATION_PROMPT.format(
                questions=json.dumps(questions),
                result_sample=result_sample,
            )
        }]
    )
    if tracker:
        tracker.record(resp, VALIDATION_MODEL, "handler_validation")
    try:
        return json.loads(resp.content[0].text)
    except Exception:
        return {"score": 0.5, "ready_for_pr": False}


def create_github_pr(handler_name: str, handler_code: str,
                      intent_entry: str, evaluator_key: str,
                      cluster_topic: str, questions: list):
    """
    Open a GitHub PR proposing the generated handler, via the
    GitHub Contents API (github_memory.GitHubMemory) rather than
    a local git checkout — safe to run unattended in CI and never
    touches the working tree of the running job.

    Only appends the handler to api/handlers.py. INTENT_PROMPT and
    STRUCTURED_HANDLERS entries are too risky for the generator to
    touch automatically, so they're logged for manual addition.

    Returns the PR URL or None if creation fails.
    """
    from datetime import datetime
    from github_memory import GitHubMemory

    branch = (f"auto-handler-{cluster_topic}-"
              f"{datetime.now().strftime('%Y%m%d%H%M%S')}")
    pr_title = (f"Auto-generated handler: {handler_name} "
                f"(fixes {len(questions)} failed questions)")

    handlers_path = REPO_ROOT / "api" / "handlers.py"
    existing_code = handlers_path.read_text()
    new_code = existing_code.rstrip("\n") + f"\n\n\n{handler_code}\n"

    print(f"\nManual additions needed after merge:")
    print(f"  INTENT_PROMPT: {intent_entry}")
    print(f'  STRUCTURED_HANDLERS: "{handler_name}": "{evaluator_key}"')

    pr_body = f"""## Auto-generated handler: `{handler_name}`

**Generated by:** handler_generator.py on {date.today()}
**Fixes:** {len(questions)} failed questions in cluster `{cluster_topic}`

### Failed questions this handler addresses
{chr(10).join(f'- {q}' for q in questions[:10])}

### What was added
- `{handler_name}()` appended to `api/handlers.py`

### Still needs manual addition (generator cannot touch these files)
- INTENT_PROMPT entry in `api/router.py`:
  `{intent_entry}`
- STRUCTURED_HANDLERS entry in `api/evaluator.py`:
  `"{handler_name}": "{evaluator_key}"`

### Human review checklist
- [ ] Handler code is read-only (no writes/deletes)
- [ ] Return dict makes sense for the question type
- [ ] INTENT_PROMPT entry added and specific enough
- [ ] STRUCTURED_HANDLERS entry added
- [ ] Tested locally against real data

**Auto-generated — requires human review. DO NOT MERGE without review.**
"""

    gm = GitHubMemory(REPO_ROOT)
    pr_url = gm.create_pr(
        branch_name=branch,
        title=pr_title,
        body=pr_body,
        files_to_commit={"api/handlers.py": new_code},
    )
    if pr_url:
        print(f"PR created: {pr_url}")
    else:
        print("PR creation failed (or not running in GitHub Actions) — "
              "add the handler manually from the printed code.")
    return pr_url


async def main():
    import argparse, anthropic
    from supabase import create_client
    from api.schema_context import get_schema_context
    from token_tracker import TokenTracker

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cluster",
        help="Process specific cluster only")
    parser.add_argument("--create-pr", action="store_true",
        help="Create GitHub PRs for passing handlers")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_KEY"])
    client = anthropic.Anthropic()
    tracker = TokenTracker(REPO_ROOT / "memory", job="handler_generator")
    schema = get_schema_context(sb)

    print(f"Clustering failures from last {args.days} days...")
    clusters = cluster_failures(sb, args.days)
    print(f"Found {len(clusters)} clusters needing handlers")

    for cluster in clusters:
        topic = cluster["topic"]
        questions = cluster["questions"]

        if args.cluster and args.cluster != topic:
            continue

        print(f"\n{'='*50}")
        print(f"Cluster: {topic} ({cluster['count']} questions)")
        print(f"Sample: {questions[0][:60]}")

        print("Generating handler...")
        generated = generate_handler(questions, schema, client, tracker)
        if not generated:
            print("  Generation failed — skipping")
            continue

        handler_name = generated["handler_name"]
        handler_code = generated["handler_code"]
        confidence   = generated.get("confidence", 0)
        print(f"  Generated: {handler_name} "
              f"(confidence: {confidence:.2f})")

        if confidence < 0.6:
            print("  Low confidence — skipping")
            continue

        is_safe, reason = validate_handler_code(handler_code)
        if not is_safe:
            print(f"  Safety check failed: {reason}")
            continue
        print("  Safety check passed")

        if args.dry_run:
            print(f"  DRY RUN — handler code:")
            print(handler_code)
            continue

        print("  Testing against Supabase...")
        test_result = await test_handler(handler_code, handler_name, sb)

        if not test_result["success"]:
            print(f"  Test failed: {test_result['error']}")
            continue
        print(f"  Handler ran successfully")

        print("  Validating answer quality...")
        validation = validate_answer_quality(
            questions, test_result["result"], client, tracker)
        score = validation.get("score", 0)
        print(f"  Quality score: {score:.2f}")

        if not validation.get("ready_for_pr"):
            print(f"  Not ready for PR: "
                  f"{validation.get('missing', 'low quality')}")
            continue

        print(f"  Handler passes quality check")

        if args.create_pr:
            pr_url = create_github_pr(
                handler_name=handler_name,
                handler_code=handler_code,
                intent_entry=generated["intent_entry"],
                evaluator_key=generated["evaluator_key"],
                cluster_topic=topic,
                questions=questions,
            )
            if pr_url:
                print(f"  PR created: {pr_url}")
        else:
            print(f"  Run with --create-pr to create PR")
            print(f"  Handler:\n{handler_code}")

    summary = tracker.save()
    tracker.print_summary(summary, show_monthly=False)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
