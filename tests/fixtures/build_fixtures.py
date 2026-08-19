"""Regenerate the shared test fixtures that Person B and Person C both consume.

Owner: Person A.  Sub-phase: A0.3.

    Run:  make fixtures        (or: python tests/fixtures/build_fixtures.py)

    RULES.md §10.3 — the generated .db, .json and data files ARE committed,
    because B and C consume them directly. They are regenerated only by this
    script, NEVER hand-edited.

    RULES.md §3.4 step 3 — after any schema or event-dict change, re-run this so
    B's and C's tests stay green, then tell them what changed.

Phase 0 exit criterion (PERSON_A.md §A0.3)
    B and C can each run pytest against these fixtures with ZERO QGIS running
    and zero Person A code beyond storage/store.py.

Everything here is DETERMINISTIC — fixed timestamps, uuid5 ids derived from
readable names, no clocks, no randomness. Regenerating without changing this
file must produce byte-identical output, or every regeneration churns the diff
and hides the real change. `make fixtures` checks this and says so.

What the fixture set deliberately contains
    The reference workflow, plus every awkward case B and C will otherwise
    discover the hard way in week 10:

      * research doc §7.3 Buffer -> Clip, verbatim, with paths that do NOT
        exist on disk  -> Person C's audit gets a genuine "input missing" case
      * an 8-step chain (research doc §9.2 Workflow B) with a memory layer
        (path=None) in the middle  -> Person B must skip it, not hash it
      * a FAILED activity that was retried  -> §4.10, and RQ1 counts it
      * a BRANCH: one activity with two outputs, each feeding a different
        downstream step  -> Person C's layout meets a non-linear graph early
      * a RE-RUN that overwrites a file, producing content_version 2 of the
        same path  -> Appendix B.1, the case that makes derivation chains and
        the history view correct
      * two different agents (QGIS 3.34.8 and 3.40.0)  -> Person C's
        "environment similar" check has something to vary on
      * real files on disk under data/  -> Person B's fingerprinter has real
        bytes to hash and Person C's "does this exist?" check can pass
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import sys
import uuid

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from geoprovenance.storage.store import (  # noqa: E402
    ProvenanceStore,
    environment_fingerprint,
)

sys.path.insert(0, str(HERE))
from _minifiles import (  # noqa: E402
    normalise_sqlite_header,
    write_point_geopackage,
    write_point_shapefile,
)

OUT_DIR = HERE
MOCK_DB = OUT_DIR / "mock_provenance.db"
MOCK_EVENTS = OUT_DIR / "mock_events.json"
MOCK_IDS = OUT_DIR / "mock_ids.json"
DATA_DIR = OUT_DIR / "data"


def use_output_dir(out_dir: pathlib.Path) -> None:
    """Point the generator at a different directory.

    Only reason this exists: the determinism test builds the whole fixture set
    twice into two temporary directories and compares the bytes. Without it the
    test would have to overwrite the committed fixtures to check them.
    """
    global OUT_DIR, MOCK_DB, MOCK_EVENTS, MOCK_IDS, DATA_DIR
    OUT_DIR = pathlib.Path(out_dir)
    MOCK_DB = OUT_DIR / "mock_provenance.db"
    MOCK_EVENTS = OUT_DIR / "mock_events.json"
    MOCK_IDS = OUT_DIR / "mock_ids.json"
    DATA_DIR = OUT_DIR / "data"

#: Fixed namespace so ids are stable across regenerations and across machines.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://geoprovenance.invalid/fixtures/v1")

#: All fixture timestamps are offsets from this instant. Never datetime.now().
EPOCH = dt.datetime(2026, 8, 8, 10, 0, 0, tzinfo=dt.timezone.utc)

QGIS_334 = {
    "qgis_version": "3.34.8",
    "os_info": "Ubuntu 22.04",
    "python_version": "3.10.12",
    "plugin_versions": {"GeoProvenance": "0.1.0"},
}
QGIS_340 = {
    "qgis_version": "3.40.0",
    "os_info": "Ubuntu 24.04",
    "python_version": "3.12.3",
    "plugin_versions": {"GeoProvenance": "0.1.0", "QuickMapServices": "0.19.34"},
}

_ids: dict[str, str] = {}


def fid(name: str) -> str:
    """A stable UUID for a readable fixture name. Recorded in mock_ids.json."""
    value = str(uuid.uuid5(NAMESPACE, name))
    _ids[name] = value
    return value


def _relation(store: ProvenanceStore, *, relation_type: str, source_id: str,
              target_id: str, created_at: str, role: str | None = None,
              qgis_param_key: str | None = None) -> str:
    """add_relation with a DETERMINISTIC id derived from the relation itself.

    Relations are the one row type with no natural name to hang a fixed id on,
    so without this they get a fresh uuid4 per build and the committed database
    changes on every regeneration — churning the diff and hiding real changes.
    Not recorded in mock_ids.json: 70 machine-generated keys would drown the
    readable names that file exists to provide.
    """
    key = f"rel/{relation_type}/{source_id}/{target_id}/{role}"
    return store.add_relation(
        relation_id=str(uuid.uuid5(NAMESPACE, key)),
        relation_type=relation_type, source_id=source_id, target_id=target_id,
        role=role, qgis_param_key=qgis_param_key, created_at=created_at,
    )


def _agent(name: str, env: dict, store: ProvenanceStore, created_at: str) -> str:
    """An agent row with a deterministic id and the real §4.6 fingerprint."""
    return store.add_agent(
        agent_id=fid(name),
        label=f"QGIS {env['qgis_version']}",
        env_fingerprint=environment_fingerprint(
            env["qgis_version"], env["os_info"], env["python_version"],
            env["plugin_versions"],
        ),
        created_at=created_at,
        **env,
    )


def ts(seconds: float) -> str:
    """Microsecond ISO 8601, ``seconds`` after EPOCH (RULES.md §3.2 decision 4)."""
    return (EPOCH + dt.timedelta(seconds=seconds)).isoformat(timespec="microseconds")


def fake_hash(name: str) -> str:
    """A stable stand-in fingerprint.

    Person B computes REAL fingerprints (§1.2). These exist only so Person C's
    "has this file changed?" check has a recorded value to compare against, and
    so the shape of a fingerprint row is exercised. They are not, and must not
    be presented as, real content hashes of anything.
    """
    return hashlib.sha256(f"geoprovenance-fixture:{name}".encode()).hexdigest()


# ===========================================================================
# real files on disk — Person B hashes these, Person C checks they exist
# ===========================================================================

def build_data_files() -> list[pathlib.Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    points = [
        (77.5946, 12.9716), (77.6100, 12.9800), (77.5800, 12.9600),
        (77.6250, 12.9900), (77.5700, 12.9500), (77.6400, 13.0100),
        (77.5600, 12.9400), (77.6500, 13.0200),
    ]
    attributes = [
        {"name": f"site_{i:02d}", "category": "urban" if i % 2 == 0 else "rural"}
        for i in range(len(points))
    ]

    written = write_point_shapefile(
        DATA_DIR / "sample_points.shp",
        points,
        attributes,
        fields=[("name", "C", 16), ("category", "C", 12)],
    )
    written.append(
        write_point_geopackage(
            DATA_DIR / "sample_areas.gpkg", "sample_areas", points[:4], attributes[:4]
        )
    )
    return sorted(written)


# ===========================================================================
# workflow 1 — research doc §7.3, verbatim. Paths do NOT exist on disk.
# ===========================================================================

def build_workflow_1(store: ProvenanceStore, agent: str) -> list[dict]:
    session = fid("session/w1")
    shp = {"format": "Shapefile", "crs": "EPSG:4326", "layer_type": "vector"}

    with store.transaction():
        roads = store.add_entity(entity_id=fid("w1/roads"), label="roads.shp",
                                 file_path="/data/roads.shp", created_at=ts(0), **shp)
        buffered = store.add_entity(entity_id=fid("w1/buffered_roads"),
                                    label="buffered_roads.shp",
                                    file_path="/output/buffered_roads.shp",
                                    created_at=ts(1), **shp)
        boundary = store.add_entity(entity_id=fid("w1/city_boundary"),
                                    label="city_boundary.shp",
                                    file_path="/data/city_boundary.shp",
                                    created_at=ts(2), **shp)
        final = store.add_entity(entity_id=fid("w1/final_roads"), label="final_roads.shp",
                                 file_path="/output/final_roads.shp",
                                 created_at=ts(3), **shp)

        buffer_run = store.add_activity(
            activity_id=fid("w1/buffer"), algorithm_id="native:buffer",
            algorithm_name="Buffer", provider="qgis", session_id=session,
            started_at=ts(10), ended_at=ts(11),
            parameters={"DISTANCE": 500, "SEGMENTS": 5, "DISSOLVE": False,
                        "END_CAP_STYLE": 0, "JOIN_STYLE": 0, "MITER_LIMIT": 2},
            capture_channel="post_hook", dedup_key="w1-buffer")

        # §5.9's evidence path, which nothing in the fixture set exercised
        # before: this job was seen by BOTH the hook and the processing.run
        # wrapper. The hook got there first and inserted; the wrapper arrived
        # second and corroborated. Person C's panel and Person B's mapper
        # should meet a corroborated row at least once, and RQ1's per-channel
        # split (§8.3) is read straight off this column.
        #
        # Through increment_corroboration rather than a literal, so the fixture
        # is built by the same call production makes.
        store.increment_corroboration(buffer_run)
        clip_run = store.add_activity(
            activity_id=fid("w1/clip"), algorithm_id="native:clip",
            algorithm_name="Clip", provider="qgis", session_id=session,
            started_at=ts(20), ended_at=ts(22), parameters={},
            # The one fixture job caught by the processing.run monkeypatch.
            # `run_wrapper` has been a legal `source` since A3 and appears in
            # both docs/CONTRACT_event.md and schemas/event.schema.json, but no
            # fixture used it, so Person B's `source` switch never saw the third
            # case in the data it develops against.
            capture_channel="run_wrapper", dedup_key="w1-clip")

        for kwargs in (
            dict(relation_type="used", source_id=buffer_run, target_id=roads,
                 role="input", qgis_param_key="INPUT"),
            dict(relation_type="wasGeneratedBy", source_id=buffered,
                 target_id=buffer_run, role="output", qgis_param_key="OUTPUT"),
            dict(relation_type="used", source_id=clip_run, target_id=buffered,
                 role="input", qgis_param_key="INPUT"),
            dict(relation_type="used", source_id=clip_run, target_id=boundary,
                 role="overlay", qgis_param_key="OVERLAY"),
            dict(relation_type="wasGeneratedBy", source_id=final,
                 target_id=clip_run, role="output", qgis_param_key="OUTPUT"),
            dict(relation_type="wasDerivedFrom", source_id=buffered, target_id=roads),
            dict(relation_type="wasDerivedFrom", source_id=final, target_id=buffered),
            dict(relation_type="wasAssociatedWith", source_id=buffer_run,
                 target_id=agent),
            dict(relation_type="wasAssociatedWith", source_id=clip_run, target_id=agent),
        ):
            _relation(store, created_at=ts(30), **kwargs)

        for offset, (name, entity) in enumerate(
            (("roads", roads), ("buffered_roads", buffered),
             ("city_boundary", boundary), ("final_roads", final))
        ):
            store.add_fingerprint(
                fingerprint_id=fid(f"w1/fp/{name}"), entity_id=entity,
                hash_value=fake_hash(f"w1/{name}"), hash_strategy="file",
                file_size_bytes=8192 + offset * 512, feature_count=1204,
                computed_at=ts(31 + offset))

        workflow = store.add_workflow(
            workflow_id=fid("w1"), name="Buffer then Clip",
            description="Research doc §7.3 reference workflow. Paths do not exist "
                        "on disk on purpose — Person C's audit needs a missing input.",
            session_id=session, created_at=ts(40))
        store.add_workflow_activity(workflow_id=workflow, activity_id=buffer_run,
                                    sequence_order=0)
        store.add_workflow_activity(workflow_id=workflow, activity_id=clip_run,
                                    sequence_order=1)

    return [
        _event("w1/buffer", session, "native:buffer", "Buffer", ts(10), ts(11),
               parameters={"DISTANCE": 500, "SEGMENTS": 5, "DISSOLVE": False,
                           "END_CAP_STYLE": 0, "JOIN_STYLE": 0, "MITER_LIMIT": 2},
               inputs=[_layer("INPUT", "/data/roads.shp", **shp, feature_count=1204)],
               outputs=[_layer("OUTPUT", "/output/buffered_roads.shp", **shp,
                               feature_count=1204)],
               agent=QGIS_334),
        _event("w1/clip", session, "native:clip", "Clip", ts(20), ts(22),
               source="run_wrapper",
               parameters={},
               inputs=[_layer("INPUT", "/output/buffered_roads.shp", **shp,
                              feature_count=1204),
                       _layer("OVERLAY", "/data/city_boundary.shp", **shp,
                              feature_count=1)],
               outputs=[_layer("OUTPUT", "/output/final_roads.shp", **shp,
                               feature_count=842)],
               agent=QGIS_334),
    ]


# ===========================================================================
# workflow 2 — 8-step NDVI chain (research doc §9.2 Workflow B),
# with a memory layer and a failed-then-retried step
# ===========================================================================

W2_STEPS = [
    # (name, algorithm_id, algorithm_name, output path, output layer_type, params)
    ("merge", "gdal:merge", "Merge", "/work/ndvi/merged.tif", "raster",
     {"DATA_TYPE": 5, "SEPARATE": True}),
    ("reproject", "gdal:warpreproject", "Warp (reproject)",
     "/work/ndvi/reprojected.tif", "raster",
     {"TARGET_CRS": "EPSG:32643", "RESAMPLING": 0}),
    ("clip", "gdal:cliprasterbymasklayer", "Clip raster by mask layer",
     None, "raster", {"CROP_TO_CUTLINE": True}),          # <- memory layer
    ("ndvi", "qgis:rastercalculator", "Raster calculator",
     "/work/ndvi/ndvi.tif", "raster",
     {"EXPRESSION": "(B8 - B4) / (B8 + B4)", "CELLSIZE": 10}),
    ("reclassify", "native:reclassifybytable", "Reclassify by table",
     "/work/ndvi/classes.tif", "raster", {"NODATA_FOR_MISSING": True, "RANGE_BOUNDARIES": 0}),
    ("polygonize", "gdal:polygonize", "Polygonize",
     "/work/ndvi/classes.gpkg", "vector", {"FIELD": "class", "EIGHT_CONNECTEDNESS": False}),
    ("dissolve", "native:dissolve", "Dissolve",
     "/work/ndvi/dissolved.gpkg", "vector", {"FIELD": ["class"], "SEPARATE_DISJOINT": False}),
    ("addarea", "qgis:fieldcalculator", "Field calculator",
     "/work/ndvi/land_cover.gpkg", "vector",
     {"FIELD_NAME": "area_ha", "FORMULA": "$area / 10000"}),
]


def build_workflow_2(store: ProvenanceStore, agent: str) -> list[dict]:
    session = fid("session/w2")
    events: list[dict] = []

    with store.transaction():
        band4 = store.add_entity(entity_id=fid("w2/band4"), label="B04.jp2",
                                 file_path="/data/sentinel2/B04.jp2", format="JP2000",
                                 crs="EPSG:32643", layer_type="raster", created_at=ts(100))
        band8 = store.add_entity(entity_id=fid("w2/band8"), label="B08.jp2",
                                 file_path="/data/sentinel2/B08.jp2", format="JP2000",
                                 crs="EPSG:32643", layer_type="raster", created_at=ts(101))
        study = store.add_entity(entity_id=fid("w2/study_area"), label="study_area.shp",
                                 file_path="/data/study_area.shp", format="Shapefile",
                                 crs="EPSG:32643", layer_type="vector", created_at=ts(102))

        workflow = store.add_workflow(
            workflow_id=fid("w2"), name="Sentinel-2 NDVI land cover",
            description="Research doc §9.2 Workflow B. Contains a memory layer "
                        "(path=None) that Person B must NOT try to hash, and a "
                        "failed step that was retried (§4.10).",
            session_id=session, created_at=ts(103))

        # A first attempt at the reproject that failed. §4.10 — recorded, not
        # dropped: Person C's audit needs it and RQ1 completeness counts it.
        failed = store.add_activity(
            activity_id=fid("w2/reproject_failed"), algorithm_id="gdal:warpreproject",
            algorithm_name="Warp (reproject)", provider="gdal", session_id=session,
            started_at=ts(120), ended_at=ts(121), status="failed",
            parameters={"TARGET_CRS": "EPSG:32643", "RESAMPLING": 0},
            execution_log="ERROR 1: Attempt to create new tiff file failed: "
                          "No space left on device",
            capture_channel="post_hook", dedup_key="w2-reproject-failed")
        _relation(store, relation_type="wasAssociatedWith", source_id=failed,
                           target_id=agent, created_at=ts(121))
        store.add_workflow_activity(workflow_id=workflow, activity_id=failed,
                                    sequence_order=0)
        events.append(
            _event("w2/reproject_failed", session, "gdal:warpreproject",
                   "Warp (reproject)", ts(120), ts(121), status="failed",
                   parameters={"TARGET_CRS": "EPSG:32643", "RESAMPLING": 0},
                   inputs=[_layer("INPUT", "/work/ndvi/merged.tif", "GeoTIFF",
                                  "EPSG:32643", "raster", **S2_RASTER)],
                   outputs=[], agent=QGIS_334, provider="gdal",
                   execution_log="ERROR 1: Attempt to create new tiff file failed: "
                                 "No space left on device"))

        previous = None
        for index, (name, alg_id, alg_name, out_path, out_type, params) in enumerate(W2_STEPS):
            started, ended = ts(200 + index * 10), ts(205 + index * 10)
            provider = alg_id.split(":")[0]
            provider = {"qgis": "qgis", "native": "qgis", "gdal": "gdal"}.get(provider, provider)

            activity = store.add_activity(
                activity_id=fid(f"w2/{name}"), algorithm_id=alg_id,
                algorithm_name=alg_name, provider=provider, session_id=session,
                started_at=started, ended_at=ended, parameters=params,
                capture_channel="post_hook", dedup_key=f"w2-{name}")

            # path=None marks the memory / TEMPORARY_OUTPUT layer (§3.3).
            output = store.add_entity(
                entity_id=fid(f"w2/out/{name}"),
                label=pathlib.Path(out_path).name if out_path else "Clipped (temporary)",
                file_path=out_path,
                format=None if out_path is None else (
                    "GeoTIFF" if out_path.endswith(".tif") else "GeoPackage"),
                crs="EPSG:32643", layer_type=out_type, created_at=ended,
                metadata={"temporary": out_path is None})

            step_inputs: list[str] = []
            if index == 0:
                step_inputs = [band4, band8]
            else:
                step_inputs = [previous]
            if name == "clip":
                step_inputs.append(study)

            for source in step_inputs:
                role = "overlay" if source == study else "input"
                key = "MASK" if source == study else "INPUT"
                _relation(store, relation_type="used", source_id=activity,
                                   target_id=source, role=role, qgis_param_key=key,
                                   created_at=started)
                _relation(store, relation_type="wasDerivedFrom", source_id=output,
                                   target_id=source, created_at=ended)
            _relation(store, relation_type="wasGeneratedBy", source_id=output,
                               target_id=activity, role="output",
                               qgis_param_key="OUTPUT", created_at=ended)
            _relation(store, relation_type="wasAssociatedWith", source_id=activity,
                               target_id=agent, created_at=ended)
            store.add_workflow_activity(workflow_id=workflow, activity_id=activity,
                                        sequence_order=index + 1)

            # No fingerprint for the memory layer — there is no file to hash.
            if out_path is not None:
                store.add_fingerprint(
                    fingerprint_id=fid(f"w2/fp/{name}"), entity_id=output,
                    hash_value=fake_hash(f"w2/{name}"), hash_strategy="file",
                    file_size_bytes=1_048_576 + index * 4096,
                    computed_at=ts(206 + index * 10))

            events.append(_event(
                f"w2/{name}", session, alg_id, alg_name, started, ended,
                parameters=params, provider=provider,
                inputs=[_entity_layer(store, e, key="INPUT") for e in step_inputs],
                outputs=[_entity_layer(store, output, key="OUTPUT")],
                agent=QGIS_334))
            previous = output

        for name, entity in (("band4", band4), ("band8", band8), ("study_area", study)):
            store.add_fingerprint(
                fingerprint_id=fid(f"w2/fp/{name}"), entity_id=entity,
                hash_value=fake_hash(f"w2/{name}"), hash_strategy="file",
                file_size_bytes=120_586_240, computed_at=ts(110))

    return events


# ===========================================================================
# workflow 3 — a BRANCH plus a RE-RUN, over files that really exist on disk
# ===========================================================================

def build_workflow_3(store: ProvenanceStore, agent: str) -> list[dict]:
    session = fid("session/w3")
    shp = {"format": "Shapefile", "crs": "EPSG:4326", "layer_type": "vector"}
    gpkg = {"format": "GeoPackage", "crs": "EPSG:4326", "layer_type": "vector"}

    # Relative to tests/fixtures/ — see README.md. Absolute paths would be
    # machine-specific and useless to B and C once committed.
    points_path = "data/sample_points.shp"
    areas_path = "data/sample_areas.gpkg"

    with store.transaction():
        points = store.add_entity(entity_id=fid("w3/points"), label="sample_points.shp",
                                  file_path=points_path, created_at=ts(300), **shp)
        areas = store.add_entity(entity_id=fid("w3/areas"), label="sample_areas.gpkg",
                                 file_path=areas_path, created_at=ts(301), **gpkg)
        buffered_v1 = store.add_entity(
            entity_id=fid("w3/buffered/v1"), label="points_buffered.shp",
            file_path="data/derived/points_buffered.shp", content_version=1,
            created_at=ts(302), **shp)
        matching = store.add_entity(entity_id=fid("w3/matching"), label="urban.shp",
                                    file_path="data/derived/urban.shp",
                                    created_at=ts(303), **shp)
        nonmatching = store.add_entity(entity_id=fid("w3/nonmatching"),
                                       label="not_urban.shp",
                                       file_path="data/derived/not_urban.shp",
                                       created_at=ts(304), **shp)
        dissolved = store.add_entity(entity_id=fid("w3/dissolved"),
                                     label="urban_dissolved.gpkg",
                                     file_path="data/derived/urban_dissolved.gpkg",
                                     created_at=ts(305), **gpkg)
        centroids = store.add_entity(entity_id=fid("w3/centroids"),
                                     label="not_urban_centroids.shp",
                                     file_path="data/derived/not_urban_centroids.shp",
                                     created_at=ts(306), **shp)
        # Appendix B.1: the SECOND run overwrites points_buffered.shp, so the
        # same path gets a NEW row at content_version 2 rather than an update.
        buffered_v2 = store.add_entity(
            entity_id=fid("w3/buffered/v2"), label="points_buffered.shp",
            file_path="data/derived/points_buffered.shp", content_version=2,
            created_at=ts(400), **shp)

        workflow = store.add_workflow(
            workflow_id=fid("w3"), name="Points analysis (branching)",
            description="One job with TWO outputs feeding two different downstream "
                        "steps, plus a re-run that overwrites a file and so creates "
                        "content_version 2 of the same path (Appendix B.1). Inputs "
                        "are real files under tests/fixtures/data/.",
            session_id=session, created_at=ts(307))

        def step(order, name, alg_id, alg_name, started, ended, params, ins, outs):
            activity = store.add_activity(
                activity_id=fid(f"w3/{name}"), algorithm_id=alg_id,
                algorithm_name=alg_name, provider="qgis", session_id=session,
                started_at=started, ended_at=ended, parameters=params,
                capture_channel="post_hook" if order % 2 == 0 else "history_signal",
                dedup_key=f"w3-{name}")
            for entity, role, key in ins:
                _relation(store, relation_type="used", source_id=activity,
                                   target_id=entity, role=role, qgis_param_key=key,
                                   created_at=started)
            for entity, key in outs:
                _relation(store, relation_type="wasGeneratedBy", source_id=entity,
                                   target_id=activity, role="output",
                                   qgis_param_key=key, created_at=ended)
                for source, _, _ in ins:
                    _relation(store, relation_type="wasDerivedFrom",
                                       source_id=entity, target_id=source,
                                       created_at=ended)
            _relation(store, relation_type="wasAssociatedWith", source_id=activity,
                               target_id=agent, created_at=ended)
            store.add_workflow_activity(workflow_id=workflow, activity_id=activity,
                                        sequence_order=order)
            return activity

        step(0, "buffer", "native:buffer", "Buffer", ts(310), ts(311),
             {"DISTANCE": 0.01, "SEGMENTS": 8, "DISSOLVE": False},
             [(points, "input", "INPUT")], [(buffered_v1, "OUTPUT")])

        # THE BRANCH: one activity, two outputs, each feeding a different step.
        step(1, "extract", "native:extractbyattribute", "Extract by attribute",
             ts(320), ts(321),
             {"FIELD": "category", "OPERATOR": 0, "VALUE": "urban"},
             [(buffered_v1, "input", "INPUT")],
             [(matching, "OUTPUT"), (nonmatching, "FAIL_OUTPUT")])

        step(2, "dissolve", "native:dissolve", "Dissolve", ts(330), ts(332),
             {"FIELD": ["category"], "SEPARATE_DISJOINT": False},
             [(matching, "input", "INPUT"), (areas, "overlay", "OVERLAY")],
             [(dissolved, "OUTPUT")])

        step(3, "centroids", "native:centroids", "Centroids", ts(340), ts(341),
             {"ALL_PARTS": False},
             [(nonmatching, "input", "INPUT")], [(centroids, "OUTPUT")])

        # The re-run. Same algorithm, same input, same output PATH, new version.
        step(4, "buffer_rerun", "native:buffer", "Buffer", ts(410), ts(411),
             {"DISTANCE": 0.02, "SEGMENTS": 8, "DISSOLVE": False},
             [(points, "input", "INPUT")], [(buffered_v2, "OUTPUT")])

        # Real files get fingerprints computed from their actual bytes, so
        # Person B has a value to check their own implementation against.
        for name, entity, disk_path in (
            ("points", points, DATA_DIR / "sample_points.shp"),
            ("areas", areas, DATA_DIR / "sample_areas.gpkg"),
        ):
            payload = disk_path.read_bytes()
            store.add_fingerprint(
                fingerprint_id=fid(f"w3/fp/{name}"), entity_id=entity,
                hash_value=hashlib.sha256(payload).hexdigest(), hash_strategy="file",
                file_size_bytes=len(payload), feature_count=8 if name == "points" else 4,
                computed_at=ts(309))

        for offset, (name, entity) in enumerate(
            (("buffered_v1", buffered_v1), ("matching", matching),
             ("nonmatching", nonmatching), ("dissolved", dissolved),
             ("centroids", centroids), ("buffered_v2", buffered_v2))
        ):
            store.add_fingerprint(
                fingerprint_id=fid(f"w3/fp/{name}"), entity_id=entity,
                hash_value=fake_hash(f"w3/{name}"), hash_strategy="file",
                file_size_bytes=2048 + offset * 128, feature_count=8 - offset,
                computed_at=ts(350 + offset))

    def layer(path, fmt, count):
        return {"format": fmt, "crs": "EPSG:4326", "layer_type": "vector",
                "feature_count": count, "path": path}

    return [
        _event("w3/buffer", session, "native:buffer", "Buffer", ts(310), ts(311),
               parameters={"DISTANCE": 0.01, "SEGMENTS": 8, "DISSOLVE": False},
               inputs=[_layer("INPUT", points_path, "Shapefile", "EPSG:4326",
                              "vector", 8)],
               outputs=[_layer("OUTPUT", "data/derived/points_buffered.shp",
                               "Shapefile", "EPSG:4326", "vector", 8)],
               agent=QGIS_340),
        _event("w3/extract", session, "native:extractbyattribute",
               "Extract by attribute", ts(320), ts(321), source="history_signal",
               parameters={"FIELD": "category", "OPERATOR": 0, "VALUE": "urban"},
               inputs=[_layer("INPUT", "data/derived/points_buffered.shp",
                              "Shapefile", "EPSG:4326", "vector", 8)],
               outputs=[_layer("OUTPUT", "data/derived/urban.shp", "Shapefile",
                               "EPSG:4326", "vector", 4),
                        _layer("FAIL_OUTPUT", "data/derived/not_urban.shp",
                               "Shapefile", "EPSG:4326", "vector", 4)],
               agent=QGIS_340),
        _event("w3/dissolve", session, "native:dissolve", "Dissolve", ts(330), ts(332),
               parameters={"FIELD": ["category"], "SEPARATE_DISJOINT": False},
               inputs=[_layer("INPUT", "data/derived/urban.shp", "Shapefile",
                              "EPSG:4326", "vector", 4),
                       _layer("OVERLAY", areas_path, "GeoPackage", "EPSG:4326", "vector", 4)],
               outputs=[_layer("OUTPUT", "data/derived/urban_dissolved.gpkg", "GeoPackage",
                               "EPSG:4326", "vector", 1)],
               agent=QGIS_340),
        _event("w3/centroids", session, "native:centroids", "Centroids",
               ts(340), ts(341), source="history_signal",
               parameters={"ALL_PARTS": False},
               inputs=[_layer("INPUT", "data/derived/not_urban.shp", "Shapefile",
                              "EPSG:4326", "vector", 4)],
               outputs=[_layer("OUTPUT", "data/derived/not_urban_centroids.shp",
                               "Shapefile", "EPSG:4326", "vector", 4)],
               agent=QGIS_340),
        _event("w3/buffer_rerun", session, "native:buffer", "Buffer",
               ts(410), ts(411),
               parameters={"DISTANCE": 0.02, "SEGMENTS": 8, "DISSOLVE": False},
               inputs=[_layer("INPUT", points_path, "Shapefile", "EPSG:4326",
                              "vector", 8)],
               outputs=[_layer("OUTPUT", "data/derived/points_buffered.shp",
                               "Shapefile", "EPSG:4326", "vector", 8)],
               agent=QGIS_340),
    ]


# ===========================================================================
# event-dict construction (docs/CONTRACT_event.md)
# ===========================================================================

def _layer(param, path, format=None, crs=None, layer_type="vector",  # noqa: A002
           feature_count=None, band_count=None, pixel_size=None,
           width=None, height=None):
    """One inputs/outputs entry (docs/CONTRACT_event.md).

    Every key is present whatever the layer type — vector fields are null on a
    raster and raster fields are null on a vector — so Person B's mapper tests
    for null, never for key presence.
    """
    return {"param": param, "path": path, "format": format, "crs": crs,
            "layer_type": layer_type, "feature_count": feature_count,
            "band_count": band_count, "pixel_size": pixel_size,
            "width": width, "height": height}


#: Plausible Sentinel-2 raster metadata, so Person B's mapper meets a populated
#: raster entry in the fixtures rather than only ever seeing nulls.
S2_RASTER = {"band_count": 1, "pixel_size": [10.0, 10.0], "width": 10980, "height": 10980}


def _entity_layer(store: ProvenanceStore, entity_id: str, key: str) -> dict:
    row = store.get_entity(entity_id)
    raster = S2_RASTER if (row["layer_type"] or "") == "raster" else {}
    return _layer(key, row["file_path"], row["format"], row["crs"],
                  row["layer_type"] or "unknown", **raster)


def _event(name, session, algorithm_id, algorithm_name, started, ended, *,
           parameters, inputs, outputs, agent, status="completed",
           source="post_hook", provider="qgis", execution_log=None) -> dict:
    return {
        "event_id": fid(f"event/{name}"),
        "session_id": session,
        "source": source,
        "algorithm_id": algorithm_id,
        "algorithm_name": algorithm_name,
        "provider": provider,
        "started_at": started,
        "ended_at": ended,
        "status": status,
        "parameters": parameters,
        "inputs": inputs,
        "outputs": outputs,
        "agent": agent,
        "execution_log": execution_log,
    }


def validate_events(events: list[dict]) -> None:
    """Every event must validate against the frozen JSON Schema (§3.1)."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("  ! jsonschema not installed — events NOT validated. "
              "Run `make venv` (RULES.md §2.3).")
        return

    schema = json.loads((REPO_ROOT / "schemas" / "event.schema.json").read_text())
    validator = Draft202012Validator(schema)
    problems = []
    for event in events:
        for error in validator.iter_errors(event):
            problems.append(f"{event['algorithm_id']} @ {list(error.path)}: {error.message}")
    if problems:
        raise SystemExit(
            "Events do not match schemas/event.schema.json:\n  "
            + "\n  ".join(problems)
        )
    print(f"  validated {len(events)} events against event.schema.json")


