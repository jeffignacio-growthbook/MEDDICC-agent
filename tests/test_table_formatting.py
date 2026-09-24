#!/usr/bin/env python3
"""
Multi-row answers: code-fenced, space-aligned tables instead of bullets.

Until 2026-09-24 every synthesis prompt said "Never use markdown tables. Use
bullet lists." This pins:
  1. all three prompts carry the same TABLE_FORMAT_RULE and none still
     forbids tables (DYNAMIC_SYSTEM_PROMPT still .format()s);
  2. scripts/eval_table_formatting.check_answer_tables(), the checker the
     live eval uses, on tonight's real answers: the 15:05 waterfall table
     passes, and the movement answer's bullet stage breakdown, a ragged
     table, a pipe table and markup inside a fence all fail;
  3. api/slack_format.py, the safety net, is unchanged: fenced tables pass
     through byte-for-byte, and pipe tables are still converted;
  4. the per-week basis answer check still reads rows inside a fence.

Whether the model reliably writes the tables can only be measured live:
scripts/eval_table_formatting.py.
"""
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.router as router  # noqa: E402
from api.slack_format import to_slack_mrkdwn  # noqa: E402
from api.plausibility import check_answer_week_basis  # noqa: E402
from eval_table_formatting import check_answer_tables  # noqa: E402
import test_week_basis_check_live_false_positive as live  # noqa: E402

F = "```"
# The live 15:05 waterfall table (its rows, verbatim), fenced.
LIVE_TABLE = "\n".join(l for l in live.LIVE_ANSWER.splitlines()
                       if l.startswith(("Week Ending", "-----------", "Aug ", "Sep ")))
FENCED_ANSWER = f"*Q3 FY2027 Pipeline Waterfall*\n{F}\n{LIVE_TABLE}\n{F}\nLost $965,000 is a mixed basis."

# The live 15:26 movement answer's stage breakdown, as it was sent (bullets).
LIVE_MOVEMENT_BULLETS = """Stage-by-stage net movement:
• Discovery: +21 deals (78 → 99) — biggest intake, 33 new to pipeline
• Scoping: +5 deals (25 → 30)
• Technical Evaluation: +6 deals (27 → 33) — 8 advanced from earlier stages
• Negotiating: -2 deals (13 → 11) — 8 exited, 6 entered
• Awaiting Signature: +1 deal (2 → 3)"""

MOVEMENT_TABLE = f"""Stage-by-stage:
{F}
Stage          Prior  Now  Net  New  Moved in  Exited
Discovery         78   99  +21   33         1      13
Scoping           25   30   +5   10         3       8
Tech Eval         27   33   +6    2         8       4
Negotiating       13   11   -2    3         3       8
Awaiting Sig.      2    3   +1    2         1       2
{F}"""


def test_every_synthesis_prompt_carries_the_table_rule():
    prompts = {
        "SYNTHESIS_SYSTEM_PROMPT": router.SYNTHESIS_SYSTEM_PROMPT,
        "DYNAMIC_SYSTEM_PROMPT (formatted)": router.DYNAMIC_SYSTEM_PROMPT.format(
            roster_text="", semantic_context="", schema_context=""),
        "build_synthesis_prompt (_VOICE_BASE)": router.build_synthesis_prompt({"role_group": "executive"}),
    }
    for name, text in prompts.items():
        assert router.TABLE_FORMAT_RULE in text, name
        for old in ("Never use markdown tables", "not markdown tables", "No markdown tables"):
            assert old not in text, (name, old)
    for part in ("code-fenced table", "3+ rows", "under 80 characters", "not even as footnote",
                 "totals row"):
        assert part in router.TABLE_FORMAT_RULE, part
    print(f"✓ all {len(prompts)} synthesis prompts carry TABLE_FORMAT_RULE; none forbids tables")


