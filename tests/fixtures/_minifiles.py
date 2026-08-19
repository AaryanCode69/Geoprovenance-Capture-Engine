"""Minimal, dependency-free writers for a real Shapefile and a real GeoPackage.

Owner: Person A.  Sub-phase: A0.3.  Used only by build_fixtures.py.

Why hand-rolled rather than GDAL/OGR/fiona
    The fixtures must be regenerable by Person B and Person C on a machine with
    no QGIS and no GIS stack (PERSON_A.md §A0.3 exit criterion), and RULES.md
    §2.2 keeps heavyweight dependencies out of this project. Both formats are
    open specifications and the subset needed here is small.

What these produce
    A valid single-layer point Shapefile (.shp/.shx/.dbf/.prj) and a valid
    OGC GeoPackage 1.3 with one point feature table. Enough for Person B's
    fingerprinter to hash real bytes and for Person C's "does this input still
    exist?" check to find a real file. NOT general-purpose writers — points
    only, WGS84 only, no M/Z values.

Determinism
    Every byte is a pure function of the input. No clocks, no random ids. The
    fixtures are committed (RULES.md §10.3), so a regeneration that changed
    bytes gratuitously would churn the diff and hide real changes.

References
    Shapefile:   ESRI Shapefile Technical Description (July 1998)
    dBASE III:   the .dbf layout that specification refers to
    GeoPackage:  OGC 12-128r19, GeoPackage Encoding Standard 1.3
"""

from __future__ import annotations

import pathlib
import sqlite3
import struct

WGS84_WKT = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)

_SHAPE_TYPE_POINT = 1
_FIXED_DBF_DATE = (2026, 8, 8)  # never date.today() — see "Determinism" above


# ---------------------------------------------------------------------------
# Shapefile
# ---------------------------------------------------------------------------

def _shp_header(file_length_words: int, bbox: tuple[float, float, float, float]) -> bytes:
    """The 100-byte header shared by .shp and .shx (mixed endianness, as specified)."""
    xmin, ymin, xmax, ymax = bbox
    return (
        struct.pack(">i", 9994)          # file code
        + b"\x00" * 20                   # unused
        + struct.pack(">i", file_length_words)
        + struct.pack("<i", 1000)        # version
        + struct.pack("<i", _SHAPE_TYPE_POINT)
        + struct.pack("<4d", xmin, ymin, xmax, ymax)
        + struct.pack("<4d", 0.0, 0.0, 0.0, 0.0)  # z and m ranges, unused
    )


def _dbf(fields: list[tuple[str, str, int]], records: list[list[str]]) -> bytes:
    """A dBASE III table. ``fields`` is (name, type_char, length)."""
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(length for _, _, length in fields)
    yy, mm, dd = _FIXED_DBF_DATE

    out = bytearray()
    out += struct.pack(
        "<4BIHH20x", 0x03, yy - 1900, mm, dd, len(records), header_len, record_len
    )
    for name, type_char, length in fields:
        out += struct.pack(
            "<11sc4xBB14x",
            name.encode("ascii")[:10].ljust(11, b"\x00"),
            type_char.encode("ascii"),
            length,
            0,
        )
    out += b"\x0d"  # end of field descriptors

    for record in records:
        out += b" "  # deletion flag: not deleted
        for value, (_, type_char, length) in zip(record, fields):
            raw = str(value).encode("ascii")[:length]
            # Character fields are left-justified, numerics right-justified.
            out += raw.ljust(length) if type_char == "C" else raw.rjust(length)

    out += b"\x1a"  # end of file
    return bytes(out)


