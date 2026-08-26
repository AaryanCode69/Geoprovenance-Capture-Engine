-- ============================================================================
-- GeoProvenance — provenance database schema
--
--   STATUS: READY TO FREEZE — pending Person B and Person C sign-off.
--   Every OPEN: item is closed; docs/CONTRACT_schema.md says the same thing.
--   Becomes binding when tagged `contract-v1` with Person B and Person C's
--   agreement (RULES.md §3.1). Until then, change it freely. After then, the
--   change procedure in RULES.md §3.4 is mandatory — it breaks two other
--   people's code.
--
--   Baseline: research doc §7.1, taken verbatim, plus the six frozen decisions
--   in RULES.md Appendix B. Columns added beyond §7.1 are marked [+A0.1].
--   Rationale for every addition lives in docs/CONTRACT_schema.md.
--
--   RULES.md §4.1 — nothing that reads this file may import QGIS.
-- ============================================================================

PRAGMA user_version = 2;   -- Appendix B.6. Bumped only via storage/migrations.py.


-- ---------------------------------------------------------------------------
-- Entities — datasets we are keeping track of (PROV Entity)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id              TEXT PRIMARY KEY,        -- UUID4, generated in Python (§4.9)
    entity_type     TEXT NOT NULL,           -- 'dataset' | 'parameter_set' | 'model'
    label           TEXT,                    -- human-readable name
    file_path       TEXT,                    -- NULL for memory/temporary layers (§3.3)
    content_version INTEGER NOT NULL DEFAULT 1,  -- [+A0.1] Appendix B.1
    format          TEXT,                    -- 'Shapefile', 'GeoPackage', 'GeoTIFF'...
    crs             TEXT,                    -- authid ('EPSG:4326'); WKT only if none (§5.7)
    layer_type      TEXT,                    -- [+A0.1] 'vector' | 'raster' — set even when path IS NULL
    created_at      TEXT NOT NULL,           -- microsecond UTC ISO 8601 (Appendix B.4)
    metadata_json   TEXT,

    -- Appendix B.1: identity is (file_path, content version). A file rewritten
    -- with different content gets a NEW row with content_version + 1, not an
    -- update. This is what makes B's derivation chains and C's history view
    -- able to tell "the file before" from "the file after".
    -- NOTE: SQLite treats NULLs as distinct in UNIQUE, so memory layers
    -- (file_path IS NULL) are correctly never deduplicated against each other.
    UNIQUE (file_path, content_version)
);


-- ---------------------------------------------------------------------------
-- Activities — jobs QGIS ran (PROV Activity)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activities (
    id              TEXT PRIMARY KEY,
    algorithm_id    TEXT NOT NULL,           -- 'native:buffer'
    algorithm_name  TEXT,                    -- 'Buffer'
    provider        TEXT,                    -- 'qgis' | 'gdal' | 'grass' | 'saga'
    session_id      TEXT,                    -- [+A0.1] Appendix B.5 — UUID minted at plugin startup
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    parameters_json TEXT NOT NULL,           -- always JSON-serializable (§5.5)
    status          TEXT NOT NULL DEFAULT 'completed',  -- 'completed'|'failed'|'cancelled' (§4.10)
    execution_log   TEXT,

    -- [+A0.1] RQ1 instrumentation, per RULES.md §5.9 / §8.3.
    capture_channel TEXT,                    -- 'post_hook'|'run_wrapper'|'history_signal'|'toolbox' — which won
    corroborations  INTEGER NOT NULL DEFAULT 0,  -- times the OTHER channel also saw this
    dedup_key       TEXT,                    -- (algorithm_id, params hash, started_at@100ms)

    CHECK (status IN ('completed', 'failed', 'cancelled'))
);

-- [+A0.1] Enforces §5.9 at the database level: the second channel to report an
-- execution cannot insert a duplicate row, it can only increment corroborations.
CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_dedup
    ON activities (dedup_key) WHERE dedup_key IS NOT NULL;


-- ---------------------------------------------------------------------------
-- Agents — the computer and software setup (PROV Agent)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agents (
    id                   TEXT PRIMARY KEY,
    agent_type           TEXT NOT NULL,      -- 'software' | 'user'
    label                TEXT,               -- 'QGIS 3.34.8'
    qgis_version         TEXT,
    os_info              TEXT,
    python_version       TEXT,
    plugin_versions_json TEXT,               -- {"SCP": "8.1.0", ...}
    created_at           TEXT NOT NULL,

    -- [+A0.1] RULES.md §4.6 — one row per DISTINCT environment, reused across
    -- activities via get_or_create_agent(). Without this, we write one agent
    -- row per execution and inflate our own RQ2 storage numbers.
    env_fingerprint      TEXT UNIQUE
);


