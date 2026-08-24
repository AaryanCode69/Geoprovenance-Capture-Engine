"""A dependency-free OGC GeoPackage writer — points, lines, polygons, and tables.

Owner: Person A.  Not plugin code: this lives outside ``geoprovenance/`` on
purpose, because writing map layers is not part of the write path RULES.md §1.1
puts in Person A's hands. It is demo scaffolding, and it is kept here so the
plugin package stays exactly the surface that section lists.

Why hand-rolled rather than GDAL/OGR
    The same reason ``tests/fixtures/_minifiles.py`` is hand-rolled: RULES.md
    §2.2 keeps heavyweight dependencies out of this project, and the demo has to
    be rebuildable on a machine with no GIS stack installed. GeoPackage is an
    open specification and the subset needed here is small.

    ``_minifiles.py`` already does this for points, and it is deliberately NOT
    imported or extended here. It is part of the frozen fixture build that
    Person B and Person C consume (RULES.md §3.4, §10.3); a change there ripples
    into their test data. This module borrows the technique, not the file.

What this produces
    A valid GeoPackage 1.3 with any number of feature tables (POINT, LINESTRING,
    POLYGON) and attribute-only tables. WGS 84 only, 2D only, no M/Z. Enough for
    QGIS to open every layer with full symbology and a working attribute table.

Determinism
    Every byte is a pure function of the input. No clocks, no random ids — so a
    rebuild that changes bytes changed something real.

Reference
    OGC 12-128r19, GeoPackage Encoding Standard 1.3
"""

from __future__ import annotations

import pathlib
import sqlite3
import struct
from typing import Any, NamedTuple, Sequence

WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],'
    'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]]'
)

_APPLICATION_ID = 0x47504B47  # 'GPKG'
_USER_VERSION = 10300         # 1.3.0
_FIXED_LAST_CHANGE = "2026-08-24T00:00:00.000Z"  # never datetime.now() — see above

WGS84_SRS_ID = 4326

# WKB geometry type codes (OGC simple features).
_WKB_POINT = 1
_WKB_LINESTRING = 2
_WKB_POLYGON = 3

Coord = tuple[float, float]


# ---------------------------------------------------------------------------
# Well-Known Binary
# ---------------------------------------------------------------------------

def wkb_point(x: float, y: float) -> bytes:
    return struct.pack("<BI2d", 1, _WKB_POINT, x, y)


def wkb_linestring(coords: Sequence[Coord]) -> bytes:
    body = struct.pack("<BII", 1, _WKB_LINESTRING, len(coords))
    return body + b"".join(struct.pack("<2d", x, y) for x, y in coords)


def wkb_polygon(rings: Sequence[Sequence[Coord]]) -> bytes:
    """Rings must be closed — first coordinate repeated as the last."""
    out = struct.pack("<BII", 1, _WKB_POLYGON, len(rings))
    for ring in rings:
        out += struct.pack("<I", len(ring))
        out += b"".join(struct.pack("<2d", x, y) for x, y in ring)
    return out


def wkb_box(xmin: float, ymin: float, xmax: float, ymax: float) -> bytes:
    """An axis-aligned rectangle as a single-ring polygon, wound anticlockwise."""
    ring = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax), (xmin, ymin)]
    return wkb_polygon([ring])


def _wkb_envelope(wkb: bytes) -> tuple[float, float, float, float]:
    """Bounding box of a WKB geometry, by walking its coordinate doubles.

    Only the three geometry types this module writes are supported; anything
    else raises rather than silently returning a wrong envelope.
    """
    (byte_order,), rest = struct.unpack_from("<B", wkb), wkb[1:]
    if byte_order != 1:
        raise ValueError("only little-endian WKB is written by this module")
    (gtype,) = struct.unpack_from("<I", rest)
    coords: list[Coord] = []
    if gtype == _WKB_POINT:
        coords = [struct.unpack_from("<2d", rest, 4)]
    elif gtype == _WKB_LINESTRING:
        (n,) = struct.unpack_from("<I", rest, 4)
        coords = [struct.unpack_from("<2d", rest, 8 + 16 * i) for i in range(n)]
    elif gtype == _WKB_POLYGON:
        (n_rings,) = struct.unpack_from("<I", rest, 4)
        offset = 8
        for _ in range(n_rings):
            (n,) = struct.unpack_from("<I", rest, offset)
            offset += 4
            for _ in range(n):
                coords.append(struct.unpack_from("<2d", rest, offset))
                offset += 16
    else:
        raise ValueError(f"unsupported WKB geometry type {gtype}")
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return min(xs), min(ys), max(xs), max(ys)


def gpkg_blob(wkb: bytes, srs_id: int = WGS84_SRS_ID) -> bytes:
    """Wrap WKB in a GeoPackageBinary header, with its envelope included.

    The envelope is optional in the specification, but QGIS uses it to build a
    layer's extent without scanning every feature — worth the 32 bytes.
    """
    xmin, ymin, xmax, ymax = _wkb_envelope(wkb)
    flags = 0b0000_0011  # little-endian header, envelope is [minx,maxx,miny,maxy]
    header = b"GP" + bytes([0, flags]) + struct.pack("<i", srs_id)
    envelope = struct.pack("<4d", xmin, xmax, ymin, ymax)
    return header + envelope + wkb


# ---------------------------------------------------------------------------
# Layer description
# ---------------------------------------------------------------------------

