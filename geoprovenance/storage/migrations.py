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
CURRENT_VERSION = 1

#: version -> SQL statements taking the database from (version - 1) to version.
#: v1 is the baseline and is created directly from schema.sql, so it is empty.
MIGRATIONS: dict[int, list[str]] = {
    1: [],
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
