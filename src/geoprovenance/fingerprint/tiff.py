"""Reading a GeoTIFF's grid, georeferencing and pixels, without GDAL.

Owner: Person B.  Written by Person A on 24 Oct 2026 under an explicit written
override of RULES.md §1.2 [HARD], requested by the user for the Array
manuscript's raster axes (CLAIMS_TO_IMPLEMENT.md C7). Person B still owns the
fingerprint layer.

    RULES.md §2.2 — standard library only: `struct`, `zlib`, `array`.
    RULES.md §4.1 — imports no QGIS.

Why a raster needs more than a byte hash
    A GeoTIFF rewritten with a different compression, tile size or byte order
    has entirely different bytes and identical pixels. A byte hash calls that a
    change, which is the same false alarm a re-saved GeoPackage raises. This
    module produces two complementary signals that survive such a rewrite:

    structure   the grid (width, height, bands, sample type), the CRS from the
                GeoKey directory, the geotransform and the nodata value.
    pixels      every decoded sample of the full-resolution image, streamed in
                one canonical order — row-major, pixel-interleaved,
                little-endian — whatever the storage layout on disk.

Supported subset (anything else yields no pixel signal, never a guess)
    classic TIFF and BigTIFF, either byte order; strips or tiles;
    compression 1 (none), 8 or 32946 (Deflate); predictor 1 or 2 (horizontal
    differencing, integer samples only); planar configuration 1 or 2;
    8/16/32/64-bit unsigned, signed or IEEE floating-point samples, all bands
    of one type. Only the first image file directory is read: later IFDs are
    overviews or masks derived from it, and a re-save that adds or drops
    overviews has not changed the data.

The structure signal is produced for any TIFF whose first IFD can be read, so
an LZW-compressed file still reports a CRS reassignment as a schema change; it
merely has no pixel signal, and the classifier then refuses to call a byte
change a re-save (compare.py, "no silent agreement").
"""

from __future__ import annotations

import array
import math
import pathlib
import struct
import sys
import zlib
from dataclasses import dataclass
from typing import Iterator

FORMAT_GEOTIFF = "GeoTIFF"

TIFF_SUFFIXES = (".tif", ".tiff")

# Tag numbers (TIFF 6.0, OGC GeoTIFF 1.1, GDAL private tags).
_IMAGE_WIDTH = 256
_IMAGE_LENGTH = 257
_BITS_PER_SAMPLE = 258
_COMPRESSION = 259
_STRIP_OFFSETS = 273
_SAMPLES_PER_PIXEL = 277
_ROWS_PER_STRIP = 278
_STRIP_BYTE_COUNTS = 279
_PLANAR_CONFIGURATION = 284
_PREDICTOR = 317
_TILE_WIDTH = 322
_TILE_LENGTH = 323
_TILE_OFFSETS = 324
_TILE_BYTE_COUNTS = 325
_SAMPLE_FORMAT = 339
_MODEL_PIXEL_SCALE = 33550
_MODEL_TIEPOINT = 33922
_MODEL_TRANSFORMATION = 34264
_GEO_KEY_DIRECTORY = 34735
_GEO_DOUBLE_PARAMS = 34736
_GEO_ASCII_PARAMS = 34737
_GDAL_NODATA = 42113

#: GeoKeys that are free text describing a CRS rather than defining it. Two
#: writers holding the same EPSG code routinely word these differently, so they
#: are left out of the structure digest — otherwise every re-save by another
#: library would read as a CRS change.
_CITATION_KEYS = frozenset({1026, 2049, 3073, 4097})
_GT_MODEL_TYPE = 1024
_GT_RASTER_TYPE = 1025
_GEOGRAPHIC_TYPE = 2048
_PROJECTED_CS_TYPE = 3072
_USER_DEFINED = 32767

#: Field type code -> (struct format char, byte size).
_TYPES = {
    1: ("B", 1), 2: ("s", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8),
    6: ("b", 1), 7: ("B", 1), 8: ("h", 2), 9: ("i", 4), 10: ("ii", 8),
    11: ("f", 4), 12: ("d", 8), 16: ("Q", 8), 17: ("q", 8), 18: ("Q", 8),
}

_DEFLATE = (8, 32946)
_SUPPORTED_COMPRESSION = (1,) + _DEFLATE

