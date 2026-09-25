#!/usr/bin/env python3
"""
_smart_truncate_for_synthesis tries compact JSON before cutting characters.

It serialises with indent=2 and, when that is over the limit and the
result has no rows to cap, falls to its last resort: full_json[:limit].
Indentation is a fifth or more of a nested payload, so a result whose
content fits could still lose its tail to a cut made to keep whitespace.
The tail is where late additions land (a composed result's primitives, a
_plausibility_warnings list, a note). Found building the quarter-health
composer: its downside view was 20,590 chars indented, 16,888 compact.

Now, over the limit indented, the same JSON without indentation is tried
before anything is capped or cut. A payload that fits indented is
returned exactly as before.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import api.router as router  # noqa: E402

LIMIT = router.SYNTH_PAYLOAD_CHARS


def _nested(n):
    return {"status": "ok",
            "sections": [{"name": f"s{i}", "values": {"a": i, "b": i * 2, "c": [i, i + 1]}}
                         for i in range(n)],
            "note": "LAST_NOTE: this basis must reach the model."}


def test_fits_indented_is_unchanged():
    p = _nested(20)
    out = router._smart_truncate_for_synthesis(p, LIMIT)
    assert out == json.dumps(p, indent=2, default=str)
    print("✓ a payload that fits indented is returned exactly as before")


def test_fits_compact_is_sent_compact_and_whole():
    n = 1
    while len(json.dumps(_nested(n), indent=2)) <= LIMIT:
        n += 10
    p = _nested(n)
    assert len(json.dumps(p, default=str)) <= LIMIT < len(json.dumps(p, indent=2, default=str))
    out = router._smart_truncate_for_synthesis(p, LIMIT)
    assert json.loads(out) == p, "the payload must arrive whole"
    assert "LAST_NOTE" in out
    print(f"✓ over the limit indented but not compact ({len(json.dumps(p, indent=2))} vs "
          f"{len(json.dumps(p))} chars): sent compact, whole, last key included")


def test_too_big_even_compact_still_takes_the_old_path():
    p = _nested(2000)
    out = router._smart_truncate_for_synthesis(p, LIMIT)
    assert len(out) == LIMIT
    print("✓ too big even compact: the existing cap/cut path is unchanged")


if __name__ == "__main__":
    test_fits_indented_is_unchanged()
    test_fits_compact_is_sent_compact_and_whole()
    test_too_big_even_compact_still_takes_the_old_path()
    print("\n✅ All tests passed")
