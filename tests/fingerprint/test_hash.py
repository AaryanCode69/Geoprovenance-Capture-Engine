"""SHA-256 fingerprinting — Person B, research doc §4.3 Layer 3 and §6.4.

RULES.md §6.1 — no QGIS anywhere in this file. A fingerprint needs a file path
and nothing else, so this whole suite runs under `make test`.

The two hashes in `mock_provenance.db` for `data/sample_points.shp` and
`data/sample_areas.gpkg` are GENUINE SHA-256 hashes of those bytes
(tests/fixtures/README.md). They are the ground truth here: if this
fingerprinter disagrees with them, this fingerprinter is wrong.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sqlite3

import pytest

from geoprovenance.fingerprint import (
    HASH_ALGORITHM,
    LARGE_FILE_THRESHOLD_BYTES,
    STRATEGY_FILE,
    STRATEGY_SCHEMA_SAMPLE,
    Fingerprint,
    FingerprintError,
    can_fingerprint,
    fingerprint_file,
    sha256_file,
)
from geoprovenance.fingerprint.hash import _CHUNK_BYTES

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
DATA = FIXTURES / "data"


@pytest.fixture(scope="module")
def ids() -> dict[str, str]:
    return json.loads((FIXTURES / "mock_ids.json").read_text())


# ===========================================================================
# ground truth — the committed fixtures
# ===========================================================================

def test_matches_the_hash_pinned_for_the_shapefile():
    """The fingerprinter agrees with a known-good SHA-256, pinned in source.

    Hardcoded rather than read back out of the database on purpose: reading the
    expected value from the same place that would be wrong proves nothing.

    The Shapefile and not the GeoPackage, because only one of them is stable.
    `_minifiles.write_point_shapefile` packs the bytes itself in pure Python,
    so it is byte-identical on every machine. `sample_areas.gpkg` is written by
    SQLite, whose output depends on the local library's compile flags — a build
    without SQLITE_SECURE_DELETE leaves ~1000 residue bytes elsewhere, so the
    file's SHA-256 legitimately differs per machine (see `_logical_content` in
    tests/storage/test_fixtures.py). Pinning that hash here would make this
    suite fail for whichever teammate did not regenerate the fixtures last.
    The next test covers the GeoPackage the way that survives.
    """
    result = fingerprint_file(DATA / "sample_points.shp")
    assert result.hash_value == (
        "8263ffcfdaf626e05b5bbfc249b517f30b79727d96db71d3df8b68f28975da51"
    )
    assert result.file_size_bytes == 324
    assert result.hash_strategy == STRATEGY_FILE
    assert result.hash_algorithm == HASH_ALGORITHM


def test_the_fixture_database_agrees_with_what_we_compute(ids):
    """The same check, read back through Person A's store rather than pasted.

    Catches the case where the committed database and the committed data files
    drift apart — the failure that would otherwise surface as Person C's audit
    reporting a changed file that nobody changed.
    """
    from geoprovenance.storage.store import ProvenanceStore

    store = ProvenanceStore(FIXTURES / "mock_provenance.db")
    try:
        for key, filename in (
            ("w3/points", "sample_points.shp"),
            ("w3/areas", "sample_areas.gpkg"),
        ):
            recorded = store.get_latest_fingerprint(ids[key])
            computed = fingerprint_file(DATA / filename)
            assert recorded["hash_value"] == computed.hash_value, key
            assert recorded["file_size_bytes"] == computed.file_size_bytes, key
            assert recorded["hash_algorithm"] == computed.hash_algorithm, key
    finally:
        store.close()


# ===========================================================================
# the hash itself
# ===========================================================================

def test_agrees_with_hashlib_on_the_whole_file(tmp_path):
    payload = b"the quick brown fox" * 1000
    target = tmp_path / "payload.bin"
    target.write_bytes(payload)

    digest, size = sha256_file(target)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)


def test_a_file_larger_than_one_chunk_hashes_correctly(tmp_path):
    """Guards the streaming loop. A bug that drops or repeats a chunk is
    invisible on a small file and silent on a large one."""
    payload = bytes(range(256)) * ((_CHUNK_BYTES * 2) // 256 + 1)
    assert len(payload) > _CHUNK_BYTES * 2

    target = tmp_path / "big.bin"
    target.write_bytes(payload)

    digest, size = sha256_file(target)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)


def test_an_empty_file_hashes_rather_than_raising(tmp_path):
    """An empty output is a real thing QGIS produces — a clip with no overlap
    writes a valid file with zero features. It has a fingerprint like anything
    else, and it must not be mistaken for a missing file."""
    target = tmp_path / "empty.shp"
    target.write_bytes(b"")

    result = fingerprint_file(target)
    assert result.file_size_bytes == 0
    assert result.hash_value == hashlib.sha256(b"").hexdigest()
    assert result.hash_strategy == STRATEGY_FILE


def test_one_flipped_byte_changes_the_hash(tmp_path):
    """RQ3 is change-detection accuracy. This is the property being measured."""
    original = tmp_path / "a.bin"
    original.write_bytes(b"\x00" * 4096)
    modified = tmp_path / "b.bin"
    modified.write_bytes(b"\x00" * 4095 + b"\x01")

    assert fingerprint_file(original).hash_value != fingerprint_file(modified).hash_value


def test_hashing_the_same_file_twice_gives_the_same_answer(tmp_path):
    target = tmp_path / "stable.bin"
    target.write_bytes(b"stable content")
    assert fingerprint_file(target).hash_value == fingerprint_file(target).hash_value


# ===========================================================================
# what must NOT be hashed — CONTRACT_event.md rule 1
# ===========================================================================

@pytest.mark.parametrize(
    "path",
    [None, "", "   ", "memory:clipped", "/vsimem/scratch.tif", "TEMPORARY_OUTPUT"],
)
def test_layers_with_no_bytes_on_disk_are_not_fingerprintable(path):
    assert can_fingerprint(path) is False


@pytest.mark.parametrize("path", ["/data/roads.shp", "data/sample_points.shp"])
def test_real_paths_are_fingerprintable(path):
    """can_fingerprint answers "is this the kind of thing that has bytes",
    not "does this file exist" — an input that has gone missing is Person C's
    audit finding, and must not be confused with a memory layer."""
    assert can_fingerprint(path) is True


def test_fingerprinting_a_memory_layer_says_what_to_do_instead():
    with pytest.raises(FingerprintError, match="can_fingerprint"):
        fingerprint_file("memory:scratch")


def test_a_missing_file_raises_rather_than_returning_a_hash(tmp_path):
    with pytest.raises(FingerprintError, match="cannot stat"):
        fingerprint_file(tmp_path / "never_written.shp")


# ===========================================================================
# the §6.4 tiered fallback
# ===========================================================================

def test_a_file_under_the_threshold_is_hashed_in_full(tmp_path):
    target = tmp_path / "small.bin"
    target.write_bytes(b"x" * 100)

    result = fingerprint_file(target, threshold_bytes=1000)
    assert result.hash_strategy == STRATEGY_FILE
    assert result.hash_value == hashlib.sha256(b"x" * 100).hexdigest()


def test_a_file_over_the_threshold_falls_back_to_the_schema_hash(tmp_path):
    """Simulated with a low threshold rather than a 500 MB file — the branch is
    chosen by a size comparison, and writing half a gigabyte to prove it would
    make this suite unrunnable."""
    target = tmp_path / "large.gpkg"
    target.write_bytes(b"y" * 100)

    result = fingerprint_file(
        target, feature_count=1_000_000, field_names=["id", "name"], threshold_bytes=10
    )
    assert result.hash_strategy == STRATEGY_SCHEMA_SAMPLE
    assert result.file_size_bytes == 100
    assert result.feature_count == 1_000_000
    # It must NOT be the byte hash — that is the whole point of the fallback.
    assert result.hash_value != hashlib.sha256(b"y" * 100).hexdigest()


def test_the_schema_hash_changes_when_the_feature_count_does(tmp_path):
    target = tmp_path / "large.gpkg"
    target.write_bytes(b"y" * 100)

    before = fingerprint_file(
        target, feature_count=10, field_names=["id"], threshold_bytes=10
    )
    after = fingerprint_file(
        target, feature_count=11, field_names=["id"], threshold_bytes=10
    )
    assert before.hash_value != after.hash_value


def test_the_schema_hash_changes_when_a_field_is_renamed(tmp_path):
    target = tmp_path / "large.gpkg"
    target.write_bytes(b"y" * 100)

    before = fingerprint_file(
        target, feature_count=10, field_names=["id", "name"], threshold_bytes=10
    )
    after = fingerprint_file(
        target, feature_count=10, field_names=["id", "label"], threshold_bytes=10
    )
    assert before.hash_value != after.hash_value


def test_reordering_fields_is_treated_as_a_change(tmp_path):
    """Column order is part of a schema. Sorting field names before hashing
    would silently call two different schemas identical."""
    target = tmp_path / "large.gpkg"
    target.write_bytes(b"y" * 100)

    before = fingerprint_file(
        target, feature_count=10, field_names=["a", "b"], threshold_bytes=10
    )
    after = fingerprint_file(
        target, feature_count=10, field_names=["b", "a"], threshold_bytes=10
    )
    assert before.hash_value != after.hash_value


def test_the_schema_hash_is_stable_across_calls(tmp_path):
    target = tmp_path / "large.gpkg"
    target.write_bytes(b"y" * 100)

    kwargs = dict(feature_count=10, field_names=["id", "name"], threshold_bytes=10)
    assert (
        fingerprint_file(target, **kwargs).hash_value
        == fingerprint_file(target, **kwargs).hash_value
    )


def test_an_oversized_file_with_no_schema_information_refuses_to_guess(tmp_path):
    """Falling through to a hash of nothing would produce a confident wrong
    answer, which is worse for RQ3 than refusing."""
    target = tmp_path / "large.gpkg"
    target.write_bytes(b"y" * 100)

    with pytest.raises(FingerprintError, match="feature_count"):
        fingerprint_file(target, threshold_bytes=10)


# ===========================================================================
# rasters on the fallback path
#
# Rasters are the files that actually exceed the threshold — a Shapefile of 8
# points is 324 bytes, a Sentinel-2 tile is hundreds of megabytes — so the
# fallback has to describe a grid, not just a feature table. An earlier
# version described vectors only, which made every same-sized raster hash
# alike. These tests exist so that cannot come back.
# ===========================================================================

def _raster(tmp_path, name: str, size: int = 100) -> pathlib.Path:
    target = tmp_path / name
    target.write_bytes(b"\x00" * size)
    return target


def test_two_different_rasters_of_one_size_do_not_hash_alike(tmp_path):
    """The regression test for the defect this path was written to fix.

    A vector-only fallback reduced the digest to a hash of the byte count, so
    a 2020 elevation model and a 2024 one of identical size were reported as
    the same data.
    """
    before = fingerprint_file(
        _raster(tmp_path, "dem_2020.tif"),
        band_count=1, width=1200, height=800, pixel_size=[30.0, 30.0],
        threshold_bytes=10,
    )
    after = fingerprint_file(
        _raster(tmp_path, "dem_2024.tif"),
        band_count=1, width=1500, height=900, pixel_size=[30.0, 30.0],
        threshold_bytes=10,
    )
    assert before.hash_value != after.hash_value


def test_a_raster_falls_back_without_any_vector_information(tmp_path):
    """A raster has no features and no columns. Supplying only grid properties
    must be enough — requiring feature_count would make the raster path
    unusable, which is the half that needs it most."""
    result = fingerprint_file(
        _raster(tmp_path, "scene.tif"),
        band_count=3, width=1200, height=800, pixel_size=[30.0, 30.0],
        threshold_bytes=10,
    )
    assert result.hash_strategy == STRATEGY_SCHEMA_SAMPLE
    assert result.feature_count is None


@pytest.mark.parametrize(
    "changed",
    [
        {"band_count": 4},
        {"width": 1201},
        {"height": 801},
        {"pixel_size": [10.0, 10.0]},
    ],
)
def test_changing_any_grid_property_changes_the_digest(tmp_path, changed):
    base = dict(
        band_count=3, width=1200, height=800, pixel_size=[30.0, 30.0],
        threshold_bytes=10,
    )
    target = _raster(tmp_path, "scene.tif")

    before = fingerprint_file(target, **base)
    after = fingerprint_file(target, **{**base, **changed})
    assert before.hash_value != after.hash_value, changed


def test_pixel_size_order_matters(tmp_path):
    """[30, 10] and [10, 30] are different grids — one is stretched east-west,
    the other north-south. Sorting them would call the two identical."""
    target = _raster(tmp_path, "scene.tif")
    base = dict(band_count=1, width=100, height=100, threshold_bytes=10)

    wide = fingerprint_file(target, pixel_size=[30.0, 10.0], **base)
    tall = fingerprint_file(target, pixel_size=[10.0, 30.0], **base)
    assert wide.hash_value != tall.hash_value


def test_a_raster_and_a_vector_described_alike_still_differ(tmp_path):
    """Guards against the two halves collapsing into each other — a vector
    with 3 features must not hash like a raster with 3 bands."""
    target = _raster(tmp_path, "thing.dat")

    as_vector = fingerprint_file(target, feature_count=3, threshold_bytes=10)
    as_raster = fingerprint_file(target, band_count=3, threshold_bytes=10)
    assert as_vector.hash_value != as_raster.hash_value


def test_an_oversized_raster_with_no_grid_information_refuses_to_guess(tmp_path):
    with pytest.raises(FingerprintError, match="band_count"):
        fingerprint_file(_raster(tmp_path, "scene.tif"), threshold_bytes=10)


def test_a_layer_entry_from_the_event_contract_passes_straight_through(tmp_path):
    """CONTRACT_event.md gives every layer entry the same key set, with the
    inapplicable half null. The signature is named to accept one directly, so
    Person B never has to reshape it — a raster entry, verbatim."""
    entry = {
        "param": "INPUT", "path": "/data/dem.tif", "format": "GeoTIFF",
        "crs": "EPSG:32643", "layer_type": "raster", "feature_count": None,
        "band_count": 3, "pixel_size": [30.0, 30.0], "width": 1200, "height": 800,
    }
    described = {
        key: entry[key]
        for key in ("feature_count", "band_count", "pixel_size", "width", "height")
    }

    result = fingerprint_file(
        _raster(tmp_path, "dem.tif"), threshold_bytes=10, **described
    )
    assert result.hash_strategy == STRATEGY_SCHEMA_SAMPLE


def test_the_default_threshold_is_the_one_the_research_doc_states():
    """§6.4's fallback exists for files over 500 MB. A drifting default would
    change which strategy RQ3's numbers were measured with."""
    assert LARGE_FILE_THRESHOLD_BYTES == 500 * 1024 * 1024


