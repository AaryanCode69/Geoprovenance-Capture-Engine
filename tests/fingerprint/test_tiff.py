"""The GeoTIFF axes: one dataset, many storage layouts, one answer.

Added 24 Oct 2026 with `fingerprint/tiff.py` (CLAIMS_TO_IMPLEMENT.md C7). Every
layout `tiff.py` claims to read is written by `_tiffwriter` with the SAME pixels,
and each must read back as that same data — that is the claim §3.5 of the
manuscript makes, and the reason a re-save is `resaved` and not `changed`.
"""

from __future__ import annotations

import itertools

import pytest

from geoprovenance.fingerprint import compare, hash as hashing, tiff

from _tiffwriter import write_tiff

STRUCTURE = hashing.STRATEGY_STRUCTURE
PIXELS = hashing.STRATEGY_PIXEL_CONTENT


def _grid(width=37, height=23, bands=1, kind="u"):
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            base = (x * 31 + y * 17) % 1000
            px = tuple((base + 7 * b) if kind != "f" else (base + 0.25 * b) for b in range(bands))
            row.append(px)
        rows.append(row)
    return rows


def _set(path):
    return {f.hash_strategy: f.hash_value for f in hashing.fingerprint_dataset(path)}


LAYOUTS = {
    "strips_plain_le": dict(rows_per_strip=5),
    "single_strip": dict(),
    "strips_deflate": dict(rows_per_strip=4, compression=8),
    "adobe_deflate": dict(rows_per_strip=7, compression=32946),
    "deflate_predictor2": dict(rows_per_strip=6, compression=8, predictor=2),
    "tiled_16": dict(tiled=(16, 16)),
    "tiled_deflate_pred": dict(tiled=(16, 16), compression=8, predictor=2),
    "big_endian": dict(byte_order=">", rows_per_strip=3),
    "bigtiff": dict(bigtiff=True, rows_per_strip=8, compression=8),
    "bigtiff_be_tiled": dict(bigtiff=True, byte_order=">", tiled=(32, 16)),
}


@pytest.fixture
def grid():
    return _grid()


@pytest.mark.parametrize("name", sorted(LAYOUTS))
def test_every_supported_layout_reads_the_same_pixels(tmp_path, grid, name):
    reference = tmp_path / "ref.tif"
    write_tiff(reference, grid)
    other = tmp_path / f"{name}.tif"
    write_tiff(other, grid, **LAYOUTS[name])
    a, b = _set(reference), _set(other)
    assert a[PIXELS] == b[PIXELS]
    assert a[STRUCTURE] == b[STRUCTURE]
    if a[hashing.STRATEGY_FILE] != b[hashing.STRATEGY_FILE]:
        assert compare.compare_fingerprint_sets(a, b).verdict == compare.VERDICT_RESAVED


def test_a_multiband_raster_reads_the_same_in_chunky_and_planar_layouts(tmp_path):
    grid = _grid(bands=3)
    chunky = tmp_path / "chunky.tif"
    planar = tmp_path / "planar.tif"
    planar_tiled = tmp_path / "planar_tiled.tif"
    write_tiff(chunky, grid, rows_per_strip=4, compression=8, predictor=2)
    write_tiff(planar, grid, planar=2, rows_per_strip=5)
    write_tiff(planar_tiled, grid, planar=2, tiled=(16, 16), compression=8)
    sets = [_set(p) for p in (chunky, planar, planar_tiled)]
    assert len({s[PIXELS] for s in sets}) == 1
    assert len({s[STRUCTURE] for s in sets}) == 1


def test_floating_point_samples_are_read(tmp_path):
    grid = _grid(kind="f")
    a, b = tmp_path / "a.tif", tmp_path / "b.tif"
    write_tiff(a, grid, kind="f", bits=32)
    write_tiff(b, grid, kind="f", bits=32, tiled=(16, 16), compression=8, byte_order=">")
    assert _set(a)[PIXELS] == _set(b)[PIXELS]