#: (sample format, bits) -> array typecode. 1 = unsigned, 2 = signed, 3 = float.
_TYPECODES = {
    (1, 8): "B", (1, 16): "H", (1, 32): "I", (1, 64): "Q",
    (2, 8): "b", (2, 16): "h", (2, 32): "i", (2, 64): "q",
    (3, 32): "f", (3, 64): "d",
}
_UNSIGNED_OF_WIDTH = {8: "B", 16: "H", 32: "I", 64: "Q"}

#: Same rounding as the vector bounding boxes (readers.BBOX_DECIMAL_PLACES).
_DECIMALS = 9


class TiffReadError(RuntimeError):
    """A file claimed to be a TIFF and then was not, or ended early."""


@dataclass(frozen=True)
class RasterDescription:
    """One GeoTIFF's grid and georeferencing, plus where its pixels are stored."""

    width: int
    height: int
    bands: int
    bits: tuple[int, ...]
    sample_format: tuple[int, ...]
    geokeys: tuple[tuple[int, object], ...]
    geotransform: tuple[float, ...] | None
    nodata: str | None
    # Storage layout: needed to decode, deliberately NOT part of the structure.
    byte_order: str
    compression: int
    predictor: int
    planar: int
    tile_width: int | None
    tile_length: int | None
    rows_per_strip: int | None
    offsets: tuple[int, ...]
    byte_counts: tuple[int, ...]

    def crs_payload(self) -> dict[str, object]:
        """The CRS as defining codes, not as free text (see `_CITATION_KEYS`).

        When the file names an EPSG projected or geographic system, that code
        IS the CRS and the remaining keys merely restate it — and some writers
        restate it while others do not. Only for a user-defined system do the
        individual parameters matter, and then every non-citation key is kept.
        """
        keys = dict(self.geokeys)
        model = keys.get(_GT_MODEL_TYPE)
        projected = keys.get(_PROJECTED_CS_TYPE)
        geographic = keys.get(_GEOGRAPHIC_TYPE)
        if isinstance(projected, int) and projected not in (0, _USER_DEFINED):
            return {"model": model, "projected": projected}
        if isinstance(geographic, int) and geographic not in (0, _USER_DEFINED):
            return {"model": model, "geographic": geographic}
        return {
            "keys": [
                [key, value]
                for key, value in self.geokeys
                if key not in _CITATION_KEYS and key != _GT_RASTER_TYPE
            ]
        }

    def area_geotransform(self) -> tuple[float, ...] | None:
        """The geotransform for pixel-is-AREA, whatever the file declares.

        A file may declare pixel-is-point (GTRasterTypeGeoKey = 2), anchoring
        its tiepoint at a pixel centre; another writer converts the same grid
        to pixel-is-area and moves the origin half a pixel to the corner.
        Measured on Landsat Collection 2 files re-saved by QGIS (E1 suite,
        24 Oct 2026). Both describe one grid, so the structure records the
        area form — the conversion GDAL itself applies.
        """
        gt = self.geotransform
        if gt is None:
            return None
        if dict(self.geokeys).get(_GT_RASTER_TYPE) == 2:
            x0, dx, rx, y0, ry, dy = gt
            return (x0 - 0.5 * dx - 0.5 * rx, dx, rx, y0 - 0.5 * ry - 0.5 * dy, ry, dy)
        return gt

    def canonical_nodata(self) -> str | None:
        """Nodata as the sample type stores it, so spellings of one value agree.

        "3.402823466e+38" and "3.4028234663852886e+38" are one float32 value
        written with different precision (E1 suite, 24 Oct 2026).
        """
        if self.nodata is None:
            return None
        try:
            value = float(self.nodata)
        except ValueError:
            return self.nodata
        kind, bits = self.sample_format[0], self.bits[0]
        if kind == 3 and bits == 32 and math.isfinite(value):
            try:
                value = struct.unpack("<f", struct.pack("<f", value))[0]
            except OverflowError:
                pass
        elif kind in (1, 2) and math.isfinite(value) and value.is_integer():
            return str(int(value))
        return repr(value)

    def structure_payload(self) -> dict[str, object]:
        """What the raster holds and where it sits — never how it is stored."""
        area = self.area_geotransform()
        return {
            "format": FORMAT_GEOTIFF,
            "width": self.width,
            "height": self.height,
            "bands": self.bands,
            "bits": list(self.bits),
            "sample_format": list(self.sample_format),
            "crs": self.crs_payload(),
            "geotransform": [round(v, _DECIMALS) for v in area] if area is not None else None,
            "nodata": self.canonical_nodata(),
        }

    @property
    def pixel_size(self) -> tuple[float, float] | None:
        if self.geotransform is None:
            return None
        return (abs(self.geotransform[1]), abs(self.geotransform[5]))

    @property
    def pixels_supported(self) -> bool:
        """Whether `pixel_chunks` can decode this file (the stated subset)."""
        if self.compression not in _SUPPORTED_COMPRESSION:
            return False
        if self.planar not in (1, 2) or self.predictor not in (1, 2):
            return False
        if len(set(self.bits)) != 1 or len(set(self.sample_format)) != 1:
            return False
        key = (self.sample_format[0], self.bits[0])
        if key not in _TYPECODES:
            return False
        if self.predictor == 2 and self.sample_format[0] == 3:
            return False
        if self.tile_width is None and self.rows_per_strip is None:
            return False
        return len(self.offsets) == len(self.byte_counts) and bool(self.offsets)


