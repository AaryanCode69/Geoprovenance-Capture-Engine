"""Person B's PROV layer: the graph lookups, derivation inference, export.

RULES.md §6.1 — no QGIS anywhere in this file.
"""

from __future__ import annotations

import json

import pytest

from geoprovenance import prov
from geoprovenance.storage.store import StoreError


# ---------------------------------------------------------------------------
# A small workflow built through the public API, so the expected answers are
# visible in the test rather than looked up. Buffer reads one file and writes
# one; Clip reads that file AND an overlay, and writes one.
# ---------------------------------------------------------------------------


@pytest.fixture()
def buffer_clip(store):
    agent = store.get_or_create_agent(
        qgis_version="3.34.8", os_info="Ubuntu 22.04", python_version="3.10.12"
    )
    session = "11111111-1111-4111-8111-111111111111"
    with store.transaction():
        roads = store.add_entity(label="roads.shp", file_path="/data/roads.shp",
                                 format="Shapefile", crs="EPSG:4326")
        buffered = store.add_entity(label="buffered_roads.shp",
                                    file_path="/out/buffered_roads.shp",
                                    format="Shapefile", crs="EPSG:4326")
        boundary = store.add_entity(label="city_boundary.shp",
                                    file_path="/data/city_boundary.shp",
                                    format="Shapefile", crs="EPSG:4326")
        final = store.add_entity(label="final_roads.shp",
                                 file_path="/out/final_roads.shp",
                                 format="Shapefile", crs="EPSG:4326")
        a1 = store.add_activity(algorithm_id="native:buffer", algorithm_name="Buffer",
                                session_id=session,
                                started_at="2026-08-08T10:14:22.481903+00:00",
                                ended_at="2026-08-08T10:14:23.004117+00:00",
                                parameters={"DISTANCE": 500})
        a2 = store.add_activity(algorithm_id="native:clip", algorithm_name="Clip",
                                session_id=session,
                                started_at="2026-08-08T10:15:01.100000+00:00",
                                ended_at="2026-08-08T10:15:02.200000+00:00",
                                parameters={})
        store.add_relation(relation_type="used", source_id=a1, target_id=roads,
                           role="input", qgis_param_key="INPUT")
        store.add_relation(relation_type="wasGeneratedBy", source_id=buffered,
                           target_id=a1, role="output", qgis_param_key="OUTPUT")
        store.add_relation(relation_type="used", source_id=a2, target_id=buffered,
                           role="input", qgis_param_key="INPUT")
        store.add_relation(relation_type="used", source_id=a2, target_id=boundary,
                           role="overlay", qgis_param_key="OVERLAY")
        store.add_relation(relation_type="wasGeneratedBy", source_id=final,
                           target_id=a2, role="output", qgis_param_key="OUTPUT")
        store.add_relation(relation_type="wasAssociatedWith", source_id=a1,
                           target_id=agent)
        store.add_relation(relation_type="wasAssociatedWith", source_id=a2,
                           target_id=agent)
        workflow = store.add_workflow(name="Buffer then Clip", session_id=session)
        store.set_workflow_activities(workflow_id=workflow, activity_ids=[a1, a2])
    return {"workflow": workflow, "agent": agent, "roads": roads,
            "buffered": buffered, "boundary": boundary, "final": final,
            "buffer": a1, "clip": a2}


# ---------------------------------------------------------------------------
# ProvGraph
# ---------------------------------------------------------------------------


def test_the_lookups_read_each_relation_in_the_right_direction(store, buffer_clip):
    graph = prov.ProvGraph.load(store, buffer_clip["workflow"])

    assert [e["id"] for e in graph.inputs_of(buffer_clip["buffer"])] == [
        buffer_clip["roads"]
    ]
    assert [e["id"] for e in graph.outputs_of(buffer_clip["buffer"])] == [
        buffer_clip["buffered"]
    ]
    # Clip reads two files. An audit that saw only the first would report the
    # overlay as unrelated to the file it in fact shaped.
    assert sorted(e["id"] for e in graph.inputs_of(buffer_clip["clip"])) == sorted(
        [buffer_clip["buffered"], buffer_clip["boundary"]]
    )
    assert graph.agent_for(buffer_clip["buffer"])["id"] == buffer_clip["agent"]
    assert graph.made_by(buffer_clip["final"])["id"] == buffer_clip["clip"]


