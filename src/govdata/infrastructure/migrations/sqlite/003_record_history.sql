ALTER TABLE records ADD COLUMN source_url TEXT;
ALTER TABLE records ADD COLUMN content_hash TEXT;

CREATE TABLE IF NOT EXISTS record_versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    connector_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    external_id TEXT NOT NULL,
    data_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_url TEXT,
    collected_at TEXT NOT NULL,
    source_updated_at TEXT,
    UNIQUE (connector_id, dataset, external_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_record_versions_record
ON record_versions (connector_id, dataset, external_id, collected_at);
