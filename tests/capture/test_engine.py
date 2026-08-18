"""ProvenanceCaptureEngine — the A3 write path.

No QGIS. The A3 requirement is verbatim from PERSON_A.md:

    Capture a single native:buffer -> one agents row, one activities row, two
    entities rows, used + wasGeneratedBy relations.

That is test_one_buffer_produces_the_A3_record_shape below.
"""

from __future__ import annotations

import json

import pytest

from geoprovenance.capture import normalizer
from geoprovenance.capture.engine import ProvenanceCaptureEngine
from geoprovenance.storage.store import utc_now_iso

from fakes import Explosive, FakeAlgorithmDefinitions, FakeVectorLayer

BUFFER_PARAMS = {
    "INPUT": "/data/roads.shp",
    "OUTPUT": "/out/buffered_roads.shp",
    "DISTANCE": 500,
    "SEGMENTS": 5,
    "DISSOLVE": False,
}


def run_buffer(engine, *, started_at=None, source="post_hook", status="completed",
               parameters=None, results=None, agent=None):
    return engine.record_algorithm_execution(
        algorithm_id="native:buffer",
        algorithm_name="Buffer",
        provider="qgis",
        parameters=parameters if parameters is not None else dict(BUFFER_PARAMS),
        parameter_definitions=FakeAlgorithmDefinitions.BUFFER,
        results=results,
        started_at=started_at or "2026-08-08T10:14:22.481903+00:00",
        ended_at="2026-08-08T10:14:23.004117+00:00",
        status=status,
        source=source,
        agent=agent,
    )


# ===========================================================================
# the A3 requirement
# ===========================================================================

def test_one_buffer_produces_the_A3_record_shape(engine, store):  # noqa: N802
    """PERSON_A.md §A3: one agents row, one activities row, two entities rows,
    used + wasGeneratedBy relations."""
    result = run_buffer(engine)
    assert result.recorded

    counts = store.counts()
    assert counts["agents"] == 1
    assert counts["activities"] == 1
    assert counts["entities"] == 2
    assert counts["relations"] == 3  # used, wasGeneratedBy, wasAssociatedWith

    relations = store.get_relations_for(result.activity_id, direction="both")
    assert {r["relation_type"] for r in relations} == {
        "used", "wasGeneratedBy", "wasAssociatedWith"
    }


def test_relation_directions_match_the_research_doc(engine, store):
    """Research doc §7.3: used points activity -> entity; wasGeneratedBy points
    entity -> activity. Getting these backwards renders Person C's graph
    upside down."""
    result = run_buffer(engine)
    activity_id = result.activity_id

    used = [r for r in store.get_relations_for(activity_id, "out")
            if r["relation_type"] == "used"]
    assert len(used) == 1
    assert used[0]["source_id"] == activity_id
    assert store.get_entity(used[0]["target_id"])["file_path"] == "/data/roads.shp"

    generated = [r for r in store.get_relations_for(activity_id, "in")
                 if r["relation_type"] == "wasGeneratedBy"]
    assert len(generated) == 1
    assert generated[0]["target_id"] == activity_id
    assert store.get_entity(generated[0]["source_id"])["file_path"] \
        == "/out/buffered_roads.shp"


def test_the_activity_records_which_channel_saw_it(engine, store):
    """§8.3 — the per-channel breakdown is an RQ1 result, so it is persisted as
    it happens rather than reconstructed later."""
    result = run_buffer(engine, source="run_wrapper")
    assert store.get_activity(result.activity_id)["capture_channel"] == "run_wrapper"


def test_scalar_parameters_are_stored_and_layers_are_not(engine, store):
    """§3.3 — layer-valued parameters become entities; scalars stay in the
    parameter record."""
    result = run_buffer(engine)
    stored = json.loads(store.get_activity(result.activity_id)["parameters_json"])
    assert stored == {"DISTANCE": 500, "SEGMENTS": 5, "DISSOLVE": False}


def test_the_session_id_is_stamped_on_the_activity(engine, store):
    """Appendix B.5 — what A6's workflow auto-grouping consumes."""
    result = run_buffer(engine)
    assert store.get_activity(result.activity_id)["session_id"] == engine.session_id


# ===========================================================================
# §5.9 — deduplication between channels
# ===========================================================================