# ===========================================================================
# the seam with Person A's store — RULES.md §1.3
# ===========================================================================

def test_the_result_hands_straight_to_add_fingerprint(tmp_path):
    """Person B computes, Person A stores. This asserts the shape lines up so a
    contract drift fails here rather than at a call site in Phase 2."""
    from geoprovenance.storage.store import ProvenanceStore

    target = tmp_path / "roads.shp"
    target.write_bytes(b"road bytes")

    store = ProvenanceStore(tmp_path / "prov.db")
    try:
        entity_id = store.add_entity(
            label="roads.shp", file_path=str(target), layer_type="vector"
        )
        result = fingerprint_file(target, feature_count=7)

        fingerprint_id = store.add_fingerprint(
            entity_id=entity_id, **result.as_store_kwargs()
        )

        stored = store.get_latest_fingerprint(entity_id)
        assert stored["id"] == fingerprint_id
        assert stored["hash_value"] == result.hash_value
        assert stored["hash_algorithm"] == "SHA-256"
        assert stored["hash_strategy"] == STRATEGY_FILE
        assert stored["file_size_bytes"] == len(b"road bytes")
        assert stored["feature_count"] == 7
    finally:
        store.close()


def test_an_input_and_its_output_hashed_together_both_store(tmp_path):
    """The ordinary Person B path: one job's input and output, hashed back to
    back inside one transaction.

    This is safe whatever the clock does, and was safe before schema v2 too:
    an input and an output are DIFFERENT entities, so `entity_id` alone
    separates the rows under any version of the key. Measured over 30
    consecutive runs on Windows: 0 failures.

    Kept because CONTRACT_schema.md decision 4 originally named this as the
    collision it prevented. It never was one — which is why the case that
    genuinely collides went unnoticed until it failed on Windows.
    """
    from geoprovenance.storage.store import ProvenanceStore

    source = tmp_path / "roads.shp"
    source.write_bytes(b"input bytes")
    result = tmp_path / "buffered.shp"
    result.write_bytes(b"output bytes")

    store = ProvenanceStore(tmp_path / "prov.db")
    try:
        in_id = store.add_entity(file_path=str(source), layer_type="vector")
        out_id = store.add_entity(file_path=str(result), layer_type="vector")

        with store.transaction():
            store.add_fingerprint(
                entity_id=in_id, **fingerprint_file(source).as_store_kwargs()
            )
            store.add_fingerprint(
                entity_id=out_id, **fingerprint_file(result).as_store_kwargs()
            )

        assert store.get_latest_fingerprint(in_id)["hash_value"] != (
            store.get_latest_fingerprint(out_id)["hash_value"]
        )
    finally:
        store.close()


