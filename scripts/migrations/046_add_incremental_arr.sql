-- Add incremental_arr column to deals table
-- Required for expansion tracking in renewal pipeline (separate from renewal_revenue base)

ALTER TABLE deals
ADD COLUMN IF NOT EXISTS incremental_arr NUMERIC;

-- Create index for incremental ARR queries
CREATE INDEX IF NOT EXISTS idx_deals_incremental_arr
ON deals(incremental_arr)
WHERE incremental_arr IS NOT NULL;

COMMENT ON COLUMN deals.incremental_arr IS
'Incremental ARR for renewal pipeline expansion (HubSpot incremental_arr property).
Represents expansion above renewed base. May be NULL when no expansion.
Total renewal deal value = renewal_revenue + COALESCE(incremental_arr, 0)';
