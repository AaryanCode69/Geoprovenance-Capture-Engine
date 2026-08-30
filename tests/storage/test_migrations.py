"""The forward migration path — RULES.md Appendix B.6, §3.4 step 1.

RULES.md §6.1 — no QGIS anywhere in this file.

Why this file exists
    `PRAGMA user_version` plus a working `migrations.py` is a frozen schema
    decision (Appendix B.6) whose whole purpose is that Person B's and Person
    C's databases fail loudly on a mismatch instead of breaking silently. Until
    now nothing exercised an actual migration: the tests asserted
    `CURRENT_VERSION == 2` and that a version from the future is rejected, and
    the v1 -> v2 rebuild — the only real migration in the project — was verified
    by hand and never committed.

    That verification cannot be repeated, either. The committed fixture was
    regenerated at v2, so there is no v1 database left in the repository to
    migrate. The v1 shape is therefore rebuilt here from its DDL, which makes
    this file the only remaining record of what v1 looked like.

The v1 fingerprints table, verbatim from before commit 366319a:

    hash_strategy    TEXT,                        -- nullable
    UNIQUE (entity_id, computed_at)               -- no strategy in the key
"""

from __future__ import annotations

import sqlite3

import pytest

from geoprovenance.storage import migrations
from geoprovenance.storage.store import ProvenanceStore

V1_SCHEMA = """
CREATE TABLE entities (
    id              TEXT PRIMARY KEY,
    entity_type     TEXT NOT NULL,
    label           TEXT,
    file_path       TEXT,
    content_version INTEGER NOT NULL DEFAULT 1,
    format          TEXT,
    crs             TEXT,
    layer_type      TEXT,
    created_at      TEXT NOT NULL,
    metadata_json   TEXT,
    UNIQUE (file_path, content_version)
);

CREATE TABLE fingerprints (
    id               TEXT PRIMARY KEY,
    entity_id        TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    hash_algorithm   TEXT NOT NULL DEFAULT 'SHA-256',
    hash_value       TEXT NOT NULL,
    hash_strategy    TEXT,
    file_size_bytes  INTEGER,
    feature_count    INTEGER,
    computed_at      TEXT NOT NULL,
    UNIQUE (entity_id, computed_at)
);

CREATE INDEX idx_fingerprints_entity ON fingerprints (entity_id);
"""


@pytest.fixture()
def v1_database(tmp_path):
    """A version-1 database holding one dataset and three of its fingerprints.

    One row has a NULL `hash_strategy`, which v1 permitted and v2 does not.
    That row is the reason the migration has a `coalesce` in it, so it is the
    row worth carrying in the fixture.
    """
    path = tmp_path / "v1.db"
    connection = sqlite3.connect(path)
    connection.executescript(V1_SCHEMA)
    connection.execute(
        "INSERT INTO entities (id, entity_type, file_path, created_at) "
        "VALUES ('e1', 'dataset', '/data/roads.shp', '2026-08-01T00:00:00.000001+00:00')"
    )
    connection.executemany(
        "INSERT INTO fingerprints "
        "(id, entity_id, hash_value, hash_strategy, file_size_bytes, computed_at) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("f1", "e1", "aaa", None, 100, "2026-08-01T00:00:01.000001+00:00"),
            ("f2", "e1", "bbb", "file", 200, "2026-08-01T00:00:02.000001+00:00"),
            ("f3", "e1", "ccc", "schema_sample", 300, "2026-08-01T00:00:03.000001+00:00"),
        ],
    )
    migrations.set_version(connection, 1)
    connection.commit()
    connection.close()
    return path


def _rows(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM fingerprints ORDER BY id"
        )]
    finally:
        connection.close()


def test_a_v1_database_migrates_to_the_current_version(v1_database):
    connection = sqlite3.connect(v1_database)
    try:
        assert migrations.get_version(connection) == 1
        assert migrations.apply_migrations(connection) == migrations.CURRENT_VERSION
        connection.commit()
    finally:
        connection.close()
    assert migrations.CURRENT_VERSION == 2


