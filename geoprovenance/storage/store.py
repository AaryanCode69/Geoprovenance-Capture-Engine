"""ProvenanceStore — the CRUD API that Person B and Person C both build against.

Owner: Person A.  Sub-phase: A2.

    RULES.md §4.1 [HARD] — NO QGIS IMPORTS IN THIS FILE. Standard library only.
    Enforced by tests/storage/test_no_qgis_imports.py.

    RULES.md §1.3 — B and C never write SQL. They call these methods. If a query
    they need is missing, Person A adds it here.
    RULES.md §1.5 — every public signature below is API. Renaming one is a
    breaking change and follows §3.4.

Everything returns plain ``dict`` rows, never ``sqlite3.Row``, so Person B can
hand results straight to ``json.dumps`` and Person C never has to import
``sqlite3`` to read a field.


Thread safety — the §4.7 decision, and why
------------------------------------------
QGIS may run algorithms off the main thread, so the store must survive being
called from more than one.

    DECISION: one connection per thread (``threading.local``), plus a process-wide
    re-entrant lock held for the duration of every write transaction.

Rationale. A ``sqlite3.Connection`` is not safe to share between threads, and
``check_same_thread=False`` only silences the check — it does not make
concurrent use correct. A connection per thread is correct by construction and
lets readers proceed in parallel, which matters because WAL (§4.2) allows many
readers alongside one writer: Person C's audit reads while the capture engine
writes.

The lock exists because WAL permits exactly ONE writer. Without it, two capture
threads would race and the loser would get ``SQLITE_BUSY`` mid-transaction.
Serialising our own writers in-process is cheaper and more predictable than
retrying on a busy timeout. The ``busy_timeout`` is still set, to cover writers
outside this process (another QGIS instance on the same file).

Consequence: an in-memory database cannot be used, because each thread would
silently get its OWN empty database. The constructor rejects ``:memory:``
rather than let that become a two-hour debugging session.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import pathlib
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Sequence

from . import migrations

SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = migrations.CURRENT_VERSION

#: Appendix B.2 — lowercase only. The original QGIS key goes in qgis_param_key.
VALID_ROLES = ("input", "output", "overlay", "parameter")

#: The five PROV relationships we model (research doc §7.2).
VALID_RELATION_TYPES = (
    "wasGeneratedBy",
    "used",
    "wasDerivedFrom",
    "wasAssociatedWith",
    "wasAttributedTo",
)

#: §4.10 — failed and cancelled runs are stored, never dropped.
VALID_STATUSES = ("completed", "failed", "cancelled")


class StoreError(RuntimeError):
    """Something was asked of the store that the contract does not allow."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Microsecond-precision UTC ISO 8601 (RULES.md §3.2 decision 4).

    ``timespec="microseconds"`` is not optional. Plain ``.isoformat()`` drops the
    fractional part when it happens to be zero, which produces a timestamp that
    fails the event schema's pattern AND collides under
    ``fingerprints UNIQUE(entity_id, computed_at)``.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id() -> str:
    """A UUID4 string. RULES.md §4.9 — never rowid, never autoincrement."""
    return str(uuid.uuid4())


