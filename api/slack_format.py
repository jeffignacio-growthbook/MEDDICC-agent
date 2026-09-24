"""
Standard markdown -> Slack mrkdwn, applied once, at the Slack delivery point
(api/main.py:send_to_zap), never earlier.

Why here (2026-09-23): Slack showed "**Pipeline Added — Last 2 Weeks**"
with literal asterisks. The prompts already ask for Slack syntax, but not
uniformly (DYNAMIC_SYSTEM_PROMPT only says "Bold company names with
*asterisks*"), and even where they are explicit the model still writes
standard markdown: in the 632 answers in conversation_threads, 32 have
**double** bold, 17 have "-" bullets, 6 have pipe tables and 1 has
"#" headers. A deterministic pass at the one place text leaves for Slack
fixes that whatever the model writes. The answer is still stored and
returned unconverted, for the consumers that aren't Slack: thread history
(model context on follow-ups), test_question.py, the batteries, and the
in-loop verifiers that parse it.

Converted:  **b** / __b__ -> *b*;  ***b*** -> *_b_*;  ~~s~~ -> ~s~;
            "# Title" (any level) -> *Title*;  "- x" / "* x" / "+ x" -> "• x"
            (indent kept);  pipe tables -> bold header line + "• a | b" rows;
            [text](url) / ![alt](url) -> <url|text>.
Left alone: *single* asterisks (the prompts use them as Slack bold on
            purpose), _italics_, numbered lists and "> " quotes (Slack shows
            them fine), "---" rules (shown as a plain divider), and
            everything inside `inline code` or ``` fences.
Idempotent: already-Slack text passes through unchanged.

Fenced tables (2026-09-24): a ``` block shaped like a table (a header and
2+ rows whose cells are separated by 2+ spaces) is re-aligned here, because
a model asked to pad columns can't reliably count characters (live eval: 16
of 20 prompt-only tables aligned). Cells are split on 2+ spaces; each column
is padded to its widest cell with a two-space gutter; number columns are
right-aligned, text columns left-aligned; "-----" rule rows are redrawn to
the new widths. Markup Slack would show literally inside a code block is
normalised: *bold* / _italic_ pairs lose their markers, and footnote
asterisks ("Mixed*") become daggers ("Mixed†"), as does the footnote line
right after the fence ("*QTD totals are..." -> "†QTD totals are...").
Anything that isn't table-shaped (code, prose, a one-line block) is left
exactly as written.
"""
import re

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_HRULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(?=\S)")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_BOLD_ITALIC = re.compile(r"\*\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*\*")
_BOLD_STAR = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_BOLD_UNDER = re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_LINK = re.compile(r"!?\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def _inline(text: str) -> str:
    text = _BOLD_ITALIC.sub(r"*_\1_*", text)
    text = _BOLD_STAR.sub(r"*\1*", text)
    text = _BOLD_UNDER.sub(r"*\1*", text)
    text = _STRIKE.sub(r"~\1~", text)
    return _LINK.sub(r"<\2|\1>", text)


def _bold_label(text: str) -> str:
    """A whole-line label (header / table header) as one *bold* span."""
    plain = re.sub(r"\*+", "", text).strip()
    return f"*{plain}*" if plain else ""


def _cells(row: str) -> list:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _convert_lines(block: str) -> str:
    lines = block.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        # Pipe table: a header row immediately followed by a |---| separator.
        if (_TABLE_ROW.match(line) and i + 1 < len(lines)
                and _TABLE_SEP.match(lines[i + 1])):
            out.append(_bold_label(" | ".join(_inline(c) for c in _cells(line))))
            i += 2
            while i < len(lines) and _TABLE_ROW.match(lines[i]):
                out.append("• " + " | ".join(_inline(c) for c in _cells(lines[i])))
                i += 1
            continue
        if _HRULE.match(line):
            out.append(line)
        elif _HEADER.match(line):
            out.append(_bold_label(_inline(_HEADER.match(line).group(1))))
        else:
            out.append(_inline(_BULLET.sub(r"\1• ", line)))
        i += 1
    return "\n".join(out)


_FENCE_PARTS = re.compile(r"\A(```[^\n]*\n)(.*?)(\n?```)\Z", re.S)
_RULE_ROW = re.compile(r"^\s*[-=+]{3,}[\s\-=+]*$")
_SPLIT = re.compile(r" {2,}")
_NUMBER = re.compile(r"^[(+\-−]?[$€£]?\s*[+\-−]?\d[\d,]*(\.\d+)?\s*[KMBkmb%x×]?\)?$|^[—–\-]$|^n/?a$", re.I)
_PAIR = re.compile(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])")
_FOOTNOTE = re.compile(r"(?<=\S)(\*{1,3})$")


