#!/usr/bin/env python3
"""
Backfill data_dictionary with missing columns from information_schema.

Ensures the dynamic query loop can discover and query all relevant columns
in queryable tables.

Usage:
    python scripts/backfill_data_dictionary.py --sample      # Show 10 sample descriptions
    python scripts/backfill_data_dictionary.py --dry-run     # Show all descriptions, no insert
    python scripts/backfill_data_dictionary.py               # Actually insert
"""

import os
import sys
import argparse
import psycopg2
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from llm_client import LLMClient

# Queryable tables the dynamic loop should see
QUERYABLE_TABLES = [
    "deals",
    "calls",
    "analyses",
    "objections",
    "feature_gaps",
    "waterfall_weekly",
    "forecast_weekly",
    "pipeline_generation_weekly",
    "win_loss_narratives",
    "competitive_signals",
    "pipeline_signals",
    "deal_risks",
    "rep_performance",
    "rep_targets",
    "deals_snapshot",
]

# Foreign key columns that point to entities but aren't entity IDs themselves
# Flag these for manual review rather than auto-registering
FOREIGN_KEY_COLUMNS = {
    ("calls", "deal_id"),
    ("calls", "company_id"),
    ("feature_gaps", "deal_id"),
    ("objections", "deal_id"),
    ("win_loss_narratives", "deal_id"),
}

# Map Postgres types to simplified data_type for data_dictionary
TYPE_MAPPING = {
    "text": "text",
    "character varying": "text",
    "uuid": "text",
    "bigint": "number",
    "integer": "number",
    "numeric": "number",
    "double precision": "number",
    "real": "number",
    "boolean": "boolean",
    "date": "date",
    "timestamp without time zone": "date",
    "timestamp with time zone": "date",
    "jsonb": "json",
    "json": "json",
}


def get_missing_columns(conn):
    """Query information_schema for columns missing from data_dictionary."""
    cur = conn.cursor()

    tables_clause = ",".join(f"'{t}'" for t in QUERYABLE_TABLES)

    query = f"""
    SELECT c.table_name, c.column_name, c.data_type
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name IN ({tables_clause})
      AND NOT EXISTS (
        SELECT 1 FROM data_dictionary d
        WHERE d.supabase_table = c.table_name
          AND d.supabase_column = c.column_name
      )
    ORDER BY c.table_name, c.column_name;
    """

    cur.execute(query)
    results = cur.fetchall()
    cur.close()

    return results


def map_pg_type(pg_type):
    """Map Postgres type to data_dictionary data_type."""
    # Handle array types
    pg_lower = pg_type.lower()
    if "array" in pg_lower or pg_lower.endswith("[]"):
        return "array"

    return TYPE_MAPPING.get(pg_type.lower(), "text")


