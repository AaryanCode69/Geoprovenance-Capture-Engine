"""Fixtures for the storage suite.

RULES.md §6.1 — nothing in this directory may import QGIS. Run it with:

    make test-storage
"""

from __future__ import annotations

import pytest

from geoprovenance.storage.store import ProvenanceStore, utc_now_iso


@pytest.fixture()
def db_path(tmp_path):
    """A path to a database that does not exist yet."""
    return tmp_path / "prov.db"


@pytest.fixture()
def store(db_path):
    """A fresh, initialised store. Closed automatically."""
    s = ProvenanceStore(db_path)
    yield s
    s.close()


@pytest.fixture()
def buffer_clip(store):
    """The research doc §7.3 worked example: roads -> Buffer -> Clip -> final.

    Built through the public API only, so it doubles as a check that the API is
    sufficient to express the contract's own reference workflow.
    """
    agent = store.get_or_create_agent(
        qgis_version="3.34.8",
        os_info="Ubuntu 22.04",
        python_version="3.10.12",
        plugin_versions={"GeoProvenance": "0.1.0"},
    )
    session = "11111111-1111-4111-8111-111111111111"

    with store.transaction():
        roads = store.add_entity(label="roads.shp", file_path="/data/roads.shp",
                                 format="Shapefile", crs="EPSG:4326", layer_type="vector")
        buffered = store.add_entity(label="buffered_roads.shp",
                                    file_path="/output/buffered_roads.shp",
                                    format="Shapefile", crs="EPSG:4326",
                                    layer_type="vector")
        boundary = store.add_entity(label="city_boundary.shp",
                                    file_path="/data/city_boundary.shp",
                                    format="Shapefile", crs="EPSG:4326",
                                    layer_type="vector")
        final = store.add_entity(label="final_roads.shp",
                                 file_path="/output/final_roads.shp",
                                 format="Shapefile", crs="EPSG:4326",
                                 layer_type="vector")

        a1 = store.add_activity(algorithm_id="native:buffer", algorithm_name="Buffer",
                                provider="qgis", session_id=session,
                                started_at="2026-08-08T10:14:22.481903+00:00",
                                ended_at="2026-08-08T10:14:23.004117+00:00",
                                parameters={"DISTANCE": 500, "SEGMENTS": 5,
                                            "DISSOLVE": False},
                                capture_channel="post_hook", dedup_key="k-buffer")
        a2 = store.add_activity(algorithm_id="native:clip", algorithm_name="Clip",
                                provider="qgis", session_id=session,
                                started_at="2026-08-08T10:15:01.100000+00:00",
                                ended_at="2026-08-08T10:15:02.200000+00:00",
                                parameters={},
                                capture_channel="post_hook", dedup_key="k-clip")

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
        store.add_relation(relation_type="wasDerivedFrom", source_id=buffered,
                           target_id=roads)
        store.add_relation(relation_type="wasDerivedFrom", source_id=final,
                           target_id=buffered)
        store.add_relation(relation_type="wasAssociatedWith", source_id=a1,
                           target_id=agent)
        store.add_relation(relation_type="wasAssociatedWith", source_id=a2,
                           target_id=agent)

        workflow = store.add_workflow(name="Buffer then Clip", session_id=session)
        store.add_workflow_activity(workflow_id=workflow, activity_id=a1,
                                    sequence_order=0)
        store.add_workflow_activity(workflow_id=workflow, activity_id=a2,
                                    sequence_order=1)

    return {
        "agent": agent, "session": session, "workflow": workflow,
        "roads": roads, "buffered": buffered, "boundary": boundary, "final": final,
        "buffer": a1, "clip": a2,
    }


@pytest.fixture()
def now():
    return utc_now_iso()