def test_one_edited_pixel_is_pixels_changed(tmp_path, grid):
    before, after = tmp_path / "before.tif", tmp_path / "after.tif"
    write_tiff(before, grid, tiled=(16, 16), compression=8)
    edited = [list(row) for row in grid]
    edited[11][19] = (edited[11][19][0] + 1,)
    write_tiff(after, edited, tiled=(16, 16), compression=8)
    result = compare.compare_fingerprint_sets(_set(before), _set(after))
    assert result.verdict == compare.VERDICT_PIXELS_CHANGED
    assert result.changed


def test_a_reassigned_crs_is_a_schema_change(tmp_path, grid):
    before, after = tmp_path / "before.tif", tmp_path / "after.tif"
    write_tiff(before, grid, epsg=32644)
    write_tiff(after, grid, epsg=32643)
    assert (
        compare.compare_fingerprint_sets(_set(before), _set(after)).verdict
        == compare.VERDICT_SCHEMA_CHANGED
    )


def test_a_moved_origin_is_a_schema_change(tmp_path, grid):
    before, after = tmp_path / "before.tif", tmp_path / "after.tif"
    write_tiff(before, grid)
    write_tiff(after, grid, origin=(500030.0, 1300000.0))
    assert (
        compare.compare_fingerprint_sets(_set(before), _set(after)).verdict
        == compare.VERDICT_SCHEMA_CHANGED
    )


def test_a_changed_nodata_value_is_a_schema_change(tmp_path, grid):
    before, after = tmp_path / "before.tif", tmp_path / "after.tif"
    write_tiff(before, grid, nodata="0")
    write_tiff(after, grid, nodata="65535")
    assert (
        compare.compare_fingerprint_sets(_set(before), _set(after)).verdict
        == compare.VERDICT_SCHEMA_CHANGED
    )


def test_nodata_spelled_differently_is_the_same_nodata(tmp_path, grid):
    a, b = tmp_path / "a.tif", tmp_path / "b.tif"
    write_tiff(a, grid, nodata="0")
    write_tiff(b, grid, nodata="0.0", compression=8)
    assert compare.compare_fingerprint_sets(_set(a), _set(b)).verdict == compare.VERDICT_RESAVED


def test_a_crs_citation_worded_differently_is_not_a_crs_change(tmp_path, grid):
    a, b = tmp_path / "a.tif", tmp_path / "b.tif"
    write_tiff(a, grid, citation="WGS 84 / UTM zone 44N")
    write_tiff(b, grid, citation="UTM Zone 44, Northern Hemisphere", compression=8)
    assert compare.compare_fingerprint_sets(_set(a), _set(b)).verdict == compare.VERDICT_RESAVED


def test_an_unsupported_compression_keeps_structure_but_has_no_pixel_signal(tmp_path, grid):
    plain = tmp_path / "plain.tif"
    lzw = tmp_path / "lzw.tif"
    write_tiff(plain, grid)
    write_tiff(lzw, grid)
    # Mark the second file LZW (5) without re-encoding: the structure reader
    # must still work, and the pixel decoder must refuse rather than misread.
    raw = bytearray(lzw.read_bytes())
    description = tiff.describe(lzw)
    assert description is not None and description.compression == 1
    marker = (259).to_bytes(2, "little") + (3).to_bytes(2, "little") + (1).to_bytes(4, "little") + (1).to_bytes(2, "little")
    index = raw.find(marker)
    assert index > 0
    raw[index + 8 : index + 10] = (5).to_bytes(2, "little")
    lzw.write_bytes(bytes(raw))
    s = _set(lzw)
    assert STRUCTURE in s and PIXELS not in s
    result = compare.compare_fingerprint_sets(_set(plain), s)
    # Bytes moved, structure held, pixels unmeasured on one side: never resaved.
    assert result.verdict == compare.VERDICT_CHANGED
    assert PIXELS in result.unavailable


