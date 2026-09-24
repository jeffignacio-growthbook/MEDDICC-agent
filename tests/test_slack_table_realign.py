#!/usr/bin/env python3
"""
api/slack_format.py re-aligns code-fenced tables at delivery.

A model asked to pad columns can't reliably count characters. Live eval,
2026-09-24: 20 of 20 answers used a fenced table, 16 were aligned. Column
alignment is exact, repeatable output, so it's enforced in code after
generation (like incremental_arr() and the basis checks), not asked for in
the prompt.

Fixtures are the live eval's own failing answers
(tests/fixtures/live_table_eval_2026_09_24.json):
  - a waterfall with every column shifted (numbers right-aligned under
    left-aligned headers, off by one here and there);
  - a rep table whose totals row sits a character off;
  - an 84-character-wide table;
  - a "Mixed*" footnote asterisk inside the fence;
  - a stage table with "$" pinned left of right-aligned digits (aligned as
    written, but "$         0" splits into an extra cell).
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

from api.slack_format import to_slack_mrkdwn  # noqa: E402
from api.plausibility import check_answer_week_basis  # noqa: E402
from eval_table_formatting import check_answer_tables  # noqa: E402
import test_week_basis_check_live_false_positive as live  # noqa: E402

F = "```"
LIVE = json.loads((REPO / "tests" / "fixtures" / "live_table_eval_2026_09_24.json").read_text())


def _fence(text):
    return re.search(r"```[^\n]*\n(.*?)```", text, re.S).group(1)


def test_every_live_failure_is_aligned_after_delivery():
    for name, answer in LIVE.items():
        out = to_slack_mrkdwn(answer)
        r = check_answer_tables(out)
        assert r["pass"], (name, [p for t in r["tables"] for p in t["problems"]], _fence(out))
        assert to_slack_mrkdwn(out) == out, f"{name}: not idempotent"
    raw_fail = [n for n, a in LIVE.items() if not check_answer_tables(a)["pass"]]
    assert sorted(raw_fail) == ["rep_totals_off_by_one", "waterfall_84_wide",
                                "waterfall_footnote_asterisk", "waterfall_misaligned"], raw_fail
    print(f"✓ all {len(LIVE)} live eval answers are aligned after delivery (4 failed as written: "
          "shifted columns, an off-by-one totals row, 84 chars wide, a footnote asterisk); "
          "a second pass changes nothing")


def test_columns_numbers_right_text_left():
    body = _fence(to_slack_mrkdwn(LIVE["waterfall_misaligned"]))
    rows = [l for l in body.splitlines() if l.strip() and not set(l) <= set("- ")]
    ends = {re.search(r"\$\S+", l[9:]).end() + 9 for l in rows[1:]}
    assert len(ends) == 1, ends                                     # "New" right-aligned
    assert len({l.index(l.split("  ")[0]) for l in rows}) == 1      # week column left-aligned
    assert rows[1].startswith("Aug 03     $235,000") and rows[-1].startswith("QTD Total  $425,000")
    assert max(len(l) for l in body.splitlines()) <= 80
    print("✓ number columns right-aligned, the label column left-aligned, rule rows redrawn to width")


def test_the_84_character_table_fits_after_realignment():
    def widths(body):
        lines = body.splitlines()
        is_rule = [bool(l.strip()) and set(l) <= set("- ") for l in lines]
        return (max(len(l) for l, r in zip(lines, is_rule) if not r),
                max(len(l) for l, r in zip(lines, is_rule) if r))
    raw = widths(_fence(LIVE["waterfall_84_wide"]))
    out = widths(_fence(to_slack_mrkdwn(LIVE["waterfall_84_wide"])))
    assert raw == (84, 86), raw                    # widest row 84, the model's dashed rules 86
    assert max(out) <= 80 and out[1] == out[0], out  # rules redrawn to the table's own width
    print(f"✓ the live table (rows 84, rules 86 characters wide) is {out[0]} after re-alignment "
          "(two-space gutters, rules redrawn to width)")


def test_a_pinned_dollar_sign_moves_to_its_digits():
    # the live stage table pins "$" left of right-aligned digits ("$         0"):
    # split on 2+ spaces that is an extra cell, so without moving the "$" the
    # table would be left as written instead of re-aligned
    body = _fence(to_slack_mrkdwn(LIVE["stage_dollar_pinned"]))
    rows = body.splitlines()
    assert rows[1] == "Discovery                   90      $8,678,408", rows[1]
    assert rows[-2] == "Unstaged                     1              $0", rows[-2]
    assert rows[-1] == "TOTAL                      233     $22,553,204", rows[-1]
    assert len({len(r) for r in rows[1:]}) == 1, "value column right-aligned"
    print("✓ the live stage table's pinned '$ 8,678,408' / '$         0' become right-aligned "
          "'$8,678,408' / '$0'")


def test_footnote_asterisks_and_markup_are_normalised():
    out = to_slack_mrkdwn(LIVE["waterfall_footnote_asterisk"])
    body = _fence(out)
    assert "Mixed†" in body and "*" not in body, body[-200:]
    assert "\n†QTD totals are mixed basis" in out, "the footnote line keeps its marker as †"
    assert "• *Lost ($965K)* dominates" in out, "bold outside the fence is untouched"
    bold = f"{F}\nStage      Deals\n*Discovery*   90\nScoping       34\n_Review_      13\n{F}"
    assert _fence(to_slack_mrkdwn(bold)) == "Stage      Deals\nDiscovery     90\nScoping       34\nReview        13\n"
    print("✓ 'Mixed*' -> 'Mixed†' with its footnote line -> '†…'; *bold* / _italic_ inside a fence "
          "lose their markers; bold outside the fence untouched")


def test_non_table_code_blocks_are_left_alone():
    cases = [
        f"{F}sql\nSELECT deal_id, stage\nFROM deals\nWHERE deal_status = 'active';\n{F}",
        f"{F}\none line only\n{F}",
        f"{F}\nsome prose inside a fence\nthat is not a table at all\nand has no columns\n{F}",
        f"{F}\nA    B\nC    D    E    F\nG    H\n{F}",              # a row wider than the header
    ]
    for c in cases:
        assert to_slack_mrkdwn(c) == c, c
    print(f"✓ {len(cases)} non-table code blocks (SQL, one line, prose, ragged) pass through unchanged")


def test_pipe_table_fallback_still_works_alongside():
    msg = (f"*Header*\n| Stage | Deals |\n|---|---|\n| Discovery | 99 |\n| Scoping | 30 |\n\n"
           f"{F}\nStage   Deals\nA          1\nB     2\nC          3\n{F}")
    out = to_slack_mrkdwn(msg)
    assert "*Stage | Deals*\n• Discovery | 99\n• Scoping | 30" in out, out
    assert _fence(out) == "Stage  Deals\nA          1\nB          2\nC          3\n", _fence(out)
    print("✓ in one message: the pipe table still falls back to header + bullets, and the fenced "
          "table is re-aligned")


def test_week_basis_check_reads_realigned_rows():
    fenced = live.LIVE_ANSWER.replace("Week Ending", F + "\nWeek Ending", 1).replace(
        "+$16,800     Incr. ARR", "+$16,800     Incr. ARR\n" + F, 1)
    out = to_slack_mrkdwn(fenced)
    assert out != fenced and "Sep 21" in _fence(out)
    assert not check_answer_week_basis(out, live.LIVE_ROWS), "re-aligned correct answer flagged"
    wrong = to_slack_mrkdwn(fenced.replace("+$16,800     Incr. ARR", "+$16,800     Deal value"))
    v = check_answer_week_basis(wrong, live.LIVE_ROWS)
    assert [w["week_ending"] for x in v for w in x.context.get("wrong", [])] == ["2026-09-21"], v
    print("✓ the per-week basis check reads re-aligned rows: the correct live answer passes, a "
          "wrong Sep 21 label is still caught")


if __name__ == "__main__":
    test_every_live_failure_is_aligned_after_delivery()
    test_columns_numbers_right_text_left()
    test_the_84_character_table_fits_after_realignment()
    test_a_pinned_dollar_sign_moves_to_its_digits()
    test_footnote_asterisks_and_markup_are_normalised()
    test_non_table_code_blocks_are_left_alone()
    test_pipe_table_fallback_still_works_alongside()
    test_week_basis_check_reads_realigned_rows()
    print("\n✅ All tests passed")
