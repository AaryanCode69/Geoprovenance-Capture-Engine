"""ProvenanceStore — the A2 storage suite.

RULES.md §6.1, §6.2 — runs with NO QGIS, 15+ tests required by end of A2.
Every test names the rule it defends, so a future change that breaks one is
told immediately what it broke and why the rule exists.

    make test-storage
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading

import pytest

from geoprovenance.storage import migrations
from geoprovenance.storage.store import (
    ProvenanceStore,
    StoreError,
    environment_fingerprint,
    new_id,
    utc_now_iso,
)

MICROSECOND_ISO = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}([+-]\d{2}:\d{2}|Z)$"
)


# ===========================================================================
# §4.4 / §4.2 — initialisation and connection pragmas
# ===========================================================================

def test_creates_database_file_on_first_use(db_path):
    """§4.4 — the constructor creates the DB; callers never run DDL."""
    assert not db_path.exists()
    store = ProvenanceStore(db_path)
    assert db_path.exists()
    store.close()


def test_applies_full_schema(store):
    """§4.4 — all eight contract tables exist after construction."""
    rows = store._connection().execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    assert {
        "entities", "activities", "agents", "fingerprints",
        "relations", "workflows", "workflow_activities", "audit_results",
    } <= names


def test_sets_schema_version(store):
    """Appendix B.6 — a versioned database, from day one."""
    assert store.schema_version() == migrations.CURRENT_VERSION == 1


def test_creates_required_indices(store):
    """Appendix B.3 — indices are mandatory, not an optimisation.

    Without them C's reverse lookups are slow on Workflow C, and our own RQ2
    numbers look worse than the design deserves.
    """
    rows = store._connection().execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert {
        "idx_relations_source", "idx_relations_target", "idx_relations_type",
        "idx_entities_path", "idx_fingerprints_entity", "idx_wf_activities_wf",
    } <= names


def test_journal_mode_is_wal(store):
    """§4.2 [HARD] — C's audit reads while the capture engine writes."""
    mode = store._connection().execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_foreign_keys_are_enforced(store):
    """§4.2 [HARD] — a fingerprint for a non-existent dataset must not land."""
    assert store._connection().execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        store.add_fingerprint(entity_id="does-not-exist", hash_value="abc")


def test_reopening_preserves_data(db_path):
    """§4.4 — construction is safe against an existing database."""
    first = ProvenanceStore(db_path)
    entity_id = first.add_entity(label="roads.shp", file_path="/data/roads.shp")
    first.close()

    second = ProvenanceStore(db_path)
    assert second.get_entity(entity_id)["label"] == "roads.shp"
    assert second.schema_version() == 1
    second.close()


def test_rejects_in_memory_database(tmp_path):
    """The store keeps one connection per thread, so :memory: would silently
    give each thread its own empty database. Fail loudly instead."""
    with pytest.raises(ValueError, match="file path"):
        ProvenanceStore(":memory:")


def test_refuses_database_from_a_newer_schema(db_path):
    """Appendix B.6 — a stale checkout must fail loudly, not read moved columns."""
    store = ProvenanceStore(db_path)
    store._connection().execute("PRAGMA user_version = 99")
    store.close()

    with pytest.raises(migrations.SchemaVersionError, match="version 99"):
        ProvenanceStore(db_path)


# ===========================================================================
# §3.2 decision 4 — timestamps
# ===========================================================================

def test_timestamps_are_microsecond_precision():
    """Appendix B.4 — second resolution collides under
    fingerprints UNIQUE(entity_id, computed_at)."""
    assert MICROSECOND_ISO.match(utc_now_iso())


def test_two_fingerprints_in_the_same_second_both_land(store):
    """Appendix B.4, the actual failure it prevents: Person B hashes an input
    and an output inside the same tick."""
    entity = store.add_entity(file_path="/data/roads.shp")
    with store.transaction():
        store.add_fingerprint(entity_id=entity, hash_value="aaa")
        store.add_fingerprint(entity_id=entity, hash_value="bbb")
    assert len(store.get_fingerprints_for(entity)) == 2


def test_ids_are_uuid4_strings(store):
    """§4.9 — never rowid; records must survive export and re-import."""
    entity = store.add_entity(file_path="/data/roads.shp")
    assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-", entity)
    assert new_id() != new_id()