def test_the_second_channel_corroborates_instead_of_inserting(engine, store):
    """§5.9 — first channel wins. Without this every scripted run is recorded
    twice, once by the hook and once by the processing.run wrapper."""
    first = run_buffer(engine, source="post_hook",
                       started_at="2026-08-08T10:14:22.400000+00:00")
    second = run_buffer(engine, source="run_wrapper",
                        started_at="2026-08-08T10:14:22.480000+00:00")

    assert first.recorded and not first.corroborated
    assert second.corroborated and not second.recorded
    assert second.activity_id == first.activity_id
    assert store.counts()["activities"] == 1
    assert store.get_activity(first.activity_id)["corroborations"] == 1


def test_a_genuinely_separate_run_is_not_swallowed_as_a_duplicate(engine, store):
    """The dedup bucket must not be so wide that two real runs collapse into
    one — that would understate capture completeness in RQ1."""
    run_buffer(engine, started_at="2026-08-08T10:14:22.400000+00:00")
    run_buffer(engine, started_at="2026-08-08T10:14:29.400000+00:00")
    assert store.counts()["activities"] == 2


# ===========================================================================
# §4.10 — failures are recorded, not dropped
# ===========================================================================

def test_a_failed_run_is_recorded_with_its_status(engine, store):
    """§4.10 — Person C's audit needs them and RQ1 completeness counts them."""
    result = run_buffer(engine, status="failed")
    assert store.get_activity(result.activity_id)["status"] == "failed"


def test_a_failed_run_still_records_the_input_it_read(engine, store):
    result = run_buffer(engine, status="failed")
    used = [r for r in store.get_relations_for(result.activity_id, "out")
            if r["relation_type"] == "used"]
    assert len(used) == 1


# ===========================================================================
# §4.6 — one agent row per environment
# ===========================================================================

def test_two_executions_in_one_session_share_one_agent_row(engine, store, agent_block):
    """§4.6 — a fresh agent row per execution would inflate our own RQ2
    storage-per-operation numbers with a bug of our own making."""
    run_buffer(engine, agent=agent_block, started_at="2026-08-08T10:00:00.000000+00:00")
    run_buffer(engine, agent=agent_block, started_at="2026-08-08T11:00:00.000000+00:00")
    assert store.counts()["agents"] == 1


def test_a_different_environment_gets_its_own_agent_row(engine, store, agent_block):
    run_buffer(engine, agent=agent_block, started_at="2026-08-08T10:00:00.000000+00:00")
    run_buffer(engine, agent={**agent_block, "qgis_version": "3.40.0"},
               started_at="2026-08-08T11:00:00.000000+00:00")
    assert store.counts()["agents"] == 2


# ===========================================================================
# Appendix B.1 — entity identity
# ===========================================================================

def test_reading_a_file_reuses_the_entity_already_on_record(engine, store):
    """Reading does not create a new version — the bytes we read are the bytes
    already recorded."""
    run_buffer(engine, started_at="2026-08-08T10:00:00.000000+00:00")
    run_buffer(engine, started_at="2026-08-08T11:00:00.000000+00:00",
               parameters={**BUFFER_PARAMS, "OUTPUT": "/out/other.shp"})

    versions = store.list_entity_versions("/data/roads.shp")
    assert len(versions) == 1


def test_overwriting_an_output_creates_a_second_version(engine, store):
    """Appendix B.1 — this is what lets the graph tell 'the file before' from
    'the file after'."""
    run_buffer(engine, started_at="2026-08-08T10:00:00.000000+00:00")
    run_buffer(engine, started_at="2026-08-08T11:00:00.000000+00:00",
               parameters={**BUFFER_PARAMS, "DISTANCE": 900})

    versions = store.list_entity_versions("/out/buffered_roads.shp")
    assert [v["content_version"] for v in versions] == [1, 2]
    assert versions[0]["id"] != versions[1]["id"]


def test_a_memory_output_is_recorded_without_a_path(engine, store):
    """§3.3 — Person B must not try to fingerprint it, but Person C still needs
    the node to draw the chain through."""
    result = run_buffer(engine, parameters={**BUFFER_PARAMS, "OUTPUT": "TEMPORARY_OUTPUT"})
    generated = [r for r in store.get_relations_for(result.activity_id, "in")
                 if r["relation_type"] == "wasGeneratedBy"]
    entity = store.get_entity(generated[0]["source_id"])
    assert entity["file_path"] is None
    assert store.get_fingerprints_for(entity["id"]) == []