def test_two_strategies_for_one_file_in_a_tick_both_store(tmp_path):
    """The layered case, end to end: one file, two measurements, one instant.

    This is what schema v2 exists for. Deliberately no file write between the
    two — an earlier version of this test wrote to the file in between, which
    took long enough to cross the clock tick and made it pass on every run;
    that proved a filesystem write is slow, not that the rows were kept apart
    by anything meaningful. They are kept apart by hash_strategy.
    """
    from geoprovenance.storage.store import ProvenanceStore

    target = tmp_path / "roads.shp"
    target.write_bytes(b"v1")

    store = ProvenanceStore(tmp_path / "prov.db")
    try:
        entity_id = store.add_entity(file_path=str(target), layer_type="vector")

        exact = fingerprint_file(target)
        described = fingerprint_file(
            target, feature_count=8, field_names=["name"], threshold_bytes=0
        )
        assert exact.hash_strategy == STRATEGY_FILE
        assert described.hash_strategy == STRATEGY_SCHEMA_SAMPLE

        with store.transaction():
            store.add_fingerprint(entity_id=entity_id, **exact.as_store_kwargs())
            store.add_fingerprint(entity_id=entity_id, **described.as_store_kwargs())

        recorded = store.get_fingerprints_for(entity_id)
        assert len(recorded) == 2
        assert {r["hash_strategy"] for r in recorded} == {
            STRATEGY_FILE, STRATEGY_SCHEMA_SAMPLE
        }
    finally:
        store.close()


