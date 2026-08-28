-- Add renewal_revenue column to deals table
-- Required for renewal pipeline value tracking (separate from new business arr_usd)

ALTER TABLE deals
ADD COLUMN IF NOT EXISTS renewal_revenue NUMERIC;

-- Create index for renewal revenue queries
CREATE INDEX IF NOT EXISTS idx_deals_renewal_revenue
ON deals(renewal_revenue)
WHERE renewal_revenue IS NOT NULL;

COMMENT ON COLUMN deals.renewal_revenue IS
'Renewal ARR for renewal pipeline deals (HubSpot renewal_revenue property).
Separate from arr_usd which tracks new business. See config pipeline.value_field.renewal_components';