# ===========================================================================

def main(out_dir: pathlib.Path | None = None) -> int:
    """Build the whole fixture set. Returns a process exit code.

    ``out_dir`` defaults to this directory; the determinism test passes a
    temporary one so it can build twice and compare without touching the
    committed fixtures. pytest captures the printed report.
    """
    if out_dir is not None:
        use_output_dir(out_dir)
    _ids.clear()  # so a second call in the same process starts clean

    previous_digest = _digest()

    for stale in (MOCK_DB, MOCK_DB.with_suffix(".db-wal"), MOCK_DB.with_suffix(".db-shm")):
        stale.unlink(missing_ok=True)

    print(f"Building fixtures in {OUT_DIR}")
    data_files = build_data_files()
    for path in data_files:
        print(f"  data/{path.name:<22} {path.stat().st_size:>7,} bytes")

    events: list[dict] = []
    with ProvenanceStore(MOCK_DB) as store:
        # add_agent rather than get_or_create_agent, purely so the ids are
        # deterministic — get_or_create_agent mints a uuid4 by design, which is
        # right in production and wrong for a committed fixture. The
        # env_fingerprint is computed exactly as get_or_create_agent would, so
        # a later get_or_create_agent call with the same environment still
        # de-duplicates onto these rows (§4.6).
        agent_334 = _agent("agent/qgis-3.34.8", QGIS_334, store, ts(0))
        agent_340 = _agent("agent/qgis-3.40.0", QGIS_340, store, ts(1))
        events += build_workflow_1(store, agent_334)
        events += build_workflow_2(store, agent_334)
        events += build_workflow_3(store, agent_340)
        counts = store.counts()

    # The committed database must be byte-identical on B's and C's machines
    # too, and SQLite stamps its own version into every file it writes
    # (see _minifiles.normalise_sqlite_header). Done after the store is closed
    # so nothing is rewritten underneath an open connection.
    normalise_sqlite_header(MOCK_DB)

    validate_events(events)
    MOCK_EVENTS.write_text(json.dumps(events, indent=2, sort_keys=False) + "\n")
    MOCK_IDS.write_text(json.dumps(_ids, indent=2, sort_keys=True) + "\n")

    print(f"  mock_provenance.db     {MOCK_DB.stat().st_size:>7,} bytes")
    print(f"  mock_events.json       {MOCK_EVENTS.stat().st_size:>7,} bytes "
          f"({len(events)} events)")
    print(f"  mock_ids.json          {MOCK_IDS.stat().st_size:>7,} bytes "
          f"({len(_ids)} names)")
    print("  rows: " + ", ".join(f"{k}={v}" for k, v in counts.items()))

    digest = _digest()
    if previous_digest is None:
        print("\nFixtures created.")
    elif digest == previous_digest:
        print("\nByte-identical to the previous build — nothing changed.")
    else:
        print("\nFIXTURES CHANGED. RULES.md §3.4 step 5: tell Person B and Person C "
              "what changed and what they must update.")
    return 0


def _digest() -> str | None:
    """Hash of every generated file, for the changed/unchanged report."""
    paths = sorted(
        p for p in [MOCK_DB, MOCK_EVENTS, MOCK_IDS, *DATA_DIR.glob("*")] if p.is_file()
    )
    if not paths:
        return None
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
