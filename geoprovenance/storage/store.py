"""ProvenanceStore — the CRUD API that Person B and Person C both build against.

Owner: Person A.  Sub-phase: A2.

    RULES.md §4.1 [HARD] — NO QGIS IMPORTS IN THIS FILE. Standard library only.
    Enforced by tests/storage/test_no_qgis_imports.py.

    RULES.md §1.3 — B and C never write SQL. If they need a query that isn't
    here, Person A adds the method. RULES.md §1.5 — these signatures are public
    API; renaming one is a breaking change.

Required behaviour
    §4.2  Every connection: PRAGMA foreign_keys = ON, PRAGMA journal_mode = WAL.
          WAL is required because C's audit reads while the engine writes.
    §4.3  ``with store.transaction():`` — one algorithm execution is ONE atomic
          transaction. An activities row with no relations silently corrupts C's
          graph traversal and is worse than capturing nothing.
    §4.4  Constructor creates the DB on first use, applies schema.sql, sets
          user_version. Safe to call against an existing DB.
    §4.7  Thread safety MUST be decided, implemented, and its reason documented
          here — QGIS may run algorithms off the main thread. Either
          check_same_thread=False + a lock, or a connection per thread.
          Not deciding is not an option.
    §4.9  All ids are UUID4 strings generated in Python. Never rowid.

Required method surface (§4.5) — B and C build against exactly these:
    add_entity, add_activity, add_agent, add_fingerprint, add_relation,
    get_or_create_agent, find_entity_by_path, get_activity, get_relations_for,
    list_workflows, get_workflow_graph

TODO(A2): implement. Done when 15+ tests pass with no QGIS import at all.
"""

from __future__ import annotations

SCHEMA_FILENAME = "schema.sql"
SCHEMA_VERSION = 1  # keep in sync with PRAGMA user_version in schema.sql


class ProvenanceStore:
    """TODO(A2)."""

    def __init__(self, db_path):
        raise NotImplementedError("A2")