def _clean_cell(cell: str):
    """Markup Slack shows literally in a code block. Returns (cell, marks)."""
    cell = _PAIR.sub(r"\2", cell)
    m = _FOOTNOTE.search(cell)
    if m:
        return cell[:m.start()] + "†" * len(m.group(1)), len(m.group(1))
    return cell, 0


def _realign_table(body: str):
    """Re-aligned table text and the footnote marks converted, or None when
    the block isn't table-shaped."""
    lines = body.split("\n")
    rows = []                       # list of cell lists, or None for a rule row
    for line in lines:
        if not line.strip():
            rows.append([])
        elif _RULE_ROW.match(line):
            rows.append(None)
        else:
            # "$         0" (a "$" pinned left) is one cell: "$0"
            rows.append(_SPLIT.split(re.sub(r"([$€£]) +(?=[\d(+\-])", r"\1", line.strip())))
    data = [r for r in rows if r]
    if len(data) < 3:
        return None
    ncols = len(data[0])
    if ncols < 2 or any(len(r) > ncols or len(r) < 2 for r in data):
        return None
    marks = 0
    cleaned = []
    for r in rows:
        if r:
            out = []
            for c in r:
                c, k = _clean_cell(c)
                marks = max(marks, k)
                out.append(c)
            cleaned.append(out)
        else:
            cleaned.append(r)
    data = [r for r in cleaned if r]
    widths = [max(len(r[j]) for r in data if len(r) > j) for j in range(ncols)]
    numeric = [j > 0 and all(_NUMBER.match(r[j].rstrip("†")) for r in data[1:] if len(r) > j and r[j])
               for j in range(ncols)]
    out = []
    for r in cleaned:
        if r is None:
            out.append("  ".join("-" * w for w in widths))
        elif not r:
            out.append("")
        else:
            cells = [(c.rjust(widths[j]) if numeric[j] else c.ljust(widths[j]))
                     for j, c in enumerate(r)]
            out.append("  ".join(cells).rstrip())
    return "\n".join(out), marks


def realign_fenced_table(fence: str):
    """A ``` block, re-aligned if it's a table. Returns (block, footnote marks)."""
    m = _FENCE_PARTS.match(fence)
    if not m:
        return fence, 0
    done = _realign_table(m.group(2))
    if done is None:
        return fence, 0
    body, marks = done
    return m.group(1) + body + ("\n```" if m.group(3).startswith("\n") else "```"), marks


def _protect(pattern, text, store):
    def keep(m):
        store.append(m.group(0))
        return f"\x00{len(store) - 1}\x00"
    return pattern.sub(keep, text)


def to_slack_mrkdwn(text: str) -> str:
    """Convert standard-markdown answer text to Slack mrkdwn (see module doc)."""
    if not text:
        return text
    kept = []
    text = _protect(_FENCE, text, kept)
    n_fences = len(kept)
    text = _protect(_INLINE_CODE, text, kept)
    text = _convert_lines(text)
    for i in range(n_fences):
        kept[i], marks = realign_fenced_table(kept[i])
        if marks:
            # the footnote line right after the fence: "*note" -> "†note"
            text = re.sub(r"(\x00%d\x00\n+)(\*{1,3})(?=[^*\s])" % i,
                          lambda m: m.group(1) + "†" * len(m.group(2)), text, count=1)
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
