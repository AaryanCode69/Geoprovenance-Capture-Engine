"""Schema migrations, versioned by ``PRAGMA user_version``.

Owner: Person A.  Sub-phase: A2.  RULES.md §4.1 — no QGIS imports.

Why this exists on day one (Appendix B.6)
    The schema WILL change in Phase 2 — that is when contract mismatches
    surface, and expecting otherwise is the mistake. With a version and a
    migration path, Person B's and Person C's fixture databases fail loudly
    with a version mismatch instead of breaking silently.

Changing the schema after `contract-v1` is tagged requires ALL FIVE steps in
RULES.md §3.4, in one change:
    1. Bump user_version here and add the forward migration.
    2. Update docs/CONTRACT_schema.md with a dated changelog entry.
    3. Re-run  python tests/fixtures/build_fixtures.py
    4. Verify Person A's tests still pass.
    5. TELL B AND C what broke and what they must change.

Silent contract drift is the failure mode that costs the most time in Phase 2.

TODO(A2): implement apply_migrations(conn) and the MIGRATIONS registry.
"""

CURRENT_VERSION = 1

# version -> list of SQL statements taking the DB from (version - 1) to version.
MIGRATIONS: dict[int, list[str]] = {
    1: [],  # v1 is the baseline; created directly from schema.sql.
}
