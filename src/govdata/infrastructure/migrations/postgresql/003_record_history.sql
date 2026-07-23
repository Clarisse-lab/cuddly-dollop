ALTER TABLE records ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE records ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE TABLE IF NOT EXISTS record_versions (
    version_id BIGSERIAL PRIMARY KEY,
    connector_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    external_id TEXT NOT NULL,
    data_json JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    source_url TEXT,
    collected_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ,
    UNIQUE (connector_id, dataset, external_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_record_versions_record
ON record_versions (connector_id, dataset, external_id, collected_at);
