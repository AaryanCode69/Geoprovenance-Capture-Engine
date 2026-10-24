"""C1 — interior vertices of lines and polygons, and Shapefile row order.

The point-nudge tests in `test_compare.py` pin the case where count and extent
hold; these pin it for the shapes it is hardest for — a vertex in the middle of
a line or on a polygon ring, which moves nothing a bounding box can see — and
pin that a Shapefile written with its features in another order is a re-save.
Files are written with the dependency-free writers in `qgis_demo/`, so no GDAL.
"""

from __future__ import annotations

import pathlib
import sqlite3
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from qgis_demo import geopkg, shapefile  # noqa: E402

from geoprovenance.fingerprint import (  # noqa: E402
    STRATEGY_ATTRIBUTES,
    STRATEGY_GEOMETRY,
    STRATEGY_GEOMETRY_CONTENT,
    VERDICT_GEOMETRY_CHANGED,
    VERDICT_RESAVED,
    compare_fingerprint_sets,
    fingerprint_dataset,
)

LINE = [(0.0, 0.0), (1.0, 2.0), (2.0, 1.0), (3.0, 3.0)]
RING = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (2.0, 3.0), (0.0, 4.0), (0.0, 0.0)]
OTHER = [(10.0, 10.0), (11.0, 12.0), (12.0, 10.0)]
SHAPE_POLYGON = 5


def signals(path: pathlib.Path) -> dict[str, str]:
    return {f.hash_strategy: f.hash_value for f in fingerprint_dataset(path)}


def _moved(coords, index, dx=0.25):
    out = list(coords)
    x, y = out[index]
    out[index] = (x + dx, y)
    return out


def _write_shp(path: pathlib.Path, geometries, names, *, polygon=False) -> pathlib.Path:
    # Same file name on both sides: a layer's name is part of what it describes.
    path = path.parent / path.stem / "shapes.shp"
    shapefile.write_shapefile(path, shapefile.SHAPE_POLYLINE, geometries,
                              [("name", 10)], [{"name": n} for n in names])
    if polygon:
        # A polygon record has the polyline record's layout with shape type 5,
        # so the polyline writer's output becomes a polygon by its type codes.
        raw = bytearray(path.read_bytes())
        raw[32:36] = struct.pack("<i", SHAPE_POLYGON)
        position = 100
        while position < len(raw):
            _, words = struct.unpack(">ii", raw[position:position + 8])
            raw[position + 8:position + 12] = struct.pack("<i", SHAPE_POLYGON)
            position += 8 + words * 2
        path.write_bytes(bytes(raw))
        shx = path.with_suffix(".shx")
        rawx = bytearray(shx.read_bytes())
        rawx[32:36] = struct.pack("<i", SHAPE_POLYGON)
        shx.write_bytes(bytes(rawx))
    return path


@pytest.mark.parametrize("polygon", [False, True], ids=["line", "polygon ring"])
def test_a_shapefile_interior_vertex_moved_inside_the_extent_is_a_geometry_change(tmp_path, polygon):
    shape = RING if polygon else LINE
    index = 3 if polygon else 1  # (2, 3) is inside the ring's box; (1, 2) inside the line's
    before = signals(_write_shp(tmp_path / "a.shp", [shape, OTHER], ["a", "b"], polygon=polygon))
    after = signals(_write_shp(tmp_path / "b.shp", [_moved(shape, index), OTHER], ["a", "b"], polygon=polygon))
    assert before[STRATEGY_GEOMETRY] == after[STRATEGY_GEOMETRY], "count and extent must hold"
    assert before[STRATEGY_ATTRIBUTES] == after[STRATEGY_ATTRIBUTES]
    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_GEOMETRY_CHANGED
    assert STRATEGY_GEOMETRY_CONTENT in comparison.moved


def _write_gpkg(path: pathlib.Path, wkbs, geometry_type: str) -> pathlib.Path:
    layer = geopkg.Layer(
        name="shapes", geometry_type=geometry_type, fields=[geopkg.Field("name")],
        rows=[(w, {"name": n}) for w, n in zip(wkbs, ("a", "b"))])
    return geopkg.write_geopackage(path, [layer])


@pytest.mark.parametrize("polygon", [False, True], ids=["line", "polygon ring"])
def test_a_geopackage_interior_vertex_moved_inside_the_extent_is_a_geometry_change(tmp_path, polygon):
    if polygon:
        make, shape, index, kind = (lambda c: geopkg.wkb_polygon([c])), RING, 3, "POLYGON"
    else:
        make, shape, index, kind = geopkg.wkb_linestring, LINE, 1, "LINESTRING"
    path = _write_gpkg(tmp_path / "a.gpkg", [make(shape), make(OTHER)], kind)
    before = signals(path)
    connection = sqlite3.connect(path)
    connection.execute("UPDATE shapes SET geom = ? WHERE name = 'a'",
                       (geopkg.gpkg_blob(make(_moved(shape, index))),))
    connection.commit()
    connection.close()
    after = signals(path)
    assert before[STRATEGY_ATTRIBUTES] == after[STRATEGY_ATTRIBUTES]
    comparison = compare_fingerprint_sets(before, after)
    assert comparison.verdict == VERDICT_GEOMETRY_CHANGED
    assert STRATEGY_GEOMETRY_CONTENT in comparison.moved


def test_a_shapefile_with_rows_reordered_is_resaved(tmp_path):
    """Same features, same values, written in the opposite order."""
    first = signals(_write_shp(tmp_path / "a.shp", [LINE, OTHER], ["a", "b"]))
    second = signals(_write_shp(tmp_path / "b.shp", [OTHER, LINE], ["b", "a"]))
    comparison = compare_fingerprint_sets(first, second)
    assert comparison.verdict == VERDICT_RESAVED


def test_the_shapefile_attribute_digest_ignores_row_order(tmp_path):
    first = signals(_write_shp(tmp_path / "a.shp", [LINE, OTHER], ["a", "b"]))
    second = signals(_write_shp(tmp_path / "b.shp", [OTHER, LINE], ["b", "a"]))
    assert first[STRATEGY_ATTRIBUTES] == second[STRATEGY_ATTRIBUTES]
    assert first[STRATEGY_GEOMETRY_CONTENT] == second[STRATEGY_GEOMETRY_CONTENT]
