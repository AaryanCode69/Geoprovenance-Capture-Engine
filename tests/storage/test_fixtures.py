"""The shared fixtures Person B and Person C consume (A0.3).

RULES.md §6.1 — no QGIS. This suite IS the Phase 0 exit criterion made
executable: everything here reads the fixtures using nothing but
``storage/store.py``, exactly as B and C will.

    make test-storage
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import pathlib
import sqlite3
import struct
import sys

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
DATA = FIXTURES / "data"
REPO_ROOT = FIXTURES.parents[1]

sys.path.insert(0, str(FIXTURES))

from geoprovenance.storage.store import ProvenanceStore  # noqa: E402


@pytest.fixture(scope="module")
def ids() -> dict[str, str]:
    return json.loads((FIXTURES / "mock_ids.json").read_text())


@pytest.fixture(scope="module")
def events() -> list[dict]:
    return json.loads((FIXTURES / "mock_events.json").read_text())


@pytest.fixture()
def fixture_store():
    """Opened exactly the way Person B and Person C will open it."""
    store = ProvenanceStore(FIXTURES / "mock_provenance.db")
    yield store
    store.close()


# ===========================================================================
# the files exist and are what they claim to be
# ===========================================================================

def test_all_fixture_artefacts_are_present():
    """PERSON_A.md §A0.3 — the four deliverables B and C were promised."""
    for name in ("mock_provenance.db", "mock_events.json", "mock_ids.json",
                 "build_fixtures.py"):
        assert (FIXTURES / name).is_file(), f"missing fixture: {name}"
    for name in ("sample_points.shp", "sample_points.shx", "sample_points.dbf",
                 "sample_points.prj", "sample_areas.gpkg"):
        assert (DATA / name).is_file(), f"missing data file: {name}"


def test_database_is_at_the_current_schema_version(fixture_store):
    assert fixture_store.schema_version() == 1


def test_row_counts_are_as_published(fixture_store):
    """If this fails after a schema change, RULES.md §3.4 step 3 was skipped."""
    assert fixture_store.counts() == {
        "entities": 23, "activities": 16, "agents": 2, "fingerprints": 22,
        "relations": 70, "workflows": 3, "workflow_activities": 16,
        "audit_results": 0,
    }


def test_three_workflows_are_published(fixture_store):
    names = {w["name"] for w in fixture_store.list_workflows()}
    assert names == {
        "Buffer then Clip",
        "Sentinel-2 NDVI land cover",
        "Points analysis (branching)",
    }


# ===========================================================================
# workflow 1 — the research doc §7.3 reference, verbatim
# ===========================================================================

def test_reference_workflow_matches_the_research_doc(fixture_store, ids):
    """Research doc §7.3: roads -> Buffer -> buffered -> Clip -> final."""
    graph = fixture_store.get_workflow_graph(ids["w1"])
    assert [a["algorithm_id"] for a in graph["activities"]] == [
        "native:buffer", "native:clip"
    ]
    assert {e["label"] for e in graph["entities"]} == {
        "roads.shp", "buffered_roads.shp", "city_boundary.shp", "final_roads.shp"
    }
    assert len(graph["relations"]) == 9  # §7.3 lists exactly nine


def test_reference_workflow_paths_do_not_exist_on_disk(fixture_store, ids):
    """Deliberate: Person C's audit needs a genuine 'input missing' case to
    score, not a synthetic one bolted on later."""
    graph = fixture_store.get_workflow_graph(ids["w1"])
    for entity in graph["entities"]:
        assert not pathlib.Path(entity["file_path"]).exists()


def test_overlay_role_keeps_the_original_qgis_key(fixture_store, ids):
    """Appendix B.2 — lowercase role, original key preserved separately."""
    relations = fixture_store.get_relations_for(ids["w1/clip"], direction="out")
    overlay = [r for r in relations if r["role"] == "overlay"]
    assert len(overlay) == 1
    assert overlay[0]["qgis_param_key"] == "OVERLAY"


# ===========================================================================
# workflow 2 — memory layer and a failed step
# ===========================================================================

def test_memory_layer_has_no_path_and_no_fingerprint(fixture_store, ids):
    """§3.3 — Person B must SKIP this, not hash it. If a fingerprint ever
    appears here, someone tried to hash a layer that has no file."""
    clipped = fixture_store.get_entity(ids["w2/out/clip"])
    assert clipped["file_path"] is None
    assert clipped["layer_type"] == "raster"
    assert fixture_store.get_fingerprints_for(clipped["id"]) == []


def test_failed_activity_is_present_with_its_log(fixture_store, ids):
    """§4.10 — failed runs are recorded, never dropped. C's audit needs them
    and RQ1 completeness counts them."""
    failed = fixture_store.get_activity(ids["w2/reproject_failed"])
    assert failed["status"] == "failed"
    assert "No space left on device" in failed["execution_log"]


def test_failed_step_is_part_of_the_workflow_sequence(fixture_store, ids):
    graph = fixture_store.get_workflow_graph(ids["w2"])
    statuses = [a["status"] for a in graph["activities"]]
    assert statuses.count("failed") == 1
    assert statuses.count("completed") == 8  # the eight-step chain


def test_eight_step_chain_is_ordered(fixture_store, ids):
    graph = fixture_store.get_workflow_graph(ids["w2"])
    orders = [a["sequence_order"] for a in graph["activities"]]
    assert orders == sorted(orders)
    assert len(orders) == 9  # 8 successful steps plus the failed attempt


# ===========================================================================
# workflow 3 — the branch, the re-run, and real files
# ===========================================================================

def test_one_activity_produces_two_outputs(fixture_store, ids):
    """PERSON_A.md §A0.3 — Person C's layout code must meet a non-linear graph
    early, not in week 10."""
    generated = [
        r for r in fixture_store.get_relations_for(ids["w3/extract"], direction="in")
        if r["relation_type"] == "wasGeneratedBy"
    ]
    assert len(generated) == 2
    assert {r["qgis_param_key"] for r in generated} == {"OUTPUT", "FAIL_OUTPUT"}


def test_the_two_branches_feed_different_downstream_steps(fixture_store, ids):
    matching_users = {
        r["source_id"]
        for r in fixture_store.get_relations_for(ids["w3/matching"], direction="in")
        if r["relation_type"] == "used"
    }
    other_users = {
        r["source_id"]
        for r in fixture_store.get_relations_for(ids["w3/nonmatching"], direction="in")
        if r["relation_type"] == "used"
    }
    assert matching_users == {ids["w3/dissolve"]}
    assert other_users == {ids["w3/centroids"]}
    assert matching_users != other_users


def test_a_rerun_creates_a_second_content_version(fixture_store):
    """Appendix B.1 — a file overwritten by a second run is a NEW entity row,
    not an update. This is what lets the graph tell 'before' from 'after'."""
    versions = fixture_store.list_entity_versions("data/derived/points_buffered.shp")
    assert [v["content_version"] for v in versions] == [1, 2]
    assert versions[0]["id"] != versions[1]["id"]
    assert fixture_store.find_entity_by_path(
        "data/derived/points_buffered.shp"
    )["content_version"] == 2


def test_real_input_files_exist_and_their_recorded_hash_is_correct(fixture_store, ids):
    """Person B's fingerprinter has real bytes to hash and a value to check
    against. Paths are relative to tests/fixtures/ — see that README."""
    for key, filename in (("w3/points", "sample_points.shp"),
                          ("w3/areas", "sample_areas.gpkg")):
        entity = fixture_store.get_entity(ids[key])
        on_disk = FIXTURES / entity["file_path"]
        assert on_disk.is_file(), f"{entity['file_path']} is missing"

        recorded = fixture_store.get_latest_fingerprint(entity["id"])
        assert recorded["hash_algorithm"] == "SHA-256"
        assert recorded["hash_value"] == hashlib.sha256(on_disk.read_bytes()).hexdigest()
        assert recorded["file_size_bytes"] == on_disk.stat().st_size


def test_two_distinct_environments_are_recorded(fixture_store):
    """Person C's 'environment similar' check needs something to vary on."""
    agents = fixture_store._connection().execute(
        "SELECT qgis_version, env_fingerprint FROM agents ORDER BY qgis_version"
    ).fetchall()
    assert [a["qgis_version"] for a in agents] == ["3.34.8", "3.40.0"]
    assert agents[0]["env_fingerprint"] != agents[1]["env_fingerprint"]


