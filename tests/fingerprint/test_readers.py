"""Reading a dataset's shape off disk — Person B, research doc §6.4.

RULES.md §6.1 — no QGIS anywhere in this file, and no GDAL either. The point
of `readers.py` is that a Shapefile header and a GeoPackage catalogue are both
readable with the standard library, so this whole suite runs under `make test`.

Ground truth is the committed fixtures. `sample_points` is an 8-feature point
Shapefile with two text columns; `sample_areas` is a 4-feature GeoPackage. If
the readers disagree with what those files actually contain, the readers are
wrong.
"""

from __future__ import annotations

import pathlib
import shutil
import sqlite3
import struct

import pytest

from geoprovenance.fingerprint import readers

DATA = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "data"


@pytest.fixture
def shapefile(tmp_path: pathlib.Path) -> pathlib.Path:
    """A private copy of the fixture Shapefile, sidecars and all.

    Copied rather than read in place because several tests here edit the file
    to prove a signal moves, and a test that mutates a committed fixture is a
    test that breaks every other suite the next time it runs.
    """
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        shutil.copy2(DATA / f"sample_points{suffix}", tmp_path / f"points{suffix}")
    return tmp_path / "points.shp"


@pytest.fixture
def geopackage(tmp_path: pathlib.Path) -> pathlib.Path:
    shutil.copy2(DATA / "sample_areas.gpkg", tmp_path / "areas.gpkg")
    return tmp_path / "areas.gpkg"


# ===========================================================================
# Shapefile
# ===========================================================================

def test_reads_the_shapefile_field_names_from_the_dbf():
    """The columns live in the .dbf, which is not the file the record points at.

    This is the whole reason the module exists: the path stored in `entities`
    ends in `.shp`, and everything about the attributes is in a different file.
    """
    described = readers.describe(DATA / "sample_points.shp")
    assert described is not None
    assert described.format == readers.FORMAT_SHAPEFILE
    layer = described.layers[0]
    assert layer.field_names == ("name", "category")


def test_reads_the_shapefile_field_widths_not_just_the_type_letter():
    """`C:16` and not `C`. Widening a column is a schema change.

    A bare type letter would report a 16-character name column and a
    64-character one as the same schema, and the audit would miss a migration
    that silently truncates data.
    """
    layer = readers.describe(DATA / "sample_points.shp").layers[0]
    assert layer.field_types == ("C:16", "C:12")


def test_reads_the_shapefile_bounding_box_from_the_header():
    """Bytes 36-67 of the 100-byte header, little-endian doubles."""
    layer = readers.describe(DATA / "sample_points.shp").layers[0]
    assert layer.bbox == pytest.approx((77.56, 12.94, 77.65, 13.02))


def test_counts_the_shapefile_features_from_the_index():
    """8 features, from the .shx, without reading a single geometry."""
    layer = readers.describe(DATA / "sample_points.shp").layers[0]
    assert layer.feature_count == 8


def test_reads_the_crs_from_the_prj():
    described = readers.describe(DATA / "sample_points.shp")
    assert described.crs_text is not None
    assert "GCS_WGS_1984" in described.crs_text


def test_the_prj_is_normalised_so_reformatting_is_not_a_change(
    shapefile: pathlib.Path,
):
    """Writers disagree about whitespace inside WKT while meaning the same CRS.

    A CRS signal that moved when a file was merely reformatted would be another
    false positive, which is the thing this layer exists to remove.
    """
    before = readers.describe(shapefile).crs_text
    prj = shapefile.with_suffix(".prj")
    prj.write_text(prj.read_text().replace(",", ",\n   "))
    assert readers.describe(shapefile).crs_text == before


def test_a_file_that_merely_ends_in_shp_is_refused_not_guessed_at(
    tmp_path: pathlib.Path,
):
    """Without the magic-number check, four arbitrary bytes become a bounding box.

    Returning None is right; inventing an extent from whatever happened to sit
    at offset 36 would put a confident wrong answer into an audit (§5.6).
    """
    impostor = tmp_path / "notreally.shp"
    impostor.write_bytes(b"\x00" * 200)
    assert readers.describe(impostor) is None


def test_a_shapefile_with_no_sidecars_still_describes_what_it_can(
    shapefile: pathlib.Path,
):
    """A geometry-only Shapefile is unusual but legal. It must not raise.

    The extent and the feature count are still readable; the field list is
    simply empty, and an empty field list is a fact about the file rather than
    a failure to read it.
    """
    shapefile.with_suffix(".dbf").unlink()
    shapefile.with_suffix(".prj").unlink()
    described = readers.describe(shapefile)
    assert described is not None
    assert described.layers[0].field_names == ()
    assert described.crs_text is None
    assert described.layers[0].bbox is not None


def test_sidecar_paths_finds_the_files_the_byte_hash_never_reads(
    shapefile: pathlib.Path,
):
    names = {path.suffix for path in readers.sidecar_paths(shapefile)}
    assert names == {".dbf", ".shx", ".prj"}


def test_sidecar_paths_is_empty_for_a_single_file_format(geopackage: pathlib.Path):
    assert readers.sidecar_paths(geopackage) == ()


# ===========================================================================
# GeoPackage
# ===========================================================================

def test_reads_the_geopackage_tables_and_columns():
    described = readers.describe(DATA / "sample_areas.gpkg")
    assert described is not None
    assert described.format == readers.FORMAT_GEOPACKAGE
    layer = described.layers[0]
    assert layer.name == "sample_areas"
    assert layer.field_names == ("fid", "geom", "name", "category")


def test_reads_the_geopackage_extent_and_count():
    layer = readers.describe(DATA / "sample_areas.gpkg").layers[0]
    assert layer.feature_count == 4
    assert layer.bbox == pytest.approx((77.58, 12.96, 77.625, 12.99))


