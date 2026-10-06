"""What changed about a file, not merely whether it changed — Person B, RQ3.

RULES.md §6.1 — no QGIS anywhere in this file.

Research doc §9.1 measures RQ3 as detection accuracy: correctly detected
changes over total changes. A byte hash on its own is wrong in both directions,
and the two tests named in the "the two failures" section below are the two
directions. They are the reason this module exists; if they pass, it works.
"""

from __future__ import annotations

import pathlib
import shutil
import sqlite3
import struct

import pytest

from geoprovenance.fingerprint import (
    VERDICT_ATTRIBUTES_CHANGED,
    VERDICT_CHANGED,
    VERDICT_GEOMETRY_CHANGED,
    VERDICT_RESAVED,
    VERDICT_SCHEMA_CHANGED,
    VERDICT_UNCHANGED,
    VERDICT_UNKNOWN,
    STRATEGY_ATTRIBUTES,
    STRATEGY_FILE,
    STRATEGY_GEOMETRY,
    STRATEGY_GEOMETRY_CONTENT,
    STRATEGY_STRUCTURE,
    compare_fingerprint_sets,
    fingerprint_dataset,
)

DATA = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "data"

#: Where SQLite writes its own library version into every file it creates.
#: Bytes 92-95 are the version that last wrote the file, 96-99 the version the
#: change counter is valid for. This is the exact drift measured in this
#: repository between SQLite 3.40.1, 3.51.2 and 3.53.4.
_SQLITE_VERSION_STAMP = slice(92, 100)


def signals(path: pathlib.Path) -> dict[str, str]:
    """Every measurement of one file, as `compare_fingerprint_sets` wants them."""
    return {f.hash_strategy: f.hash_value for f in fingerprint_dataset(path)}


@pytest.fixture
def shapefile(tmp_path: pathlib.Path) -> pathlib.Path:
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        shutil.copy2(DATA / f"sample_points{suffix}", tmp_path / f"points{suffix}")
    return tmp_path / "points.shp"


@pytest.fixture
def geopackage(tmp_path: pathlib.Path) -> pathlib.Path:
    shutil.copy2(DATA / "sample_areas.gpkg", tmp_path / "areas.gpkg")
    return tmp_path / "areas.gpkg"


# ===========================================================================
# the two failures this module exists to fix
# ===========================================================================

def test_a_geopackage_resaved_by_another_sqlite_build_is_not_a_change(
    geopackage: pathlib.Path,
):
    """THE FALSE POSITIVE. Different bytes, identical data.

    A GeoPackage is a SQLite file and SQLite stamps its own library version
    into everything it writes. Rebuilding `sample_areas.gpkg` from one
    identical script was measured in this repository to move bytes 92-99
    between 3.51.2 and 3.53.4, three further bytes at offset 7368 between
    3.40.1 and 3.53.4, and around a thousand bytes without
    SQLITE_SECURE_DELETE — with rows, schema text and root pages identical
    every time.

    A byte hash alone calls that a changed input, and Person C's audit then
    marks a perfectly reproducible workflow as broken. Every one of those is a
    wrong answer in RQ3's numerator.
    """
    before = signals(geopackage)
    raw = bytearray(geopackage.read_bytes())
    raw[_SQLITE_VERSION_STAMP] = struct.pack(">ii", 3040100, 12345)
    geopackage.write_bytes(bytes(raw))
    after = signals(geopackage)

    assert before[STRATEGY_FILE] != after[STRATEGY_FILE], "the bytes must differ"

    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_RESAVED
    assert comparison.moved == {STRATEGY_FILE}
    assert comparison.held == {
        STRATEGY_STRUCTURE,
        STRATEGY_GEOMETRY,
        STRATEGY_GEOMETRY_CONTENT,
        STRATEGY_ATTRIBUTES,
    }
    assert comparison.changed is False