-- ---------------------------------------------------------------------------
-- Fingerprints — Person B writes these THROUGH ProvenanceStore (§1.3)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fingerprints (
    id               TEXT PRIMARY KEY,
    entity_id        TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    hash_algorithm   TEXT NOT NULL DEFAULT 'SHA-256',
    hash_value       TEXT NOT NULL,
    -- [+A0.1] 'file' | 'schema_sample' — B's tiered fallback (research doc §6.4).
    -- NOT NULL because it is part of the uniqueness key below, and SQLite treats
    -- every NULL in a UNIQUE as distinct — a nullable column there would let two
    -- identical rows both land whenever it was left unset, which is precisely
    -- the protection the key exists to give. Every fingerprint was produced by
    -- some method, so there is no row this makes unrepresentable.
    hash_strategy    TEXT NOT NULL DEFAULT 'file',
    file_size_bytes  INTEGER,
    feature_count    INTEGER,
    computed_at      TEXT NOT NULL,

    -- One fingerprint per dataset, PER METHOD, per instant.
    --
    -- hash_strategy is in the key because a byte hash and a schema hash of the
    -- same file are two different MEASUREMENTS, not a duplicate submitted
    -- twice. Person B computes several together so they can be compared
    -- against each other — a hash that moved while the feature count and
    -- extent did not is a re-save, not an edit — and without the strategy
    -- column here the second and third are rejected as duplicates.
    --
    -- Appendix B.4 still applies: microsecond ISO 8601 is MANDATORY. It is
    -- not, however, sufficient on its own. The clock's granularity is a
    -- platform detail (Windows advances datetime.now() roughly once per
    -- millisecond, Linux far faster), so leaving strategy out of the key made
    -- row identity depend on WHEN a row was written rather than WHAT it is —
    -- measured at 13 rejections in 30 runs on Windows.
    UNIQUE (entity_id, hash_strategy, computed_at)
);


-- ---------------------------------------------------------------------------
-- Relations — PROV relationships. Person B writes these THROUGH the store (§1.3)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relations (
    id              TEXT PRIMARY KEY,
    relation_type   TEXT NOT NULL,           -- wasGeneratedBy|used|wasDerivedFrom|
                                             -- wasAssociatedWith|wasAttributedTo
    source_id       TEXT NOT NULL,           -- entity or activity id (polymorphic — no FK)
    target_id       TEXT NOT NULL,
    role            TEXT,                    -- Appendix B.2: LOWERCASE ONLY
    qgis_param_key  TEXT,                    -- [+A0.1] Appendix B.2: the original key, e.g. 'OVERLAY'
    created_at      TEXT NOT NULL,

    CHECK (relation_type IN ('wasGeneratedBy', 'used', 'wasDerivedFrom',
                             'wasAssociatedWith', 'wasAttributedTo')),
    -- Appendix B.2: research doc §7.1 says 'input'|'output'|'parameter' but the
    -- §7.3 worked example uses "INPUT"/"OVERLAY". Two vocabularies for one
    -- concept means C writes string-normalising code that should never have
    -- been needed. Lowercase wins; the original QGIS key goes in qgis_param_key.
    CHECK (role IS NULL OR role IN ('input', 'output', 'overlay', 'parameter'))
);


-- ---------------------------------------------------------------------------
-- Workflows — session-based grouping (§5.12). B's wasDerivedFrom inference is
-- data-flow-based and is a DIFFERENT job; do not reimplement it here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workflows (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    session_id  TEXT,                        -- [+A0.1] the session this was grouped from
    created_at  TEXT NOT NULL,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS workflow_activities (
    workflow_id    TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    activity_id    TEXT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    sequence_order INTEGER,                  -- by started_at (§5.12)
    PRIMARY KEY (workflow_id, activity_id)
);


-- ---------------------------------------------------------------------------
-- Audit results — Person C writes these THROUGH ProvenanceStore (§1.3).
-- Weights are C's business (research doc §4.3 Layer 5); the table is A's.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_results (
    id                        TEXT PRIMARY KEY,
    workflow_id               TEXT REFERENCES workflows(id) ON DELETE CASCADE,
    audited_at                TEXT NOT NULL,
    overall_score             REAL,          -- 0.0 - 100.0
    input_exists_score        REAL,          -- weight 30%
    input_unchanged_score     REAL,          -- weight 25%
    algorithm_available_score REAL,          -- weight 20%
    environment_similar_score REAL,          -- weight 15%
    parameters_valid_score    REAL,          -- weight 10%
    details_json              TEXT           -- per-step results
);


-- ---------------------------------------------------------------------------
-- Indices — Appendix B.3. NOT optional.
--
-- Person C's graph traversal does repeated reverse lookups on relations.
-- Without these, Workflow C (15+ operations) is slow AND our own RQ2 numbers
-- look worse than the design deserves.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_relations_source     ON relations (source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target     ON relations (target_id);
CREATE INDEX IF NOT EXISTS idx_relations_type       ON relations (relation_type);
CREATE INDEX IF NOT EXISTS idx_entities_path        ON entities (file_path);
CREATE INDEX IF NOT EXISTS idx_fingerprints_entity  ON fingerprints (entity_id);
CREATE INDEX IF NOT EXISTS idx_wf_activities_wf     ON workflow_activities (workflow_id);

-- [+A0.1] Session grouping (Appendix B.5) and audit lookups scan these.
CREATE INDEX IF NOT EXISTS idx_activities_session   ON activities (session_id);
CREATE INDEX IF NOT EXISTS idx_activities_started   ON activities (started_at);
