CREATE TABLE IF NOT EXISTS records (
    connector_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    external_id TEXT NOT NULL,
    data_json JSONB NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ,
    PRIMARY KEY (connector_id, dataset, external_id)
);