def is_tiff_path(path: str | pathlib.Path | None) -> bool:
    return path is not None and pathlib.Path(str(path)).suffix.lower() in TIFF_SUFFIXES


def describe(path: str | pathlib.Path | None) -> RasterDescription | None:
    """Read the first IFD of the TIFF at `path`, or None if it cannot be read.

    Never raises for an ordinary reason, for the reason `readers.describe`
    gives: a description is an optional extra signal (RULES.md §5.1).
    """
    if not is_tiff_path(path):
        return None
    try:
        with open(str(path), "rb") as handle:
            return _read_first_ifd(handle)
    except (OSError, struct.error, TiffReadError, ValueError, IndexError):
        return None


def pixel_chunks(
    path: str | pathlib.Path, description: RasterDescription | None = None
) -> Iterator[bytes] | None:
    """The canonical pixel stream, or None if this file is outside the subset.

    The stream opens with the grid shape and sample type, so two rasters whose
    sample bytes happen to coincide but whose shapes differ cannot collide.
    """
    description = description if description is not None else describe(path)
    if description is None or not description.pixels_supported:
        return None
    return _pixel_stream(pathlib.Path(str(path)), description)


# --------------------------------------------------------------------------
# IFD parsing
# --------------------------------------------------------------------------


def _read_first_ifd(handle) -> RasterDescription:
    head = handle.read(16)
    if head[:2] == b"II":
        bo = "<"
    elif head[:2] == b"MM":
        bo = ">"
    else:
        raise TiffReadError("not a TIFF byte-order mark")
    magic = struct.unpack(bo + "H", head[2:4])[0]
    if magic == 42:
        big = False
        ifd_offset = struct.unpack(bo + "I", head[4:8])[0]
    elif magic == 43:
        big = True
        if struct.unpack(bo + "HH", head[4:8]) != (8, 0):
            raise TiffReadError("unsupported BigTIFF offset size")
        ifd_offset = struct.unpack(bo + "Q", head[8:16])[0]
    else:
        raise TiffReadError(f"TIFF magic {magic} is neither 42 nor 43")

    handle.seek(ifd_offset)
    if big:
        count = struct.unpack(bo + "Q", handle.read(8))[0]
        entry_size, inline = 20, 8
    else:
        count = struct.unpack(bo + "H", handle.read(2))[0]
        entry_size, inline = 12, 4
    raw = handle.read(count * entry_size)
    if len(raw) != count * entry_size:
        raise TiffReadError("TIFF ends inside its first IFD")

    tags: dict[int, tuple] = {}
    for i in range(count):
        entry = raw[i * entry_size : (i + 1) * entry_size]
        if big:
            tag, typ, n = struct.unpack(bo + "HHQ", entry[:12])
            value_field = entry[12:20]
        else:
            tag, typ, n = struct.unpack(bo + "HHI", entry[:8])
            value_field = entry[8:12]
        if typ not in _TYPES:
            continue
        fmt, size = _TYPES[typ]
        total = size * n
        if total <= inline:
            data = value_field[:total]
        else:
            pointer = struct.unpack(bo + ("Q" if big else "I"), value_field)[0]
            here = handle.tell()
            handle.seek(pointer)
            data = handle.read(total)
            handle.seek(here)
            if len(data) != total:
                raise TiffReadError(f"tag {tag} points past the end of the file")
        tags[tag] = _decode_values(bo, typ, fmt, n, data)

    def one(tag: int, default=None):
        values = tags.get(tag)
        return values[0] if values else default

    width = one(_IMAGE_WIDTH)
    height = one(_IMAGE_LENGTH)
    if not width or not height:
        raise TiffReadError("first IFD has no image size")
    bands = int(one(_SAMPLES_PER_PIXEL, 1))
    bits = tuple(int(b) for b in tags.get(_BITS_PER_SAMPLE, (1,)))
    if len(bits) == 1 and bands > 1:
        bits = bits * bands
    sample_format = tuple(int(s) for s in tags.get(_SAMPLE_FORMAT, (1,)))
    if len(sample_format) == 1 and bands > 1:
        sample_format = sample_format * bands

    tiled = _TILE_WIDTH in tags
    offsets = tags.get(_TILE_OFFSETS if tiled else _STRIP_OFFSETS, ())
    counts = tags.get(_TILE_BYTE_COUNTS if tiled else _STRIP_BYTE_COUNTS, ())

    nodata = None
    if _GDAL_NODATA in tags:
        text = tags[_GDAL_NODATA].rstrip("\x00").strip()
        try:
            nodata = repr(float(text))
        except ValueError:
            nodata = text or None

    return RasterDescription(
        width=int(width),
        height=int(height),
        bands=bands,
        bits=bits,
        sample_format=sample_format,
        geokeys=_geokeys(tags),
        geotransform=_geotransform(tags),
        nodata=nodata,
        byte_order=bo,
        compression=int(one(_COMPRESSION, 1)),
        predictor=int(one(_PREDICTOR, 1)),
        planar=int(one(_PLANAR_CONFIGURATION, 1)),
        tile_width=int(one(_TILE_WIDTH)) if tiled else None,
        tile_length=int(one(_TILE_LENGTH)) if tiled else None,
        rows_per_strip=None if tiled else int(one(_ROWS_PER_STRIP, height)),
        offsets=tuple(int(o) for o in offsets),
        byte_counts=tuple(int(c) for c in counts),
    )


