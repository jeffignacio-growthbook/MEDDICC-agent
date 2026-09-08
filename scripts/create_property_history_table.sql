-- Property history table for notes_last_updated and dealstage changes
CREATE TABLE IF NOT EXISTS property_history (
    deal_id TEXT NOT NULL,
    property_name TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source_type TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint to make re-runs safe
    UNIQUE(deal_id, property_name, changed_at)
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_property_history_deal_id ON property_history(deal_id);
CREATE INDEX IF NOT EXISTS idx_property_history_property_name ON property_history(property_name);
CREATE INDEX IF NOT EXISTS idx_property_history_changed_at ON property_history(changed_at);
CREATE INDEX IF NOT EXISTS idx_property_history_deal_property ON property_history(deal_id, property_name);

-- Comment
COMMENT ON TABLE property_history IS 'HubSpot property change history for deal properties (notes_last_updated, dealstage, etc.)';
