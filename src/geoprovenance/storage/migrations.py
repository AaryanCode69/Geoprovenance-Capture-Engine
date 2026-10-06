"""Schema migrations, versioned by ``PRAGMA user_version``.

Owner: Person A.  Sub-phase: A2.  RULES.md §4.1 — no QGIS imports.

Why this exists on day one (Appendix B.6)
    The schema WILL change in Phase 2 — that is when contract mismatches
    surface, and expecting otherwise is the mistake. With a version and a
    migration path, Person B's and Person C's fixture databases fail loudly
    with a version mismatch instead of breaking silently.

Changing the schema after `contract-v1` is tagged requires ALL FIVE steps in
RULES.md §3.4, in one change:
    1. Bump CURRENT_VERSION here and add the forward migration to MIGRATIONS.
    2. Update docs/CONTRACT_schema.md with a dated changelog entry.
    3. Re-run  make fixtures
    4. Verify Person A's tests still pass.
    5. TELL B AND C what broke and what they must change.

Silent contract drift is the failure mode that costs the most time in Phase 2.
"""

from __future__ import annotations

import sqlite3

#: Keep in sync with ``PRAGMA user_version`` at the top of schema.sql.
CURRENT_VERSION = 2

#: version -> SQL statements taking the database from (version - 1) to version.
#: v1 is the baseline and is created directly from schema.sql, so it is empty.
MIGRATIONS: dict[int, list[str]] = {
    1: [],
    # v2 — `fingerprints` UNIQUE gains hash_strategy.
    #
    # WHY. The old key was (entity_id, computed_at): one fingerprint per file
    # per instant. That treats a byte hash and a schema hash of the same file
    # as duplicates, when they are two different measurements taken together
    # on purpose — Person B compares them against each other to tell a re-save
    # apart from a real edit. It also made row identity depend on the clock's
    # granularity, which is a platform detail: 13 of 30 same-file writes were
    # rejected on Windows, where datetime.now() advances about once per
    # millisecond. Genuine duplicates are still blocked, because a true
    # duplicate matches on strategy too.
    #
    # hash_strategy also becomes NOT NULL DEFAULT 'file'. That is not tidying:
    # SQLite treats every NULL in a UNIQUE as DISTINCT, so a nullable column in
    # the key would let two identical rows both land whenever the strategy was
    # left unset — removing the very protection this key exists to give, on the
    # default call path. Existing NULLs backfill to 'file', which is what they
    # were: the byte-hash strategy, and the only one written before v2.
    #
    # HOW. SQLite cannot alter a table-level UNIQUE in place — there is no
    # ALTER TABLE ... DROP CONSTRAINT — so the table is rebuilt: new shape,
    # copy, drop, rename, then put the index back (dropping a table drops its
    # indices with it). Column order and types are otherwise unchanged.
    #
    # Foreign keys are left alone deliberately. Nothing REFERENCES
    # fingerprints, so dropping it orphans nothing; and toggling
    # `PRAGMA foreign_keys` here would silently no-op inside the caller's
    # transaction, which is worse than not touching it.
    2: [
        """
        CREATE TABLE fingerprints_v2 (
            id               TEXT PRIMARY KEY,
            entity_id        TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            hash_algorithm   TEXT NOT NULL DEFAULT 'SHA-256',
            hash_value       TEXT NOT NULL,
            hash_strategy    TEXT NOT NULL DEFAULT 'file',
            file_size_bytes  INTEGER,
            feature_count    INTEGER,
            computed_at      TEXT NOT NULL,

            UNIQUE (entity_id, hash_strategy, computed_at)
        )
        """,
        """
        INSERT INTO fingerprints_v2
            (id, entity_id, hash_algorithm, hash_value, hash_strategy,
             file_size_bytes, feature_count, computed_at)
        SELECT id, entity_id, hash_algorithm, hash_value,
               coalesce(hash_strategy, 'file'),
               file_size_bytes, feature_count, computed_at
        FROM fingerprints
        """,
        "DROP TABLE fingerprints",
        "ALTER TABLE fingerprints_v2 RENAME TO fingerprints",
        "CREATE INDEX IF NOT EXISTS idx_fingerprints_entity ON fingerprints (entity_id)",
    ],
}


class SchemaVersionError(RuntimeError):
    """The database on disk is not a version this code can work with."""


def get_version(conn: sqlite3.Connection) -> int:
    """Return the database's ``PRAGMA user_version`` (0 for a fresh file)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def set_version(conn: sqlite3.Connection, version: int) -> None:
    """Set ``PRAGMA user_version``. Cannot be parameterised — hence the f-string."""
    if not isinstance(version, int) or version < 0:
        raise ValueError(f"schema version must be a non-negative int, got {version!r}")
    conn.execute(f"PRAGMA user_version = {version}")


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` up to CURRENT_VERSION. Returns the resulting version.

    Raises SchemaVersionError if the database is NEWER than this code
    understands — that means a teammate has bumped the schema and this checkout
    is stale. Failing loudly here is the entire point of Appendix B.6: the
    alternative is Person C's audit silently reading columns that have moved.
    """
    version = get_version(conn)

    if version > CURRENT_VERSION:
        raise SchemaVersionError(
            f"This database is at schema version {version}, but this code only "
            f"understands version {CURRENT_VERSION}. Someone has bumped the "
            f"schema — pull the latest code, then re-run `make fixtures`. "
            f"See RULES.md §3.4."
        )

    while version < CURRENT_VERSION:
        target = version + 1
        statements = MIGRATIONS.get(target)
        if statements is None:
            raise SchemaVersionError(
                f"No migration registered for version {target}. A version was "
                f"bumped without adding its migration — see RULES.md §3.4 step 1."
            )
        for statement in statements:
            conn.execute(statement)
        set_version(conn, target)
        version = target

    return version