def test_editing_a_school_name_in_the_dbf_is_detected(shapefile: pathlib.Path):
    """THE FALSE NEGATIVE. Identical .shp, edited data.

    A Shapefile is four files and `entities.file_path` points at the `.shp`.
    The attribute values live in the `.dbf` beside it, so editing a name leaves
    the hashed bytes untouched: the fingerprint does not move, and the audit
    reports the input unchanged. That is a missed detection, which RQ3 counts
    against us just as heavily as a false alarm.

    The replacement is the same width as the original so the `.dbf` record
    layout is byte-for-byte identical apart from the value itself — this is a
    pure attribute edit, not a schema change wearing one as a disguise.
    """
    before = signals(shapefile)
    dbf = shapefile.with_suffix(".dbf")
    raw = bytearray(dbf.read_bytes())
    start = raw.find(b"site_00")
    assert start != -1
    raw[start : start + 7] = b"SCHOOL1"
    dbf.write_bytes(bytes(raw))
    after = signals(shapefile)

    assert before[STRATEGY_FILE] == after[STRATEGY_FILE], (
        "the .shp must be untouched — that is what makes this the hard case"
    )

    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_ATTRIBUTES_CHANGED
    assert comparison.moved == {STRATEGY_ATTRIBUTES}
    assert STRATEGY_GEOMETRY in comparison.held
    assert comparison.changed is True


# ===========================================================================
# the third failure — a vertex moved inside the extent
# ===========================================================================
#
# Until 6 Oct 2026 the only geometry signal was the feature count and the
# bounding box. Moving one point or vertex without changing either moved the
# byte hash and nothing else, so the file read as `resaved`: a real edit to the
# shape reported as harmless. For a shoreline — a few features whose shape is
# the whole point — that is not a corner case. A pre-submission review named
# it; these two tests pin the fix on both formats.

#: Where the fixture's first point sits: (77.5946, 12.9716). Inside the extent
#: on both axes, so nudging it moves neither the count nor the bounding box.
_NUDGE = 0.001


def test_a_shapefile_point_moved_inside_the_extent_is_a_geometry_change(
    shapefile: pathlib.Path,
):
    before = signals(shapefile)
    raw = bytearray(shapefile.read_bytes())
    # Record 1: 100-byte file header, 8-byte record header, 4-byte shape type.
    (x,) = struct.unpack("<d", raw[112:120])
    raw[112:120] = struct.pack("<d", x + _NUDGE)
    shapefile.write_bytes(bytes(raw))
    after = signals(shapefile)

    assert before[STRATEGY_GEOMETRY] == after[STRATEGY_GEOMETRY], (
        "count and extent must hold — that is what made this the hard case"
    )
    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_GEOMETRY_CHANGED
    assert STRATEGY_GEOMETRY_CONTENT in comparison.moved
    assert comparison.changed is True


def _rewrite_blob(gpkg: pathlib.Path, fid: int, change) -> None:
    connection = sqlite3.connect(gpkg)
    (blob,) = connection.execute(
        "SELECT geom FROM sample_areas WHERE fid = ?", (fid,)
    ).fetchone()
    connection.execute(
        "UPDATE sample_areas SET geom = ? WHERE fid = ?", (change(bytes(blob)), fid)
    )
    connection.commit()
    connection.close()


def test_a_geopackage_point_moved_inside_the_extent_is_a_geometry_change(
    geopackage: pathlib.Path,
):
    def nudge(blob: bytes) -> bytes:
        # 8-byte GeoPackage header (no envelope), then WKB: byte order, type, x.
        (x,) = struct.unpack("<d", blob[13:21])
        return blob[:13] + struct.pack("<d", x + _NUDGE) + blob[21:]

    before = signals(geopackage)
    _rewrite_blob(geopackage, 1, nudge)
    after = signals(geopackage)

    assert before[STRATEGY_GEOMETRY] == after[STRATEGY_GEOMETRY]
    assert before[STRATEGY_ATTRIBUTES] == after[STRATEGY_ATTRIBUTES]
    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_GEOMETRY_CHANGED
    assert STRATEGY_GEOMETRY_CONTENT in comparison.moved


def test_a_writer_that_adds_an_envelope_has_not_moved_the_shape(
    geopackage: pathlib.Path,
):
    """The fix must not reopen the false positive it sits beside.

    A GeoPackage geometry may carry an optional bounding box in its header, and
    whether it does is the writer's choice. Same coordinates, different header,
    so different bytes: still a re-save.
    """

    def add_envelope(blob: bytes) -> bytes:
        x, y = struct.unpack("<dd", blob[13:29])
        flags = blob[3] | (1 << 1)  # envelope indicator 1: minx, maxx, miny, maxy
        return (
            blob[:3] + bytes([flags]) + blob[4:8]
            + struct.pack("<4d", x, x, y, y) + blob[8:]
        )

    before = signals(geopackage)
    _rewrite_blob(geopackage, 1, add_envelope)
    after = signals(geopackage)

    comparison = compare_fingerprint_sets(before, after)
    assert STRATEGY_FILE in comparison.moved
    assert comparison.verdict == VERDICT_RESAVED