# ===========================================================================
# the event dicts Person B consumes
# ===========================================================================

def test_every_event_validates_against_the_frozen_schema(events):
    """§3.1 — mock_events.json is only useful to B if it matches the contract."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((REPO_ROOT / "schemas" / "event.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    problems = [
        f"{e['algorithm_id']} {list(err.path)}: {err.message}"
        for e in events
        for err in validator.iter_errors(e)
    ]
    assert not problems, problems


def test_events_cover_every_activity_in_the_database(events, fixture_store):
    assert len(events) == fixture_store.counts()["activities"]


def test_events_are_json_serialisable_without_help(events):
    """§3.3 — Person B can rely on json.dumps(event) never raising, because the
    normalizer has already flattened every awkward QGIS type."""
    assert json.dumps(events)


def test_events_include_every_capture_channel(events):
    """§5.9 / §8.3 — B and C should see every channel in test data, because
    production has every channel.

    This asserted only two of the three until 19 Aug 2026. `run_wrapper` has
    been a legal `source` since A3 and is in both docs/CONTRACT_event.md and
    schemas/event.schema.json, but no fixture event carried it — so Person B's
    `source` handling never met its third case in the data B develops against.
    """
    assert {e["source"] for e in events} == {
        "post_hook", "run_wrapper", "history_signal"
    }


def test_a_corroborated_job_is_in_the_fixture_set(fixture_store):
    """§5.9 — a job both channels saw is stored ONCE with the counter moved.

    Nothing in the fixture set exercised that until 19 Aug 2026: every activity
    had corroborations = 0, so neither Person C's panel nor the RQ1 per-channel
    split (§8.3) had a single example to develop against.
    """
    corroborated = [
        a for a in fixture_store._connection().execute(
            "SELECT * FROM activities WHERE corroborations > 0"
        )
    ]
    assert corroborated, "no corroborated job in the fixtures"


def test_a_failed_event_is_present(events):
    failed = [e for e in events if e["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["outputs"] == []


def test_memory_layer_event_carries_layer_type_but_no_path(events):
    """§3.3 — the rule B will hit first."""
    null_paths = [
        layer
        for event in events
        for layer in event["inputs"] + event["outputs"]
        if layer["path"] is None
    ]
    assert null_paths, "no memory-layer case in the fixtures"
    assert all(layer["layer_type"] for layer in null_paths)


# ===========================================================================
# mock_ids.json — the readable-name map
# ===========================================================================

def test_every_published_id_resolves_in_the_database(fixture_store, ids):
    """mock_ids.json exists so B and C write IDS['w1/buffer'] instead of pasting
    a UUID. Every entry must actually resolve."""
    unresolved = []
    for name, value in ids.items():
        if name.startswith(("session/", "event/")):
            continue  # not primary keys in any table
        found = (
            fixture_store.get_entity(value)
            or fixture_store.get_activity(value)
            or fixture_store.get_agent(value)
            or fixture_store.get_workflow(value)
            or fixture_store._connection().execute(
                "SELECT 1 FROM fingerprints WHERE id = ?", (value,)
            ).fetchone()
        )
        if not found:
            unresolved.append(name)
    assert not unresolved, unresolved


# ===========================================================================
# determinism — RULES.md §10.3, the fixtures are committed
# ===========================================================================

def test_rebuilding_produces_byte_identical_fixtures(tmp_path):
    """Two full builds into two directories must match byte for byte.

    Without this, every regeneration churns the committed diff and a real
    change hides among the noise. Relations and agents both had uuid4 ids
    when this was first written, and both were caught here.
    """
    import build_fixtures

    first, second = tmp_path / "a", tmp_path / "b"
    with contextlib.redirect_stdout(io.StringIO()):
        build_fixtures.main(first)
        build_fixtures.main(second)

    produced = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert len(produced) == 8

    differing = [
        str(rel) for rel in produced
        if (first / rel).read_bytes() != (second / rel).read_bytes()
    ]
    assert not differing, f"non-deterministic fixture output: {differing}"


#: Suffixes whose bytes are written by the SQLite library rather than by us.
_SQLITE_SUFFIXES = (".db", ".gpkg")


def _logical_content(path: pathlib.Path) -> bytes:
    """A canonical dump of a SQLite file, independent of the SQLite build.

    Bytes 96-99 of every SQLite file are SQLITE_VERSION_NUMBER — the version of
    the library that wrote it — and later releases also shift page layout
    slightly. So a byte comparison of a committed .db against a fresh build
    answers "was this written by the same SQLite?", not the question
    RULES.md §10.3 actually asks, which is "did somebody hand-edit it?".

    Person B and Person C run this suite on their own machines. Comparing bytes
    made this test fail for them on any different SQLite build, with a message
    telling them to regenerate the committed artefact and notify the team —
    which would churn the shared fixture on every such run. The schema and the
    rows are what B and C consume, so those are what is compared.
    """
    with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        return "\n".join(conn.iterdump()).encode("utf-8")


def _fixture_content(path: pathlib.Path) -> bytes:
    if path.suffix in _SQLITE_SUFFIXES:
        return _logical_content(path)
    return path.read_bytes()


def test_committed_fixtures_match_a_fresh_build(tmp_path):
    """The committed files are what build_fixtures.py currently produces —
    i.e. nobody hand-edited them (RULES.md §10.3).

    SQLite files are compared by their contents rather than their bytes; see
    _logical_content for why the difference matters to B and C.
    """
    import build_fixtures

    fresh = tmp_path / "fresh"
    with contextlib.redirect_stdout(io.StringIO()):
        build_fixtures.main(fresh)

    stale = []
    for rel in sorted(p.relative_to(fresh) for p in fresh.rglob("*") if p.is_file()):
        committed = FIXTURES / rel
        if not committed.is_file():
            stale.append(str(rel))
        elif _fixture_content(committed) != _fixture_content(fresh / rel):
            stale.append(str(rel))
    assert not stale, (
        f"committed fixtures differ from a fresh build: {stale}. "
        f"Run `make fixtures`, and tell B and C (RULES.md §3.4 step 5)."
    )


# ===========================================================================
# the data files are structurally valid
#
# Parsed here against the format specifications rather than with GDAL, which
# is not installed. This catches a malformed header, a wrong file length or a
# bad record count; it does NOT prove QGIS will open them. That check belongs
# in the capture suite once a QGIS dev profile exists — see
# docs/capture_coverage.md.
# ===========================================================================

def test_shapefile_header_and_records_are_well_formed():
    shp = (DATA / "sample_points.shp").read_bytes()
    assert struct.unpack(">i", shp[0:4])[0] == 9994          # file code
    assert struct.unpack("<i", shp[28:32])[0] == 1000        # version
    assert struct.unpack("<i", shp[32:36])[0] == 1           # shape type: point
    assert struct.unpack(">i", shp[24:28])[0] * 2 == len(shp)  # declared length

    count, offset = 0, 100
    while offset < len(shp):
        number, content_words = struct.unpack(">2i", shp[offset:offset + 8])
        count += 1
        assert number == count                                # 1-based, contiguous
        assert content_words == 10                            # a point is 10 words
        offset += 8 + content_words * 2
    assert count == 8


def test_shapefile_index_matches_the_shapefile():
    shx = (DATA / "sample_points.shx").read_bytes()
    assert struct.unpack(">i", shx[24:28])[0] * 2 == len(shx)
    assert (len(shx) - 100) // 8 == 8
    for i in range(8):
        record_offset, content_words = struct.unpack(">2i", shx[100 + i * 8:108 + i * 8])
        assert record_offset == (100 + i * 28) // 2
        assert content_words == 10


def test_dbf_declares_the_right_record_and_field_layout():
    dbf = (DATA / "sample_points.dbf").read_bytes()
    assert dbf[0] == 0x03                                     # dBASE III
    num_records, header_len, record_len = struct.unpack("<IHH", dbf[4:12])
    assert num_records == 8
    assert (header_len - 33) // 32 == 2                        # name, category
    assert record_len == 1 + 16 + 12
    assert len(dbf) == header_len + num_records * record_len + 1
    assert dbf[-1] == 0x1A                                     # EOF marker
    assert b"site_00" in dbf and b"urban" in dbf


def test_geopackage_declares_itself_and_has_the_required_tables():
    import sqlite3

    gpkg = DATA / "sample_areas.gpkg"
    assert gpkg.read_bytes()[68:72] == b"GPKG"  # application_id in the SQLite header

    conn = sqlite3.connect(gpkg)
    try:
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"gpkg_contents", "gpkg_spatial_ref_sys", "gpkg_geometry_columns",
                "sample_areas"} <= tables

        srs = {r[0] for r in conn.execute("SELECT srs_id FROM gpkg_spatial_ref_sys")}
        assert {4326, -1, 0} <= srs  # the three the specification requires

        data_type, srs_id = conn.execute(
            "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name='sample_areas'"
        ).fetchone()
        assert (data_type, srs_id) == ("features", 4326)
        assert conn.execute("SELECT count(*) FROM sample_areas").fetchone()[0] == 4
    finally:
        conn.close()


def test_geopackage_geometry_blobs_parse_as_wkb_points():
    import sqlite3

    conn = sqlite3.connect(DATA / "sample_areas.gpkg")
    try:
        rows = conn.execute("SELECT geom FROM sample_areas ORDER BY fid").fetchall()
    finally:
        conn.close()

    for (blob,) in rows:
        assert blob[:2] == b"GP"                       # GeoPackageBinary magic
        assert blob[2] == 0                            # version
        assert blob[3] & 0b1 == 1                      # little-endian header
        assert struct.unpack("<i", blob[4:8])[0] == 4326
        byte_order, geom_type = struct.unpack("<BI", blob[8:13])
        assert (byte_order, geom_type) == (1, 1)       # little-endian WKB point
        longitude, latitude = struct.unpack("<2d", blob[13:29])
        assert 77 < longitude < 78 and 12 < latitude < 14


# ===========================================================================
# PERSON_A.md §A0.3 exit criterion
# ===========================================================================

def test_consumers_need_nothing_from_person_a_beyond_the_store(fixture_store, ids):
    """The Phase 0 exit criterion, executed.

    A Person C-shaped read: open the database, list workflows, pull one graph,
    walk backwards from an output to its source. No QGIS, no capture engine, no
    Person A code beyond storage/store.py.
    """
    workflows = fixture_store.list_workflows()
    assert workflows

    graph = fixture_store.get_workflow_graph(ids["w3"])
    assert graph["activities"] and graph["entities"] and graph["relations"]

    # Walk back from the dissolved output to the job that made it.
    incoming = fixture_store.get_relations_for(ids["w3/dissolved"], direction="out")
    generated_by = [r for r in incoming if r["relation_type"] == "wasGeneratedBy"]
    assert len(generated_by) == 1
    producer = fixture_store.get_activity(generated_by[0]["target_id"])
    assert producer["algorithm_id"] == "native:dissolve"
