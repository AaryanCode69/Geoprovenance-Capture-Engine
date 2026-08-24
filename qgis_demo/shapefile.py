"""A dependency-free Shapefile writer — points and polylines.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

``tests/fixtures/_minifiles.py`` already writes a point shapefile, and is
deliberately not extended: it is part of the frozen fixture build that Person B
and Person C consume (RULES.md §3.4, §10.3). This borrows the technique — and
the same mixed-endianness care the specification demands — for the demo's own
data, where polylines are needed too.

Having some of the demo data be Shapefile and some GeoPackage is the point, not
an accident: the provenance record carries a ``format`` for every file it knows
about, and a demo where every file is the same format never exercises or shows
that column.

Reference
    ESRI Shapefile Technical Description (July 1998)
    dBASE III, for the .dbf layout that specification refers to
"""

from __future__ import annotations

import pathlib
import struct
from typing import Sequence

WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)

SHAPE_POINT = 1
SHAPE_POLYLINE = 3

_FIXED_DBF_DATE = (2026, 8, 24)  # never date.today() — these outputs are committed

Coord = tuple[float, float]


def _header(file_length_words: int, shape_type: int,
            bbox: tuple[float, float, float, float]) -> bytes:
    """The 100-byte header shared by .shp and .shx. Mixed endianness, as specified."""
    xmin, ymin, xmax, ymax = bbox
    return (
        struct.pack(">i", 9994)          # file code
        + b"\x00" * 20                   # unused
        + struct.pack(">i", file_length_words)
        + struct.pack("<i", 1000)        # version
        + struct.pack("<i", shape_type)
        + struct.pack("<4d", xmin, ymin, xmax, ymax)
        + struct.pack("<4d", 0.0, 0.0, 0.0, 0.0)  # z and m ranges, unused
    )


def _point_record(x: float, y: float) -> bytes:
    return struct.pack("<i", SHAPE_POINT) + struct.pack("<2d", x, y)


def _polyline_record(coords: Sequence[Coord]) -> bytes:
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    body = struct.pack("<i", SHAPE_POLYLINE)
    body += struct.pack("<4d", min(xs), min(ys), max(xs), max(ys))
    body += struct.pack("<2i", 1, len(coords))   # one part, N points
    body += struct.pack("<i", 0)                 # that part starts at index 0
    body += b"".join(struct.pack("<2d", x, y) for x, y in coords)
    return body


def _dbf(fields: Sequence[tuple[str, int]], records: Sequence[dict]) -> bytes:
    """A dBASE III table with character fields only.

    Character fields only is a real simplification, and a deliberate one: every
    attribute the demo carries is a name or a label, and adding numeric field
    encoding would be code with no reader.
    """
    year, month, day = _FIXED_DBF_DATE
    header_length = 32 + 32 * len(fields) + 1
    record_length = 1 + sum(width for _, width in fields)

    out = bytearray()
    out += struct.pack("<B3BIHH", 0x03, year - 1900, month, day,
                       len(records), header_length, record_length)
    out += b"\x00" * 20

    for name, width in fields:
        out += name.encode("ascii")[:10].ljust(11, b"\x00")
        out += b"C"                     # character
        out += b"\x00" * 4              # field data address, unused
        out += struct.pack("<B", width)
        out += b"\x00" * 15
    out += b"\x0d"                      # header terminator

    for record in records:
        out += b" "                     # deletion flag: not deleted
        for name, width in fields:
            value = str(record.get(name, ""))
            out += value.encode("ascii", "replace")[:width].ljust(width, b" ")
    out += b"\x1a"                      # end of file
    return bytes(out)


def write_shapefile(path, shape_type: int,
                    geometries: Sequence[Sequence[Coord]],
                    fields: Sequence[tuple[str, int]],
                    records: Sequence[dict]) -> pathlib.Path:
    """Write .shp, .shx, .dbf and .prj.

    ``geometries`` is a list of coordinate lists. For ``SHAPE_POINT`` each inner
    list holds exactly one coordinate.
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    all_coords = [c for geom in geometries for c in geom]
    xs = [c[0] for c in all_coords]
    ys = [c[1] for c in all_coords]
    bbox = (min(xs), min(ys), max(xs), max(ys))

    shp_body = bytearray()
    shx_body = bytearray()
    offset_words = 50  # the 100-byte header, in 16-bit words

    for index, geom in enumerate(geometries, start=1):
        if shape_type == SHAPE_POINT:
            content = _point_record(*geom[0])
        elif shape_type == SHAPE_POLYLINE:
            content = _polyline_record(geom)
        else:
            raise ValueError(f"unsupported shape type {shape_type}")

        content_words = len(content) // 2
        shp_body += struct.pack(">2i", index, content_words) + content
        shx_body += struct.pack(">2i", offset_words, content_words)
        offset_words += 4 + content_words   # 8-byte record header, in words

    shp_length_words = 50 + len(shp_body) // 2
    shx_length_words = 50 + len(shx_body) // 2

    path.write_bytes(_header(shp_length_words, shape_type, bbox) + bytes(shp_body))
    path.with_suffix(".shx").write_bytes(
        _header(shx_length_words, shape_type, bbox) + bytes(shx_body))
    path.with_suffix(".dbf").write_bytes(_dbf(fields, records))
    path.with_suffix(".prj").write_text(WGS84_PRJ)
    return path