def _decode_values(bo: str, typ: int, fmt: str, n: int, data: bytes):
    if typ == 2:  # ASCII
        return data.decode("latin-1")
    if typ in (5, 10):  # (signed) rational -> float
        pairs = struct.unpack(bo + fmt[0] * (2 * n), data)
        return tuple(pairs[i] / pairs[i + 1] if pairs[i + 1] else 0.0 for i in range(0, 2 * n, 2))
    return struct.unpack(bo + fmt * n, data)


def _geokeys(tags: dict[int, tuple]) -> tuple[tuple[int, object], ...]:
    """The GeoKey directory resolved to `(key, value)` pairs, sorted by key."""
    directory = tags.get(_GEO_KEY_DIRECTORY)
    if not directory or len(directory) < 4:
        return ()
    doubles = tags.get(_GEO_DOUBLE_PARAMS, ())
    ascii_params = tags.get(_GEO_ASCII_PARAMS, "")
    pairs: list[tuple[int, object]] = []
    for i in range(directory[3]):
        base = 4 + 4 * i
        if base + 4 > len(directory):
            break
        key, location, count, value = directory[base : base + 4]
        if location == 0:
            resolved: object = int(value)
        elif location == _GEO_DOUBLE_PARAMS:
            chunk = doubles[value : value + count]
            resolved = [round(v, _DECIMALS) for v in chunk]
            if len(resolved) == 1:
                resolved = resolved[0]
        elif location == _GEO_ASCII_PARAMS:
            resolved = ascii_params[value : value + count].rstrip("|\x00").strip()
        else:
            resolved = None
        pairs.append((int(key), resolved))
    return tuple(sorted(pairs, key=lambda kv: kv[0]))


