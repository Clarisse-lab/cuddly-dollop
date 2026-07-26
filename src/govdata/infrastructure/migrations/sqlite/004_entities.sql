CREATE TABLE IF NOT EXISTS entities (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    display_name TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS entity_links (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    external_id TEXT NOT NULL,
    role TEXT,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id, connector_id, dataset, external_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_links_record
ON entity_links (connector_id, dataset, external_id);
