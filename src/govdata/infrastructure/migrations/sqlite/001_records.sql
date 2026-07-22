CREATE TABLE IF NOT EXISTS records (
    connector_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    external_id TEXT NOT NULL,
    data_json TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    source_updated_at TEXT,
    PRIMARY KEY (connector_id, dataset, external_id)
);
