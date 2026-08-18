#!/usr/bin/env python3
"""
Weekly learning report for the CRO agent.
Reads learning_log + unanswered_queries for the past 7 days,
clusters failures, and generates routing improvement
suggestions for human review.

Does NOT auto-apply any changes. All suggestions require
human approval before modifying INTENT_PROMPT or handlers.

Usage:
  python scripts/weekly_learning_report.py
  python scripts/weekly_learning_report.py --slack
    # also posts to #deal-intelligence
"""

import os
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from collections import Counter, defaultdict

REPO_ROOT = Path(__file__).parent.parent


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--slack", action="store_true",
        help="Post report to Slack channel")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--generate-handlers", action="store_true",
        help="Generate new handlers for failure clusters "
             "(read-only, always requires human PR review)")
    parser.add_argument("--create-pr", action="store_true",
        help="Create GitHub PRs for handlers that pass "
             "testing and quality checks (implies --generate-handlers)")
    parser.add_argument("--check-schema-gaps", action="store_true",
        help="Check the enrichment schema for missing "
             "categories (read-only, never re-enriches)")
    args = parser.parse_args()

    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_KEY")
        sys.exit(1)

    from supabase import create_client
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from supabase_client import select_all

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    cutoff = (date.today() - timedelta(days=args.days)
              ).isoformat()

    # 1. Unanswered questions
    unanswered = select_all(sb, "unanswered_queries",
        columns="question,reason,asked_at",
        filters=[("gte", "asked_at", cutoff),
                 ("neq", "asked_by", "system_assessment")])

    # 2. Learning log entries
    learning = select_all(sb, "learning_log",
        columns="question,handler_used,issue_type,"
                "suggested_fix,retry_succeeded,retries_used",
        filters=[("gte", "logged_at", cutoff)])

    # 3. Cluster unanswered by topic
    unanswered_reasons = Counter(
        r.get("reason", "unknown") for r in unanswered)

    # 4. Cluster learning log by issue type
    issues = Counter(
        r.get("issue_type") for r in learning
        if r.get("issue_type"))

    # 5. Find retry success rate
    retried = [r for r in learning if r.get("retries_used", 0) > 0]
    succeeded = [r for r in retried if r.get("retry_succeeded")]
    retry_rate = (len(succeeded) / len(retried) * 100
                  if retried else 0)

    # 6. Generate routing suggestions
    suggestions = _generate_suggestions(learning, unanswered)

    # 7. Build report
    report = _build_report(
        days=args.days,
        unanswered=unanswered,
        unanswered_reasons=unanswered_reasons,
        issues=issues,
        retried=retried,
        retry_rate=retry_rate,
        suggestions=suggestions,
    )

    print(report)

    if args.slack:
        _post_to_slack(report)

    if args.generate_handlers or args.create_pr:
        _generate_handlers(sb, args)

    # Schema gap detection
    if args.check_schema_gaps:
        print("\nChecking enrichment schema gaps...")
        from scripts.enrichment.category_gap_detector import (
            get_existing_categories,
            get_unanswered_questions,
            detect_implied_categories,
            cluster_other_category,
            build_report,
            generate_pr_content,
            create_category_pr,
        )
        existing = get_existing_categories(sb)
        questions = get_unanswered_questions(sb, args.days)
        implied = detect_implied_categories(questions)
        clusters = cluster_other_category(sb)
        gap_report = build_report(existing, implied,
                                  clusters, args.days)
        print(gap_report)
        if args.slack:
            _post_to_slack(gap_report)

        # Proposals only ever become a PR — never an applied
        # prompt change, and never a re-enrichment run.
        if args.create_pr:
            pr_content = generate_pr_content(implied, clusters)
            if pr_content:
                create_category_pr(
                    pr_content,
                    f"{len(implied) + len(clusters)} candidate(s)")
            else:
                print("No new categories to propose")


def _generate_handlers(sb, args):
    """
    Auto-generate precomputed handlers for failure clusters that
    keep coming up. Never auto-merges — passing handlers become
    GitHub PRs for human review (--create-pr) or are just printed.
    Capped at 3 clusters per run to avoid PR noise.
    """
    from llm_client import LLMClient
    from handler_generator import (
        cluster_failures, generate_handler, validate_handler_code,
        test_handler, validate_answer_quality, create_github_pr,
    )
    from api.schema_context import get_schema_context
    from token_tracker import TokenTracker
    import asyncio

    print("\nChecking for auto-generatable handlers...")
    clusters = cluster_failures(sb, args.days)
    clusters_needing_handlers = [
        c for c in clusters
        if c["count"] >= 3  # threshold: 3+ failures
        and c["topic"] != "other"
    ][:3]  # max 3 per cycle

    if not clusters_needing_handlers:
        print("No clusters met the 3+ failure threshold this week.")
        return

    client = LLMClient.from_config("generator")
    tracker = TokenTracker(REPO_ROOT / "memory", job="handler_generator")
    schema = get_schema_context(sb)
    created_prs = []

    for cluster in clusters_needing_handlers:
        topic, questions = cluster["topic"], cluster["questions"]
        print(f"\nCluster: {topic} ({cluster['count']} questions)")

        generated = generate_handler(questions, schema, client, tracker)
        if not generated or generated.get("confidence", 0) < 0.6:
            print("  Skipping — generation failed or low confidence")
            continue

        handler_name, handler_code = (
            generated["handler_name"], generated["handler_code"])
        is_safe, reason = validate_handler_code(handler_code)
        if not is_safe:
            print(f"  Skipping — safety check failed: {reason}")
            continue

        test_result = asyncio.run(
            test_handler(handler_code, handler_name, sb))
        if not test_result["success"]:
            print(f"  Skipping — test failed: {test_result['error']}")
            continue

        validation = validate_answer_quality(
            questions, test_result["result"], client, tracker)
        if not validation.get("ready_for_pr"):
            print(f"  Skipping — quality score "
                  f"{validation.get('score', 0):.2f} too low")
            continue

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
                created_prs.append({
                    "handler_name": handler_name,
                    "pr_url": pr_url,
                    "cluster_topic": topic,
                    "fixes_count": len(questions),
                    "sample_questions": questions[:2],
                })
        else:
            print(f"  Handler ready — run with --create-pr to open a PR")

    summary = tracker.save()
    tracker.print_summary(summary, show_monthly=False)

    if created_prs and args.slack:
        _post_handler_prs_to_slack(created_prs)


