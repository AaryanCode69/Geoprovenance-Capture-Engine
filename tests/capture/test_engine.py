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
    used + wasGeneratedBy relations.

    Measured with Person B's after-the-commit pass switched off, because this is
    the A3 deliverable and B's `wasDerivedFrom` is explicitly not part of it
    (RULES.md §1.2, §5.12). The enriched shape is the next test.
    """
    engine.enrich = False
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


def test_the_engine_also_links_the_files_once_person_bs_pass_is_on(engine, store):
    """The default. A captured job leaves the record ready to draw as a tree.

    Person A's capture writes "this job read that file" and "this job made that
    file"; the link a family tree is actually drawn from — "this file came from
    that file" — is inferred afterwards (§5.12). Without it the picture has no
    edges between files at all.
    """
    assert engine.enrich is True
    result = run_buffer(engine)

    relations = store.get_relations_for(result.activity_id, direction="both")
    assert {r["relation_type"] for r in relations} == {
        "used", "wasGeneratedBy", "wasAssociatedWith"
    }
    derived = [
        r for r in store.get_relations_for(
            [rel for rel in relations if rel["relation_type"] == "wasGeneratedBy"][0][
                "source_id"
            ]
        )
        if r["relation_type"] == "wasDerivedFrom"
    ]
    assert len(derived) == 1


def test_replaying_the_same_job_does_not_double_the_links(engine, store):
    """Person B's pass reruns over the whole session after every capture, so it
    must be idempotent or a four-step workflow ends up with sixteen links."""
    run_buffer(engine)
    before = store.counts()["relations"]
    run_buffer(engine, started_at="2026-08-08T11:00:00.000000+00:00")
    after = store.counts()["relations"]
    assert after - before == 4  # exactly one more job's worth, not a re-link


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
    'the file after'. The path here is not on disk, so the write cannot be
    verified — and an unverifiable *write* is still evidence of a change."""
    run_buffer(engine, started_at="2026-08-08T10:00:00.000000+00:00")
    run_buffer(engine, started_at="2026-08-08T11:00:00.000000+00:00",
               parameters={**BUFFER_PARAMS, "DISTANCE": 900})

    versions = store.list_entity_versions("/out/buffered_roads.shp")
    assert [v["content_version"] for v in versions] == [1, 2]
    assert versions[0]["id"] != versions[1]["id"]


# ===========================================================================
# decision 1 — when content_version bumps (docs/CONTRACT_schema.md)
# ===========================================================================

def _run_over(engine, tmp_path, *, started_at, rewrite=True):
    """One buffer whose input and output are real files on disk."""
    source = tmp_path / "roads.shp"
    written = tmp_path / "buffered.shp"
    if not source.exists():
        source.write_text("roads")
    if rewrite or not written.exists():
        written.write_text("buffered")
    return run_buffer(
        engine,
        started_at=started_at,
        parameters={**BUFFER_PARAMS, "INPUT": str(source), "OUTPUT": str(written)},
    )


def test_an_output_that_provably_did_not_change_reuses_the_entity(engine, store, tmp_path):
    """A3 bumped on every write regardless of content. Bumping when nothing
    changed puts phantom nodes in Person C's graph and inflates Person A's own
    RQ2 storage numbers with a bug of Person A's making (§8.6)."""
    written = tmp_path / "buffered.shp"
    _run_over(engine, tmp_path, started_at="2026-08-08T10:00:00.000000+00:00")
    _run_over(engine, tmp_path, started_at="2026-08-08T11:00:00.000000+00:00", rewrite=False)

    versions = store.list_entity_versions(str(written))
    assert [v["content_version"] for v in versions] == [1]


def test_a_changed_output_mints_a_new_version(engine, store, tmp_path):
    written = tmp_path / "buffered.shp"
    _run_over(engine, tmp_path, started_at="2026-08-08T10:00:00.000000+00:00")

    written.write_text("buffered, but wider this time")  # different size
    _run_over(engine, tmp_path, started_at="2026-08-08T11:00:00.000000+00:00")

    versions = store.list_entity_versions(str(written))
    assert [v["content_version"] for v in versions] == [1, 2]