def test_checker_on_tonights_real_answers():
    ok = check_answer_tables(FENCED_ANSWER)
    assert ok["pass"] and ok["tables"][0]["rows"] == 9, ok
    assert check_answer_tables(MOVEMENT_TABLE)["pass"]
    fail = {
        "live movement bullets": LIVE_MOVEMENT_BULLETS,
        "ragged table": MOVEMENT_TABLE.replace("Scoping           25", "Scoping    25"),
        "pipe table": "| Stage | Deals |\n|---|---|\n| Discovery | 99 |\n| Scoping | 30 |\n| Tech Eval | 33 |",
        "bold inside fence": MOVEMENT_TABLE.replace("Discovery         78", "*Discovery*       78"),
        "emoji inside fence": MOVEMENT_TABLE.replace("Scoping           25", ":warning:         25"),
        "two-row fence": f"{F}\nStage  Deals\nA         1\nB         2\n{F}",
    }
    for name, answer in fail.items():
        assert not check_answer_tables(answer)["pass"], name
    # From the 2026-09-24 live eval: a totals row may leave its Basis cell blank
    blank_tail = f"""{F}
Rep            Deals  Pipeline  Notes
Christian         65    $7.55M  Largest book
Scott Keller      43    $3.47M
Andy Marshall     10    $0.30M  AM, no quota
{F}"""
    assert check_answer_tables(blank_tail)["pass"], check_answer_tables(blank_tail)
    # live eval run 2: a "$" pinned left with right-aligned digits is aligned
    pinned = f"{F}\nStage          Deals  Pipeline\nDiscovery         90  $ 8,678,408\nReview            13  $   197,500\nUnstaged           1  $         0\n{F}"
    assert check_answer_tables(pinned)["pass"], check_answer_tables(pinned)
    # ...but a value one character off its column still fails (live rep table, run 2)
    off_by_one = blank_tail.replace("Andy Marshall     10    $0.30M", "Andy Marshall     10   $0.30M ")
    assert not check_answer_tables(off_by_one)["pass"]
    footnote = blank_tail.replace("$3.47M", "$3.47M*")
    assert not check_answer_tables(footnote)["pass"]
    print(f"✓ checker: the live 15:05 waterfall table (9 rows), an aligned stage table and a "
          f"blank-trailing-cell table pass; {len(fail) + 2} failing shapes fail, incl. the live 15:26 "
          f"movement bullets, a one-character misalignment and a footnote asterisk")


def test_slack_fallback_is_unchanged():
    assert to_slack_mrkdwn(FENCED_ANSWER) == FENCED_ANSWER, "a fenced table must reach Slack untouched"
    assert to_slack_mrkdwn(MOVEMENT_TABLE) == MOVEMENT_TABLE
    pipe = "| Stage | Deals |\n|---|---|\n| Discovery | 99 |\n| Scoping | 30 |"
    assert to_slack_mrkdwn(pipe) == "*Stage | Deals*\n• Discovery | 99\n• Scoping | 30", to_slack_mrkdwn(pipe)
    print("✓ slack_format: fenced tables pass through byte-for-byte; a pipe table is still converted "
          "to a bold header plus bullets (safety net in place)")


def test_week_basis_check_reads_rows_inside_a_fence():
    fenced_live = live.LIVE_ANSWER.replace("Week Ending", F + "\nWeek Ending", 1).replace(
        "+$16,800     Incr. ARR", "+$16,800     Incr. ARR\n" + F, 1)
    assert F in fenced_live
    assert not check_answer_week_basis(fenced_live, live.LIVE_ROWS)
    wrong = fenced_live.replace("+$16,800     Incr. ARR", "+$16,800     Deal value")
    v = check_answer_week_basis(wrong, live.LIVE_ROWS)
    assert [w["week_ending"] for x in v for w in x.context.get("wrong", [])] == ["2026-09-21"], v
    print("✓ the per-week basis check reads table rows inside a fence (a wrong label is still caught)")


if __name__ == "__main__":
    test_every_synthesis_prompt_carries_the_table_rule()
    test_checker_on_tonights_real_answers()
    test_slack_fallback_is_unchanged()
    test_week_basis_check_reads_rows_inside_a_fence()
    print("\n✅ All tests passed")