class Field(NamedTuple):
    name: str
    sql_type: str = "TEXT"   # TEXT | INTEGER | REAL


class Layer(NamedTuple):
    """One table in the GeoPackage.

    ``geometry_type`` of ``None`` produces an attribute-only table — a real
    GeoPackage construct (``data_type = 'attributes'``) that QGIS opens as a
    table with no map presence. That is how records with no location on Earth
    are carried without inventing coordinates for them.
    """
    name: str
    geometry_type: str | None            # POINT | LINESTRING | POLYGON | None
    fields: Sequence[Field]
    rows: Sequence[tuple[bytes | None, dict[str, Any]]]
    description: str = ""


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

_SQLITE_VERSION_FIELD = slice(92, 100)


def _blank_sqlite_version_stamp(path: pathlib.Path) -> None:
    """Blank bytes 92-99, the version of the library that last wrote the file.

    Informational bytes that SQLite re-stamps on the next write and nothing
    reads for correctness — but they are the largest single source of byte drift
    between machines, and these outputs are committed. Same reasoning, and the
    same caveat, as ``_minifiles.normalise_sqlite_header``: this makes the file
    reproducible by its contents, not by its bytes.
    """
    raw = bytearray(path.read_bytes())
    if len(raw) < _SQLITE_VERSION_FIELD.stop or bytes(raw[:15]) != b"SQLite format 3":
        return
    raw[_SQLITE_VERSION_FIELD] = b"\x00" * 8
    path.write_bytes(bytes(raw))


def write_geopackage(path, layers: Sequence[Layer]) -> pathlib.Path:
    """Write a GeoPackage 1.3 holding every layer given, replacing any existing file."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version = {_USER_VERSION}")
        _create_core_tables(conn)

        for layer in layers:
            _write_layer(conn, layer)

        conn.commit()
    finally:
        conn.close()
    _blank_sqlite_version_stamp(path)
    return path


def _create_core_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE gpkg_spatial_ref_sys ("
        " srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY,"
        " organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,"
        " definition TEXT NOT NULL, description TEXT)"
    )
    conn.execute(
        "CREATE TABLE gpkg_contents ("
        " table_name TEXT PRIMARY KEY, data_type TEXT NOT NULL,"
        " identifier TEXT UNIQUE, description TEXT DEFAULT '',"
        " last_change TEXT NOT NULL, min_x DOUBLE, min_y DOUBLE,"
        " max_x DOUBLE, max_y DOUBLE, srs_id INTEGER,"
        " CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)"
        "  REFERENCES gpkg_spatial_ref_sys(srs_id))"
    )
    conn.execute(
        "CREATE TABLE gpkg_geometry_columns ("
        " table_name TEXT NOT NULL, column_name TEXT NOT NULL,"
        " geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,"
        " z TINYINT NOT NULL, m TINYINT NOT NULL,"
        " CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name))"
    )
    # The three rows the specification requires to be present.
    conn.executemany(
        "INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",
        [
            ("WGS 84 geodetic", WGS84_SRS_ID, "EPSG", 4326, WGS84_WKT,
             "longitude/latitude coordinates in decimal degrees on WGS 84"),
            ("Undefined cartesian SRS", -1, "NONE", -1, "undefined",
             "undefined cartesian coordinate reference system"),
            ("Undefined geographic SRS", 0, "NONE", 0, "undefined",
             "undefined geographic coordinate reference system"),
        ],
    )


def _write_layer(conn: sqlite3.Connection, layer: Layer) -> None:
    columns = ["fid INTEGER PRIMARY KEY AUTOINCREMENT"]
    if layer.geometry_type is not None:
        columns.append("geom BLOB")
    columns += [f'"{f.name}" {f.sql_type}' for f in layer.fields]
    conn.execute(f'CREATE TABLE "{layer.name}" ({", ".join(columns)})')

    insert_columns = (["geom"] if layer.geometry_type else []) + \
                     [f.name for f in layer.fields]
    placeholders = ", ".join("?" for _ in insert_columns)
    quoted = ", ".join(f'"{c}"' for c in insert_columns)

    bounds: list[tuple[float, float, float, float]] = []
    payload = []
    for wkb, attrs in layer.rows:
        values: list[Any] = []
        if layer.geometry_type is not None:
            if wkb is None:
                values.append(None)
            else:
                bounds.append(_wkb_envelope(wkb))
                values.append(gpkg_blob(wkb))
        values += [attrs.get(f.name) for f in layer.fields]
        payload.append(tuple(values))

    conn.executemany(
        f'INSERT INTO "{layer.name}" ({quoted}) VALUES ({placeholders})', payload
    )

    if layer.geometry_type is None:
        conn.execute(
            "INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)",
            (layer.name, "attributes", layer.name, layer.description,
             _FIXED_LAST_CHANGE, None, None, None, None, None),
        )
        return

    if bounds:
        min_x = min(b[0] for b in bounds)
        min_y = min(b[1] for b in bounds)
        max_x = max(b[2] for b in bounds)
        max_y = max(b[3] for b in bounds)
    else:
        min_x = min_y = max_x = max_y = None

    conn.execute(
        "INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)",
        (layer.name, "features", layer.name, layer.description,
         _FIXED_LAST_CHANGE, min_x, min_y, max_x, max_y, WGS84_SRS_ID),
    )
    conn.execute(
        "INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",
        (layer.name, "geom", layer.geometry_type, WGS84_SRS_ID, 0, 0),
    )
