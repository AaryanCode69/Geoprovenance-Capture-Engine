"""Reading a dataset's *shape* off disk, without QGIS and without GDAL.

Owner: Person B.  Research doc §6.4 row 2 ("feature-count + schema hash").

    RULES.md §2.2 — standard library only. `struct`, `sqlite3`, `pathlib`, `json`.
    RULES.md §4.1 — imports no QGIS, so the whole layer runs under `make test`.

Why this module has to exist
    A byte hash answers one question: are these the same bytes? That is the
    wrong question twice over, and both wrong answers are counted by RQ3
    (research doc §9.1 — detection accuracy).

    It says CHANGED when nothing changed. A GeoPackage is a SQLite file, and
    SQLite stamps its own library version into every file it writes. Rebuilding
    tests/fixtures/data/sample_areas.gpkg from one identical script under
    different SQLite builds was measured in this repository to move bytes 92-99
    between 3.51.2 and 3.53.4, three further bytes at offset 7368 between 3.40.1
    and 3.53.4, and roughly a thousand bytes without SQLITE_SECURE_DELETE —
    while rows, schema text and root pages stayed identical every time.

    It says UNCHANGED when something changed. A Shapefile is four files, and
    the path the record holds points at the .shp. Editing a name in the .dbf
    leaves the .shp byte-identical, so the fingerprint does not move and the
    audit reports the file untouched.

    Reading the shape of the data separates the two. A byte hash that moved
    while the field list, feature count and extent all held is a re-save; a
    .dbf that moved while the .shp held is an attribute edit.

Why it reads the file rather than taking QGIS's word for it
    RQ3 is measured by changing a file and re-auditing it. That comparison
    happens long after capture, against whatever is on disk now, with no layer
    open — so the description has to be obtainable from a path alone.
    `feature_count` arrives on the capture event today (see `hash.py`); an
    extent and a field list cannot arrive that way and still be re-measurable.

What can be read, and what cannot
    Shapefile   the .shp header carries the bounding box at bytes 36-67, the
                .shx carries the record count, the .dbf header carries the
                field names and types, and the .prj carries the CRS.
    GeoPackage  it is a SQLite database: `gpkg_contents` carries the extent
                per table and `PRAGMA table_info` carries the columns.
    everything else, GeoTIFF included, returns None.

    GeoTIFF is the honest gap, and it is the same one `qgis_demo/footprints.py`
    documents: reading a GeoTIFF's georeferencing means parsing TIFF IFDs and
    the GeoKey directory, and the alternative is a GDAL dependency, which is
    exactly what RULES.md §2.2 exists to refuse. A dataset with no description
    contributes no complementary fingerprints, and the comparison then reports
    `unknown` on those axes rather than guessing (RULES.md §5.6).
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import sqlite3
import struct
from dataclasses import dataclass
from typing import Iterator, Sequence

#: `describe()` results carry this so a digest can never silently compare a
#: Shapefile's shape against a GeoPackage's.
FORMAT_SHAPEFILE = "Shapefile"
FORMAT_GEOPACKAGE = "GeoPackage"

#: The Shapefile magic number, big-endian, at bytes 0-3 of both .shp and .shx.
_SHAPEFILE_MAGIC = 9994

#: Both Shapefile index files open with a fixed 100-byte header; every .shx
#: record after it is exactly 8 bytes (offset + length), so the record count is
#: arithmetic rather than a scan.
_SHAPEFILE_HEADER_BYTES = 100
_SHX_RECORD_BYTES = 8

#: The .dbf field descriptor array starts here, runs in 32-byte entries, and
#: ends at this terminator byte (dBASE III+, which is what every GIS writes).
_DBF_FIELD_ARRAY_OFFSET = 32
_DBF_FIELD_DESCRIPTOR_BYTES = 32
_DBF_FIELD_TERMINATOR = 0x0D

#: Bytes 1-3 of a .dbf are the date it was last written (YY, MM, DD). They move
#: when the file is rewritten even if not one value changed, which is the same
#: class of false positive as SQLite's version stamp. Blanked before hashing —
#: `tests/fixtures/build_fixtures.py` already does exactly this to the
#: GeoPackage header for the same reason.
_DBF_LAST_UPDATE_SLICE = slice(1, 4)

#: Coordinates are rounded before they reach a digest so that a bounding box
#: recomputed by another writer cannot differ in the last unit in the last
#: place and read as a moved geometry. Nine places is under a tenth of a
#: millimetre at the equator — far finer than any real edit, far coarser than
#: float64 noise.
BBOX_DECIMAL_PLACES = 9

#: How many rows the GeoPackage attribute digest will read. Above it, no
#: attribute signal is produced at all: the rows are sorted before hashing (see
#: `attribute_chunks`), so the whole table has to be held at once, and a signal
#: that costs unbounded memory inside a user's processing run is one RULES.md
#: §5.1 would refuse anyway. A missing signal compares as `unknown`, which is
#: true; a cheaper approximate one would be confidently wrong.
DEFAULT_MAX_ATTRIBUTE_ROWS = 100_000


class DatasetReadError(RuntimeError):
    """A file claimed to be a format this module reads, and then was not."""


@dataclass(frozen=True)
class LayerDescription:
    """One layer's shape. A Shapefile has exactly one; a GeoPackage may have many."""

    name: str
    field_names: tuple[str, ...]
    field_types: tuple[str, ...]
    feature_count: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class DatasetDescription:
    """What one dataset looks like, read from the file itself."""

    format: str
    layers: tuple[LayerDescription, ...]
    crs_text: str | None = None

    def structure_payload(self) -> dict[str, object]:
        """The parts that describe the SHAPE of the data — what it holds, not how much.

        Field order is preserved rather than sorted: reordering columns is a
        schema change, and sorting here would hide it. `hash.py` makes the same
        choice for the same reason.
        """
        return {
            "format": self.format,
            "crs_text": self.crs_text,
            "layers": [
                {
                    "name": layer.name,
                    "field_names": list(layer.field_names),
                    "field_types": list(layer.field_types),
                }
                for layer in self.layers
            ],
        }

    def geometry_payload(self) -> dict[str, object]:
        """The parts that describe the EXTENT of the data — how much, and where.

        Separate from `structure_payload` on purpose. Two digests that move
        independently are what let the comparison say "the columns are the same
        but the features moved" instead of one undifferentiated "different".
        """
        return {
            "format": self.format,
            "layers": [
                {
                    "name": layer.name,
                    "feature_count": layer.feature_count,
                    "bbox": _round_bbox(layer.bbox),
                }
                for layer in self.layers
            ],
        }


