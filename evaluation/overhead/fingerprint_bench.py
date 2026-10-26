"""E3 — fingerprinting cost against file size (manuscript §5.5, Fig. 6).

    evaluation/qgis.sh gp-q42 evaluation/overhead/fingerprint_bench.py generate
    evaluation/qgis.sh gp-q42 evaluation/overhead/fingerprint_bench.py measure

`generate` writes synthetic datasets of about 1, 10, 100 and 1000 MB per
format with GDAL/OGR (points with two attributes for Shapefile and
GeoPackage; a float32, 256x256-tiled, Deflate GeoTIFF of noise, which
compresses poorly so the file is as large as its pixels). They live under
data/ (gitignored); sizes are measured, not assumed.

`measure` fingerprints each file REPEATS times, each time in a fresh
interpreter that imports only geoprovenance.fingerprint, and records the wall
time of fingerprint_dataset() and the child's peak resident set size
(ru_maxrss). The interpreter's own baseline RSS (imports done, nothing read)
is measured the same way and reported beside it. The page cache is warm after
the first repeat; the median over repeats is reported.
Writes results/fingerprint_bench.json.
"""

from __future__ import annotations

import json
import os
import pathlib
import statistics
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"
SIZES_MB = (1, 10, 100, 1000)
REPEATS = 3

# Bytes per feature/pixel, measured on small files, so a target size maps to a count.
SHP_BYTES_PER_POINT = 28 + 8 + 31      # .shp record + .shx entry + .dbf row (int 10, real 19, flag)
GPKG_BYTES_PER_POINT = 95              # measured: 10 k points -> ~0.95 MB
TIF_BYTES_PER_PIXEL = 4.1              # float32 noise barely compresses


def _vector(path: pathlib.Path, driver: str, count: int) -> None:
    from osgeo import ogr, osr
    import random

    rng = random.Random(42)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32644)
    ds = ogr.GetDriverByName(driver).CreateDataSource(str(path))
    layer = ds.CreateLayer("points", srs, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn("value", ogr.OFTReal))
    defn = layer.GetLayerDefn()
    layer.StartTransaction()
    for i in range(count):
        feature = ogr.Feature(defn)
        feature.SetField(0, i)
        feature.SetField(1, rng.random() * 1000)
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint_2D(360000 + rng.random() * 10000, 1290000 + rng.random() * 10000)
        feature.SetGeometry(point)
        layer.CreateFeature(feature)
        if i % 200000 == 199999:
            layer.CommitTransaction()
            layer.StartTransaction()
    layer.CommitTransaction()
    ds = None


def _raster(path: pathlib.Path, side: int) -> None:
    import numpy as np
    from osgeo import gdal, osr

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32644)
    ds = gdal.GetDriverByName("GTiff").Create(
        str(path), side, side, 1, gdal.GDT_Float32,
        ["TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"])
    ds.SetGeoTransform((360000, 30, 0, 1300000, 0, -30))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999)
    rng = np.random.default_rng(42)
    for y in range(0, side, 256):
        rows = min(256, side - y)
        band.WriteArray(rng.random((rows, side), dtype=np.float32) * 1000, 0, y)
    ds = None


def generate() -> None:
    DATA.mkdir(exist_ok=True)
    for mb in SIZES_MB:
        target = mb * 1_000_000
        shp = DATA / f"points_{mb}mb.shp"
        if not shp.exists():
            _vector(shp, "ESRI Shapefile", int(target / SHP_BYTES_PER_POINT))
        gpkg = DATA / f"points_{mb}mb.gpkg"
        if not gpkg.exists():
            _vector(gpkg, "GPKG", int(target / GPKG_BYTES_PER_POINT))
        tif = DATA / f"noise_{mb}mb.tif"
        if not tif.exists():
            _raster(tif, int((target / TIF_BYTES_PER_PIXEL) ** 0.5))
        print(f"{mb} MB done", flush=True)


CHILD = r"""
import json, resource, sys, time
sys.path.insert(0, sys.argv[1])
from geoprovenance.fingerprint import hash as hashing
path = sys.argv[2]
seconds = None
rows = []
if path != "-":
    start = time.perf_counter()
    rows = hashing.fingerprint_dataset(path)
    seconds = time.perf_counter() - start
print(json.dumps({"seconds": seconds, "rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "strategies": sorted(r.hash_strategy for r in rows)}))
"""


def _child(path: str) -> dict:
    out = subprocess.run([sys.executable, "-c", CHILD, str(ROOT / "src"), path],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _dataset_bytes(path: pathlib.Path) -> int:
    if path.suffix == ".shp":
        return sum(path.with_suffix(s).stat().st_size for s in (".shp", ".shx", ".dbf", ".prj")
                   if path.with_suffix(s).exists())
    return path.stat().st_size


def measure() -> None:
    baseline = [_child("-")["rss_kb"] for _ in range(REPEATS)]
    results = []
    for fmt, pattern in (("Shapefile", "points_{}mb.shp"), ("GeoPackage", "points_{}mb.gpkg"),
                         ("GeoTIFF", "noise_{}mb.tif")):
        for mb in SIZES_MB:
            path = DATA / pattern.format(mb)
            runs = [_child(str(path)) for _ in range(REPEATS)]
            row = {
                "format": fmt, "nominal_mb": mb, "bytes": _dataset_bytes(path),
                "primary_file_bytes": path.stat().st_size,
                "seconds_median": statistics.median(r["seconds"] for r in runs),
                "seconds_runs": [r["seconds"] for r in runs],
                "peak_rss_kb_median": statistics.median(r["rss_kb"] for r in runs),
                "strategies": runs[0]["strategies"],
            }
            results.append(row)
            print(f"{fmt:10} {mb:5} MB  {row['seconds_median']:8.2f} s  "
                  f"{row['peak_rss_kb_median'] / 1024:7.1f} MiB  {row['strategies']}", flush=True)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "fingerprint_bench.json").write_text(json.dumps({
        "python": sys.version.split()[0], "repeats": REPEATS,
        "interpreter_baseline_rss_kb_median": statistics.median(baseline),
        "results": results,
    }, indent=2) + "\n")


if __name__ == "__main__":
    {"generate": generate, "measure": measure}[sys.argv[1]]()
    sys.stdout.flush()
    os._exit(0)