def test_the_migration_preserves_every_row_and_every_value(v1_database):
    """A table rebuild copies data by hand, which is where a migration loses it.

    SQLite has no `ALTER TABLE ... DROP CONSTRAINT`, so changing the UNIQUE
    means creating a new table, copying, dropping and renaming. A column left
    out of the INSERT list is silently NULL afterwards — this asserts every
    value survived, not merely every row.
    """
    before = {row["id"]: row for row in _rows(v1_database)}
    connection = sqlite3.connect(v1_database)
    migrations.apply_migrations(connection)
    connection.commit()
    connection.close()
    after = {row["id"]: row for row in _rows(v1_database)}

    assert set(after) == set(before) == {"f1", "f2", "f3"}
    for key in ("entity_id", "hash_algorithm", "hash_value", "file_size_bytes",
                "feature_count", "computed_at"):
        for row_id in before:
            assert after[row_id][key] == before[row_id][key], f"{row_id}.{key}"


def test_a_null_strategy_backfills_to_file_because_that_is_what_it_was(
    v1_database,
):
    """`file` is not a default chosen for tidiness — it is the true value.

    v1 had exactly one strategy in use; every row written under it was a byte
    hash. Backfilling to anything else, or leaving NULL, would misdescribe
    data that already exists.
    """
    connection = sqlite3.connect(v1_database)
    migrations.apply_migrations(connection)
    connection.commit()
    connection.close()

    rows = {row["id"]: row["hash_strategy"] for row in _rows(v1_database)}
    assert rows == {"f1": "file", "f2": "file", "f3": "schema_sample"}


def test_the_new_key_admits_the_rows_the_old_one_rejected(v1_database):
    """The point of the migration, stated as behaviour rather than as DDL.

    Two measurements of one dataset at one instant is what Person B produces
    and what v1 could not store.
    """
    connection = sqlite3.connect(v1_database)
    migrations.apply_migrations(connection)
    instant = "2026-08-02T09:00:00.000001+00:00"
    connection.execute(
        "INSERT INTO fingerprints (id, entity_id, hash_value, hash_strategy, computed_at) "
        "VALUES ('n1','e1','ddd','file',?)", (instant,)
    )
    connection.execute(
        "INSERT INTO fingerprints (id, entity_id, hash_value, hash_strategy, computed_at) "
        "VALUES ('n2','e1','eee','geometry',?)", (instant,)
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO fingerprints (id, entity_id, hash_value, hash_strategy, computed_at) "
            "VALUES ('n3','e1','fff','file',?)", (instant,)
        )
    connection.close()


def test_the_migration_puts_the_index_back(v1_database):
    """Dropping a table drops its indices with it.

    `fingerprints(entity_id)` is a mandatory index (RULES.md §3.2 decision 3,
    Appendix B.3) because Person C's traversal does repeated lookups on it. A
    rebuild that forgot to recreate it would leave the schema correct and the
    performance claim in RQ2 quietly wrong.
    """
    connection = sqlite3.connect(v1_database)
    migrations.apply_migrations(connection)
    connection.commit()
    names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='fingerprints'"
        )
    }
    connection.close()
    assert "idx_fingerprints_entity" in names


def test_the_scratch_table_does_not_survive_the_migration(v1_database):
    """`fingerprints_v2` is scaffolding; leaving it behind would double storage."""
    connection = sqlite3.connect(v1_database)
    migrations.apply_migrations(connection)
    connection.commit()
    names = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    connection.close()
    assert "fingerprints_v2" not in names
    assert "fingerprints" in names


def test_the_store_migrates_a_v1_database_when_it_opens_it(v1_database):
    """The path a teammate actually takes: open an old database and keep working.

    Nobody calls `apply_migrations` by hand. What happens is that Person B or C
    opens a database written before the bump, and it either works or it does
    not.
    """
    store = ProvenanceStore(v1_database)
    try:
        assert store.schema_version() == migrations.CURRENT_VERSION
        assert len(store.get_fingerprints_for("e1")) == 3
        assert store.get_latest_fingerprint("e1", "file")["hash_value"] == "bbb"
    finally:
        store.close()


def test_a_database_from_the_future_is_refused_rather_than_read(v1_database):
    """Appendix B.6's actual purpose: fail loudly, do not read moved columns."""
    connection = sqlite3.connect(v1_database)
    migrations.set_version(connection, migrations.CURRENT_VERSION + 5)
    connection.commit()
    with pytest.raises(migrations.SchemaVersionError):
        migrations.apply_migrations(connection)
    connection.close()
