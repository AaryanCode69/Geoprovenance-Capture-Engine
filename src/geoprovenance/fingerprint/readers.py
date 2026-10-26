"""Reading a dataset's *shape* off disk, without QGIS and without GDAL.

Owner: Person B.  Research doc §6.4 row 2 ("feature-count + schema hash").

`geometry_chunks` was added by Person A on 6 Oct 2026 under an explicit written
override of RULES.md §1.2 [HARD], requested by the user for this one fix. On
24 Oct 2026 Person A made the Shapefile coordinate and attribute payloads
order-insensitive under a second explicit written override, requested by the
user for the Array manuscript (CLAIMS_TO_IMPLEMENT.md C1). Person B still owns
this file.

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
    everything else returns None here.

    GeoTIFF is read by its own module, `tiff.py` (added 24 Oct 2026), which
    parses the TIFF IFDs and the GeoKey directory with `struct` and decodes
    Deflate pixels with `zlib` — still no GDAL (RULES.md §2.2). Any other
    format contributes no complementary fingerprints, and the comparison then
    reports those axes as unavailable rather than guessing (RULES.md §5.6).
"""

from __future__ import annotations

import contextlib
import hashlib
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

#: Coordinates are rounded before they reach a digest so that a bounding box
#: recomputed by another writer cannot differ in the last unit in the last
#: place and read as a moved geometry. Nine places is under a tenth of a
#: millimetre at the equator — far finer than any real edit, far coarser than
#: float64 noise.
BBOX_DECIMAL_PLACES = 9

#: No row ceiling by default (since 24 Oct 2026). Until then the content
#: payloads SORTED one digest per row to be order-insensitive, which held the
#: whole table in memory, so above 100,000 rows no attribute or coordinate
#: signal was produced at all — measured in the E3 benchmark: every vector file
#: of 10 MB or more fell back to the byte hash. They are now an additive
#: multiset digest (`_Multiset`), order-insensitive in constant memory, so the
#: ceiling is no longer needed. A caller may still pass one.
DEFAULT_MAX_ATTRIBUTE_ROWS: int | None = None


#: AdHash (Bellare and Micciancio, EUROCRYPT 1997): each row is expanded to
#: MULTISET_BITS with SHAKE-256 and the rows are summed modulo 2**MULTISET_BITS.
#: Addition commutes, so row order cannot matter, and the state is one integer
#: however many rows there are. The modulus is large because Wagner's
#: generalised birthday attack (CRYPTO 2002) finds additive collisions far
#: faster than a birthday bound on a small one; at 2048 bits it is out of reach.
MULTISET_BITS = 2048
_MULTISET_MASK = (1 << MULTISET_BITS) - 1