def test_a_file_nothing_made_has_no_maker(store, buffer_clip):
    graph = prov.ProvGraph.load(store, buffer_clip["workflow"])
    assert graph.made_by(buffer_clip["roads"]) is None


# ---------------------------------------------------------------------------
# Derivation inference
# ---------------------------------------------------------------------------


def test_every_output_is_derived_from_every_input_of_its_job(store, buffer_clip):
    """The full cross-product, not just the primary chain.

    The research doc §7.3 example lists final_roads <- buffered_roads and stops.
    Clip's result depends on the boundary it was clipped against too, and that
    link is the one a reproducibility audit needs in order to notice that
    editing the boundary invalidates the result.
    """
    graph = prov.ProvGraph.load(store, buffer_clip["workflow"])
    assert sorted(prov.infer_derivations(graph)) == sorted([
        (buffer_clip["buffered"], buffer_clip["roads"]),
        (buffer_clip["final"], buffer_clip["buffered"]),
        (buffer_clip["final"], buffer_clip["boundary"]),
    ])


def test_writing_derivations_persists_them_and_is_idempotent(store, buffer_clip):
    assert prov.write_derivations(store, buffer_clip["workflow"]) == 3
    assert prov.write_derivations(store, buffer_clip["workflow"]) == 0

    graph = prov.ProvGraph.load(store, buffer_clip["workflow"])
    assert sorted(e["id"] for e in graph.derived_from(buffer_clip["final"])) == sorted(
        [buffer_clip["buffered"], buffer_clip["boundary"]]
    )


def test_it_agrees_with_the_record_the_fixtures_already_hold(recorded_store):
    """The strongest evidence available: it agrees with all three, and it did not.

    `tests/fixtures/mock_provenance.db` carries its "this file came from that
    file" links from `build_fixtures.py`, written months before this module
    existed, so agreeing with them is evidence rather than a restatement of the
    code under test. Two of the three pieces of work agreed on the first run.

    The third did not, and the fixture was the one that was wrong. "Buffer then
    Clip" was research doc §7.3 transcribed literally, and §7.3 records
    `final_roads.shp` as coming from `buffered_roads.shp` while omitting the
    `city_boundary.shp` it was clipped against — so the fixture asserted that
    editing the boundary could not affect the result. It plainly could. The
    other two workflows build their links by looping over every input
    (build_fixtures.py:416-423, :525-537), which is this rule.

    Fixed 31 Aug 2026 rather than left pinned: a shared fixture that asserts
    something false trains every consumer of it on that falsehood, and this
    particular falsehood is the exact claim audit.py's input_unchanged check
    exists to make. Told to B and C per RULES.md §3.4 step 5 —
    tests/fixtures/README.md. Zero here now means the inference and the
    recorded record agree everywhere, with nothing left over on either side.
    """
    missing = {
        workflow["name"]: prov.write_derivations(recorded_store, workflow["id"])
        for workflow in recorded_store.list_workflows()
    }
    assert missing == {
        "Points analysis (branching)": 0,
        "Sentinel-2 NDVI land cover": 0,
        "Buffer then Clip": 0,
    }


def test_the_clip_result_comes_from_the_boundary_too(recorded_store, ids):
    """The defect above, pinned in the committed fixture so it cannot return.

    Distinct from the hand-built case earlier in this file: that one proves
    `infer_derivations` computes the cross-product, this one proves the shared
    artefact B and C build against actually *contains* it. The omission was
    invisible for months precisely because nothing read the fixture back and
    asked.
    """
    graph = prov.ProvGraph.load(recorded_store, ids["w1"])
    sources = {
        graph.entity(e["id"])["label"]
        for e in graph.derived_from(ids["w1/final_roads"])
    }
    assert sources == {"buffered_roads.shp", "city_boundary.shp"}