def test_the_same_file_and_strategy_twice_in_a_tick_is_rejected(tmp_path):
    """Widening the key must not stop it catching real duplicates.

    Person B must not paper over this by nudging computed_at: writing a
    timestamp known to be false, into a record whose whole purpose is an
    accurate account of what happened, is a worse trade than the failed insert.
    """
    from geoprovenance.storage.store import ProvenanceStore

    target = tmp_path / "roads.shp"
    target.write_bytes(b"v1")

    store = ProvenanceStore(tmp_path / "prov.db")
    try:
        entity_id = store.add_entity(file_path=str(target), layer_type="vector")
        stamp = "2026-08-26T14:00:00.123456+00:00"
        result = fingerprint_file(target)

        store.add_fingerprint(
            entity_id=entity_id, computed_at=stamp, **result.as_store_kwargs()
        )
        with pytest.raises(sqlite3.IntegrityError):
            store.add_fingerprint(
                entity_id=entity_id, computed_at=stamp, **result.as_store_kwargs()
            )
    finally:
        store.close()


def test_as_store_kwargs_does_not_carry_a_timestamp():
    """Explicit, because passing computed_at is exactly how decision 4 gets
    violated by a well-meaning caller."""
    result = Fingerprint(
        hash_value="deadbeef", hash_strategy=STRATEGY_FILE, file_size_bytes=1
    )
    assert "computed_at" not in result.as_store_kwargs()


