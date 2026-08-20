"""
Every config key must have a reader, or be explicitly recorded as unread.

Three findings this workstream shared one shape: something looked configured,
nothing consumed it, and the gap was invisible because the tests exercised the
config's own structure rather than the consumption path.

  - min_snapshot_coverage_pct: an 80% gate with no consumer anywhere, so the
    first consumer would have picked whichever population was to hand.
  - the numeric stage keys: present in config, never matched at runtime,
    because yaml parsed them as ints and HubSpot sends strings.
  - context.yaml coaching content: declared, never read.

A test that iterates the config and checks the config is self-consistent
cannot catch any of them. This checks the other direction: for each key, does
any code actually read it?

A reader means a string-literal reference — 'key' or "key" — in python or
workflow source. Bare substring matching is not enough: it credits
query_deal_health as a reader of deal_health.

RATCHET, not a cleanup mandate. 31 keys were already unread when this was
written; they are recorded in config/reserved_keys.yaml as UNAUDITED, meaning
observed-unread and not yet investigated, NOT blessed as intentional. The
check fails on any key that is unread and not in that ledger, so the count can
fall but not grow. Removing a key from the ledger requires either wiring a
reader or deleting the key.

Usage:
    python scripts/analytics/audit_config_readers.py
    python scripts/analytics/audit_config_readers.py --write-ledger
"""
import argparse
import re
import sys
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LEDGER = REPO_ROOT / 'config/reserved_keys.yaml'
AUDITED_CONFIGS = ['config/client.yaml']

# Keys that are DATA — fields of list items like pipeline stages or dictionary
# entries — rather than configuration knobs. A stage's `order` is a value, not
# a setting, and every one of them would otherwise need its own reader.
DATA_KEYS = {
    'id', 'name', 'order', 'label', 'bucket', 'transition', 'aliases',
    'alias_labels', 'historical', 'stage_probability', 'is_won', 'is_lost',
    'exclude_from_analysis', 'last_seen', 'first_seen', 'entries', 'deals',
    'reason', 'hubspot', 'column', 'description', 'type', 'components',
}


def knob_keys(node, path='', out=None, in_list=False):
    """Config knob keys, skipping fields of list items."""
    if out is None:
        out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if not isinstance(k, str):
                continue
            if not in_list and k not in DATA_KEYS:
                out.append((f"{path}.{k}".lstrip('.'), k))
            knob_keys(v, f"{path}.{k}", out, in_list)
    elif isinstance(node, list):
        for v in node:
            knob_keys(v, path, out, in_list=True)
    return out


def build_haystack():
    """Python and workflow source that could read a config key."""
    paths = [p for p in (list(REPO_ROOT.glob('scripts/**/*.py'))
                         + list(REPO_ROOT.glob('api/**/*.py'))
                         + list(REPO_ROOT.glob('*.py')))
             if '__pycache__' not in str(p)]
    paths += list(REPO_ROOT.glob('.github/workflows/*.yml'))
    return "\n".join(p.read_text(errors='ignore') for p in paths)


def find_unread():
    haystack = build_haystack()
    unread, seen = [], set()
    for cfg in AUDITED_CONFIGS:
        doc = yaml.safe_load((REPO_ROOT / cfg).read_text())
        for full, key in knob_keys(doc):
            if key in seen:
                continue
            seen.add(key)
            # String-literal reference only.
            if not re.search(r"['\"]" + re.escape(key) + r"['\"]", haystack):
                unread.append(full)
    return sorted(unread), len(seen)


def load_ledger():
    if not LEDGER.exists():
        return set()
    doc = yaml.safe_load(LEDGER.read_text()) or {}
    return set(doc.get('unaudited_unread', []) or [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write-ledger', action='store_true',
                        help='Record the current unread set as the baseline. '
                             'Only for establishing the ratchet.')
    args = parser.parse_args()

    unread, total = find_unread()

    if args.write_ledger:
        LEDGER.write_text(
            "# Config keys observed with no reader, recorded as a ratchet\n"
            "# baseline by scripts/analytics/audit_config_readers.py.\n"
            "#\n"
            "# UNAUDITED means: observed unread, NOT investigated, NOT blessed\n"
            "# as intentional. Each is either a knob that silently does\n"
            "# nothing, or a reader that was never wired. Working the list\n"
            "# down is real work; the ledger exists so the count cannot grow\n"
            "# while nobody is looking.\n"
            "#\n"
            "# To remove an entry: wire a reader, or delete the config key.\n"
            "# Do not add entries to silence the check.\n"
            f"# Baseline: {len(unread)} of {total} knob keys.\n"
            "\nunaudited_unread:\n"
            + "".join(f"  - {k}\n" for k in unread))
        print(f"✓ Wrote {LEDGER.relative_to(REPO_ROOT)} with {len(unread)} entries")
        return 0

    ledger = load_ledger()
    new = [k for k in unread if k not in ledger]
    fixed = sorted(ledger - set(unread))

    print("=" * 74)
    print("CONFIG READER AUDIT")
    print("=" * 74)
    print(f"\nKnob keys: {total}   unread: {len(unread)}   "
          f"ledger: {len(ledger)}")

    if fixed:
        print(f"\n✓ {len(fixed)} ledger key(s) now have a reader or are gone —"
              f" remove them from the ledger:")
        for k in fixed:
            print(f"    {k}")

    if new:
        print(f"\n✗ {len(new)} config key(s) have NO reader and are not in the"
              f" ledger:")
        for k in new:
            print(f"    {k}")
        print("\n  Either wire a reader, delete the key, or — if it is"
              " genuinely reserved —")
        print("  add it to config/reserved_keys.yaml with a note saying why.")
        return 1

    print("\n✓ No new unread config keys.")
    if unread:
        print(f"  {len(unread)} remain in the ledger, unaudited. Each is a knob"
              f" that may do nothing.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