def test_reports_the_geopackage_crs_the_way_the_schema_records_one():
    """`EPSG:4326`, matching how `entities.crs` stores an authid (§5.7).

    Taken from the tables' own `srs_id` rather than from every row of
    `gpkg_spatial_ref_sys`: every GeoPackage ships the same three placeholder
    entries, so hashing the whole table would describe the format instead of
    the file.
    """
    assert readers.describe(DATA / "sample_areas.gpkg").crs_text == "EPSG:4326"


def test_describing_a_geopackage_does_not_modify_it(geopackage: pathlib.Path):
    """Opened read-only, so no journal appears beside a user's data.

    This runs against files QGIS may have open, and a fingerprinter that left
    a -wal file next to someone's dataset would be a capture side effect
    (RULES.md §5.1).
    """
    before = geopackage.read_bytes()
    readers.describe(geopackage)
    assert geopackage.read_bytes() == before
    assert list(geopackage.parent.iterdir()) == [geopackage]


def test_a_sqlite_file_that_is_not_a_geopackage_returns_none(tmp_path: pathlib.Path):
    plain = tmp_path / "plain.gpkg"
    connection = sqlite3.connect(plain)
    connection.execute("CREATE TABLE t (a TEXT)")
    connection.commit()
    connection.close()
    assert readers.describe(plain) is None


# ===========================================================================
# what cannot be read
# ===========================================================================

def test_an_unreadable_format_returns_none_rather_than_raising(
    tmp_path: pathlib.Path,
):
    """GeoTIFF is the honest gap, and it degrades rather than failing.

    Reading a GeoTIFF's georeferencing means parsing TIFF IFDs and the GeoKey
    directory; the alternative is GDAL, which RULES.md §2.2 refuses. A dataset
    with no description simply contributes no complementary signals.
    """
    raster = tmp_path / "elevation.tif"
    raster.write_bytes(b"II*\x00" + b"\x00" * 64)
    assert readers.describe(raster) is None
    assert readers.attribute_chunks(raster) is None


def test_a_missing_file_returns_none(tmp_path: pathlib.Path):
    assert readers.describe(tmp_path / "gone.shp") is None


def test_none_is_accepted_because_memory_layers_arrive_as_none():
    """CONTRACT_event.md rule 1 — memory and temporary layers have `path: None`."""
    assert readers.describe(None) is None
    assert readers.attribute_chunks(None) is None
    assert readers.sidecar_paths(None) == ()


# ===========================================================================
# attribute payload
# ===========================================================================

def test_the_shapefile_attribute_payload_is_the_dbf(shapefile: pathlib.Path):
    payload = b"".join(readers.attribute_chunks(shapefile))
    assert len(payload) == shapefile.with_suffix(".dbf").stat().st_size


def test_the_dbf_last_written_date_is_blanked_before_hashing(
    shapefile: pathlib.Path,
):
    """Bytes 1-3 hold the date the .dbf was rewritten, not any of its data.

    They move on every rewrite whether or not a value changed. Leaving them in
    would have the attribute signal agreeing with the byte hash exactly when it
    most needs to disagree — that is, on a re-save.
    """
    before = b"".join(readers.attribute_chunks(shapefile))
    dbf = shapefile.with_suffix(".dbf")
    raw = bytearray(dbf.read_bytes())
    raw[1:4] = b"\x63\x0c\x1f"
    dbf.write_bytes(bytes(raw))
    assert b"".join(readers.attribute_chunks(shapefile)) == before


def test_the_geopackage_attribute_payload_excludes_geometry(
    geopackage: pathlib.Path,
):
    """Geometry has its own signal; mixing it in makes the two indistinguishable.

    If the geometry blob were part of the attribute digest, an attribute edit
    and a geometry edit would move the same value again — which is the failure
    being fixed.
    """
    payload = b"".join(readers.attribute_chunks(geopackage))
    assert b"site_00" in payload
    assert b"GP\x00\x01".hex().encode() not in payload


def test_the_geopackage_attribute_payload_is_row_order_independent(
    geopackage: pathlib.Path,
):
    """A rewrite that renumbers rows without changing a value is a re-save.

    Rows are sorted by their serialised value before hashing, so re-inserting
    the same data in a different order does not read as an edit.
    """
    before = b"".join(readers.attribute_chunks(geopackage))
    connection = sqlite3.connect(geopackage)
    rows = connection.execute(
        "SELECT geom, name, category FROM sample_areas ORDER BY fid DESC"
    ).fetchall()
    connection.execute("DELETE FROM sample_areas")
    connection.executemany(
        "INSERT INTO sample_areas (geom, name, category) VALUES (?,?,?)", rows
    )
    connection.commit()
    connection.close()
    assert b"".join(readers.attribute_chunks(geopackage)) == before


def test_a_geopackage_over_the_row_ceiling_yields_no_attribute_signal(
    geopackage: pathlib.Path,
):
    """None, not an empty payload.

    Empty would hash to a real value and assert the file has no attributes,
    which is a different and false claim. None means "not measured", and
    `compare` reports that axis as unavailable rather than as agreement.
    """
    assert readers.attribute_chunks(geopackage, max_rows=1) is None
    assert readers.attribute_chunks(geopackage, max_rows=4) is not None


def test_editing_one_value_moves_the_attribute_payload(geopackage: pathlib.Path):
    before = b"".join(readers.attribute_chunks(geopackage))
    connection = sqlite3.connect(geopackage)
    connection.execute("UPDATE sample_areas SET name = 'renamed' WHERE fid = 1")
    connection.commit()
    connection.close()
    assert b"".join(readers.attribute_chunks(geopackage)) != before