def write_point_shapefile(
    base_path: pathlib.Path,
    points: list[tuple[float, float]],
    attributes: list[dict[str, str]],
    fields: list[tuple[str, str, int]],
) -> list[pathlib.Path]:
    """Write ``base_path`` .shp/.shx/.dbf/.prj. Returns the paths written."""
    base_path = pathlib.Path(base_path)
    if len(points) != len(attributes):
        raise ValueError("points and attributes must be the same length")

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    bbox = (min(xs), min(ys), max(xs), max(ys))

    # Point record content: shape type + X + Y = 20 bytes = 10 16-bit words.
    content_words = 10
    record_bytes = 8 + content_words * 2

    shp = bytearray(_shp_header((100 + len(points) * record_bytes) // 2, bbox))
    shx = bytearray(_shp_header((100 + len(points) * 8) // 2, bbox))

    for index, (x, y) in enumerate(points):
        offset_words = (100 + index * record_bytes) // 2
        shp += struct.pack(">2i", index + 1, content_words)
        shp += struct.pack("<i", _SHAPE_TYPE_POINT) + struct.pack("<2d", x, y)
        shx += struct.pack(">2i", offset_words, content_words)

    records = [[attrs[name] for name, _, _ in fields] for attrs in attributes]

    written = []
    for suffix, payload in (
        (".shp", bytes(shp)),
        (".shx", bytes(shx)),
        (".dbf", _dbf(fields, records)),
        (".prj", WGS84_WKT.encode("ascii")),
    ):
        path = base_path.with_suffix(suffix)
        path.write_bytes(payload)
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# GeoPackage
# ---------------------------------------------------------------------------

_GPKG_APPLICATION_ID = 0x47504B47  # 'GPKG'
_GPKG_USER_VERSION = 10300         # 1.3.0
_GPKG_FIXED_LAST_CHANGE = "2026-08-08T10:00:00.000Z"


#: Bytes 92-99 of every SQLite file are the "version-valid-for" number and
#: SQLITE_VERSION_NUMBER — the version of the library that last wrote the file.
#: They are informational: SQLite treats the stored version number as stale
#: whenever version-valid-for disagrees with the change counter, and re-stamps
#: both on the next write. Nothing reads them for correctness.
_SQLITE_VERSION_FIELD = slice(92, 100)


def normalise_sqlite_header(path) -> None:
    """Blank the SQLite-version stamp — the largest single source of byte drift.

    Everything else in this module is written for byte determinism — a fixed
    ``last_change``, a fixed page size, no autoincrement drift — because the
    fixtures are COMMITTED and shared (RULES.md §10.3), and a churning binary
    diff hides real changes.

    The version stamp defeated all of it. A GeoPackage written by SQLite
    3.51.2 and one written by 3.53.4 differ in exactly these bytes, so the
    file's SHA-256 differs too — and ``build_fixtures.py`` records that hash in
    ``mock_provenance.db``. The result was that Person B and Person C could not
    reproduce the committed fixtures on their own machines at all, and the test
    that noticed blamed them for hand-editing.

    Necessary, but NOT sufficient, and the difference matters to whoever reads
    this next. The stamp is the only cross-version difference between 3.51.2
    and 3.53.4, but 3.40.1 also leaves three stale bytes (``02 80 00 4b``) in
    the free space of the schema page where 3.53.4 leaves zeros, and a library
    built without ``SQLITE_SECURE_DELETE`` leaves about a thousand such bytes
    at any version. ``VACUUM`` and ``VACUUM INTO`` reproduce the residue rather
    than erasing it, so there is nothing further to do here: the committed
    SQLite files are reproducible by their CONTENTS, not by their bytes. See
    ``_logical_content`` in tests/storage/test_fixtures.py and the "Across
    machines" section of this directory's README.

    Test-only. Nothing under ``geoprovenance/`` may call this: the plugin must
    never rewrite bytes underneath SQLite.
    """
    path = pathlib.Path(path)
    raw = bytearray(path.read_bytes())
    if len(raw) < _SQLITE_VERSION_FIELD.stop or bytes(raw[:15]) != b"SQLite format 3":
        return
    raw[_SQLITE_VERSION_FIELD] = b"\x00" * 8
    path.write_bytes(bytes(raw))


def _gpkg_point_blob(x: float, y: float, srs_id: int = 4326) -> bytes:
    """A GeoPackageBinary point: 8-byte header + little-endian WKB point."""
    flags = 0b0000_0001  # little-endian header, no envelope, standard geometry
    header = b"GP" + bytes([0, flags]) + struct.pack("<i", srs_id)
    wkb = struct.pack("<BI2d", 1, 1, x, y)  # byte order, geometry type 1, x, y
    return header + wkb


def write_point_geopackage(
    path: pathlib.Path,
    table_name: str,
    points: list[tuple[float, float]],
    attributes: list[dict[str, str]],
) -> pathlib.Path:
    """Write a GeoPackage 1.3 containing one point feature table."""
    path = pathlib.Path(path)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    try:
        # 1 KB pages keep the fixture small; the default 4 KB inflates it 4x for
        # a file that holds a handful of rows.
        conn.execute("PRAGMA page_size = 1024")
        conn.execute(f"PRAGMA application_id = {_GPKG_APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version = {_GPKG_USER_VERSION}")

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

        # The three SRS rows the specification requires to be present.
        conn.executemany(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",
            [
                ("WGS 84 geodetic", 4326, "EPSG", 4326, WGS84_WKT,
                 "longitude/latitude coordinates in decimal degrees on WGS 84"),
                ("Undefined cartesian SRS", -1, "NONE", -1, "undefined",
                 "undefined cartesian coordinate reference system"),
                ("Undefined geographic SRS", 0, "NONE", 0, "undefined",
                 "undefined geographic coordinate reference system"),
            ],
        )

        conn.execute(
            f'CREATE TABLE "{table_name}" ('
            " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
            " geom BLOB, name TEXT, category TEXT)"
        )

        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        conn.execute(
            "INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)",
            (table_name, "features", table_name, "GeoProvenance test fixture",
             _GPKG_FIXED_LAST_CHANGE, min(xs), min(ys), max(xs), max(ys), 4326),
        )
        conn.execute(
            "INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",
            (table_name, "geom", "POINT", 4326, 0, 0),
        )
        conn.executemany(
            f'INSERT INTO "{table_name}" (geom, name, category) VALUES (?,?,?)',
            [
                (_gpkg_point_blob(x, y), attrs["name"], attrs["category"])
                for (x, y), attrs in zip(points, attributes)
            ],
        )
        conn.commit()
    finally:
        conn.close()
    normalise_sqlite_header(path)
    return path