def test_an_input_edited_between_runs_gets_a_new_version(engine, store, tmp_path):
    """The signal Person C's 'is this input unchanged?' audit component wants."""
    source = tmp_path / "roads.shp"
    _run_over(engine, tmp_path, started_at="2026-08-08T10:00:00.000000+00:00")

    source.write_text("roads, edited outside QGIS")
    _run_over(engine, tmp_path, started_at="2026-08-08T11:00:00.000000+00:00")

    versions = store.list_entity_versions(str(source))
    assert [v["content_version"] for v in versions] == [1, 2]


def test_an_unreadable_input_reuses_rather_than_inventing_a_version(engine, store):
    """§5.6 — a job that merely READ a file it cannot stat has demonstrated no
    change, so guessing at one would be inventing a fact."""
    run_buffer(engine, started_at="2026-08-08T10:00:00.000000+00:00")
    run_buffer(engine, started_at="2026-08-08T11:00:00.000000+00:00",
               parameters={**BUFFER_PARAMS, "OUTPUT": "/out/other.shp"})

    assert len(store.list_entity_versions("/data/roads.shp")) == 1


def test_the_size_and_time_probe_is_recorded_for_later_comparison(engine, store, tmp_path):
    written = tmp_path / "buffered.shp"
    _run_over(engine, tmp_path, started_at="2026-08-08T10:00:00.000000+00:00")

    entity = store.find_entity_by_path(str(written))
    metadata = json.loads(entity["metadata_json"])
    assert metadata["size_bytes"] == written.stat().st_size
    assert metadata["mtime_ns"] == written.stat().st_mtime_ns


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
    assert entity["format"] == "Shapefile"   # canonicalised from "ESRI Shapefile"
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


# ===========================================================================
# workflow grouping (A6)
# ===========================================================================

def _buffer(engine, source, written, *, started_at):
    """One captured job reading `source` and writing `written`."""
    return engine.record_algorithm_execution(
        algorithm_id="native:buffer", algorithm_name="Buffer",
        parameters={"INPUT": source, "OUTPUT": written, "DISTANCE": 500},
        parameter_definitions=FakeAlgorithmDefinitions.BUFFER,
        results={"OUTPUT": written},
        started_at=started_at,
    )


def test_capturing_a_chain_groups_it_without_being_asked(engine, store):
    """The Review 2 claim, at the engine level: nobody calls the grouper —
    capture does, after the record is safely committed."""
    _buffer(engine, "/data/roads.shp", "/work/step1.shp",
            started_at="2026-08-08T10:00:00.000000+00:00")
    _buffer(engine, "/work/step1.shp", "/work/step2.shp",
            started_at="2026-08-08T10:01:00.000000+00:00")

    workflows = store.find_workflows_by_session(engine.session_id)
    assert len(workflows) == 1, "two linked jobs are one piece of work"

    graph = store.get_workflow_graph(workflows[0]["id"])
    assert [a["algorithm_id"] for a in graph["activities"]] == [
        "native:buffer", "native:buffer",
    ]
    assert workflows[0]["name"] == "Buffer, then Buffer"


def test_grouping_follows_the_event_not_the_engine(engine, store):
    """An event replayed from the fixtures carries its own session id — the
    Review 2 demo does exactly that (§7.3). Grouping must follow the row that
    was written, not the engine's own session."""
    other = "99999999-9999-4999-8999-999999999999"
    assert other != engine.session_id

    event = normalizer.build_event(
        algorithm_id="native:buffer", algorithm_name="Buffer",
        session_id=other, started_at=utc_now_iso(), ended_at=utc_now_iso(),
        parameters=dict(BUFFER_PARAMS),
        parameter_definitions=FakeAlgorithmDefinitions.BUFFER,
        agent={"qgis_version": "3.34.8", "os_info": "Linux", "python_version": "3.10.12",
               "plugin_versions": {}},
    )
    assert engine.record_event(event).recorded

    assert store.find_workflows_by_session(other), "the replayed session was grouped"
    assert not store.find_workflows_by_session(engine.session_id)