# ===========================================================================
# Appendix B.1 — entity identity
# ===========================================================================

def test_same_path_and_version_cannot_be_inserted_twice(store):
    """Appendix B.1 — identity is (file_path, content_version)."""
    store.add_entity(file_path="/data/roads.shp", content_version=1)
    with pytest.raises(sqlite3.IntegrityError):
        store.add_entity(file_path="/data/roads.shp", content_version=1)


def test_rewritten_file_gets_a_new_version_not_an_update(store):
    """Appendix B.1 — this is what lets the graph tell 'the file before' from
    'the file after'."""
    v1 = store.add_entity(file_path="/data/roads.shp", content_version=1)
    v2 = store.add_entity(file_path="/data/roads.shp", content_version=2)
    assert v1 != v2
    assert [e["content_version"] for e in store.list_entity_versions("/data/roads.shp")] == [1, 2]


def test_find_entity_by_path_returns_latest_version(store):
    """C's 'does this input still exist?' check wants the newest by default."""
    store.add_entity(file_path="/data/roads.shp", content_version=1)
    v2 = store.add_entity(file_path="/data/roads.shp", content_version=2)
    assert store.find_entity_by_path("/data/roads.shp")["id"] == v2
    assert store.find_entity_by_path("/data/roads.shp", content_version=1)["id"] != v2


def test_next_content_version_counts_up(store):
    assert store.next_content_version("/data/roads.shp") == 1
    store.add_entity(file_path="/data/roads.shp", content_version=1)
    assert store.next_content_version("/data/roads.shp") == 2


def test_memory_layers_have_no_path_and_do_not_collide(store):
    """§3.3 — memory:, TEMPORARY_OUTPUT and /vsimem/ layers carry path=None but
    keep layer_type, so Person B knows not to fingerprint them. SQLite treats
    NULLs as distinct in UNIQUE, so several may coexist."""
    a = store.add_entity(file_path=None, layer_type="vector", label="memory layer 1")
    b = store.add_entity(file_path=None, layer_type="vector", label="memory layer 2")
    assert a != b
    assert store.get_entity(a)["file_path"] is None
    assert store.get_entity(a)["layer_type"] == "vector"


# ===========================================================================
# §4.10 / §5.9 — activities, status, dedup
# ===========================================================================

def test_failed_runs_are_recorded_not_dropped(store):
    """§4.10 — C's audit needs them and RQ1 completeness counts them."""
    for status in ("completed", "failed", "cancelled"):
        activity = store.add_activity(
            algorithm_id="native:buffer", started_at=utc_now_iso(), status=status
        )
        assert store.get_activity(activity)["status"] == status


def test_invalid_status_is_rejected_with_a_readable_message(store):
    with pytest.raises(StoreError, match="status must be one of"):
        store.add_activity(
            algorithm_id="native:buffer", started_at=utc_now_iso(), status="done"
        )


def test_parameters_are_stored_as_json(store):
    """§3.3 — parameters are always JSON-serializable by the time they reach here."""
    activity = store.add_activity(
        algorithm_id="native:buffer",
        started_at=utc_now_iso(),
        parameters={"DISTANCE": 500, "DISSOLVE": False},
    )
    stored = json.loads(store.get_activity(activity)["parameters_json"])
    assert stored == {"DISTANCE": 500, "DISSOLVE": False}


def test_dedup_key_cannot_be_used_twice(store):
    """§5.9 — the second channel to report an execution must not insert."""
    store.add_activity(algorithm_id="native:buffer", started_at=utc_now_iso(),
                       dedup_key="same-key")
    with pytest.raises(sqlite3.IntegrityError):
        store.add_activity(algorithm_id="native:buffer", started_at=utc_now_iso(),
                           dedup_key="same-key")


def test_null_dedup_keys_do_not_collide(store):
    """The unique index is partial — un-keyed rows must still be insertable."""
    store.add_activity(algorithm_id="native:buffer", started_at=utc_now_iso())
    store.add_activity(algorithm_id="native:buffer", started_at=utc_now_iso())
    assert store.counts()["activities"] == 2