def describe(path: str | pathlib.Path | None) -> DatasetDescription | None:
    """Read the shape of the dataset at `path`, or None if it cannot be read.

    Never raises for an ordinary reason — an unknown format, a missing file, a
    truncated header and an unreadable directory all return None. A description
    is an optional extra signal, and a fingerprinter that crashed on a file it
    did not recognise would be a capture failure dressed up as rigour
    (RULES.md §5.1).
    """
    if path is None:
        return None
    target = pathlib.Path(str(path))
    suffix = target.suffix.lower()
    try:
        if suffix == ".shp":
            return _describe_shapefile(target)
        if suffix in (".gpkg", ".geopackage"):
            return _describe_geopackage(target)
    except (OSError, struct.error, sqlite3.Error, DatasetReadError, UnicodeDecodeError):
        return None
    return None


def sidecar_paths(path: str | pathlib.Path | None) -> tuple[pathlib.Path, ...]:
    """The other files that are part of this dataset and exist on disk.

    Empty for anything that is a single file. For a Shapefile it is the point
    of the exercise: `.dbf`, `.shx` and `.prj` carry the attributes, the index
    and the CRS, and none of them is touched by hashing the `.shp` the record
    actually points at.
    """
    if path is None:
        return ()
    target = pathlib.Path(str(path))
    if target.suffix.lower() != ".shp":
        return ()
    return tuple(
        candidate
        for suffix in (".dbf", ".shx", ".prj", ".cpg")
        for candidate in (target.with_suffix(suffix),)
        if candidate.is_file()
    )


