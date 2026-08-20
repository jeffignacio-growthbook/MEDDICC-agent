#!/usr/bin/env python3
"""Find deals with clean Fireflies data for model comparison."""

import os
import psycopg2

# PostgreSQL connection. Credentials come from the environment — never
# hardcode a DB password in source; a committed credential stays live until
# rotated. Set SUPABASE_DB_URL (a postgresql:// connection string).
db_url = os.environ["SUPABASE_DB_URL"]
conn = psycopg2.connect(db_url)

query = """
-- Deals where the ABSOLUTE most recent call (any source) is Fireflies
-- with a clean summary and existing Claude analysis
WITH absolute_latest_call AS (
    SELECT
        deal_id,
        source,
        call_date,
        summary,
        length(summary) as summary_length,
        ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY call_date DESC) as rn
    FROM calls
),
latest_analysis AS (
    SELECT
        deal_id,
        overall_score,
        champion_score,
        economic_buyer_score,
        metrics_score,
        analyzed_at,
        ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY analyzed_at DESC) as rn
    FROM analyses
)
SELECT
    d.company_name,
    d.deal_id,
    d.arr_usd,
    d.stage,
    alc.call_date as latest_call_date,
    alc.source as latest_call_source,
    alc.summary_length,
    left(alc.summary, 100) as summary_preview,
    la.overall_score as claude_score,
    la.champion_score,
    la.economic_buyer_score,
    la.metrics_score,
    COUNT(c.call_id) as total_calls
FROM absolute_latest_call alc
JOIN deals d ON d.deal_id = alc.deal_id
JOIN latest_analysis la ON la.deal_id = alc.deal_id AND la.rn = 1
JOIN calls c ON c.deal_id = alc.deal_id
WHERE alc.rn = 1  -- only the absolute most recent call
  AND alc.source = 'fireflies'  -- and it must be from Fireflies
  AND alc.summary NOT LIKE '%Summary failed%'
  AND alc.summary IS NOT NULL
  AND length(alc.summary) > 200
  AND d.deal_status = 'active'
  AND d.arr_usd > 0
  AND la.overall_score > 15
GROUP BY d.company_name, d.deal_id, d.arr_usd, d.stage,
         alc.call_date, alc.source, alc.summary_length,
         alc.summary, la.overall_score, la.champion_score,
         la.economic_buyer_score, la.metrics_score
ORDER BY la.overall_score DESC, total_calls DESC
LIMIT 20;
"""

try:
    cursor = conn.cursor()
    cursor.execute(query)
    rows = cursor.fetchall()

    print(f"\n{'Company':<35} {'Deal ID':<15} {'ARR':<12} {'Score':<8} {'C':<3} {'E':<3} {'M':<3} {'Calls':<7} {'Latest'}")
    print("-" * 110)

    for row in rows:
        company = row[0][:33] if row[0] else 'Unknown'
        deal_id = row[1]
        arr = f"${row[2]:,.0f}" if row[2] else '$0'
        overall = row[8] if row[8] else 0
        champion = row[9] if row[9] else 0
        eb = row[10] if row[10] else 0
        metrics = row[11] if row[11] else 0
        calls = row[12]
        call_date = str(row[4])[:10]

        print(f"{company:<35} {deal_id:<15} {arr:<12} {overall:>2}/70   {champion:>2}  {eb:>2}  {metrics:>2}  {calls:<7} {call_date}")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