def generate_descriptions_batch(columns, api_key, batch_size=40):
    """Generate descriptions for columns using Claude Haiku in batched calls.

    Args:
        columns: List of (table, column, data_type) tuples
        api_key: Anthropic API key
        batch_size: Number of columns per API call (default 40)
    """
    import time

    client = LLMClient.from_config("generator")

    all_descriptions = {}

    # Process in batches to avoid JSON parsing issues with large responses
    for i in range(0, len(columns), batch_size):
        batch = columns[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(columns) + batch_size - 1) // batch_size

        print(f"  Batch {batch_num}/{total_batches}: {len(batch)} columns...", end=" ", flush=True)

        # Build prompt for this batch
        columns_text = "\n".join([
            f"- {table}.{column} ({data_type})"
            for table, column, data_type in batch
        ])

        prompt = f"""Generate concise, technical descriptions for these database columns in a revenue operations / sales pipeline system.

Each description should:
- Be 1-2 sentences
- Explain what the column stores and when it's populated
- Use present tense ("stores X", "indicates Y")
- Be specific to the business context

Return ONLY a JSON array with objects containing "table", "column", and "description" fields.
No markdown code fences, no explanation.

Columns:
{columns_text}

Context:
- deals: Sales opportunities/pipeline (B2B SaaS sales)
- calls: Sales call transcripts from Apollo/Fireflies/Gong
- analyses: MEDDICC scores and deal assessment results
- objections: Customer objections extracted from call transcripts
- feature_gaps: Missing features/capabilities mentioned in calls
- waterfall_weekly: Week-over-week pipeline movement and changes
- forecast_weekly: Weekly forecast category snapshots
- pipeline_generation_weekly: New pipeline created each week
- win_loss_narratives: Why deals closed won/lost (narrative summaries)
- competitive_signals: Competitor mentions and win/loss patterns
- pipeline_signals: Leading indicators of pipeline health
- deal_risks: Risk flags and warning indicators for deals
- rep_performance: Sales rep metrics and quota attainment
- rep_targets: Quota targets and goals by rep/period
- deals_snapshot: LARGE time-series table (~61k rows) with weekly deal state snapshots - MUST filter by snapshot_date"""

        try:
            response = client.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000
            )

            import json
            # Extract JSON from response
            text = response.text.strip()

            # Remove markdown code fences if present
            if text.startswith("```"):
                lines = text.split("\n")
                # Skip first line (```json or ```)
                text = "\n".join(lines[1:])
                if text.endswith("```"):
                    text = text[:-3]

            descriptions = json.loads(text)

            # Merge into all_descriptions
            for item in descriptions:
                key = (item["table"], item["column"])
                desc = item["description"]

                # Special handling: inject warnings for deals_snapshot columns
                if item["table"] == "deals_snapshot":
                    if item["column"] == "snapshot_date":
                        desc = f"{desc} ⚠️ REQUIRED FILTER: This table has ~61k rows - queries MUST filter by snapshot_date to avoid unbounded pulls."
                    elif item["column"] == "deal_id":
                        desc = f"{desc} ⚠️ NOTE: deals_snapshot is a large time-series table - always filter by snapshot_date when querying."

                all_descriptions[key] = desc

            print("✓")

            # Rate limiting between batches
            if i + batch_size < len(columns):
                time.sleep(0.5)

        except Exception as e:
            print(f"✗ Error: {e}")
            # Provide fallback descriptions for this batch
            for table, column, data_type in batch:
                key = (table, column)
                all_descriptions[key] = f"Column {column} in {table} table (auto-generated fallback)"

    return all_descriptions


def backfill_data_dictionary(conn, columns_with_descriptions, dry_run=True):
    """Insert missing columns into data_dictionary."""
    cur = conn.cursor()

    inserted = 0
    flagged_fks = []

    for (table, column, pg_type), description in columns_with_descriptions:
        data_type = map_pg_type(pg_type)

        # Check if this is a foreign key that should be flagged
        if (table, column) in FOREIGN_KEY_COLUMNS:
            flagged_fks.append((table, column, description))
            print(f"  🚩 FLAGGED: {table}.{column} (foreign key, needs manual review)")
            continue

        if dry_run:
            print(f"  → {table}.{column} ({data_type})")
            print(f"     {description}")
        else:
            cur.execute("""
                INSERT INTO data_dictionary (
                    source, supabase_table, supabase_column,
                    data_type, description, is_queryable
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (supabase_table, supabase_column) DO NOTHING
            """, (
                'supabase',
                table,
                column,
                data_type,
                description,
                True
            ))
            inserted += 1

    if not dry_run:
        conn.commit()
        print(f"\n✓ Inserted {inserted} columns into data_dictionary")

    if flagged_fks:
        print(f"\n{'='*80}")
        print("FOREIGN KEYS FLAGGED FOR MANUAL REVIEW")
        print("="*80)
        print("\nThese columns point to entities but aren't entity IDs themselves.")
        print("Decide whether they should be queryable or registered as entity links:\n")
        for table, column, desc in flagged_fks:
            print(f"  {table}.{column}")
            print(f"    {desc}\n")

    cur.close()
    return inserted, flagged_fks


