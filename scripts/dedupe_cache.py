#!/usr/bin/env python3
"""
Deduplicate ambiguous cache files.

Merges duplicate cache files by combining calls, deduplicating by ID,
and saving to canonical filename.
"""
import json
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent.parent
CALLS_DIR = REPO_ROOT / 'memory' / 'calls'

# Files to merge into canonical slugs
MERGES = [
    ('bestseller',  ['bestseller-growthbook.json',
                     'growthbook-bestseller.json']),
    ('fixter',      ['fixter-growthbook.json',
                     'fixter-growthbook-s.json']),
    ('inpost',      ['inpost-growthbook.json',
                     'growthbook-inpost.json']),
    ('skyscanner',  ['skyscanner-growthbook.json',
                     'skyscanner-growthbook-catch-up.json']),
    ('ryanair',     ['ryanair-growthbook.json',
                     'ryanair-enterprise-trial.json']),
    ('deel',        ['deel-growthbook.json',
                     'deel-consolidation-discussion.json']),
]

# Square is a special case - different companies, just rename
RENAMES = [
    ('growthbook-square.json', 'square.json'),  # Block/Square payments company
    # square-enix.json stays as-is (video game company)
]


def merge_cache_files(canonical_slug: str, source_files: list):
    """
    Merge multiple cache files into one canonical file.

    Args:
        canonical_slug: The canonical slug for the merged file
        source_files: List of source filenames to merge
    """
    print(f"\n{'='*60}")
    print(f"Merging: {canonical_slug}")
    print(f"{'='*60}")

    all_calls = []
    company_name = None

    # Load all source files
    for filename in source_files:
        path = CALLS_DIR / filename
        if not path.exists():
            print(f"  ⚠️  {filename} not found, skipping")
            continue

        try:
            with open(path) as f:
                data = json.load(f)
                calls = data.get('calls', [])

                # Use first non-empty company name we find
                if not company_name and data.get('company'):
                    company_name = data.get('company')

                all_calls.extend(calls)
                print(f"  ✓ Loaded {len(calls)} calls from {filename}")
        except Exception as e:
            print(f"  ✗ Error loading {filename}: {e}")

    if not all_calls:
        print(f"  ⚠️  No calls found, skipping merge")
        return

    # Deduplicate by call ID
    calls_by_id = {}
    for call in all_calls:
        call_id = call.get('id')
        if call_id:
            # Keep first occurrence (they should be identical)
            if call_id not in calls_by_id:
                calls_by_id[call_id] = call

    # Sort by date ascending
    merged_calls = sorted(calls_by_id.values(), key=lambda c: c.get('date', ''))

    print(f"  → Merged: {len(all_calls)} total → {len(merged_calls)} unique calls")

    # Build canonical cache
    canonical_cache = {
        'company': company_name or canonical_slug.replace('-', ' ').title(),
        'slug': canonical_slug,
        'last_etl_date': datetime.now().isoformat(),
        'calls': merged_calls
    }

    # Save to canonical filename
    canonical_path = CALLS_DIR / f'{canonical_slug}.json'
    with open(canonical_path, 'w', encoding='utf-8') as f:
        json.dump(canonical_cache, f, indent=2, ensure_ascii=False)

    print(f"  ✓ Saved {canonical_path.name}")

    # Delete source files
    for filename in source_files:
        path = CALLS_DIR / filename
        if path.exists():
            path.unlink()
            print(f"  🗑️  Deleted {filename}")


def rename_file(old_name: str, new_name: str):
    """Rename a cache file."""
    print(f"\n{'='*60}")
    print(f"Renaming: {old_name} → {new_name}")
    print(f"{'='*60}")

    old_path = CALLS_DIR / old_name
    new_path = CALLS_DIR / new_name

    if not old_path.exists():
        print(f"  ⚠️  {old_name} not found, skipping")
        return

    if new_path.exists():
        print(f"  ⚠️  {new_name} already exists, skipping rename")
        return

    # Load and update slug
    try:
        with open(old_path) as f:
            data = json.load(f)

        data['slug'] = new_name.replace('.json', '')
        data['last_etl_date'] = datetime.now().isoformat()

        with open(new_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        old_path.unlink()
        print(f"  ✓ Renamed {old_name} → {new_name}")
    except Exception as e:
        print(f"  ✗ Error: {e}")


def main():
    print("="*60)
    print("CACHE FILE DEDUPLICATION")
    print("="*60)

    # Process merges
    for canonical_slug, source_files in MERGES:
        merge_cache_files(canonical_slug, source_files)

    # Process renames
    for old_name, new_name in RENAMES:
        rename_file(old_name, new_name)

    print(f"\n{'='*60}")
    print("DEDUPLICATION COMPLETE")
    print("="*60)


if __name__ == '__main__':
    main()
