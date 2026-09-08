-- Add company_country column to deals table
-- One-time enrichment from HubSpot Company.country property

ALTER TABLE deals ADD COLUMN IF NOT EXISTS company_country TEXT;

-- Add index for region-based queries
CREATE INDEX IF NOT EXISTS idx_deals_company_country ON deals(company_country);

-- Comment
COMMENT ON COLUMN deals.company_country IS 'Company country from HubSpot Company.country property. Populated via one-time enrichment pull. Used for region classification (NAM/EMEA/ROW).';