def attribute_chunks(
    path: str | pathlib.Path | None,
    *,
    max_rows: int = DEFAULT_MAX_ATTRIBUTE_ROWS,
) -> Iterator[bytes] | None:
    """Bytes describing the dataset's attribute values, or None if unobtainable.

    This is the signal that catches an edit the byte hash of the `.shp` cannot
    see. It is deliberately separate from geometry: an attribute digest that
    moved while the geometry digest held is precisely "same shapes, different
    data", which is the answer the audit could not previously give.

    Returned as an iterator of chunks so a large attribute table is never held
    in memory as one object; the caller feeds them straight into a digest.

    None — not an empty iterator — when there is nothing trustworthy to say:
    an unknown format, or a GeoPackage over `max_rows`. Empty would hash to a
    real value and assert that the file has no attributes, which is a different
    and false claim.
    """
    if path is None:
        return None
    target = pathlib.Path(str(path))
    suffix = target.suffix.lower()
    try:
        if suffix == ".shp":
            dbf = target.with_suffix(".dbf")
            if not dbf.is_file():
                return None
            return _dbf_chunks(dbf)
        if suffix in (".gpkg", ".geopackage"):
            return _geopackage_attribute_chunks(target, max_rows=max_rows)
    except (OSError, struct.error, sqlite3.Error, DatasetReadError):
        return None
    return None


# --------------------------------------------------------------------------
# Shapefile
# --------------------------------------------------------------------------


def _describe_shapefile(shp: pathlib.Path) -> DatasetDescription:
    bbox = _shapefile_bbox(shp)
    field_names, field_types = _dbf_fields(shp.with_suffix(".dbf"))
    return DatasetDescription(
        format=FORMAT_SHAPEFILE,
        crs_text=_prj_text(shp.with_suffix(".prj")),
        layers=(
            LayerDescription(
                name=shp.stem,
                field_names=field_names,
                field_types=field_types,
                feature_count=_shapefile_feature_count(shp),
                bbox=bbox,
            ),
        ),
    )


def _shapefile_bbox(shp: pathlib.Path) -> tuple[float, float, float, float] | None:
    """Bytes 36-67 of the fixed 100-byte header: xmin, ymin, xmax, ymax, little-endian.

    The magic number at bytes 0-3 is big-endian and is checked first, because a
    file that merely ends in `.shp` and is not one would otherwise produce four
    plausible-looking floats out of whatever bytes happened to be there.
    """
    with shp.open("rb") as handle:
        header = handle.read(_SHAPEFILE_HEADER_BYTES)
    if len(header) < 68 or struct.unpack(">i", header[0:4])[0] != _SHAPEFILE_MAGIC:
        raise DatasetReadError(f"{shp} does not begin with a Shapefile header")
    xmin, ymin, xmax, ymax = struct.unpack("<4d", header[36:68])
    return (xmin, ymin, xmax, ymax)


def _shapefile_feature_count(shp: pathlib.Path) -> int | None:
    """From the `.shx` index, which is 100 bytes of header then 8 bytes per record.

    Counted from the index rather than by walking the `.shp` records because
    the index exists to make exactly this arithmetic possible, and because a
    walk would read the whole geometry to learn one number.
    """
    shx = shp.with_suffix(".shx")
    if not shx.is_file():
        return None
    with shx.open("rb") as handle:
        header = handle.read(_SHAPEFILE_HEADER_BYTES)
    if len(header) < 4 or struct.unpack(">i", header[0:4])[0] != _SHAPEFILE_MAGIC:
        return None
    body = shx.stat().st_size - _SHAPEFILE_HEADER_BYTES
    if body < 0 or body % _SHX_RECORD_BYTES:
        return None
    return body // _SHX_RECORD_BYTES


