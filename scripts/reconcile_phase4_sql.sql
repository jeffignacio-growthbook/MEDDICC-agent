-- Phase 4 Reconciliation: Compare OLD vs NEW classification logic
-- Run this in Supabase SQL Editor

-- OLD logic (hardcoded stage lists)
WITH old_classification AS (
    SELECT
        CASE
            WHEN stage IN ('closedwon', '1297321623') THEN 'won'
            WHEN stage IN ('closedlost', '1297321624', '68509551') THEN 'lost'
            ELSE 'open'
        END as outcome,
        COUNT(*) as deal_count,
        SUM(COALESCE(arr_usd, 0)) as total_arr
    FROM deals
    GROUP BY 1
),

-- NEW logic (field_semantics - expanded from STAGE_MAP)
new_classification AS (
    SELECT
        CASE
            -- is_won: closedwon and its aliases
            WHEN stage IN ('closedwon', '1297321623') THEN 'won'
            -- is_lost: closedlost and its aliases (including Disqualified)
            WHEN stage IN ('closedlost', '1297321624', '68509551') THEN 'lost'
            -- is_open: discovery, scoping, proposal buckets
            WHEN stage IN ('appointmentscheduled', 'qualifiedtobuy', 'presentationscheduled',
                          'decisionmakerboughtin', 'contractsent') THEN 'open'
            -- Unknown stages default to open (field_semantics behavior)
            ELSE 'open'
        END as outcome,
        COUNT(*) as deal_count,
        SUM(COALESCE(arr_usd, 0)) as total_arr
    FROM deals
    GROUP BY 1
)

-- Compare side by side
SELECT
    COALESCE(o.outcome, n.outcome) as outcome,
    o.deal_count as old_count,
    o.total_arr as old_arr,
    n.deal_count as new_count,
    n.total_arr as new_arr,
    CASE
        WHEN o.deal_count = n.deal_count AND o.total_arr = n.total_arr THEN '✓ Match'
        ELSE '✗ DIFFER'
    END as status
FROM old_classification o
FULL OUTER JOIN new_classification n ON o.outcome = n.outcome
ORDER BY outcome;

-- If any differences, show which deals changed classification
-- Uncomment to see details:
/*
SELECT
    deal_id,
    company_name,
    stage,
    arr_usd,
    CASE
        WHEN stage IN ('closedwon', '1297321623') THEN 'won'
        WHEN stage IN ('closedlost', '1297321624', '68509551') THEN 'lost'
        ELSE 'open'
    END as old_classification,
    CASE
        WHEN stage IN ('closedwon', '1297321623') THEN 'won'
        WHEN stage IN ('closedlost', '1297321624', '68509551') THEN 'lost'
        WHEN stage IN ('appointmentscheduled', 'qualifiedtobuy', 'presentationscheduled',
                      'decisionmakerboughtin', 'contractsent') THEN 'open'
        ELSE 'open'
    END as new_classification
FROM deals
WHERE CASE
        WHEN stage IN ('closedwon', '1297321623') THEN 'won'
        WHEN stage IN ('closedlost', '1297321624', '68509551') THEN 'lost'
        ELSE 'open'
    END != CASE
        WHEN stage IN ('closedwon', '1297321623') THEN 'won'
        WHEN stage IN ('closedlost', '1297321624', '68509551') THEN 'lost'
        WHEN stage IN ('appointmentscheduled', 'qualifiedtobuy', 'presentationscheduled',
                      'decisionmakerboughtin', 'contractsent') THEN 'open'
        ELSE 'open'
    END;
*/