# ===========================================================================
# fingerprint_dataset — the primary measurement plus what can be read
# ===========================================================================

def test_a_dataset_yields_the_byte_hash_and_the_signals_that_explain_it():
    """Four rows for a Shapefile, one per method, all distinct.

    The `fingerprints UNIQUE(entity_id, hash_strategy, computed_at)` key was
    widened in schema v2 precisely so a set like this can land at one instant.
    Before this function nothing produced one, so the widened key permitted
    something nothing wrote.
    """
    from geoprovenance.fingerprint import (
        STRATEGY_ATTRIBUTES,
        STRATEGY_GEOMETRY,
        STRATEGY_STRUCTURE,
        fingerprint_dataset,
    )

    results = fingerprint_dataset(DATA / "sample_points.shp")
    strategies = [f.hash_strategy for f in results]
    assert strategies[0] == STRATEGY_FILE, "the primary measurement comes first"
    assert set(strategies) == {
        STRATEGY_FILE,
        STRATEGY_STRUCTURE,
        STRATEGY_GEOMETRY,
        STRATEGY_ATTRIBUTES,
    }
    assert len(strategies) == len(set(strategies)), "one row per method"


def test_the_byte_hash_in_the_set_is_the_same_one_as_before():
    """`fingerprint_dataset` adds rows; it does not change the one that existed.

    If the `file` value moved, every fingerprint already in a database would
    stop comparing equal to a freshly computed one, and the first audit after
    an upgrade would report every input as changed.
    """
    from geoprovenance.fingerprint import fingerprint_dataset

    alone = fingerprint_file(DATA / "sample_points.shp")
    in_set = fingerprint_dataset(DATA / "sample_points.shp")[0]
    assert in_set.hash_value == alone.hash_value
    assert in_set.hash_strategy == alone.hash_strategy
    assert in_set.file_size_bytes == alone.file_size_bytes


