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
    text = _protect(_INLINE_CODE, text, kept)
    text = _convert_lines(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