# ===========================================================================
# the other verdicts
# ===========================================================================

def test_an_untouched_file_is_unchanged(shapefile: pathlib.Path):
    before = signals(shapefile)
    assert compare_fingerprint_sets(before, signals(shapefile)).verdict == (
        VERDICT_UNCHANGED
    )


def test_adding_a_column_is_a_schema_change(geopackage: pathlib.Path):
    before = signals(geopackage)
    connection = sqlite3.connect(geopackage)
    connection.execute("ALTER TABLE sample_areas ADD COLUMN surveyed TEXT")
    connection.commit()
    connection.close()

    comparison = compare_fingerprint_sets(before, signals(geopackage))
    assert comparison.verdict == VERDICT_SCHEMA_CHANGED
    assert STRATEGY_STRUCTURE in comparison.moved


def test_removing_a_feature_is_a_geometry_change(geopackage: pathlib.Path):
    before = signals(geopackage)
    connection = sqlite3.connect(geopackage)
    connection.execute("DELETE FROM sample_areas WHERE fid = 1")
    connection.commit()
    connection.close()

    comparison = compare_fingerprint_sets(before, signals(geopackage))
    assert comparison.verdict == VERDICT_GEOMETRY_CHANGED
    assert STRATEGY_GEOMETRY in comparison.moved


def test_a_schema_change_outranks_the_edits_that_came_with_it(
    geopackage: pathlib.Path,
):
    """When several signals move, the most structural one is the finding.

    A dropped column is why every downstream step may now behave differently;
    reporting "some values changed" would bury the cause. The full set is still
    on `.moved` for a caller that wants it.
    """
    before = signals(geopackage)
    connection = sqlite3.connect(geopackage)
    connection.execute("ALTER TABLE sample_areas DROP COLUMN category")
    connection.execute("DELETE FROM sample_areas WHERE fid = 1")
    connection.commit()
    connection.close()

    comparison = compare_fingerprint_sets(before, signals(geopackage))
    assert comparison.verdict == VERDICT_SCHEMA_CHANGED
    assert {STRATEGY_STRUCTURE, STRATEGY_GEOMETRY} <= comparison.moved


# ===========================================================================
# what it refuses to conclude
# ===========================================================================

def test_a_format_with_no_readable_description_degrades_to_changed(
    tmp_path: pathlib.Path,
):
    """A GeoTIFF has only a byte hash, so only a byte hash's answer is available.

    `changed` and not `resaved`: with nothing measured about the data, three
    signals that agree cannot be produced, and inferring a re-save from signals
    that were never taken is exactly the confident wrong answer §5.6 forbids.
    """
    raster = tmp_path / "elevation.tif"
    raster.write_bytes(b"II*\x00" + b"\x00" * 64)
    before = signals(raster)
    raster.write_bytes(b"II*\x00" + b"\x01" * 64)
    after = signals(raster)

    assert set(before) == {STRATEGY_FILE}
    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_CHANGED
    assert comparison.unavailable == {
        STRATEGY_STRUCTURE,
        STRATEGY_GEOMETRY,
        STRATEGY_GEOMETRY_CONTENT,
        STRATEGY_ATTRIBUTES,
    }
    assert "cannot say in what way" in comparison.explain()


def test_a_signal_measured_on_only_one_side_is_never_read_as_agreement():
    """The single most dangerous mistake this module could make.

    A record written before the complementary strategies existed has only a
    byte hash. Treating "absent" as "held" would turn every such comparison
    into a confident `resaved` — silently reclassifying real changes as
    harmless re-saves, in the direction that loses data.
    """
    before = {STRATEGY_FILE: "aaa"}
    after = {STRATEGY_FILE: "bbb", STRATEGY_GEOMETRY: "ggg"}
    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_CHANGED
    assert STRATEGY_GEOMETRY in comparison.unavailable


def test_an_attribute_change_without_a_geometry_signal_is_only_changed():
    """Claiming "the shapes are the same" requires having looked at the shapes."""
    comparison = compare_fingerprint_sets(
        {STRATEGY_FILE: "a", STRATEGY_ATTRIBUTES: "x"},
        {STRATEGY_FILE: "b", STRATEGY_ATTRIBUTES: "y"},
    )
    assert comparison.verdict == VERDICT_CHANGED