def test_every_strategy_produced_is_one_of_the_known_ones():
    """The column has no CHECK constraint, so this is where a typo is caught.

    Constraining `hash_strategy` in SQL would mean a schema migration every
    time a strategy is added; the constants are the single definition instead,
    and this asserts nothing escapes them.
    """
    from geoprovenance.fingerprint import KNOWN_STRATEGIES, fingerprint_dataset

    for path in (DATA / "sample_points.shp", DATA / "sample_areas.gpkg"):
        for result in fingerprint_dataset(path):
            assert result.hash_strategy in KNOWN_STRATEGIES


def test_a_format_that_cannot_be_read_still_gets_its_byte_hash(tmp_path):
    """GeoTIFF degrades to exactly today's answer, and says so by omission.

    An absent signal is reported as unavailable by `compare`, never as
    agreement — so the audit falls back to same-or-different rather than
    inferring a re-save from checks that were never run.
    """
    from geoprovenance.fingerprint import fingerprint_dataset

    raster = tmp_path / "elevation.tif"
    raster.write_bytes(b"II*\x00" + b"\x00" * 64)
    results = fingerprint_dataset(raster)
    assert [f.hash_strategy for f in results] == [STRATEGY_FILE]


def test_complementary_signals_never_raise_on_a_file_they_cannot_read(tmp_path):
    """RULES.md §5.1 — this runs inside a user's processing run.

    A truncated, corrupt or half-written file must produce no signals rather
    than an exception, because the alternative is capture code taking down
    somebody's analysis.
    """
    from geoprovenance.fingerprint import complementary_fingerprints

    broken = tmp_path / "truncated.shp"
    broken.write_bytes(b"\x00\x00\x27\x0a")
    assert complementary_fingerprints(broken) == []

    missing = tmp_path / "gone.gpkg"
    assert complementary_fingerprints(missing) == []


