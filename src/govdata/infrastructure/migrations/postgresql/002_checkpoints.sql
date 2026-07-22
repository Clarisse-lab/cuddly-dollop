CREATE TABLE IF NOT EXISTS checkpoints (
    connector_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    scope TEXT NOT NULL,
    cursor TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (connector_id, dataset, scope)
);