def _geotransform(tags: dict[int, tuple]) -> tuple[float, ...] | None:
    """GDAL-order affine (x0, dx, rx, y0, ry, dy), from either encoding."""
    matrix = tags.get(_MODEL_TRANSFORMATION)
    if matrix and len(matrix) >= 8:
        return (matrix[3], matrix[0], matrix[1], matrix[7], matrix[4], matrix[5])
    scale = tags.get(_MODEL_PIXEL_SCALE)
    tie = tags.get(_MODEL_TIEPOINT)
    if scale and tie and len(scale) >= 2 and len(tie) >= 6:
        i, j, _, x, y, _ = tie[:6]
        sx, sy = scale[0], scale[1]
        return (x - i * sx, sx, 0.0, y + j * sy, 0.0, -sy)
    return None


# --------------------------------------------------------------------------
# Pixel decoding
# --------------------------------------------------------------------------


def _pixel_stream(path: pathlib.Path, d: RasterDescription) -> Iterator[bytes]:
    typecode = _TYPECODES[(d.sample_format[0], d.bits[0])]
    itemsize = d.bits[0] // 8
    swap = (d.byte_order == ">") != (sys.byteorder == "big")
    out_swap = sys.byteorder == "big"  # canonical stream is little-endian
    yield (
        f"geotiff-pixels|{d.width}x{d.height}x{d.bands}|{typecode}\n".encode("ascii")
    )

    planes = d.bands if d.planar == 2 else 1
    per_chunk = d.bands if d.planar == 1 else 1  # samples per pixel inside a chunk

    with path.open("rb") as handle:

        def decode(index: int, n_values: int) -> array.array:
            handle.seek(d.offsets[index])
            raw = handle.read(d.byte_counts[index])
            if len(raw) != d.byte_counts[index]:
                raise TiffReadError("TIFF ends inside image data")
            if d.compression in _DEFLATE:
                raw = zlib.decompress(raw)
            values = array.array(_UNSIGNED_OF_WIDTH[d.bits[0]])
            need = n_values * itemsize
            if len(raw) < need:
                raise TiffReadError("decoded chunk is shorter than its tile or strip")
            values.frombytes(raw[:need])
            if swap and itemsize > 1:
                values.byteswap()
            return values

        def undo_predictor(values: array.array, row_len: int, rows: int) -> array.array:
            if d.predictor != 2:
                return values
            mask = (1 << d.bits[0]) - 1
            for r in range(rows):
                start = r * row_len * per_chunk
                for s in range(per_chunk):
                    lane = values[start + s : start + row_len * per_chunk : per_chunk]
                    acc = 0
                    fixed = []
                    for v in lane:
                        acc = (acc + v) & mask
                        fixed.append(acc)
                    values[start + s : start + row_len * per_chunk : per_chunk] = array.array(
                        values.typecode, fixed
                    )
            return values

        def plane_rows(plane: int, block: int) -> list[array.array]:
            """Every image row of one block (strip or tile-row) of one plane."""
            if d.tile_width is None:
                rps = d.rows_per_strip or d.height
                strips_per_plane = -(-d.height // rps)
                index = plane * strips_per_plane + block
                rows = min(rps, d.height - block * rps)
                values = undo_predictor(decode(index, rows * d.width * per_chunk), d.width, rows)
                stride = d.width * per_chunk
                return [values[r * stride : (r + 1) * stride] for r in range(rows)]
            tw, tl = d.tile_width, d.tile_length
            across = -(-d.width // tw)
            down = -(-d.height // tl)
            rows = min(tl, d.height - block * tl)
            out = [array.array(values_typecode) for _ in range(rows)]
            for t in range(across):
                index = plane * across * down + block * across + t
                values = undo_predictor(decode(index, tw * tl * per_chunk), tw, tl)
                keep = min(tw, d.width - t * tw) * per_chunk
                stride = tw * per_chunk
                for r in range(rows):
                    out[r].extend(values[r * stride : r * stride + keep])
            return out

        values_typecode = _UNSIGNED_OF_WIDTH[d.bits[0]]
        block_rows = d.tile_length if d.tile_width is not None else (d.rows_per_strip or d.height)
        blocks = -(-d.height // block_rows)
        for block in range(blocks):
            per_plane = [plane_rows(p, block) for p in range(planes)]
            for r in range(len(per_plane[0])):
                if planes == 1:
                    row = per_plane[0][r]
                else:
                    row = array.array(values_typecode, bytes(d.width * planes * itemsize))
                    for p in range(planes):
                        row[p::planes] = per_plane[p][r]
                if out_swap and itemsize > 1:
                    row.byteswap()
                yield row.tobytes()
