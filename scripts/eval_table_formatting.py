#!/usr/bin/env python3
"""
Live formatting eval: do multi-row answers come back as aligned,
code-fenced tables?

Asks real questions through the real dynamic_query_loop (real prompts, real
Supabase, real model) N times each and checks every answer with
check_answer_tables(). Writes nothing: every log/cache insert the loop makes
goes to a no-op table, reads pass through.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... ANTHROPIC_API_KEY=... \\
        python scripts/eval_table_formatting.py [--repeats N] [--label NAME]

Exit 1 if any answer fails. --label only tags the printed report (the
workflow runs it once on the branch's prompts and once on main's).
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))
sys.path.insert(0, str(REPO / "scripts"))

QUESTIONS = [
    "Show me this quarter's pipeline waterfall — new, won and lost by week",
    "How has pipeline moved this quarter?",
    "What does our pipeline look like by stage?",
    "Break down our pipeline by rep",
]

_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_CELL = re.compile(r"\S+(?: \S+)*")            # cells are separated by 2+ spaces
_RULE_LINE = re.compile(r"^[\s\-=+]+$")        # a "-----  ----" separator row
_EMOJI_CODE = re.compile(r":[a-z0-9_+\-]+:")


def _cells(line):
    # "$         0" (a "$" pinned left, digits right-aligned) is one cell: move
    # the "$" next to its digits without changing any column position
    line = re.sub(r"\$( +)(?=[\d(-])", lambda m: m.group(1) + "$", line)
    return [(m.start(), m.end()) for m in _CELL.finditer(line)]


def check_table(body: str) -> dict:
    """One fenced block: is it a clean, aligned table of 3+ data rows?"""
    rows = [l.rstrip() for l in body.split("\n") if l.strip() and not _RULE_LINE.match(l)]
    problems = []
    if len(rows) < 4:
        return {"is_table": False, "rows": max(len(rows) - 1, 0), "problems": ["fewer than 3 data rows"]}
    header, data = rows[0], rows[1:]
    spans = [_cells(r) for r in rows]
    n = len(spans[0])
    if n < 2:
        problems.append("single column")
    # a row may leave trailing cells blank (a totals row with no Basis, a Notes
    # column only some rows fill); every cell it does have must line up
    if any(len(s) > n for s in spans) or any(len(s) < 2 for s in spans[1:]):
        problems.append(f"cell counts differ across rows: {sorted({len(s) for s in spans})}")
    else:
        for j in range(n):
            col = [s[j] for s in spans[1:] if len(s) > j]
            if not col:
                continue
            starts = {c[0] for c in col}
            ends = {c[1] for c in col}
            if len(starts) > 1 and len(ends) > 1:
                problems.append(f"column {j + 1} not aligned (starts {sorted(starts)}, ends {sorted(ends)})")
                continue
            lo = min(c[0] for c in col)
            hi = max(c[1] for c in col)
            h0, h1 = spans[0][j]
            if h1 <= lo or h0 >= hi:
                problems.append(f"header cell {j + 1} is not over its column")
    for r in rows:
        if "|" in r:
            problems.append("pipe inside the fence"); break
    for r in rows:
        if re.search(r"(?<!\w)\*\S|\S\*(?!\w)|(?<!\w)_\S.*\S_(?!\w)", r) or _EMOJI_CODE.search(r):
            problems.append("markup or emoji inside the fence"); break
    width = max(len(r) for r in rows)
    if width > 80:
        problems.append(f"{width} characters wide (> 80)")
    return {"is_table": True, "rows": len(data), "width": width, "problems": problems}


def check_answer_tables(answer: str) -> dict:
    """pass = at least one fenced table with 3+ data rows, and every fenced
    table in the answer is clean and aligned; no markdown pipe table."""
    tables = [check_table(b) for b in _FENCE.findall(answer or "")]
    real = [t for t in tables if t["is_table"]]
    pipe_table = bool(re.search(r"^\s*\|.*\|\s*\n\s*\|?\s*:?-{3,}", answer or "", re.M))
    bullets = len(re.findall(r"^\s*[•\-*]\s", answer or "", re.M))
    ok = bool(real) and all(not t["problems"] for t in real) and not pipe_table
    return {"pass": ok, "tables": real, "pipe_table": pipe_table, "bullet_lines": bullets}


class _NoWrite:
    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        return type("R", (), {"data": []})()


class ReadOnlySB:
    """Reads pass through; any insert/upsert/update/delete is dropped."""
    _WRITES = {"insert", "upsert", "update", "delete"}

    def __init__(self, sb):
        self._sb = sb

    def table(self, name):
        real = self._sb.table(name)
        outer = self

        class _T:
            def __getattr__(self, attr):
                if attr in outer._WRITES:
                    return lambda *a, **k: _NoWrite()
                return getattr(real, attr)
        return _T()

    def __getattr__(self, attr):
        return getattr(self._sb, attr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--label", default="branch")
    args = ap.parse_args()

    import api.router as router
    from llm_client import LLMClient
    router._log_query_cost = lambda *a, **k: None
    sb = ReadOnlySB(router.get_supabase())
    generator = LLMClient.from_config(role="generator")
    classifier = LLMClient.from_config(role="classifier")
    roster = sb.table("user_personas").select("name,email,role").execute().data or []
    roster_text = "\n".join(f"- {r['name']} — {r['email']} ({r['role']})" for r in roster)
    tw = {"label": "FY2027 Q3", "start": "2026-08-01", "end": "2026-10-31"}

    results, failures = [], 0
    for q in QUESTIONS:
        for k in range(args.repeats):
            out = asyncio.run(router.dynamic_query_loop(
                question=q, history=[], params={"time_window": tw}, sb=sb,
                client=generator, roster_text=roster_text, classifier_client=classifier))
            answer = out.get("answer", "")
            chk = check_answer_tables(answer)
            failures += not chk["pass"]
            results.append({"question": q, "run": k + 1, **chk, "answer": answer})
            probs = [p for t in chk["tables"] for p in t["problems"]]
            print(f"[{args.label}] {'PASS' if chk['pass'] else 'FAIL'} {q[:50]!r} run {k + 1}: "
                  f"{len(chk['tables'])} table(s) {[t['rows'] for t in chk['tables']]} rows, "
                  f"pipe_table={chk['pipe_table']}, bullets={chk['bullet_lines']}"
                  + (f", problems={probs}" if probs else ""), flush=True)
    n = len(results)
    print(f"\n[{args.label}] {n - failures}/{n} answers had an aligned code-fenced table")
    for r in results:
        print(f"\n===== [{args.label}] {r['question']} (run {r['run']}) =====\n{r['answer']}")
    print("\nJSON " + json.dumps([{k: v for k, v in r.items() if k != "answer"} for r in results]))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