def main():
    parser = argparse.ArgumentParser(
        description="Backfill data_dictionary with missing columns"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without actually inserting"
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Generate and show sample descriptions only (first 10 columns)"
    )
    args = parser.parse_args()

    # Get DB connection
    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        print("ERROR: SUPABASE_DB_URL not set")
        print("Export with: export SUPABASE_DB_URL='postgresql://...'")
        return 1

    # Get Anthropic API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return 1

    conn = psycopg2.connect(db_url)

    print("="*80)
    print("DATA_DICTIONARY BACKFILL")
    print("="*80)

    # Get missing columns
    missing = get_missing_columns(conn)

    if not missing:
        print("\n✓ No missing columns - data_dictionary is complete")
        conn.close()
        return 0

    print(f"\nFound {len(missing)} missing columns across {len(QUERYABLE_TABLES)} tables")

    # Count by table
    by_table = {}
    for table, col, dt in missing:
        by_table.setdefault(table, 0)
        by_table[table] += 1

    print("\nBreakdown:")
    for table in sorted(by_table.keys()):
        print(f"  {table}: {by_table[table]} columns")

    # Generate descriptions
    if args.sample:
        sample_columns = missing[:10]
        print(f"\n{'='*80}")
        print(f"SAMPLE: Generating descriptions for first 10 columns")
        print("="*80)
    else:
        sample_columns = missing
        print(f"\n{'='*80}")
        print(f"Generating descriptions for all {len(missing)} columns...")
        print("="*80)

    descriptions = generate_descriptions_batch(sample_columns, api_key)

    # Build list with descriptions
    columns_with_desc = []
    for table, column, pg_type in sample_columns:
        desc = descriptions.get((table, column))
        if not desc:
            desc = f"Column {column} in {table} table"
        columns_with_desc.append(((table, column, pg_type), desc))

    if args.sample:
        print(f"\nSample descriptions ({len(columns_with_desc)} columns):\n")
        for (table, column, pg_type), desc in columns_with_desc:
            is_fk = (table, column) in FOREIGN_KEY_COLUMNS
            flag = " 🚩 FK" if is_fk else ""
            print(f"{table}.{column} ({pg_type}){flag}")
            print(f"  → {desc}\n")

        print("="*80)
        print("Review quality, then run without --sample to backfill all")
        print("="*80)
        conn.close()
        return 0

    # Full backfill
    if not args.dry_run:
        # Generate descriptions for remaining columns if we only did a sample
        if len(sample_columns) < len(missing):
            remaining = missing[len(sample_columns):]
            print(f"\nGenerating descriptions for remaining {len(remaining)} columns...")
            remaining_desc = generate_descriptions_batch(remaining, api_key)

            for table, column, pg_type in remaining:
                desc = remaining_desc.get((table, column), f"Column {column} in {table} table")
                columns_with_desc.append(((table, column, pg_type), desc))

    mode = "DRY RUN" if args.dry_run else "INSERTING"
    print(f"\n{'='*80}")
    print(f"{mode}: {len(columns_with_desc)} columns")
    print("="*80)
    print()

    inserted, flagged = backfill_data_dictionary(conn, columns_with_desc, dry_run=args.dry_run)

    if not args.dry_run:
        # Verify
        print("\n" + "="*80)
        print("Verifying backfill...")
        print("="*80)

        remaining = get_missing_columns(conn)
        # Filter out flagged FKs
        remaining_non_fk = [
            (t, c, dt) for t, c, dt in remaining
            if (t, c) not in FOREIGN_KEY_COLUMNS
        ]

        if remaining_non_fk:
            print(f"\n⚠️  {len(remaining_non_fk)} columns still missing (unexpected)")
            for t, c, dt in remaining_non_fk[:5]:
                print(f"  - {t}.{c}")
        else:
            print(f"\n✓ All non-FK columns registered ({inserted} inserted)")
            print(f"✓ {len(flagged)} foreign keys flagged for manual review")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