def test_an_overlay_input_keeps_its_role_and_original_key(engine, store):
    """Appendix B.2 — lowercase role, original QGIS key preserved separately."""
    result = engine.record_algorithm_execution(
        algorithm_id="native:clip", algorithm_name="Clip",
        parameters={"INPUT": "/data/roads.shp", "OVERLAY": "/data/city.shp",
                    "OUTPUT": "/out/clipped.shp"},
        parameter_definitions=FakeAlgorithmDefinitions.CLIP,
        started_at=utc_now_iso(),
    )
    used = {r["qgis_param_key"]: r for r in
            store.get_relations_for(result.activity_id, "out")
            if r["relation_type"] == "used"}
    assert used["INPUT"]["role"] == "input"
    assert used["OVERLAY"]["role"] == "overlay"


# ===========================================================================
# §5.1 — capture must never break the user's run
# ===========================================================================

def test_capture_never_raises_however_bad_the_input(engine):
    """§5.1 [HARD] — losing one record is acceptable; aborting a user's real
    analysis is not."""
    result = engine.record_algorithm_execution(
        algorithm_id="native:buffer",
        parameters={"INPUT": Explosive(), "OUTPUT": Explosive()},
        parameter_definitions={"INPUT": "source", "OUTPUT": "sink"},
        results=Explosive(),
        started_at=utc_now_iso(),
    )
    assert result is not None  # returned, not raised


def test_capture_reports_failure_rather_than_pretending_to_succeed(engine, monkeypatch):
    """A silent no-op would make a broken write path look like a working one,
    and RQ1 completeness would be measuring nothing."""
    monkeypatch.setattr(engine.store, "add_activity",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("disk full")))
    result = run_buffer(engine)
    assert not result.recorded
    assert "disk full" in result.reason


def test_a_write_that_fails_partway_leaves_nothing_behind(engine, store, monkeypatch):
    """§4.3 [HARD] — an activities row with no relations silently corrupts
    Person C's graph traversal and is worse than capturing nothing."""
    original = store.add_relation
    calls = {"n": 0}

    def explode_on_second(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("interrupted mid-write")
        return original(**kwargs)

    monkeypatch.setattr(store, "add_relation", explode_on_second)
    result = run_buffer(engine)

    assert not result.recorded
    counts = store.counts()
    assert counts["activities"] == 0
    assert counts["relations"] == 0


# ===========================================================================
# the singleton the hook script depends on
# ===========================================================================

def test_the_hook_script_can_find_the_running_engine(engine):
    """The generated hook script runs in its own namespace with no reference to
    the plugin object. instance() is the only way it can reach the engine."""
    assert ProvenanceCaptureEngine.instance() is engine


def test_there_is_no_engine_when_the_plugin_is_not_loaded(store):
    ProvenanceCaptureEngine.stop()
    assert ProvenanceCaptureEngine.instance() is None


def test_starting_replaces_the_previous_instance(store):
    first = ProvenanceCaptureEngine.start(store)
    second = ProvenanceCaptureEngine.start(store)
    assert ProvenanceCaptureEngine.instance() is second
    assert first is not second
    ProvenanceCaptureEngine.stop()


# ===========================================================================
# end to end, the way the hook will call it
# ===========================================================================

def test_a_layer_object_from_qgis_is_captured_whole(engine, store):
    """The realistic shape: QGIS hands the hook layer objects, not paths."""
    result = engine.record_algorithm_execution(
        algorithm_id="native:buffer", algorithm_name="Buffer",
        parameters={
            "INPUT": FakeVectorLayer("/data/roads.shp", crs="EPSG:4326",
                                     feature_count=1204),
            "OUTPUT": "TEMPORARY_OUTPUT",
            "DISTANCE": 500,
        },
        parameter_definitions=FakeAlgorithmDefinitions.BUFFER,
        results={"OUTPUT": FakeVectorLayer("/out/buffered.shp", feature_count=1204)},
        started_at=utc_now_iso(),
    )
    assert result.recorded

    entity = store.find_entity_by_path("/data/roads.shp")
    assert entity["crs"] == "EPSG:4326"
    assert entity["format"] == "ESRI Shapefile"
    assert entity["layer_type"] == "vector"

    output = store.find_entity_by_path("/out/buffered.shp")
    assert output is not None, "results should have resolved the temporary output"


def test_the_event_the_engine_writes_matches_the_contract(engine, agent_block):
    """The event dict Person B consumes and the rows Person A writes come from
    the same object — they cannot drift apart."""
    event = normalizer.build_event(
        algorithm_id="native:buffer", session_id=engine.session_id,
        started_at=utc_now_iso(), ended_at=utc_now_iso(), agent=agent_block,
        parameters=dict(BUFFER_PARAMS),
        parameter_definitions=FakeAlgorithmDefinitions.BUFFER,
    )
    result = engine.record_event(event)
    assert result.recorded