def _json_or_none(value: Any) -> str | None:
    """Accept a dict/list and serialise it, pass a string through, keep None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _placeholders(values: Sequence[Any]) -> str:
    return ",".join("?" * len(values))


def environment_fingerprint(
    qgis_version: str | None,
    os_info: str | None,
    python_version: str | None,
    plugin_versions: Any = None,
) -> str:
    """Stable digest of one environment, for agent de-duplication (§4.6).

    NOT dataset fingerprinting — that is Person B's (§1.2). This is a dictionary
    digest used purely as a de-duplication key, so that one `agents` row is
    reused across every activity run in the same environment. Writing one agent
    row per execution would inflate our own RQ2 storage numbers (§8.6).
    """
    payload = json.dumps(
        {
            "qgis_version": qgis_version,
            "os_info": os_info,
            "python_version": python_version,
            "plugin_versions": plugin_versions,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# the store
# --------------------------------------------------------------------------

class ProvenanceStore:
    """Read/write access to the provenance database.

    >>> store = ProvenanceStore("/tmp/prov.db")
    >>> with store.transaction():
    ...     activity_id = store.add_activity(algorithm_id="native:buffer",
    ...                                      started_at=utc_now_iso())
    """

    def __init__(self, db_path: str | pathlib.Path, busy_timeout: float = 30.0):
        if str(db_path) in (":memory:", ""):
            raise ValueError(
                "ProvenanceStore needs a file path, not an in-memory database. "
                "It keeps one connection per thread (see the module docstring), "
                "so each thread would get its own empty in-memory database. "
                "In tests use pytest's tmp_path fixture."
            )
        self.db_path = pathlib.Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout = busy_timeout
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._closed = False

        # Apply schema / migrations once, on the creating thread.
        self._initialise(self._connection())

    # -- connection management ---------------------------------------------

    def _connection(self) -> sqlite3.Connection:
        """The calling thread's connection, opened on first use."""
        if self._closed:
            raise StoreError("ProvenanceStore is closed")
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self._busy_timeout,
                # isolation_level=None turns OFF the sqlite3 module's implicit
                # transaction handling, so transaction() below controls BEGIN /
                # COMMIT / ROLLBACK explicitly. §4.3 needs exact boundaries.
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            # §4.2 [HARD]. foreign_keys is per-connection and must be set every
            # time; journal_mode is persisted in the file but is cheap to repeat.
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout * 1000)}")
            self._local.conn = conn
            self._local.depth = 0
        return conn

    def _initialise(self, conn: sqlite3.Connection) -> None:
        """Create the schema on a fresh file, or migrate an existing one (§4.4)."""
        has_tables = (
            conn.execute(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type='table' AND name='activities'"
            ).fetchone()[0]
            > 0
        )
        version = migrations.get_version(conn)

        if not has_tables:
            conn.executescript(SCHEMA_PATH.read_text())
        elif version == 0:
            raise migrations.SchemaVersionError(
                f"{self.db_path} has tables but no schema version. It predates "
                f"versioning and cannot be migrated safely. See RULES.md §3.4."
            )

        migrations.apply_migrations(conn)

    def close(self) -> None:
        """Close this thread's connection. Safe to call more than once."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
        self._closed = True

    def __enter__(self) -> "ProvenanceStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- transactions ------------------------------------------------------

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One algorithm execution is one atomic transaction (RULES.md §4.3).

        An ``activities`` row with no ``relations`` silently corrupts Person C's
        graph traversal, and is worse than having captured nothing at all — so
        either the whole execution lands or none of it does.

        Nesting is supported via SAVEPOINTs, because the capture engine composes
        smaller writes inside one outer execution boundary. Only the outermost
        block commits.
        """
        conn = self._connection()
        with self._write_lock:
            depth = getattr(self._local, "depth", 0)
            if depth == 0:
                # BEGIN IMMEDIATE takes the write lock now rather than on first
                # write, so two writers fail fast instead of halfway through.
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute(f"SAVEPOINT sp_{depth}")
            self._local.depth = depth + 1

            try:
                yield conn
            except BaseException:
                if depth == 0:
                    conn.execute("ROLLBACK")
                else:
                    conn.execute(f"ROLLBACK TO sp_{depth}")
                    conn.execute(f"RELEASE sp_{depth}")
                raise
            else:
                if depth == 0:
                    conn.execute("COMMIT")
                else:
                    conn.execute(f"RELEASE sp_{depth}")
            finally:
                self._local.depth = depth

    def _write(self, sql: str, params: Sequence[Any]) -> None:
        """Execute a write, wrapping it in a transaction if not already in one."""
        if getattr(self._local, "depth", 0) > 0:
            self._connection().execute(sql, params)
        else:
            with self.transaction() as conn:
                conn.execute(sql, params)

    # -- entities ----------------------------------------------------------

    def add_entity(
        self,
        *,
        entity_type: str = "dataset",
        label: str | None = None,
        file_path: str | None = None,
        content_version: int = 1,
        format: str | None = None,  # noqa: A002 — matches the schema column name
        crs: str | None = None,
        layer_type: str | None = None,
        metadata: Any = None,
        entity_id: str | None = None,
        created_at: str | None = None,
    ) -> str:
        """Insert a dataset row and return its id.

        Appendix B.1 — identity is ``(file_path, content_version)``. A file
        rewritten with different content gets a NEW row with a bumped
        ``content_version``, never an update in place; that is what lets the
        graph distinguish "the file before" from "the file after".

        ``file_path=None`` is correct and expected for memory / temporary /
        ``/vsimem/`` layers (§3.3); ``layer_type`` is still set so Person B knows
        not to try to fingerprint them.
        """
        entity_id = entity_id or new_id()
        self._write(
            "INSERT INTO entities (id, entity_type, label, file_path, "
            "content_version, format, crs, layer_type, created_at, metadata_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                entity_id,
                entity_type,
                label,
                file_path,
                content_version,
                format,
                crs,
                layer_type,
                created_at or utc_now_iso(),
                _json_or_none(metadata),
            ),
        )
        return entity_id

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        return _row_to_dict(
            self._connection()
            .execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
            .fetchone()
        )

    def find_entity_by_path(
        self, file_path: str, content_version: int | None = None
    ) -> dict[str, Any] | None:
        """The entity for a path. Defaults to the LATEST content version.

        Person C's "does this input still exist?" check and Person B's
        derivation inference both want the newest version unless they say
        otherwise.
        """
        conn = self._connection()
        if content_version is None:
            row = conn.execute(
                "SELECT * FROM entities WHERE file_path = ? "
                "ORDER BY content_version DESC LIMIT 1",
                (file_path,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM entities WHERE file_path = ? AND content_version = ?",
                (file_path, content_version),
            ).fetchone()
        return _row_to_dict(row)

    def list_entity_versions(self, file_path: str) -> list[dict[str, Any]]:
        """Every recorded version of one path, oldest first."""
        return _rows_to_dicts(
            self._connection().execute(
                "SELECT * FROM entities WHERE file_path = ? ORDER BY content_version",
                (file_path,),
            )
        )

    def next_content_version(self, file_path: str) -> int:
        """The content version a NEW version of ``file_path`` would take.

        Mechanism only. The *policy* — when a bump is warranted — is decision 1
        in docs/CONTRACT_schema.md, closed 18 Aug 2026: the version moves when a
        size + mtime probe disagrees with what was recorded for that path. It
        lives in capture/engine.py, where the filesystem is in reach; keeping it
        out of here is what lets storage/ import zero QGIS and stay pure (§4.1).

        Deliberately not implicit: add_entity never auto-bumps. A caller that
        wants a new version asks for one, so the decision is always visible at
        the call site rather than hidden in an insert.

        Person B: do not call this to correct a version after fingerprinting.
        A hash that disagrees with the previous version is an audit finding for
        Person C, not a correction to the record (§1.2).
        """
        row = self._connection().execute(
            "SELECT max(content_version) FROM entities WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return 1 if row[0] is None else int(row[0]) + 1

    # -- activities --------------------------------------------------------

    def add_activity(
        self,
        *,
        algorithm_id: str,
        started_at: str,
        algorithm_name: str | None = None,
        provider: str | None = None,
        session_id: str | None = None,
        ended_at: str | None = None,
        parameters: Any = None,
        status: str = "completed",
        execution_log: str | None = None,
        capture_channel: str | None = None,
        dedup_key: str | None = None,
        activity_id: str | None = None,
    ) -> str:
        """Insert a job-run row and return its id.

        §4.10 — ``status='failed'`` and ``status='cancelled'`` are first-class.
        Person C's audit needs them and RQ1 completeness counts them, so a
        failed run is recorded, never dropped.
        """
        if status not in VALID_STATUSES:
            raise StoreError(
                f"status must be one of {VALID_STATUSES}, got {status!r} (§4.10)"
            )
        activity_id = activity_id or new_id()
        self._write(
            "INSERT INTO activities (id, algorithm_id, algorithm_name, provider, "
            "session_id, started_at, ended_at, parameters_json, status, "
            "execution_log, capture_channel, corroborations, dedup_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)",
            (
                activity_id,
                algorithm_id,
                algorithm_name,
                provider,
                session_id,
                started_at,
                ended_at,
                _json_or_none(parameters) or "{}",
                status,
                execution_log,
                capture_channel,
                dedup_key,
            ),
        )
        return activity_id

    def get_activity(self, activity_id: str) -> dict[str, Any] | None:
        return _row_to_dict(
            self._connection()
            .execute("SELECT * FROM activities WHERE id = ?", (activity_id,))
            .fetchone()
        )

    def find_activity_by_dedup_key(self, dedup_key: str) -> dict[str, Any] | None:
        """Has this execution already been recorded by the other channel? (§5.9)"""
        return _row_to_dict(
            self._connection()
            .execute("SELECT * FROM activities WHERE dedup_key = ?", (dedup_key,))
            .fetchone()
        )

    def increment_corroboration(self, activity_id: str) -> int:
        """Record that the second channel also saw this execution (§5.9).

        First channel wins and inserts; the second one lands here instead. The
        counter is not bookkeeping — the hook-vs-history split is a reportable
        RQ1 result (§8.3), so it has to be persisted as it happens.
        """
        self._write(
            "UPDATE activities SET corroborations = corroborations + 1 WHERE id = ?",
            (activity_id,),
        )
        row = self._connection().execute(
            "SELECT corroborations FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"no activity {activity_id!r}")
        return int(row[0])

    def list_activities_for_session(self, session_id: str) -> list[dict[str, Any]]:
        """Every job run in one QGIS session, oldest first (Appendix B.5).

        This is what A6's workflow auto-grouping consumes.
        """
        return _rows_to_dicts(
            self._connection().execute(
                "SELECT * FROM activities WHERE session_id = ? ORDER BY started_at",
                (session_id,),
            )
        )

    # -- agents ------------------------------------------------------------

    def add_agent(
        self,
        *,
        agent_type: str = "software",
        label: str | None = None,
        qgis_version: str | None = None,
        os_info: str | None = None,
        python_version: str | None = None,
        plugin_versions: Any = None,
        agent_id: str | None = None,
        env_fingerprint: str | None = None,
        created_at: str | None = None,
    ) -> str:
        agent_id = agent_id or new_id()
        self._write(
            "INSERT INTO agents (id, agent_type, label, qgis_version, os_info, "
            "python_version, plugin_versions_json, created_at, env_fingerprint) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                agent_id,
                agent_type,
                label,
                qgis_version,
                os_info,
                python_version,
                _json_or_none(plugin_versions),
                created_at or utc_now_iso(),
                env_fingerprint,
            ),
        )
        return agent_id

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        return _row_to_dict(
            self._connection()
            .execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
            .fetchone()
        )

    def get_or_create_agent(
        self,
        *,
        qgis_version: str | None = None,
        os_info: str | None = None,
        python_version: str | None = None,
        plugin_versions: Any = None,
        label: str | None = None,
        agent_type: str = "software",
        created_at: str | None = None,
    ) -> str:
        """One agent row per DISTINCT environment, reused across activities (§4.6).

        Writing a fresh agent row per execution would inflate our own RQ2
        storage-per-operation numbers with a bug of our own making (§8.6).
        """
        fingerprint = environment_fingerprint(
            qgis_version, os_info, python_version, plugin_versions
        )
        existing = self._connection().execute(
            "SELECT id FROM agents WHERE env_fingerprint = ?", (fingerprint,)
        ).fetchone()
        if existing is not None:
            return str(existing[0])
        return self.add_agent(
            agent_type=agent_type,
            label=label or (f"QGIS {qgis_version}" if qgis_version else None),
            qgis_version=qgis_version,
            os_info=os_info,
            python_version=python_version,
            plugin_versions=plugin_versions,
            env_fingerprint=fingerprint,
            created_at=created_at,
        )

    # -- fingerprints (Person B writes these THROUGH here — §1.3) -----------

    def add_fingerprint(
        self,
        *,
        entity_id: str,
        hash_value: str,
        hash_algorithm: str = "SHA-256",
        hash_strategy: str | None = None,
        file_size_bytes: int | None = None,
        feature_count: int | None = None,
        computed_at: str | None = None,
        fingerprint_id: str | None = None,
    ) -> str:
        """Record a dataset fingerprint. Person B computes it; Person A stores it.

        ``computed_at`` MUST be microsecond precision — the table declares
        ``UNIQUE(entity_id, computed_at)`` and B hashes input and output inside
        the same second (Appendix B.4). Defaults to a correct value.
        """
        fingerprint_id = fingerprint_id or new_id()
        self._write(
            "INSERT INTO fingerprints (id, entity_id, hash_algorithm, hash_value, "
            "hash_strategy, file_size_bytes, feature_count, computed_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                fingerprint_id,
                entity_id,
                hash_algorithm,
                hash_value,
                hash_strategy,
                file_size_bytes,
                feature_count,
                computed_at or utc_now_iso(),
            ),
        )
        return fingerprint_id

    def get_fingerprints_for(self, entity_id: str) -> list[dict[str, Any]]:
        """Every fingerprint recorded for one dataset, oldest first."""
        return _rows_to_dicts(
            self._connection().execute(
                "SELECT * FROM fingerprints WHERE entity_id = ? ORDER BY computed_at",
                (entity_id,),
            )
        )

    def get_latest_fingerprint(self, entity_id: str) -> dict[str, Any] | None:
        """The most recent fingerprint — Person C's "has this changed?" check."""
        return _row_to_dict(
            self._connection().execute(
                "SELECT * FROM fingerprints WHERE entity_id = ? "
                "ORDER BY computed_at DESC LIMIT 1",
                (entity_id,),
            ).fetchone()
        )

    # -- relations (Person B writes these THROUGH here — §1.3) --------------

    def add_relation(
        self,
        *,
        relation_type: str,
        source_id: str,
        target_id: str,
        role: str | None = None,
        qgis_param_key: str | None = None,
        relation_id: str | None = None,
        created_at: str | None = None,
    ) -> str:
        """Link two nodes.

        Appendix B.2 — ``role`` is lowercase, from VALID_ROLES. The original QGIS
        parameter key (``OVERLAY``, ``INPUT``) goes in ``qgis_param_key``
        unmodified. Validated here with a readable message rather than left to
        the CHECK constraint, because Person B hits this one first.
        """
        if relation_type not in VALID_RELATION_TYPES:
            raise StoreError(
                f"relation_type must be one of {VALID_RELATION_TYPES}, "
                f"got {relation_type!r}"
            )
        if role is not None and role not in VALID_ROLES:
            raise StoreError(
                f"role must be lowercase, one of {VALID_ROLES}, got {role!r}. "
                f"The original QGIS key (e.g. 'OVERLAY') goes in qgis_param_key "
                f"— see docs/CONTRACT_schema.md decision 2."
            )
        relation_id = relation_id or new_id()
        self._write(
            "INSERT INTO relations (id, relation_type, source_id, target_id, "
            "role, qgis_param_key, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                relation_id,
                relation_type,
                source_id,
                target_id,
                role,
                qgis_param_key,
                created_at or utc_now_iso(),
            ),
        )
        return relation_id

    def get_relations_for(
        self, node_id: str, direction: str = "both"
    ) -> list[dict[str, Any]]:
        """Relations touching ``node_id``.

        ``direction``: ``'out'`` (node is source), ``'in'`` (node is target), or
        ``'both'``. Person C's traversal walks backwards from an output, so
        ``'in'`` and ``'out'`` are both hot paths — hence the indices in
        Appendix B.3.
        """
        conn = self._connection()
        if direction == "out":
            sql, params = "SELECT * FROM relations WHERE source_id = ?", (node_id,)
        elif direction == "in":
            sql, params = "SELECT * FROM relations WHERE target_id = ?", (node_id,)
        elif direction == "both":
            sql = "SELECT * FROM relations WHERE source_id = ? OR target_id = ?"
            params = (node_id, node_id)
        else:
            raise StoreError(f"direction must be 'in', 'out' or 'both', got {direction!r}")
        return _rows_to_dicts(conn.execute(sql, params))

    # -- workflows ---------------------------------------------------------

    def add_workflow(
        self,
        *,
        name: str,
        description: str | None = None,
        session_id: str | None = None,
        workflow_id: str | None = None,
        created_at: str | None = None,
    ) -> str:
        workflow_id = workflow_id or new_id()
        now = created_at or utc_now_iso()
        self._write(
            "INSERT INTO workflows (id, name, description, session_id, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (workflow_id, name, description, session_id, now, now),
        )
        return workflow_id

    def add_workflow_activity(
        self, *, workflow_id: str, activity_id: str, sequence_order: int
    ) -> None:
        """Place an activity in a workflow at a given position (§5.12).

        Ordering is temporal, by ``started_at``. Person B independently infers
        ``wasDerivedFrom`` from data flow — a different job; do not conflate them.
        """
        self._write(
            "INSERT INTO workflow_activities (workflow_id, activity_id, sequence_order) "
            "VALUES (?,?,?)",
            (workflow_id, activity_id, sequence_order),
        )

    def set_workflow_activities(
        self, *, workflow_id: str, activity_ids: Sequence[str]
    ) -> None:
        """Replace a workflow's membership with ``activity_ids``, in that order.

        Idempotent, which add_workflow_activity is not — the primary key is
        ``(workflow_id, activity_id)``, so re-running the grouping over a
        session would otherwise fail on the second pass. A6's grouping is a
        recomputation, not an append, so it needs the replacing form.

        ``sequence_order`` is the position in the sequence given. The caller
        orders by ``started_at`` (§5.12); this method does not reorder, because
        the temporal decision belongs with the grouping logic and not in SQL.
        """
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM workflow_activities WHERE workflow_id = ?", (workflow_id,)
            )
            conn.executemany(
                "INSERT INTO workflow_activities "
                "(workflow_id, activity_id, sequence_order) VALUES (?,?,?)",
                [(workflow_id, aid, order) for order, aid in enumerate(activity_ids)],
            )
            conn.execute(
                "UPDATE workflows SET updated_at = ? WHERE id = ?",
                (utc_now_iso(), workflow_id),
            )

    def update_workflow(
        self,
        workflow_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Rename or re-describe a workflow. Backs A6's "Name this workflow".

        Only the fields given are touched, so naming a workflow cannot wipe
        its description. Always moves ``updated_at`` — before this, that column
        was written once at insert and never again, which made it a lie.
        """
        fields: list[str] = []
        values: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if description is not None:
            fields.append("description = ?")
            values.append(description)
        if not fields:
            return

        fields.append("updated_at = ?")
        values.extend([utc_now_iso(), workflow_id])
        self._write(f"UPDATE workflows SET {', '.join(fields)} WHERE id = ?", tuple(values))

    def delete_workflow(self, workflow_id: str) -> None:
        """Remove a workflow. Its membership rows cascade; activities survive.

        Used when A6's grouping merges two workflows and one is left empty.
        The activities themselves are never deleted — they are the record.
        """
        self._write("DELETE FROM workflows WHERE id = ?", (workflow_id,))

    def find_workflows_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Workflows grouped out of one QGIS session, oldest first.

        Oldest first because A6's merge policy keeps the oldest workflow of an
        overlapping set, so that a name the user already gave one survives a
        later regrouping.
        """
        return _rows_to_dicts(
            self._connection().execute(
                "SELECT * FROM workflows WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )
        )

    def list_session_datasets(self, session_id: str) -> list[dict[str, Any]]:
        """(activity_id, file_path) for every dataset touched in one session.

        The input to A6's grouping: two activities that touch a common path
        belong to the same workflow. One query rather than a
        ``get_relations_for`` per activity, because a 15-operation workflow
        would otherwise be 15 round trips inside the user's QGIS session.

        Direction is deliberately NOT returned. Grouping asks "are these
        connected?", which is undirected; Person B separately infers *directed*
        ``wasDerivedFrom`` edges from the same paths (§5.12). Handing direction
        to the grouper would invite it to quietly become B's job.
        """
        return _rows_to_dicts(
            self._connection().execute(
                "SELECT DISTINCT a.id AS activity_id, e.file_path AS file_path "
                "FROM activities a "
                "JOIN relations r ON r.source_id = a.id OR r.target_id = a.id "
                "JOIN entities e ON e.id = r.source_id OR e.id = r.target_id "
                "WHERE a.session_id = ? AND e.file_path IS NOT NULL "
                "AND r.relation_type IN ('used', 'wasGeneratedBy')",
                (session_id,),
            )
        )

    def list_session_workflow_members(self, session_id: str) -> list[dict[str, Any]]:
        """(workflow_id, activity_id) for every workflow grouped from a session.

        A6 regroups a whole session at once and has to reconcile what it
        computes against what is already stored, so it needs the existing
        membership in one query rather than one per workflow.
        """
        return _rows_to_dicts(
            self._connection().execute(
                "SELECT wa.workflow_id, wa.activity_id, wa.sequence_order "
                "FROM workflow_activities wa "
                "JOIN workflows w ON w.id = wa.workflow_id "
                "WHERE w.session_id = ? ORDER BY wa.sequence_order",
                (session_id,),
            )
        )

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        return _row_to_dict(
            self._connection()
            .execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
            .fetchone()
        )

    def list_workflows(self) -> list[dict[str, Any]]:
        """All workflows, newest first, each with its step count."""
        return _rows_to_dicts(
            self._connection().execute(
                "SELECT w.*, count(wa.activity_id) AS activity_count "
                "FROM workflows w "
                "LEFT JOIN workflow_activities wa ON wa.workflow_id = w.id "
                "GROUP BY w.id ORDER BY w.created_at DESC"
            )
        )

    def get_workflow_graph(self, workflow_id: str) -> dict[str, Any]:
        """Everything Person C needs to draw and audit one workflow, in one call.

        Returns ``{workflow, activities, entities, agents, relations}`` where
        ``activities`` is ordered by ``sequence_order``. One method rather than
        five round trips, because §1.3 says C never writes SQL and C should not
        have to assemble a graph out of fragments either.
        """
        conn = self._connection()
        workflow = self.get_workflow(workflow_id)
        if workflow is None:
            raise StoreError(f"no workflow {workflow_id!r}")

        activities = _rows_to_dicts(
            conn.execute(
                "SELECT a.*, wa.sequence_order FROM activities a "
                "JOIN workflow_activities wa ON wa.activity_id = a.id "
                "WHERE wa.workflow_id = ? "
                "ORDER BY wa.sequence_order, a.started_at",
                (workflow_id,),
            )
        )
        activity_ids = [a["id"] for a in activities]
        if not activity_ids:
            return {
                "workflow": workflow,
                "activities": [],
                "entities": [],
                "agents": [],
                "relations": [],
            }

        marks = _placeholders(activity_ids)
        relations = _rows_to_dicts(
            conn.execute(
                f"SELECT * FROM relations "
                f"WHERE source_id IN ({marks}) OR target_id IN ({marks})",
                (*activity_ids, *activity_ids),
            )
        )

        # Whatever is on the other end of those relations and is a dataset.
        touched = {r["source_id"] for r in relations} | {r["target_id"] for r in relations}
        candidates = list(touched - set(activity_ids))
        entities: list[dict[str, Any]] = []
        agents: list[dict[str, Any]] = []
        if candidates:
            marks_c = _placeholders(candidates)
            entities = _rows_to_dicts(
                conn.execute(
                    f"SELECT * FROM entities WHERE id IN ({marks_c})", candidates
                )
            )
            agents = _rows_to_dicts(
                conn.execute(
                    f"SELECT * FROM agents WHERE id IN ({marks_c})", candidates
                )
            )

        # Dataset-to-dataset links (wasDerivedFrom) sit between two entities, so
        # the activity-anchored query above misses them.
        entity_ids = [e["id"] for e in entities]
        if entity_ids:
            marks_e = _placeholders(entity_ids)
            seen = {r["id"] for r in relations}
            extra = _rows_to_dicts(
                conn.execute(
                    f"SELECT * FROM relations "
                    f"WHERE source_id IN ({marks_e}) AND target_id IN ({marks_e})",
                    (*entity_ids, *entity_ids),
                )
            )
            relations.extend(r for r in extra if r["id"] not in seen)

        return {
            "workflow": workflow,
            "activities": activities,
            "entities": entities,
            "agents": agents,
            "relations": relations,
        }

    # -- audit results (Person C writes these THROUGH here — §1.3) ----------

    def add_audit_result(
        self,
        *,
        workflow_id: str,
        overall_score: float,
        input_exists_score: float | None = None,
        input_unchanged_score: float | None = None,
        algorithm_available_score: float | None = None,
        environment_similar_score: float | None = None,
        parameters_valid_score: float | None = None,
        details: Any = None,
        audited_at: str | None = None,
        audit_id: str | None = None,
    ) -> str:
        """Store one reproducibility audit run.

        The five component weights and how the scores are computed are Person
        C's (§1.2, research doc §4.3 Layer 5). The table and this writer are
        Person A's.
        """
        audit_id = audit_id or new_id()
        self._write(
            "INSERT INTO audit_results (id, workflow_id, audited_at, overall_score, "
            "input_exists_score, input_unchanged_score, algorithm_available_score, "
            "environment_similar_score, parameters_valid_score, details_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                audit_id,
                workflow_id,
                audited_at or utc_now_iso(),
                overall_score,
                input_exists_score,
                input_unchanged_score,
                algorithm_available_score,
                environment_similar_score,
                parameters_valid_score,
                _json_or_none(details),
            ),
        )
        return audit_id

    def list_audit_results(self, workflow_id: str) -> list[dict[str, Any]]:
        """Audit history for one workflow, newest first."""
        return _rows_to_dicts(
            self._connection().execute(
                "SELECT * FROM audit_results WHERE workflow_id = ? "
                "ORDER BY audited_at DESC",
                (workflow_id,),
            )
        )

    # -- introspection -----------------------------------------------------

    def schema_version(self) -> int:
        return migrations.get_version(self._connection())

    def channel_statistics(self) -> dict[str, dict[str, int]]:
        """Per-channel capture split — the RQ1 result from §5.9 and §8.3.

        ``{"post_hook": {"first": 47, "corroborations": 3}, ...}`` where
        *first* is how many executions that channel was the first to see (it
        won the race and inserted the row) and *corroborations* is how many
        times a LATER channel confirmed one of those same executions.

        This is the query behind "the hook caught 98%, the history channel
        caught the other 2%" — §5.9 says keep that counter and report it,
        because it is a genuine finding rather than bookkeeping.

        Note what corroborations does NOT tell you: which channel did the
        confirming. The schema counts confirmations per activity, not per
        confirming channel, and adding that would be a §3.4 breaking change
        for a number the RQ1 protocol does not ask for (§8.3 wants the
        first-to-see split, which `first` is).
        """
        rows = self._connection().execute(
            "SELECT coalesce(capture_channel, 'unknown') AS channel, "
            "count(*) AS first, coalesce(sum(corroborations), 0) AS corroborations "
            "FROM activities GROUP BY channel ORDER BY channel"
        ).fetchall()
        return {
            row["channel"]: {
                "first": int(row["first"]),
                "corroborations": int(row["corroborations"]),
            }
            for row in rows
        }

    def counts(self) -> dict[str, int]:
        """Row count per table — used by the RQ2 storage measurement (§8.6)."""
        conn = self._connection()
        tables = (
            "entities", "activities", "agents", "fingerprints",
            "relations", "workflows", "workflow_activities", "audit_results",
        )
        return {
            t: int(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
            for t in tables
        }