def _post_handler_prs_to_slack(created_prs: list):
    """Notify Jeff/Ryan in Slack when the learning system proposes
    a new handler. Requires their approval before it goes live."""
    import requests
    ZAP_URL = os.environ.get("ZAP_REPLY_URL", "")
    if not ZAP_URL:
        print("ZAP_REPLY_URL not set — skipping Slack notification")
        return

    for pr in created_prs:
        lines = [
            "*New handler proposed by the learning system:*",
            f"• Handler: `{pr['handler_name']}`",
            f"• Fixes: {pr['fixes_count']} questions that kept failing",
            f"• PR: {pr['pr_url']}",
            "• Sample questions it now handles:",
        ]
        for q in pr["sample_questions"]:
            lines.append(f"  — \"{q}\"")
        lines.append("")
        lines.append(
            "Review the PR and merge to activate. The handler was "
            "tested against real data and passed quality checks. "
            "It requires your approval before going live.")

        requests.post(ZAP_URL, json={
            "channel_id": os.environ.get("SLACK_REPORT_CHANNEL", ""),
            "thread_ts": "",
            "text": "\n".join(lines),
        }, timeout=10)
    print(f"Posted {len(created_prs)} handler proposal(s) to Slack")


def _generate_suggestions(learning: list,
                           unanswered: list) -> list:
    """
    Identify patterns and suggest INTENT_PROMPT additions.
    Returns list of suggestion strings for human review.
    """
    suggestions = []

    # Wrong handler patterns
    wrong_handler = [r for r in learning
                     if r.get("issue_type") == "wrong_handler"]
    by_handler = defaultdict(list)
    for r in wrong_handler:
        by_handler[r.get("handler_used", "unknown")].append(
            r.get("question", ""))

    for handler, questions in by_handler.items():
        if len(questions) >= 2:
            suggestions.append(
                f"• Handler '{handler}' was wrong for "
                f"{len(questions)} questions. Sample: "
                f'"{questions[0][:60]}..." — '
                f"consider adding a more specific handler "
                f"or updating INTENT_PROMPT routing."
            )

    # Frequently unanswered topics
    unanswered_topics = defaultdict(list)
    for r in unanswered:
        q = r.get("question", "").lower()
        if "won" in q or "win" in q:
            unanswered_topics["wins"].append(q)
        elif "rep" in q or "owner" in q or "attainment" in q:
            unanswered_topics["rep_performance"].append(q)
        elif "trend" in q or "compare" in q or "vs" in q:
            unanswered_topics["trends"].append(q)
        elif "forecast" in q:
            unanswered_topics["forecast"].append(q)

    for topic, questions in unanswered_topics.items():
        if len(questions) >= 2:
            suggestions.append(
                f"• {len(questions)} unanswered questions "
                f"about '{topic}' — consider adding a "
                f"query_{topic} handler or data layer."
            )

    if not suggestions:
        suggestions.append("• No routing improvements needed "
                           "this week — patterns look healthy.")

    return suggestions


def _build_report(days, unanswered, unanswered_reasons,
                   issues, retried, retry_rate,
                   suggestions) -> str:
    from datetime import date
    lines = [
        f"*CRO Agent — Weekly Learning Report*",
        f"_{date.today().strftime('%B %d, %Y')} | "
        f"Last {days} days_",
        "",
        f"*Response quality:*",
        f"• Unanswered questions: {len(unanswered)}",
    ]

    if unanswered_reasons:
        for reason, count in unanswered_reasons.most_common(3):
            lines.append(f"  - {reason}: {count}")

    if retried:
        lines.append(
            f"• Retry attempts: {len(retried)} "
            f"({retry_rate:.0f}% succeeded)"
        )

    if issues:
        lines.append(f"• Issue types caught by assessor:")
        for issue, count in issues.most_common(3):
            lines.append(f"  - {issue}: {count}")

    lines.append("")
    lines.append("*Routing improvement suggestions "
                 "(human review required):*")
    lines.extend(suggestions)
    lines.append("")
    lines.append("_These are suggestions only. Reply to "
                 "approve any routing change before it's "
                 "applied._")

    return "\n".join(lines)


def _post_to_slack(report: str):
    """Post report to #deal-intelligence via Zapier."""
    import requests
    ZAP_URL = os.environ.get("ZAP_REPLY_URL", "")
    if not ZAP_URL:
        print("ZAP_REPLY_URL not set — skipping Slack post")
        return
    requests.post(ZAP_URL, json={
        "channel_id": os.environ.get(
            "SLACK_REPORT_CHANNEL", ""),
        "thread_ts":  "",  # top-level message
        "text":       report,
    }, timeout=10)
    print("Posted to Slack")


if __name__ == "__main__":
    main()
