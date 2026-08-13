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
    args = parser.parse_args()

    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_KEY")
        sys.exit(1)

    from supabase import create_client
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
