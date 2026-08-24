"""Where on Earth is the file at this path? — derived, never stored.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

Why this module has to exist
    The provenance database records ``entities.file_path``, ``entities.crs`` and
    ``entities.format``. It records NO geometry: there is no extent column, no
    bounding box, no centroid. That is not an oversight — the schema is frozen
    as ``contract-v1`` and Person B and Person C build against it, so adding a
    column to make the map easier would be a breaking change to two other
    people's work (RULES.md §3.4).

    So the coordinates are derived at export time, by opening the file the
    record points at. If the file is gone, there is no footprint, and the map
    says so instead of inventing one.

What can be read, and what cannot
    Shapefile   the 100-byte header carries the bounding box at bytes 36-67
    GeoPackage  ``gpkg_contents`` carries it per table
    everything else, GeoTIFF included, returns None

    GeoTIFF is the honest gap. Reading a GeoTIFF's georeferencing means parsing
    TIFF IFDs and the GeoKey directory, which is a great deal of code for a demo
    — and the alternative, depending on GDAL, is exactly the dependency RULES.md
    §2.2 exists to refuse. A raster with no footprint is reported as "we would
    need extra software to place this one", which is true and is a limitation
    worth a reviewer seeing (§7.10).
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
import struct
from typing import NamedTuple


class Footprint(NamedTuple):
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    crs: str | None = None

    @property
    def centroid(self) -> tuple[float, float]:
        return ((self.xmin + self.xmax) / 2.0, (self.ymin + self.ymax) / 2.0)

    def padded(self, fraction: float = 0.02, minimum: float = 1e-4) -> "Footprint":
        """Grow a footprint so a zero-area one (a single point, a single row)
        still draws as a visible rectangle rather than an invisible degenerate
        polygon."""
        pad_x = max((self.xmax - self.xmin) * fraction, minimum)
        pad_y = max((self.ymax - self.ymin) * fraction, minimum)
        return Footprint(self.xmin - pad_x, self.ymin - pad_y,
                         self.xmax + pad_x, self.ymax + pad_y, self.crs)


#: Why a file has no footprint. These strings are shown to a reviewer, so they
#: are written in plain words (RULES.md §7.5).
NO_PATH = "this job worked in memory — there was never a file on disk"
MISSING = "the file is not on this computer any more"
UNREADABLE_FORMAT = "we would need extra software to place this one on a map"
UNKNOWN_FORMAT = "we do not know how to read this kind of file"


def footprint_of(path: str | pathlib.Path | None) -> tuple[Footprint | None, str | None]:
    """Return ``(footprint, reason_it_has_none)``. Exactly one is ever set."""
    if not path:
        return None, NO_PATH

    resolved = pathlib.Path(path)
    if not resolved.exists():
        return None, MISSING

    suffix = resolved.suffix.lower()
    try:
        if suffix == ".shp":
            return _shapefile_footprint(resolved), None
        if suffix == ".gpkg":
            return _geopackage_footprint(resolved), None
    except (OSError, struct.error, sqlite3.Error, ValueError):
        # A file that exists but will not parse is a real outcome, not a crash.
        return None, UNREADABLE_FORMAT

    if suffix in (".tif", ".tiff", ".jp2", ".img", ".vrt"):
        return None, UNREADABLE_FORMAT
    return None, UNKNOWN_FORMAT


# ---------------------------------------------------------------------------
# Shapefile
# ---------------------------------------------------------------------------

def _shapefile_footprint(path: pathlib.Path) -> Footprint:
    """Bytes 36-67 of the 100-byte header: xmin, ymin, xmax, ymax, little-endian.

    Reference: ESRI Shapefile Technical Description (July 1998), page 4.
    """
    with path.open("rb") as handle:
        header = handle.read(100)
    if len(header) < 68 or struct.unpack(">i", header[0:4])[0] != 9994:
        raise ValueError(f"{path} is not a shapefile")
    xmin, ymin, xmax, ymax = struct.unpack("<4d", header[36:68])
    return Footprint(xmin, ymin, xmax, ymax, _prj_crs(path.with_suffix(".prj")))


_EPSG_AUTHORITY = re.compile(r'AUTHORITY\s*\[\s*"EPSG"\s*,\s*"?(\d+)"?\s*\]', re.I)


def _prj_crs(prj_path: pathlib.Path) -> str | None:
    """Best effort authid from a sidecar .prj.

    An ESRI-style .prj often carries no AUTHORITY node at all — the fixture
    shapefile in this repository is one such — so recognising bare WGS 84 by its
    datum name is the difference between labelling the layer and leaving it
    blank. Anything unrecognised returns None rather than a guess (RULES.md §5.6).
    """
    if not prj_path.exists():
        return None
    try:
        wkt = prj_path.read_text(errors="replace")
    except OSError:
        return None
    match = _EPSG_AUTHORITY.search(wkt)
    if match:
        return f"EPSG:{match.group(1)}"
    if "D_WGS_1984" in wkt or "WGS_1984" in wkt or "WGS 84" in wkt:
        return "EPSG:4326"
    return None


# ---------------------------------------------------------------------------
# GeoPackage
# ---------------------------------------------------------------------------

def _geopackage_footprint(path: pathlib.Path) -> Footprint:
    """The union of every feature table's declared extent in ``gpkg_contents``.

    Opened read-only through a URI so this never creates, locks or modifies a
    file it was only asked to look at.
    """
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            "SELECT min_x, min_y, max_x, max_y, srs_id FROM gpkg_contents "
            "WHERE data_type = 'features' AND min_x IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise ValueError(f"{path} declares no feature table extent")
    xmin = min(r[0] for r in rows)
    ymin = min(r[1] for r in rows)
    xmax = max(r[2] for r in rows)
    ymax = max(r[3] for r in rows)
    srs_ids = {r[4] for r in rows}
    crs = f"EPSG:{srs_ids.pop()}" if len(srs_ids) == 1 else None
    return Footprint(xmin, ymin, xmax, ymax, crs)