def test_corroboration_counter_increments(store):
    """§5.9 — the hook-vs-history split is a reportable RQ1 result (§8.3), so it
    is persisted as it happens rather than reconstructed later."""
    activity = store.add_activity(algorithm_id="native:buffer",
                                  started_at=utc_now_iso(),
                                  capture_channel="post_hook",
                                  dedup_key="k1")
    assert store.get_activity(activity)["corroborations"] == 0
    assert store.increment_corroboration(activity) == 1
    assert store.increment_corroboration(activity) == 2


def test_find_activity_by_dedup_key(store):
    activity = store.add_activity(algorithm_id="native:buffer",
                                  started_at=utc_now_iso(), dedup_key="k1")
    assert store.find_activity_by_dedup_key("k1")["id"] == activity
    assert store.find_activity_by_dedup_key("nope") is None


def test_activities_for_session_are_ordered_by_time(store):
    """Appendix B.5 — what A6's workflow auto-grouping consumes."""
    session = "22222222-2222-4222-8222-222222222222"
    store.add_activity(algorithm_id="b", started_at="2026-08-08T10:02:00.000000+00:00",
                       session_id=session)
    store.add_activity(algorithm_id="a", started_at="2026-08-08T10:01:00.000000+00:00",
                       session_id=session)
    store.add_activity(algorithm_id="other", started_at="2026-08-08T10:03:00.000000+00:00",
                       session_id="different-session")
    got = [a["algorithm_id"] for a in store.list_activities_for_session(session)]
    assert got == ["a", "b"]


# ===========================================================================
# §4.6 — agent de-duplication
# ===========================================================================

def test_same_environment_reuses_one_agent_row(store):
    """§4.6 — a fresh agent row per execution would inflate our own RQ2
    storage-per-operation numbers with a bug of our own making."""
    env = dict(qgis_version="3.34.8", os_info="Ubuntu 22.04",
               python_version="3.10.12", plugin_versions={"GeoProvenance": "0.1.0"})
    first = store.get_or_create_agent(**env)
    second = store.get_or_create_agent(**env)
    assert first == second
    assert store.counts()["agents"] == 1


def test_different_environment_creates_a_new_agent(store):
    base = dict(qgis_version="3.34.8", os_info="Ubuntu 22.04",
                python_version="3.10.12", plugin_versions={})
    first = store.get_or_create_agent(**base)
    second = store.get_or_create_agent(**{**base, "qgis_version": "3.40.0"})
    assert first != second
    assert store.counts()["agents"] == 2


def test_environment_fingerprint_ignores_dict_ordering(store):
    """Plugin enumeration order must not manufacture a second agent row."""
    a = environment_fingerprint("3.34.8", "Ubuntu", "3.10", {"A": "1", "B": "2"})
    b = environment_fingerprint("3.34.8", "Ubuntu", "3.10", {"B": "2", "A": "1"})
    assert a == b


# ===========================================================================
# Appendix B.2 — relation vocabulary
# ===========================================================================

def test_uppercase_role_is_rejected(store):
    """Appendix B.2 — §7.1 said 'input', §7.3's example said 'INPUT'. Lowercase
    wins; the original QGIS key goes in qgis_param_key, so Person C never has to
    write string-normalising code."""
    with pytest.raises(StoreError, match="qgis_param_key"):
        store.add_relation(relation_type="used", source_id="a", target_id="b",
                           role="INPUT")


def test_original_qgis_key_is_preserved_alongside_the_lowercase_role(store):
    relation = store.add_relation(relation_type="used", source_id="a", target_id="b",
                                  role="overlay", qgis_param_key="OVERLAY")
    row = store._connection().execute(
        "SELECT role, qgis_param_key FROM relations WHERE id = ?", (relation,)
    ).fetchone()
    assert row["role"] == "overlay"
    assert row["qgis_param_key"] == "OVERLAY"


def test_unknown_relation_type_is_rejected(store):
    with pytest.raises(StoreError, match="relation_type must be one of"):
        store.add_relation(relation_type="wasInspiredBy", source_id="a", target_id="b")


def test_check_constraint_backs_up_the_python_validation(store):
    """Defence in depth: even a raw INSERT that bypasses add_relation is refused,
    so a contract violation cannot reach Person C's renderer."""
    with pytest.raises(sqlite3.IntegrityError):
        store._connection().execute(
            "INSERT INTO relations (id, relation_type, source_id, target_id, role, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (new_id(), "used", "a", "b", "INPUT", utc_now_iso()),
        )


