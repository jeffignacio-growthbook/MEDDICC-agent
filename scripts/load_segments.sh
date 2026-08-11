#!/bin/bash
# Load segments from CSV files and query distribution
set -e

# Check environment variables
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_SERVICE_KEY" ]; then
    echo "❌ Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set"
    echo ""
    echo "Get the values from GitHub secrets and run:"
    echo "  export SUPABASE_URL='your-url'"
    echo "  export SUPABASE_SERVICE_KEY='your-key'"
    echo "  ./scripts/load_segments.sh"
    exit 1
fi

DEALS_CSV="/Users/jeffignacio/Downloads/all-deals.csv"
COMPANIES_CSV="/Users/jeffignacio/Downloads/all-companies.csv"

if [ ! -f "$DEALS_CSV" ] || [ ! -f "$COMPANIES_CSV" ]; then
    echo "❌ Error: CSV files not found"
    exit 1
fi

echo "✓ Found CSV files"
echo ""
echo "Running ETL with CSV files..."
python scripts/etl_deals.py --mode analytics --file "$DEALS_CSV" --companies-file "$COMPANIES_CSV"

if [ $? -ne 0 ]; then
    echo "❌ ETL failed"
    exit 1
fi

echo ""
echo "Querying segment distribution..."
python scripts/query_segments_simple.py