def _dbf_fields(dbf: pathlib.Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Field names and types from the `.dbf` header's 32-byte descriptor array.

    A descriptor is 11 bytes of null-padded name, then one type character, and
    the array ends at 0x0D. The declared width and decimal count travel with
    the type (`C:16`, `N:8.2`) because widening a column is a schema change and
    a bare type letter would hide it.
    """
    if not dbf.is_file():
        return ((), ())
    with dbf.open("rb") as handle:
        raw = handle.read(_DBF_FIELD_ARRAY_OFFSET + 1)
    if len(raw) < _DBF_FIELD_ARRAY_OFFSET + 1:
        raise DatasetReadError(f"{dbf} is too short to hold a dBASE header")
    header_length = struct.unpack("<H", raw[8:10])[0]
    with dbf.open("rb") as handle:
        header = handle.read(max(header_length, _DBF_FIELD_ARRAY_OFFSET + 1))

    names: list[str] = []
    types: list[str] = []
    offset = _DBF_FIELD_ARRAY_OFFSET
    while offset + _DBF_FIELD_DESCRIPTOR_BYTES <= len(header):
        if header[offset] == _DBF_FIELD_TERMINATOR:
            break
        descriptor = header[offset : offset + _DBF_FIELD_DESCRIPTOR_BYTES]
        name = descriptor[0:11].split(b"\x00")[0].decode("ascii", "replace").strip()
        kind = chr(descriptor[11])
        width = descriptor[16]
        decimals = descriptor[17]
        names.append(name)
        types.append(f"{kind}:{width}.{decimals}" if decimals else f"{kind}:{width}")
        offset += _DBF_FIELD_DESCRIPTOR_BYTES
    return (tuple(names), tuple(types))


def _dbf_chunks(dbf: pathlib.Path, chunk_bytes: int = 1024 * 1024) -> Iterator[bytes]:
    """The `.dbf` file, streamed, with its last-written date blanked.

    Hashing the attribute file whole is exact and costs one sequential read —
    there is no cheaper way to notice that one name in one row changed, and no
    more accurate one either.

    Bytes 1-3 are zeroed because they hold the date the file was last written.
    They move on every rewrite whether or not a value changed, which is the
    same false positive this module exists to remove; leaving them in would
    have the attribute signal agreeing with the byte hash exactly when it most
    needs to disagree.
    """

    def stream() -> Iterator[bytes]:
        with dbf.open("rb") as handle:
            first = handle.read(chunk_bytes)
            if first:
                patched = bytearray(first)
                patched[_DBF_LAST_UPDATE_SLICE] = b"\x00\x00\x00"
                yield bytes(patched)
            while chunk := handle.read(chunk_bytes):
                yield chunk

    return stream()


#: WKT structural punctuation. Whitespace beside any of it is layout, not
#: content, and is removed before the text reaches a digest.
_WKT_PUNCTUATION = ",[]()"


def _prj_text(prj: pathlib.Path) -> str | None:
    """The `.prj` WKT, normalised so that reformatting it is not a change.

    Writers disagree about where they put line breaks and indentation inside
    WKT while meaning the identical coordinate system. Collapsing runs of
    whitespace is not enough on its own — `GEOGCS["a",DATUM[` and
    `GEOGCS["a",\n   DATUM[` collapse to strings that still differ by one
    space — so whitespace adjacent to WKT's structural punctuation goes too.

    Spaces *inside* quoted names survive, because they are part of the name:
    `"WGS 84"` and `"WGS84"` are different coordinate systems and must stay
    different here.
    """
    if not prj.is_file():
        return None
    text = " ".join(prj.read_text(encoding="utf-8", errors="replace").split())
    for mark in _WKT_PUNCTUATION:
        text = text.replace(f" {mark}", mark).replace(f"{mark} ", mark)
    return text or None


# --------------------------------------------------------------------------
# GeoPackage
# --------------------------------------------------------------------------


def _open_geopackage(gpkg: pathlib.Path) -> sqlite3.Connection:
    """Open read-only, so describing a dataset can never modify it.

    `mode=ro` also means no journal or WAL file is created beside the user's
    data, which matters because this runs against files QGIS may have open.
    """
    if not gpkg.is_file():
        raise DatasetReadError(f"{gpkg} does not exist")
    connection = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    connection.text_factory = str
    return connection


# Callers wrap this in `contextlib.closing`, not in `with connection:`.
# A sqlite3 connection used as a context manager commits or rolls back a
# TRANSACTION and leaves the connection itself open — which here would leak
# one file handle per dataset described, inside a plugin that describes a
# dataset on every processing run.


def _describe_geopackage(gpkg: pathlib.Path) -> DatasetDescription:
    with contextlib.closing(_open_geopackage(gpkg)) as connection:
        tables = _geopackage_tables(connection)
        if not tables:
            raise DatasetReadError(f"{gpkg} has no gpkg_contents — not a GeoPackage")
        layers = []
        for name, bbox in tables:
            field_names, field_types = _geopackage_columns(connection, name)
            layers.append(
                LayerDescription(
                    name=name,
                    field_names=field_names,
                    field_types=field_types,
                    feature_count=_geopackage_count(connection, name),
                    bbox=bbox,
                )
            )
        crs_text = _geopackage_crs_text(connection)
    return DatasetDescription(
        format=FORMAT_GEOPACKAGE,
        layers=tuple(layers),
        crs_text=crs_text,
    )


def _geopackage_tables(
    connection: sqlite3.Connection,
) -> list[tuple[str, tuple[float, float, float, float] | None]]:
    """Feature and tile tables from `gpkg_contents`, with their declared extents.

    Sorted by name so the description does not depend on insertion order —
    a re-save that rewrote the catalogue in a different order would otherwise
    move the digest without moving the data.
    """
    rows = connection.execute(
        "SELECT table_name, min_x, min_y, max_x, max_y FROM gpkg_contents "
        "ORDER BY table_name"
    ).fetchall()
    tables = []
    for name, xmin, ymin, xmax, ymax in rows:
        extent = None
        if None not in (xmin, ymin, xmax, ymax):
            extent = (float(xmin), float(ymin), float(xmax), float(ymax))
        tables.append((str(name), extent))
    return tables


def _geopackage_columns(
    connection: sqlite3.Connection, table: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Column names and declared types, in the table's own column order.

    `PRAGMA table_info` cannot be parameterised, so the identifier is quoted
    rather than bound. Every name reaching here came out of `gpkg_contents` in
    this same file, so it is not user input in any meaningful sense — but it is
    still an identifier being interpolated, and quoting it is what makes a
    table called `my table` work at all.
    """
    quoted = table.replace('"', '""')
    rows = connection.execute(f'PRAGMA table_info("{quoted}")').fetchall()
    names = tuple(str(row[1]) for row in rows)
    types = tuple(str(row[2] or "") for row in rows)
    return (names, types)


def _geopackage_count(connection: sqlite3.Connection, table: str) -> int | None:
    quoted = table.replace('"', '""')
    try:
        row = connection.execute(f'SELECT count(*) FROM "{quoted}"').fetchone()
    except sqlite3.Error:
        # A tile pyramid or an attributes-only table listed in gpkg_contents
        # that this file does not actually carry. Not having a count is a fact,
        # not a failure.
        return None
    return int(row[0]) if row else None


def _geopackage_crs_text(connection: sqlite3.Connection) -> str | None:
    """The coordinate systems actually referenced by this file's tables.

    Reported as `EPSG:4326`, matching how `entities.crs` records one (§5.7),
    and taken from the tables' own `srs_id` rather than from every row of
    `gpkg_spatial_ref_sys` — every GeoPackage ships the same three placeholder
    entries, so hashing the whole table would describe the format rather than
    the file.
    """
    try:
        rows = connection.execute(
            "SELECT DISTINCT s.organization, s.organization_coordsys_id "
            "FROM gpkg_contents c JOIN gpkg_spatial_ref_sys s ON c.srs_id = s.srs_id "
            "ORDER BY s.organization, s.organization_coordsys_id"
        ).fetchall()
    except sqlite3.Error:
        return None
    parts = [f"{org}:{code}" for org, code in rows if org and code is not None]
    return ",".join(parts) or None


def _geopackage_attribute_chunks(
    gpkg: pathlib.Path, *, max_rows: int
) -> Iterator[bytes] | None:
    """Every non-geometry value in every feature table, canonicalised.

    Geometry columns are excluded because geometry already has its own signal;
    mixing them would make an attribute edit and a geometry edit indistinguish-
    able again, which is the whole failure being fixed.

    The primary key is excluded too. A GeoPackage `fid` is a storage row id,
    not data: rewriting a table renumbers it while every value the user cares
    about stays put, so hashing it would report a re-save as an edit. The
    column itself still appears in the `structure` signal, so renaming or
    dropping it is a schema change and is still seen.

    Rows are SORTED by their serialised value rather than left in rowid order.
    A rewrite that renumbers or reorders rows without changing any value is a
    re-save, and ordering by rowid would report it as an edit. Sorting is why
    the row ceiling exists: the table has to be materialised to sort it.
    """
    with contextlib.closing(_open_geopackage(gpkg)) as connection:
        feature_tables = _geopackage_feature_tables(connection)
        if not feature_tables:
            return None

        total = 0
        for table in feature_tables:
            count = _geopackage_count(connection, table)
            if count is None:
                return None
            total += count
        if total > max_rows:
            return None

        serialised: list[str] = []
        for table in feature_tables:
            excluded = _geopackage_geometry_columns(
                connection, table
            ) | _geopackage_primary_keys(connection, table)
            names, _ = _geopackage_columns(connection, table)
            wanted = [name for name in names if name not in excluded]
            if not wanted:
                continue
            quoted_table = table.replace('"', '""')
            quoted_columns = ", ".join(f'"{n}"' for n in (c.replace('"', '""') for c in wanted))
            rows = connection.execute(
                f'SELECT {quoted_columns} FROM "{quoted_table}"'
            ).fetchall()
            for row in rows:
                serialised.append(
                    json.dumps(
                        [table, [_jsonable(value) for value in row]],
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    )
                )

    serialised.sort()
    return (line.encode("utf-8") + b"\n" for line in serialised)


def _geopackage_feature_tables(connection: sqlite3.Connection) -> list[str]:
    try:
        rows = connection.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' "
            "ORDER BY table_name"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [str(row[0]) for row in rows]


def _geopackage_primary_keys(
    connection: sqlite3.Connection, table: str
) -> frozenset[str]:
    quoted = table.replace('"', '""')
    try:
        rows = connection.execute(f'PRAGMA table_info("{quoted}")').fetchall()
    except sqlite3.Error:
        return frozenset()
    return frozenset(str(row[1]) for row in rows if row[5])


def _geopackage_geometry_columns(
    connection: sqlite3.Connection, table: str
) -> frozenset[str]:
    try:
        rows = connection.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
            (table,),
        ).fetchall()
    except sqlite3.Error:
        return frozenset()
    return frozenset(str(row[0]) for row in rows)


def _jsonable(value: object) -> object:
    """Make one column value serialisable without losing what distinguishes it.

    A stray BLOB in a non-geometry column becomes its hex, not its `repr` —
    two different blobs must not collapse to the same string, or an edit to one
    of them stops being detectable.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, float):
        return repr(value)
    return value


def _round_bbox(
    bbox: Sequence[float] | None,
) -> list[float] | None:
    if bbox is None:
        return None
    return [round(float(value), BBOX_DECIMAL_PLACES) for value in bbox]