class _Multiset:
    """An order-insensitive digest of a multiset of rows, in constant memory."""

    __slots__ = ("count", "total")

    def __init__(self) -> None:
        self.count = 0
        self.total = 0

    def add(self, *parts: bytes) -> None:
        h = hashlib.shake_256()
        for part in parts:
            h.update(part)
        self.total = (self.total + int.from_bytes(h.digest(MULTISET_BITS // 8), "big")) & _MULTISET_MASK
        self.count += 1

    def chunks(self) -> Iterator[bytes]:
        """The payload the version-tagged digest in `hash.py` is taken over."""
        return iter([f"{self.count}:{self.total:0{MULTISET_BITS // 4}x}\n".encode("ascii")])


def _over(count: int, max_rows: int | None) -> bool:
    return max_rows is not None and count > max_rows

#: GeoPackage geometry blob header (GeoPackage 1.x, clause 2.1.3): "GP", a
#: version byte, a flags byte, a 4-byte srs_id, then an optional envelope whose
#: size is coded in flag bits 1-3. Everything after it is plain WKB.
_GPKG_BLOB_MAGIC = b"GP"
_GPKG_BLOB_FIXED_BYTES = 8
_GPKG_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}

#: What a NULL geometry contributes to the geometry digest. A row with no
#: geometry is still a row, and filling one in or clearing one is an edit.
_NULL_GEOMETRY = b"NULL"


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
    max_rows: int | None = DEFAULT_MAX_ATTRIBUTE_ROWS,
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
            return _dbf_row_chunks(dbf, max_rows=max_rows)
        if suffix in (".gpkg", ".geopackage"):
            return _geopackage_attribute_chunks(target, max_rows=max_rows)
    except (OSError, struct.error, sqlite3.Error, DatasetReadError):
        return None
    return None


def geometry_chunks(
    path: str | pathlib.Path | None,
    *,
    max_rows: int | None = DEFAULT_MAX_ATTRIBUTE_ROWS,
) -> Iterator[bytes] | None:
    """Bytes describing the coordinates themselves, or None if unobtainable.

    `DatasetDescription.geometry_payload` describes how many features there are
    and where their bounding box sits. That misses the edit that matters most
    for a shoreline or a boundary: one vertex moved without changing the count
    or the extent. The byte hash moved, structure, geometry and attributes all
    held, and the comparison called it a re-save. This is the signal that sees
    the vertex.

    It reads coordinates, not files, so it still survives a re-save: the
    Shapefile record numbers and the GeoPackage blob header (whose envelope a
    writer may include or leave out) are left out of it.

    None, as with `attribute_chunks`, when there is nothing trustworthy to say:
    an unknown format, a GeoPackage over `max_rows`, a geometry that is not a
    standard GeoPackage blob, or a big-endian WKB. The last is refused rather
    than byte-swapped, because a re-save that switched byte order would then
    read as a geometry edit. Every writer this project has met writes
    little-endian.
    """
    if path is None:
        return None
    target = pathlib.Path(str(path))
    suffix = target.suffix.lower()
    try:
        if suffix == ".shp":
            _shapefile_bbox(target)  # checks the magic number before reading
            return _shp_record_chunks(target, max_rows=max_rows)
        if suffix in (".gpkg", ".geopackage"):
            return _geopackage_geometry_chunks(target, max_rows=max_rows)
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


def _dbf_row_chunks(dbf: pathlib.Path, *, max_rows: int | None) -> Iterator[bytes] | None:
    """The multiset of live `.dbf` rows — the Shapefile attribute payload.

    Until 24 Oct 2026 this was the `.dbf` file itself, streamed with its date
    blanked. That was exact, but it made the attribute signal depend on row
    ORDER and on how a writer pads a value, so a Shapefile rewritten with its
    rows in another order, or by a writer that formats numbers differently,
    read as an attribute edit. The GeoPackage payload never had that problem
    (rows sorted, values canonical); this brings the Shapefile in line.

    Each value is canonicalised by its dBASE type: character fields lose their
    padding, numeric fields are parsed so `1.50` and `  1.5` agree, logicals
    collapse to T/F/?. Rows marked deleted are skipped — they are not data.
    The decoded bytes are kept as Latin-1, a lossless mapping, so no encoding
    guess can merge two different values.

    Sorting means pairing a row with its shape is not checked here, nor in the
    coordinate payload: two features swapping attributes and nothing else is
    invisible. That residual is shared with the GeoPackage payloads and is
    stated in the manuscript (§3.5). None above `max_rows`, as for GeoPackage.
    """
    with dbf.open("rb") as handle:
        header = handle.read(32)
        if len(header) < 32:
            raise DatasetReadError(f"{dbf} is too short to hold a dBASE header")
        count, header_length, record_length = struct.unpack("<IHH", header[4:12])
        if _over(count, max_rows):
            return None
        handle.seek(0)
        descriptors = handle.read(header_length)
        fields: list[tuple[str, int]] = []
        offset = _DBF_FIELD_ARRAY_OFFSET
        while offset + _DBF_FIELD_DESCRIPTOR_BYTES <= len(descriptors):
            if descriptors[offset] == _DBF_FIELD_TERMINATOR:
                break
            fields.append((chr(descriptors[offset + 11]), descriptors[offset + 16]))
            offset += _DBF_FIELD_DESCRIPTOR_BYTES
        handle.seek(header_length)
        rows = _Multiset()
        for _ in range(count):
            record = handle.read(record_length)
            if len(record) < record_length:
                raise DatasetReadError(f"{dbf} ends inside a record")
            if record[:1] == b"*":
                continue
            values = []
            position = 1
            for kind, width in fields:
                raw = record[position : position + width]
                position += width
                values.append(_dbf_value(kind, raw))
            rows.add(json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode("ascii"))
    return rows.chunks()


def _dbf_value(kind: str, raw: bytes) -> object:
    text = raw.decode("latin-1").strip()
    if kind in ("N", "F"):
        if not text or set(text) <= {"*"}:
            return None
        try:
            number = float(text)
        except ValueError:
            return text
        # dBASE stores numbers as text, and writers format the same double
        # differently: GDAL wrote "1309812.000000000000000" where QGIS's
        # "Save As" wrote "1309811.999999999767169" — more digits than a
        # double holds (measured in the E1 suite, 24 Oct 2026). Fifteen
        # significant digits (DBL_DIG) is the most that survives a round trip
        # through a double, so it is the canonical form.
        return f"{number:.15g}"
    if kind == "L":
        if text[:1] in ("T", "t", "Y", "y"):
            return "T"
        if text[:1] in ("F", "f", "N", "n"):
            return "F"
        return None
    return text


def _shp_record_chunks(shp: pathlib.Path, *, max_rows: int | None) -> Iterator[bytes] | None:
    """The multiset of `.shp` record contents (order-insensitive, constant memory).

    The 8-byte record header (record number, content length) is left out: the
    number only says where a record sits. The content — shape type, the
    record's own box and the coordinates — is hashed as written.

    Sorted since 24 Oct 2026, so a Shapefile rewritten with its features in
    another order reads as a re-save, as a GeoPackage already did. Until then
    file order was kept because `.dbf` rows pair with records by position; the
    attribute payload is now order-free too, so keeping order here would only
    have made row reordering look like a geometry edit. The pairing residual
    this leaves is stated in `_dbf_row_chunks`.
    """
    records = _Multiset()
    with shp.open("rb") as handle:
        handle.seek(_SHAPEFILE_HEADER_BYTES)
        while header := handle.read(8):
            if len(header) < 8:
                raise DatasetReadError(f"{shp} ends inside a record header")
            _, words = struct.unpack(">ii", header)
            length = words * 2
            content = handle.read(length)
            if words < 0 or len(content) != length:
                raise DatasetReadError(f"{shp} ends inside a record")
            records.add(content)
            if _over(records.count, max_rows):
                return None
    return records.chunks()


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
    # A geometry column's declared SQL type is a storage spelling — a writer
    # may declare BLOB or the geometry type name — while its geometry type is
    # recorded in gpkg_geometry_columns. Use that, so two writers holding the
    # same geometry agree (E1 suite, 24 Oct 2026).
    geometry_types = _geopackage_geometry_types(connection, table)
    types = tuple(
        geometry_types.get(str(row[1]), str(row[2] or "")) for row in rows
    )
    return (names, types)


def _geopackage_geometry_types(connection: sqlite3.Connection, table: str) -> dict[str, str]:
    try:
        rows = connection.execute(
            "SELECT column_name, geometry_type_name FROM gpkg_geometry_columns "
            "WHERE table_name = ?",
            (table,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(name): f"GEOMETRY:{str(kind).upper()}" for name, kind in rows}


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
    gpkg: pathlib.Path, *, max_rows: int | None
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

    Rows are combined as a multiset (`_Multiset`) rather than in rowid order.
    A rewrite that renumbers or reorders rows without changing any value is a
    re-save, and ordering by rowid would report it as an edit. Until 24 Oct
    2026 they were sorted, which held the table in memory and needed a row
    ceiling; the multiset streams the cursor in constant memory.
    """
    with contextlib.closing(_open_geopackage(gpkg)) as connection:
        feature_tables = _geopackage_feature_tables(connection)
        if not feature_tables:
            return None

        if not _geopackage_within_rows(connection, feature_tables, max_rows):
            return None

        rows = _Multiset()
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
            for row in connection.execute(f'SELECT {quoted_columns} FROM "{quoted_table}"'):
                rows.add(
                    json.dumps(
                        [table, [_jsonable(value) for value in row]],
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ).encode("utf-8")
                )

    return rows.chunks()


def _geopackage_geometry_chunks(
    gpkg: pathlib.Path, *, max_rows: int | None
) -> Iterator[bytes] | None:
    """The multiset of geometry values (order-insensitive, constant memory).

    Order-free for the reason the attribute digest is: a rewrite that renumbers
    or reorders rows is a re-save.

    The known residual, which order-freedom creates and the attribute digest shares:
    two features swapping geometries with nothing else changed is invisible,
    because neither digest pairs a shape with its row.
    """
    with contextlib.closing(_open_geopackage(gpkg)) as connection:
        feature_tables = _geopackage_feature_tables(connection)
        if not feature_tables:
            return None
        if not _geopackage_within_rows(connection, feature_tables, max_rows):
            return None

        geometries = _Multiset()
        for table in feature_tables:
            quoted_table = table.replace('"', '""')
            for column in sorted(_geopackage_geometry_columns(connection, table)):
                quoted_column = column.replace('"', '""')
                rows = connection.execute(
                    f'SELECT "{quoted_column}" FROM "{quoted_table}"'
                )
                for (value,) in rows:
                    wkb = _gpkg_blob_wkb(value)
                    if wkb is None:
                        return None
                    geometries.add(table.encode("utf-8") + b"\x00",
                                   column.encode("utf-8") + b"\x00", wkb + b"\x00")

    return geometries.chunks()


def _gpkg_blob_wkb(value: object) -> bytes | None:
    """The WKB inside one GeoPackage geometry blob, or None if it cannot be trusted.

    The header is dropped because it describes the geometry rather than being
    it: the envelope is optional, and two writers holding the same coordinates
    may include it or not.
    """
    if value is None:
        return _NULL_GEOMETRY
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return None
    blob = bytes(value)
    if len(blob) < _GPKG_BLOB_FIXED_BYTES or blob[:2] != _GPKG_BLOB_MAGIC:
        return None
    envelope = _GPKG_ENVELOPE_BYTES.get((blob[3] >> 1) & 0b111)
    if envelope is None:
        return None
    wkb = blob[_GPKG_BLOB_FIXED_BYTES + envelope :]
    if not wkb or wkb[0] != 1:  # 1 = little-endian (NDR)
        return None
    return wkb


def _geopackage_within_rows(
    connection: sqlite3.Connection, tables: Sequence[str], max_rows: int | None
) -> bool:
    """Whether every table can be counted and the total fits under `max_rows`."""
    if max_rows is None:
        return True
    total = 0
    for table in tables:
        count = _geopackage_count(connection, table)
        if count is None:
            return False
        total += count
    return total <= max_rows


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