def test_a_grouping_failure_never_reaches_the_user(engine, monkeypatch):
    """§5.1 [HARD] — grouping is the SHOULD-have half of chaining; the record
    is the MUST-have and is already committed by the time this runs."""
    from geoprovenance.storage import workflows as workflows_module

    def explode(*_args, **_kwargs):
        raise RuntimeError("grouping is broken")

    monkeypatch.setattr(workflows_module, "group_session", explode)
    assert engine.group_session() == []

    result = _buffer(engine, "/data/roads.shp", "/out/buffered.shp",
                     started_at=utc_now_iso())
    assert result.recorded, "the job is still written down"


def test_starting_a_new_workflow_separates_what_follows(engine, store):
    """Appendix B.5 — session_id IS the grouping key, so a new one is the
    whole mechanism behind the 'Start new workflow' menu action."""
    _buffer(engine, "/data/roads.shp", "/work/step1.shp",
            started_at="2026-08-08T10:00:00.000000+00:00")
    first_session = engine.session_id

    second_session = engine.begin_new_workflow()
    assert second_session != first_session

    # Reads the file the previous job wrote — linked by data, separated by the
    # boundary the user drew on purpose.
    _buffer(engine, "/work/step1.shp", "/work/step2.shp",
            started_at="2026-08-08T10:01:00.000000+00:00")

    assert len(store.find_workflows_by_session(first_session)) == 1
    assert len(store.find_workflows_by_session(second_session)) == 1


def test_earlier_work_is_left_alone_by_a_new_workflow(engine, store):
    """Nothing is rewritten — the jobs already captured keep their session."""
    _buffer(engine, "/data/roads.shp", "/work/step1.shp",
            started_at="2026-08-08T10:00:00.000000+00:00")
    first_session = engine.session_id
    before = store.get_workflow_graph(
        store.find_workflows_by_session(first_session)[0]["id"]
    )

    engine.begin_new_workflow()

    after = store.get_workflow_graph(
        store.find_workflows_by_session(first_session)[0]["id"]
    )
    assert [a["id"] for a in after["activities"]] == [
        a["id"] for a in before["activities"]
    ]


# ===========================================================================
# §5.9 — the regression suite for cross-channel dedup
#
# Every test below fails against the pre-fix engine. The three §5.9 tests that
# already existed did not, because each was built on the one case where the
# defect is invisible: they drove the hook side WITHOUT parameter_definitions,
# so both channels split the parameters identically, and they chose timestamps
# inside a single 100 ms bucket.
# ===========================================================================

#: What the history channel actually reports: no QgsProcessingAlgorithm in
#: hand, so no parameter type map and nothing lifted into inputs/outputs.
def run_buffer_as_history(engine, *, started_at, parameters=None):
    return engine.record_algorithm_execution(
        algorithm_id="native:buffer",
        parameters=parameters if parameters is not None else dict(BUFFER_PARAMS),
        parameter_definitions=None,          # the whole point
        started_at=started_at,
        ended_at=started_at,
        source="history_signal",
    )


def test_the_hook_and_the_history_channel_agree_on_one_execution(engine, store):
    """§5.9 [HARD] — THE regression test.

    The hook holds the algorithm and passes parameter_definitions, so INPUT and
    OUTPUT are lifted out of `parameters`. The history channel passes none, so
    they stay in. The key used to be computed over the post-split dict, so the
    two channels produced different digests for one execution — for every
    algorithm with a layer parameter, i.e. all of them. Every job was written
    twice and `corroborations` never moved off zero, which silently invalidates
    the per-channel split RQ1 reports (§8.3).
    """
    first = run_buffer(engine, source="post_hook",
                       started_at="2026-08-08T10:14:22.481903+00:00")
    second = run_buffer_as_history(engine,
                                   started_at="2026-08-08T10:14:22.900000+00:00")

    assert first.recorded and not first.corroborated
    assert second.corroborated and not second.recorded, (
        "the history channel must corroborate the hook's record, not insert a "
        "second row for the same execution"
    )
    assert store.counts()["activities"] == 1
    assert store.get_activity(first.activity_id)["corroborations"] == 1
    assert store.get_activity(first.activity_id)["capture_channel"] == "post_hook"