def test_a_large_file_can_now_describe_itself_instead_of_refusing(tmp_path):
    """Closes the gap `fingerprint_file`'s own docstring names.

    Over the §6.4 threshold the fallback needs a description, and the capture
    event has nowhere to put `field_names` — so before this the fallback could
    only ever see a feature count, and with nothing supplied at all it refused.
    Reading the file supplies both.
    """
    from geoprovenance.fingerprint import fingerprint_dataset

    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        (tmp_path / f"points{suffix}").write_bytes(
            (DATA / f"sample_points{suffix}").read_bytes()
        )
    shapefile = tmp_path / "points.shp"

    with pytest.raises(FingerprintError):
        fingerprint_file(shapefile, threshold_bytes=0)

    results = fingerprint_dataset(shapefile, threshold_bytes=0)
    assert results[0].hash_strategy == STRATEGY_SCHEMA_SAMPLE
    assert results[0].feature_count == 8


def test_the_whole_set_stores_together_under_the_v2_key(tmp_path):
    """The end-to-end reason schema v2 exists, exercised through the real store."""
    from geoprovenance.fingerprint import fingerprint_dataset
    from geoprovenance.storage.store import ProvenanceStore

    store = ProvenanceStore(tmp_path / "prov.db")
    try:
        entity = store.add_entity(
            entity_type="dataset", file_path=str(DATA / "sample_points.shp")
        )
        written = store.add_fingerprints(
            entity_id=entity,
            fingerprints=fingerprint_dataset(DATA / "sample_points.shp"),
        )
        assert len(written) == 4
        assert set(store.get_fingerprint_set(entity)) == {
            "file", "structure", "geometry", "attributes"
        }
    finally:
        store.close()


def test_structure_and_geometry_claim_no_byte_coverage():
    """They are digests of a description, not of a byte range.

    Recording a `file_size_bytes` against them would imply they had read that
    many bytes of the file, which is exactly the overstatement `hash_strategy`
    exists to prevent.
    """
    from geoprovenance.fingerprint import fingerprint_dataset

    by_strategy = {
        f.hash_strategy: f for f in fingerprint_dataset(DATA / "sample_points.shp")
    }
    assert by_strategy["structure"].file_size_bytes is None
    assert by_strategy["geometry"].file_size_bytes is None
    assert by_strategy["file"].file_size_bytes == 324
    assert by_strategy["attributes"].file_size_bytes == 330


def test_the_digest_recipe_travels_inside_the_hash():
    """If what goes into a digest ever changes, old values must stop matching.

    A version kept beside the hash could be ignored by a caller comparing two
    hex strings, and a changed recipe would then read as a changed file. Same
    reasoning as `_schema_sample_digest`'s "algorithm" key.
    """
    from geoprovenance.fingerprint.hash import (
        STRUCTURE_ALGORITHM,
        _json_digest,
        _stream_digest,
    )

    payload = {"format": "Shapefile", "layers": []}
    assert _json_digest(STRUCTURE_ALGORITHM, payload) != _json_digest(
        "geoprovenance/structure/2", payload
    )
    assert _stream_digest("a", [b"x"])[0] != _stream_digest("b", [b"x"])[0]