def test_get_relations_for_respects_direction(buffer_clip, store):
    ids = buffer_clip
    outgoing = store.get_relations_for(ids["buffer"], direction="out")
    assert {r["relation_type"] for r in outgoing} == {"used", "wasAssociatedWith"}

    incoming = store.get_relations_for(ids["buffer"], direction="in")
    assert {r["relation_type"] for r in incoming} == {"wasGeneratedBy"}

    both = store.get_relations_for(ids["buffer"], direction="both")
    assert len(both) == len(outgoing) + len(incoming)


def test_get_relations_for_rejects_a_bad_direction(store):
    with pytest.raises(StoreError, match="direction must be"):
        store.get_relations_for("x", direction="sideways")


# ===========================================================================
# §4.3 — transactions
# ===========================================================================

def test_transaction_commits_everything(store):
    with store.transaction():
        entity = store.add_entity(file_path="/data/roads.shp")
        activity = store.add_activity(algorithm_id="native:buffer",
                                      started_at=utc_now_iso())
        store.add_relation(relation_type="used", source_id=activity,
                           target_id=entity, role="input")
    assert store.counts()["relations"] == 1


def test_a_failed_execution_leaves_nothing_behind(store):
    """§4.3 [HARD] — an activities row with no relations silently corrupts C's
    graph traversal, and is worse than having captured nothing at all."""
    with pytest.raises(RuntimeError, match="hook blew up"):
        with store.transaction():
            store.add_activity(algorithm_id="native:buffer", started_at=utc_now_iso())
            raise RuntimeError("hook blew up halfway through")

    counts = store.counts()
    assert counts["activities"] == 0
    assert counts["relations"] == 0


def test_nested_transaction_rolls_back_only_the_inner_part(store):
    """The capture engine composes smaller writes inside one execution boundary,
    so nesting must not discard the outer work."""
    with store.transaction():
        outer = store.add_entity(file_path="/data/kept.shp")
        with pytest.raises(ValueError):
            with store.transaction():
                store.add_entity(file_path="/data/discarded.shp")
                raise ValueError("inner step failed")

    assert store.get_entity(outer) is not None
    assert store.find_entity_by_path("/data/discarded.shp") is None


def test_writes_outside_a_transaction_still_commit(store):
    """Single-statement convenience writes must not be left dangling."""
    entity = store.add_entity(file_path="/data/roads.shp")
    assert store.get_entity(entity) is not None


# ===========================================================================
# §4.7 — thread safety
# ===========================================================================

def test_concurrent_writers_from_two_threads(db_path):
    """§4.7 — QGIS may run algorithms off the main thread. One connection per
    thread plus a write lock; both threads' work must land intact."""
    store = ProvenanceStore(db_path)
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker(tag: str) -> None:
        try:
            barrier.wait(timeout=5)
            for i in range(20):
                with store.transaction():
                    store.add_activity(
                        algorithm_id=f"{tag}:{i}", started_at=utc_now_iso()
                    )
        except BaseException as exc:  # noqa: BLE001 — surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert store.counts()["activities"] == 40
    store.close()


def test_reader_thread_sees_committed_writes(db_path):
    """§4.2 — WAL is what lets C's audit read while the engine writes."""
    store = ProvenanceStore(db_path)
    activity = store.add_activity(algorithm_id="native:buffer",
                                  started_at=utc_now_iso())
    seen: list[object] = []

    def reader() -> None:
        seen.append(store.get_activity(activity))

    thread = threading.Thread(target=reader)
    thread.start()
    thread.join(timeout=10)

    assert seen and seen[0]["algorithm_id"] == "native:buffer"
    store.close()


# ===========================================================================
# Workflows, graph assembly, audit results
# ===========================================================================

def test_workflow_graph_returns_the_whole_reference_workflow(buffer_clip, store):
    """The research doc §7.3 example, assembled in one call so Person C never
    has to stitch a graph out of fragments (§1.3)."""
    graph = store.get_workflow_graph(buffer_clip["workflow"])

    assert [a["algorithm_id"] for a in graph["activities"]] == [
        "native:buffer", "native:clip"
    ]
    assert {e["label"] for e in graph["entities"]} == {
        "roads.shp", "buffered_roads.shp", "city_boundary.shp", "final_roads.shp"
    }
    assert len(graph["agents"]) == 1
    assert len(graph["relations"]) == 9


