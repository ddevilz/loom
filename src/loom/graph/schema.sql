-- Loom SQLite schema
-- Two sections: CORE (always) and FTS5 (if extension available).
-- Loaded by db.py:init_schema(). Do not run directly — migrations in init_schema() must run too.

-- ── CORE ──────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS nodes (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    source          TEXT NOT NULL,
    name            TEXT NOT NULL,
    path            TEXT NOT NULL,
    start_line      INTEGER,
    end_line        INTEGER,
    language        TEXT,
    content_hash    TEXT,
    file_hash       TEXT,
    file_mtime      REAL,
    summary         TEXT,
    summary_hash    TEXT,
    token_count     INTEGER,
    community_id    TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}',
    updated_at      INTEGER NOT NULL,
    deleted_at      INTEGER,
    complexity      TEXT DEFAULT NULL,
    tags_normalized TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_nodes_name    ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_path    ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_kind    ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_lang    ON nodes(language);
CREATE INDEX IF NOT EXISTS idx_nodes_deleted ON nodes(deleted_at);

CREATE TABLE IF NOT EXISTS edges (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id          TEXT NOT NULL,
    to_id            TEXT NOT NULL,
    kind             TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 1.0,
    confidence_tier  TEXT NOT NULL DEFAULT 'extracted',
    metadata         TEXT NOT NULL DEFAULT '{}',
    UNIQUE(from_id, to_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_edges_from      ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to        ON edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind      ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_to_kind   ON edges(to_id, kind);
CREATE INDEX IF NOT EXISTS idx_edges_from_kind ON edges(from_id, kind);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL DEFAULT 'default',
    started_at  INTEGER NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id, started_at DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS savings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           INTEGER NOT NULL,
    node_id      TEXT    NOT NULL,
    query        TEXT,
    tokens_saved INTEGER NOT NULL DEFAULT 0,
    summary_type TEXT    NOT NULL DEFAULT 'auto'
);
CREATE INDEX IF NOT EXISTS idx_savings_ts ON savings(ts DESC);

CREATE TABLE IF NOT EXISTS node_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    node_id     TEXT    NOT NULL,
    tool        TEXT    NOT NULL,
    visited_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visits_session ON node_visits(session_id, visited_at DESC);
CREATE INDEX IF NOT EXISTS idx_visits_node    ON node_visits(node_id);

-- New table: fingerprints for incremental indexing
CREATE TABLE IF NOT EXISTS file_fingerprints (
    file_path    TEXT PRIMARY KEY,
    content_sha  TEXT NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    indexed_at   REAL NOT NULL
);

-- New table: tag storage (system + agent tags)
CREATE TABLE IF NOT EXISTS node_tags (
    node_id  TEXT NOT NULL,
    tag      TEXT NOT NULL,
    source   TEXT NOT NULL DEFAULT 'system',
    UNIQUE(node_id, tag, source)
);
CREATE INDEX IF NOT EXISTS idx_node_tags_tag  ON node_tags(tag, node_id);
CREATE INDEX IF NOT EXISTS idx_node_tags_node ON node_tags(node_id);

-- ── FTS5 (loaded only when SQLite was compiled with fts5) ─────────────────────

-- @fts5
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    id UNINDEXED, name, summary, path, tags_normalized,
    content='nodes', content_rowid='rowid',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, id, name, summary, path, tags_normalized)
    VALUES (new.rowid, new.id, new.name, new.summary, new.path, new.tags_normalized);
END;
CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, id, name, summary, path, tags_normalized)
    VALUES ('delete', old.rowid, old.id, old.name, old.summary, old.path, old.tags_normalized);
END;
CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, id, name, summary, path, tags_normalized)
    VALUES ('delete', old.rowid, old.id, old.name, old.summary, old.path, old.tags_normalized);
    INSERT INTO nodes_fts(rowid, id, name, summary, path, tags_normalized)
    VALUES (new.rowid, new.id, new.name, new.summary, new.path, new.tags_normalized);
END;