def test_a_file_that_merely_ends_in_tif_yields_no_signals(tmp_path):
    fake = tmp_path / "fake.tif"
    fake.write_bytes(b"not a tiff at all")
    fps = hashing.fingerprint_dataset(fake)
    assert [f.hash_strategy for f in fps] == [hashing.STRATEGY_FILE]


def test_a_truncated_tiff_yields_no_pixel_signal_and_does_not_raise(tmp_path, grid):
    path = tmp_path / "t.tif"
    write_tiff(path, grid, rows_per_strip=4)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) - 40])
    s = _set(path)
    assert PIXELS not in s


def test_the_description_reads_the_grid_and_georeferencing(tmp_path, grid):
    path = tmp_path / "g.tif"
    write_tiff(path, grid, origin=(400000.0, 1290000.0), pixel_size=(30.0, 30.0), nodata="0")
    d = tiff.describe(path)
    assert (d.width, d.height, d.bands) == (37, 23, 1)
    assert d.geotransform == (400000.0, 30.0, 0.0, 1290000.0, 0.0, -30.0)
    assert d.crs_payload() == {"model": 1, "projected": 32644}
    assert d.nodata == "0.0"


def test_a_raster_over_the_threshold_falls_back_to_its_own_grid(tmp_path, grid):
    path = tmp_path / "big.tif"
    write_tiff(path, grid)
    fps = hashing.fingerprint_dataset(path, threshold_bytes=10)
    strategies = [f.hash_strategy for f in fps]
    assert strategies[0] == hashing.STRATEGY_SCHEMA_SAMPLE
    assert PIXELS in strategies


def test_the_pixel_stream_does_not_depend_on_strip_or_tile_size(tmp_path):
    grid = _grid(width=50, height=41)
    digests = set()
    for i, (layout) in enumerate(itertools.chain(
        [dict(rows_per_strip=n) for n in (1, 2, 7, 41)],
        [dict(tiled=(t, t)) for t in (16, 32, 64)],
    )):
        p = tmp_path / f"{i}.tif"
        write_tiff(p, grid, **layout)
        digests.add(_set(p)[PIXELS])
    assert len(digests) == 1


# ---------------------------------------------------------------------------
# Found by the E1 development run (24 Oct 2026): storage details that leaked
# ---------------------------------------------------------------------------

def test_pixel_is_point_and_pixel_is_area_of_one_grid_are_one_structure(tmp_path, grid):
    """QGIS rewrites a pixel-is-point Landsat file as pixel-is-area, moving the
    origin half a pixel; the grid is the same."""
    from _tiffwriter import write_tiff as w

    point = tmp_path / "point.tif"
    area = tmp_path / "area.tif"
    w(point, grid, origin=(500015.0, 1299985.0))
    raw = bytearray(point.read_bytes())
    # flip GTRasterTypeGeoKey (1025) from 1 (area) to 2 (point) in place
    needle = (1025).to_bytes(2, "little") + (0).to_bytes(2, "little") + (1).to_bytes(2, "little") + (1).to_bytes(2, "little")
    i = raw.find(needle)
    assert i > 0
    raw[i + 6:i + 8] = (2).to_bytes(2, "little")
    point.write_bytes(bytes(raw))
    w(area, grid, origin=(500000.0, 1300000.0), compression=8)
    assert compare.compare_fingerprint_sets(_set(point), _set(area)).verdict == compare.VERDICT_RESAVED


def test_float32_nodata_spelled_with_different_precision_is_one_value(tmp_path):
    grid = _grid(kind="f")
    a, b = tmp_path / "a.tif", tmp_path / "b.tif"
    write_tiff(a, grid, kind="f", bits=32, nodata="3.402823466e+38")
    write_tiff(b, grid, kind="f", bits=32, nodata="3.4028234663852886e+38", compression=8)
    assert compare.compare_fingerprint_sets(_set(a), _set(b)).verdict == compare.VERDICT_RESAVED