def test_workflow_graph_includes_dataset_to_dataset_links(buffer_clip, store):
    """wasDerivedFrom sits between two datasets, so an activity-anchored query
    alone would miss it — and that is exactly the edge C draws."""
    graph = store.get_workflow_graph(buffer_clip["workflow"])
    derived = [r for r in graph["relations"] if r["relation_type"] == "wasDerivedFrom"]
    assert len(derived) == 2


def test_workflow_activities_come_back_in_sequence_order(buffer_clip, store):
    graph = store.get_workflow_graph(buffer_clip["workflow"])
    assert [a["sequence_order"] for a in graph["activities"]] == [0, 1]


def test_empty_workflow_returns_an_empty_graph(store):
    workflow = store.add_workflow(name="nothing here yet")
    graph = store.get_workflow_graph(workflow)
    assert graph["activities"] == []
    assert graph["entities"] == []


def test_unknown_workflow_raises(store):
    with pytest.raises(StoreError, match="no workflow"):
        store.get_workflow_graph("not-a-workflow")


def test_list_workflows_reports_step_counts(buffer_clip, store):
    workflows = store.list_workflows()
    assert len(workflows) == 1
    assert workflows[0]["activity_count"] == 2
    assert workflows[0]["name"] == "Buffer then Clip"


def test_audit_results_round_trip(buffer_clip, store):
    """§1.3 — Person C writes through this method; the weights are C's business,
    the table and writer are Person A's."""
    store.add_audit_result(
        workflow_id=buffer_clip["workflow"],
        overall_score=87.0,
        input_exists_score=100.0,
        input_unchanged_score=71.0,
        algorithm_available_score=100.0,
        environment_similar_score=86.0,
        parameters_valid_score=100.0,
        details={"steps": 7},
    )
    results = store.list_audit_results(buffer_clip["workflow"])
    assert len(results) == 1
    assert results[0]["overall_score"] == 87.0
    assert json.loads(results[0]["details_json"]) == {"steps": 7}


def test_latest_fingerprint_is_the_newest_one(store):
    """C's 'has this file changed?' check reads the most recent fingerprint."""
    entity = store.add_entity(file_path="/data/roads.shp")
    store.add_fingerprint(entity_id=entity, hash_value="old",
                          computed_at="2026-08-08T10:00:00.000000+00:00")
    store.add_fingerprint(entity_id=entity, hash_value="new",
                          computed_at="2026-08-09T10:00:00.000000+00:00")
    assert store.get_latest_fingerprint(entity)["hash_value"] == "new"
    assert store.get_fingerprints_for(entity)[0]["hash_value"] == "old"


def test_counts_covers_every_table(buffer_clip, store):
    """§8.6 — the RQ2 storage measurement reads this."""
    counts = store.counts()
    assert counts["entities"] == 4
    assert counts["activities"] == 2
    assert counts["agents"] == 1
    assert counts["relations"] == 9
    assert counts["workflow_activities"] == 2


# ===========================================================================
# Interface shape — what B and C actually depend on
# ===========================================================================

def test_rows_come_back_as_plain_dicts(store):
    """§1.3 — Person B hands results straight to json.dumps and Person C never
    imports sqlite3 to read a field."""
    entity_id = store.add_entity(file_path="/data/roads.shp", label="roads.shp")
    row = store.get_entity(entity_id)
    assert type(row) is dict
    assert json.dumps(row)


def test_required_method_surface_exists():
    """§4.5 / §1.5 — these signatures are the contract B and C build against.
    Renaming one is a breaking change under §3.4."""
    required = (
        "add_entity", "add_activity", "add_agent", "add_fingerprint",
        "add_relation", "get_or_create_agent", "find_entity_by_path",
        "get_activity", "get_relations_for", "list_workflows",
        "get_workflow_graph",
    )
    missing = [name for name in required if not callable(getattr(ProvenanceStore, name, None))]
    assert not missing, f"§4.5 method surface is incomplete: {missing}"


def test_store_works_as_a_context_manager(db_path):
    with ProvenanceStore(db_path) as store:
        store.add_entity(file_path="/data/roads.shp")
    with pytest.raises(StoreError, match="closed"):
        store.get_entity("anything")