def test_a_job_that_read_nothing_derives_nothing(store):
    """A job the history channel saw but attached no files to.

    RULES.md §4.10 and §5.12 — these rows are real and must not crash the
    inference; they simply have no data flow to infer.
    """
    with store.transaction():
        activity = store.add_activity(
            algorithm_id="native:buffer",
            started_at="2026-08-08T10:14:22.481903+00:00",
            parameters={},
        )
        workflow = store.add_workflow(name="Just a job")
        store.set_workflow_activities(workflow_id=workflow, activity_ids=[activity])
    assert prov.write_derivations(store, workflow) == 0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_prov_json_names_both_ends_of_every_relation_with_the_standards_keys(
    store, buffer_clip
):
    prov.write_derivations(store, buffer_clip["workflow"])
    document = prov.to_prov_json(prov.ProvGraph.load(store, buffer_clip["workflow"]))

    assert document["prefix"]["prov"] == "http://www.w3.org/ns/prov#"
    assert f"gp:{buffer_clip['roads']}" in document["entity"]
    assert f"gp:{buffer_clip['buffer']}" in document["activity"]
    assert f"gp:{buffer_clip['agent']}" in document["agent"]

    # A usage names the job and the file; a generation names them by the other
    # two key names; a derivation names which end was generated.
    used = list(document["used"].values())
    assert all({"prov:activity", "prov:entity"} <= set(u) for u in used)
    generated = list(document["wasGeneratedBy"].values())
    assert all({"prov:entity", "prov:activity"} <= set(g) for g in generated)
    derived = list(document["wasDerivedFrom"].values())
    assert all({"prov:generatedEntity", "prov:usedEntity"} <= set(d) for d in derived)


def test_exported_roles_are_lowercase_and_keep_the_original_qgis_key(
    store, buffer_clip
):
    """Research doc §7.3 writes "OVERLAY"; RULES.md §3.2 decision 2 overrides it.

    Emitting §7.3's spelling would produce a document the database it came from
    would refuse to accept back — the schema CHECK-constrains role to lowercase.
    """
    document = prov.to_prov_json(prov.ProvGraph.load(store, buffer_clip["workflow"]))
    overlay = [
        u for u in document["used"].values() if u.get("gp:qgisParamKey") == "OVERLAY"
    ]
    assert len(overlay) == 1
    assert overlay[0]["gp:role"] == "overlay"

    with pytest.raises(StoreError, match="lowercase"):
        store.add_relation(
            relation_type="used",
            source_id=buffer_clip["clip"],
            target_id=buffer_clip["boundary"],
            role="OVERLAY",
        )


def test_both_exports_survive_a_round_trip_through_json(store, buffer_clip):
    graph = prov.ProvGraph.load(store, buffer_clip["workflow"])
    for document in (prov.to_prov_json(graph), prov.to_record_json(graph)):
        assert json.loads(json.dumps(document)) == document


def test_a_file_with_no_path_still_appears(store):
    """A memory layer cannot be fingerprinted but is still part of the flow.

    docs/CONTRACT_event.md — temporary layers carry `path: None`. Dropping them
    from the export would break the chain either side of them.
    """
    with store.transaction():
        temp = store.add_entity(label="Clipped (temporary)", file_path=None,
                                crs="EPSG:4326", layer_type="vector")
        activity = store.add_activity(algorithm_id="native:clip",
                                      started_at="2026-08-08T10:14:22.481903+00:00",
                                      parameters={})
        store.add_relation(relation_type="wasGeneratedBy", source_id=temp,
                           target_id=activity, role="output")
        workflow = store.add_workflow(name="Into memory")
        store.set_workflow_activities(workflow_id=workflow, activity_ids=[activity])

    document = prov.to_prov_json(prov.ProvGraph.load(store, workflow))
    record = document["entity"][f"gp:{temp}"]
    assert record["prov:label"] == "Clipped (temporary)"
    assert "gp:filePath" not in record  # omitted, not written as null