def test_a_slow_algorithm_still_dedups_across_channels(engine, store):
    """The hook stamps BEFORE the run; the history registry writes its entry
    AFTER it. For anything slower than the old 100 ms bucket — which is every
    real reproject — the two observations could never land in one bucket. The
    match is against the activity's own interval, so it does not matter how
    long the job took."""
    run_buffer(engine, source="post_hook",
               started_at="2026-08-08T10:14:22.000000+00:00")
    # ended_at from run_buffer is 10:14:23.004117; the history entry lands
    # after that, as it does in QGIS.
    late = run_buffer_as_history(engine,
                                 started_at="2026-08-08T10:14:23.500000+00:00")

    assert late.corroborated, "a slow job must still be recognised as one run"
    assert store.counts()["activities"] == 1


def test_two_observations_either_side_of_a_bucket_boundary_are_one_run(engine, store):
    """The old key floored timestamps onto a fixed 100 ms grid, so observations
    2 ms apart got different keys whenever a grid line fell between them — and
    the hook and the run wrapper stamp within milliseconds of each other."""
    run_buffer(engine, source="post_hook",
               started_at="2026-08-08T10:14:22.099000+00:00")
    straddling = run_buffer(engine, source="run_wrapper",
                            started_at="2026-08-08T10:14:22.101000+00:00")

    assert straddling.corroborated
    assert store.counts()["activities"] == 1


def test_a_rerun_over_the_same_data_is_still_a_separate_job(engine, store):
    """The other half of §5.9, and the one the fix must not break: the same
    algorithm over the same files an hour later is a NEW execution. Collapsing
    it would understate RQ1 completeness instead of overstating it."""
    run_buffer(engine, source="post_hook",
               started_at="2026-08-08T10:14:22.000000+00:00")
    run_buffer(engine, source="post_hook",
               started_at="2026-08-08T11:14:22.000000+00:00")
    assert store.counts()["activities"] == 2


def test_different_inputs_are_different_jobs_even_at_the_same_moment(engine, store):
    """Dedup keys on the input paths, so two jobs that differ only in which
    file they read must not collapse into one."""
    at = "2026-08-08T10:14:22.000000+00:00"
    run_buffer(engine, started_at=at)
    other = dict(BUFFER_PARAMS, INPUT="/data/rivers.shp")
    run_buffer(engine, started_at=at, parameters=other)
    assert store.counts()["activities"] == 2


def test_the_channel_split_survives_a_realistic_pair(engine, store):
    """§8.3's reportable number, built the way production builds it rather than
    from two identically-shaped calls."""
    run_buffer(engine, source="post_hook",
               started_at="2026-08-08T10:14:22.481903+00:00")
    run_buffer_as_history(engine, started_at="2026-08-08T10:14:22.900000+00:00")
    run_buffer_as_history(engine, started_at="2026-08-08T12:00:00.000000+00:00",
                          parameters=dict(BUFFER_PARAMS, INPUT="/data/rails.shp"))

    stats = store.channel_statistics()
    assert stats["post_hook"] == {"first": 1, "corroborations": 1}
    assert stats["history_signal"] == {"first": 1, "corroborations": 0}


def test_the_agent_row_does_not_survive_a_failed_execution(engine, store):
    """§4.3 / §4.6 — the agent write used to commit in its own transaction just
    before the execution's, so a failure in between left an orphan agents row.
    Everything now lands together or not at all."""
    bad = dict(BUFFER_PARAMS)
    with pytest.raises(Exception):
        engine.record_event({
            "algorithm_id": "native:buffer",
            "session_id": engine.session_id,
            "started_at": "2026-08-08T10:14:22.000000+00:00",
            "ended_at": None,
            "source": "post_hook",
            "status": "not-a-valid-status",   # rejected by add_activity
            "parameters": bad,
            "inputs": [], "outputs": [],
            "agent": {"qgis_version": "9.9.9", "os_info": "x", "python_version": "3"},
        })
    assert store.counts()["agents"] == 0, "no orphan agent row from a failed write"
    assert store.counts()["activities"] == 0