def test_count_and_extent_holding_does_not_prove_the_shapes_held():
    """An attribute edit is only `attributes_changed` if the coordinates held.

    `geometry` holding says the count and extent are as they were, and a vertex
    can move without disturbing either. A record fingerprinted before
    `geometry_content` existed has nothing more, so it gets the true answer.
    """
    before = {
        STRATEGY_FILE: "a",
        STRATEGY_STRUCTURE: "s",
        STRATEGY_GEOMETRY: "g",
        STRATEGY_ATTRIBUTES: "x",
    }
    after = dict(before, **{STRATEGY_FILE: "b", STRATEGY_ATTRIBUTES: "y"})
    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_CHANGED
    assert STRATEGY_GEOMETRY_CONTENT in comparison.unavailable


def test_a_record_from_before_the_coordinate_signal_is_not_called_resaved():
    """Old records: bytes moved, attributes held, coordinates never measured.

    Before 6 Oct 2026 this was `resaved`, and a moved vertex looked exactly
    like it. Without the coordinate signal on both sides the two cannot be
    told apart, so the answer is `changed` — and the explanation says why.
    """
    before = {
        STRATEGY_FILE: "a",
        STRATEGY_STRUCTURE: "s",
        STRATEGY_GEOMETRY: "g",
        STRATEGY_ATTRIBUTES: "x",
    }
    after = dict(before, **{STRATEGY_FILE: "b"}, **{STRATEGY_GEOMETRY_CONTENT: "c"})
    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_CHANGED
    assert STRATEGY_GEOMETRY_CONTENT in comparison.unavailable
    assert "could not be run" in comparison.explain()


def test_nothing_in_common_is_unknown_not_unchanged():
    comparison = compare_fingerprint_sets(
        {STRATEGY_FILE: "a"}, {STRATEGY_GEOMETRY: "g"}
    )
    assert comparison.verdict == VERDICT_UNKNOWN
    assert comparison.changed is False


def test_two_empty_sets_are_unknown():
    assert compare_fingerprint_sets({}, {}).verdict == VERDICT_UNKNOWN


def test_every_verdict_has_a_plain_english_sentence():
    """RULES.md §7.5 — this text reaches a reviewer through Person C's report.

    None of the banned words appear: no entity, no hash, no provenance, no
    schema. "a short code that changes if the file changes even slightly" is
    the sanctioned replacement and is what these sentences use.
    """
    banned = ("entity", "activity", "agent", "hash", "provenance", "schema", "DAG")
    for verdict in (
        VERDICT_UNCHANGED,
        VERDICT_RESAVED,
        VERDICT_ATTRIBUTES_CHANGED,
        VERDICT_GEOMETRY_CHANGED,
        VERDICT_SCHEMA_CHANGED,
        VERDICT_CHANGED,
        VERDICT_UNKNOWN,
    ):
        sentence = compare_fingerprint_sets({}, {}).__class__(
            verdict=verdict,
            moved=frozenset(),
            held=frozenset(),
            unavailable=frozenset(),
        ).explain()
        assert sentence.endswith((".", ")"))
        for word in banned:
            assert word not in sentence.lower(), f"{verdict}: {word!r}"


def test_a_resave_is_only_claimed_when_the_values_were_actually_checked():
    """`structure` and `geometry` holding is not evidence that the data held.

    A row can be edited without adding a column or moving the bounding box, so
    concluding "rewritten, not edited" from those two alone would hide a real
    change — the same unmeasured-equals-unchanged mistake, in the direction
    that loses data. Reachable for a GeoPackage past the attribute row ceiling,
    which is exactly where the two genuinely cannot be told apart.
    """
    before = {
        STRATEGY_FILE: "a",
        STRATEGY_STRUCTURE: "s",
        STRATEGY_GEOMETRY: "g",
    }
    after = dict(before, **{STRATEGY_FILE: "b"})
    comparison = compare_fingerprint_sets(before, after)

    assert comparison.verdict == VERDICT_CHANGED
    assert STRATEGY_ATTRIBUTES in comparison.unavailable
    assert "cannot say in what way" in comparison.explain()
    assert "could not be run" in comparison.explain()
