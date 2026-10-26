"""Case study 2: watershed delineation upstream of Cuddalore, run live in QGIS.

    PATH=$HOME/micromamba/envs/gp-grass/bin:$PATH \\
        evaluation/qgis.sh gp-q42 evaluation/case_hydro/run_in_qgis.py

Data: Copernicus DEM GLO-30 (tile N11 E079) from the Microsoft Planetary
Computer, a window over the Gadilam and Ponnaiyar lower basins.

Workflow, every step a captured Processing call:
    clip the DEM window -> reproject to UTM 44N at 30 m -> fill sinks (Wang &
    Liu, native) -> flow accumulation and drainage direction (GRASS
    r.watershed) -> stream network (GRASS r.stream.extract) -> watershed above
    the outlet (GRASS r.water.outlet) -> watershed polygon (GRASS r.to.vect)
    -> its area.

Perturbations (hypotheses frozen in expected.json before the run):
    H1 DEM re-saved with Deflate + tiling          -> resaved
    H2 DEM raised by 5 m in a 1 km block           -> pixels_changed
    H3 stream threshold 2000 -> 1000 cells         -> geometry_changed (streams)
    H4 watershed polygon's CRS reassigned          -> schema_changed

Writes results/hydro.json.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import sys
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from common import qgis_session  # noqa: E402

DATA = HERE / "data"
RUN = HERE / "run"
RESULTS = HERE / "results"
DB = HERE / "provenance.db"
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
ITEM = "Copernicus_DSM_COG_10_N11_00_E079_00_DEM"
WINDOW_LONLAT = (79.00, 11.45, 79.85, 11.99)
#: Approximate Gadilam river mouth at Cuddalore; the outlet is snapped to the
#: highest-accumulation cell within SNAP_M of it.
MOUTH_LONLAT = (79.770, 11.735)
SNAP_M = 1500.0
STREAM_THRESHOLD = 2000
STREAM_THRESHOLD_H3 = 1000


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def download() -> dict:
    from osgeo import gdal

    gdal.UseExceptions()
    DATA.mkdir(parents=True, exist_ok=True)
    item = json.loads(_get(f"{STAC}/collections/cop-dem-glo-30/items/{ITEM}"))
    raw = item["assets"]["data"]["href"]
    href = json.loads(_get(f"{SIGN_URL}?href={urllib.parse.quote(raw, safe='')}"))["href"]
    out = DATA / "dem_window.tif"
    w, s, e, n = WINDOW_LONLAT
    gdal.Translate(str(out), "/vsicurl/" + href, projWin=[w, n, e, s])
    return {"item": ITEM, "collection": "cop-dem-glo-30", "window_lonlat": WINDOW_LONLAT,
            "file": out.name}


def run(alg, params):
    import processing

    return processing.run(alg, params)


def chain(out: pathlib.Path, dem: pathlib.Path, *, threshold: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    p = lambda n: str(out / n)  # noqa: E731
    w, s, e, n = WINDOW_LONLAT
    run("gdal:cliprasterbyextent", {"INPUT": str(dem), "PROJWIN": f"{w},{e},{s},{n} [EPSG:4326]",
                                    "OVERCRS": False, "DATA_TYPE": 0, "OUTPUT": p("dem_clip.tif")})
    run("gdal:warpreproject", {"INPUT": p("dem_clip.tif"), "TARGET_CRS": "EPSG:32644",
                               "RESAMPLING": 1, "TARGET_RESOLUTION": 30.0, "DATA_TYPE": 0,
                               "OUTPUT": p("dem_utm.tif")})
    run("native:fillsinkswangliu", {"INPUT": p("dem_utm.tif"), "BAND": 1, "MIN_SLOPE": 0.01,
                                    "OUTPUT_FILLED_DEM": p("dem_filled.tif")})
    run("grass:r.watershed", {"elevation": p("dem_filled.tif"), "threshold": threshold,
                              "-s": True, "-a": True, "memory": 1000,
                              "accumulation": p("accumulation.tif"), "drainage": p("drainage.tif"),
                              "GRASS_REGION_CELLSIZE_PARAMETER": 0})
    run("grass:r.stream.extract", {"elevation": p("dem_filled.tif"), "accumulation": p("accumulation.tif"),
                                   "threshold": threshold, "memory": 1000,
                                   "stream_vector": p("streams.gpkg"),
                                   "GRASS_REGION_CELLSIZE_PARAMETER": 0,
                                   "GRASS_OUTPUT_TYPE_PARAMETER": 2})
    x, y = _snap_outlet(pathlib.Path(p("accumulation.tif")))
    run("grass:r.water.outlet", {"input": p("drainage.tif"), "coordinates": f"{x},{y} [EPSG:32644]",
                                 "output": p("watershed.tif"), "GRASS_REGION_CELLSIZE_PARAMETER": 0})
    run("grass:r.to.vect", {"input": p("watershed.tif"), "type": 2, "column": "value", "-s": True,
                            "output": p("watershed_raw.gpkg"), "GRASS_REGION_CELLSIZE_PARAMETER": 0,
                            "GRASS_OUTPUT_TYPE_PARAMETER": 3})
    run("native:fieldcalculator", {"INPUT": p("watershed_raw.gpkg"), "FIELD_NAME": "area_km2",
                                   "FIELD_TYPE": 0, "FIELD_LENGTH": 20, "FIELD_PRECISION": 4,
                                   "FORMULA": "$area / 1e6", "OUTPUT": p("watershed.gpkg")})
    return {"outlet": [x, y], "streams": p("streams.gpkg"), "watershed": p("watershed.gpkg"),
            "dem_utm": p("dem_utm.tif")}


def _snap_outlet(accumulation: pathlib.Path) -> tuple[float, float]:
    """The highest-accumulation cell near the river mouth (deterministic)."""
    import numpy as np
    from osgeo import gdal
    from pyproj import Transformer

    x0, y0 = Transformer.from_crs(4326, 32644, always_xy=True).transform(*MOUTH_LONLAT)
    ds = gdal.Open(str(accumulation))
    gt = ds.GetGeoTransform()
    a = np.abs(ds.GetRasterBand(1).ReadAsArray().astype("float64"))
    c0, r0 = int((x0 - gt[0]) / gt[1]), int((y0 - gt[3]) / gt[5])
    k = int(SNAP_M / gt[1])
    window = a[max(r0 - k, 0): r0 + k + 1, max(c0 - k, 0): c0 + k + 1]
    r, c = np.unravel_index(np.nanargmax(window), window.shape)
    r += max(r0 - k, 0)
    c += max(c0 - k, 0)
    return gt[0] + (c + 0.5) * gt[1], gt[3] + (r + 0.5) * gt[5]


def _measure(paths: dict) -> dict:
    out = {}
    with sqlite3.connect(paths["watershed"]) as conn:
        table = conn.execute("SELECT table_name FROM gpkg_contents").fetchone()[0]
        out["watershed_km2"] = conn.execute(f'SELECT sum(area_km2) FROM "{table}" WHERE value = 1').fetchone()[0]
    from osgeo import ogr

    ds = ogr.Open(paths["streams"])
    layer = ds.GetLayer(0)
    out["stream_segments"] = layer.GetFeatureCount()
    out["stream_km"] = sum(f.GetGeometryRef().Length() for f in layer) / 1000.0
    ds = None
    return out


def _recorded(store, path) -> dict:
    entity = store.find_entity_by_path(str(path))
    return {k: v["hash_value"] for k, v in store.get_fingerprint_set(entity["id"]).items()}


def _classify(recorded, candidate) -> dict:
    from geoprovenance.fingerprint import compare, hash as hashing

    fresh = {f.hash_strategy: f.hash_value for f in hashing.fingerprint_dataset(candidate)}
    r = compare.compare_fingerprint_sets(recorded, fresh)
    return {"verdict": r.verdict, "moved": sorted(r.moved)}


def main() -> int:
    from osgeo import gdal, osr

    gdal.UseExceptions()
    shutil.rmtree(RUN, ignore_errors=True)
    for suffix in ("", "-wal", "-shm"):
        pathlib.Path(str(DB) + suffix).unlink(missing_ok=True)
    RESULTS.mkdir(exist_ok=True)
    source = download()
    qgis_session.start_qgis()
    from qgis.core import QgsApplication

    if QgsApplication.processingRegistry().algorithmById("grass:r.watershed") is None:
        print("GRASS provider unavailable", file=sys.stderr)
        return 1
    plugin = qgis_session.load_plugin(DB)
    expected = json.loads((HERE / "expected.json").read_text())
    dem = DATA / "dem_window.tif"
    base = chain(RUN / "baseline", dem, threshold=STREAM_THRESHOLD)
    baseline = _measure(base)
    store = plugin.store
    trials = []

    # H1 — the DEM re-saved with Deflate and tiles.
    d = RUN / "H1"
    d.mkdir()
    h1 = d / "dem_window.tif"
    gdal.Translate(str(h1), str(dem), creationOptions=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=1"])
    trials.append({"id": "H1", "target": "DEM (GeoTIFF)", "how": "gdal_translate -co COMPRESS=DEFLATE -co TILED=YES",
                   "expected": expected["H1"], **_classify(_recorded(store, dem), h1),
                   "effect": _measure(chain(d / "rerun", h1, threshold=STREAM_THRESHOLD))})

    # H2 — DEM cells raised by 5 m in a 1 km block inside the basin.
    d = RUN / "H2"
    d.mkdir()
    h2 = d / "dem_window.tif"
    shutil.copy2(dem, h2)
    ds = gdal.Open(str(h2), gdal.GA_Update)
    band = ds.GetRasterBand(1)
    gt = ds.GetGeoTransform()
    col = int((79.55 - gt[0]) / gt[1])
    row = int((11.70 - gt[3]) / gt[5])
    size = max(int(1000 / 30), 1)
    block = band.ReadAsArray(col, row, size, size)
    band.WriteArray(block + 5, col, row)
    ds = None
    trials.append({"id": "H2", "target": "DEM (GeoTIFF)", "how": f"+5 m on a {size}x{size}-cell block at 79.55E 11.70N",
                   "expected": expected["H2"], **_classify(_recorded(store, dem), h2),
                   "effect": _measure(chain(d / "rerun", h2, threshold=STREAM_THRESHOLD))})

    # H3 — stream threshold halved; the stream network re-derived.
    d = RUN / "H3"
    h3 = chain(d, dem, threshold=STREAM_THRESHOLD_H3)
    trials.append({"id": "H3", "target": "stream network (GeoPackage)",
                   "how": f"r.stream.extract threshold {STREAM_THRESHOLD} -> {STREAM_THRESHOLD_H3} cells",
                   "expected": expected["H3"], **_classify(_recorded(store, base["streams"]), h3["streams"]),
                   "effect": _measure(h3)})

    # H4 — watershed polygon CRS reassigned (coordinates untouched).
    d = RUN / "H4"
    d.mkdir()
    h4 = d / "watershed.gpkg"
    gdal.VectorTranslate(str(h4), base["watershed"], options=["-f", "GPKG", "-a_srs", "EPSG:32643"])
    trials.append({"id": "H4", "target": "watershed (GeoPackage)", "how": "CRS reassigned to EPSG:32643",
                   "expected": expected["H4"], **_classify(_recorded(store, base["watershed"]), h4),
                   "effect": None})

    plugin.engine.finish_hook_probe()
    sys.path.insert(0, str(HERE.parent / "case_cuddalore"))
    from run_in_qgis import record_summary  # noqa: E402 — the same counting as case 1

    plugin.unload()
    result = {"source": source, "versions": qgis_session.versions(),
              "record_after_all_runs": record_summary(DB), "baseline": {**baseline, "outlet": base["outlet"]},
              "trials": trials, "stream_threshold": STREAM_THRESHOLD}
    (RESULTS / "hydro.json").write_text(json.dumps(result, indent=2) + "\n")
    for t in trials:
        print(t["id"], t["verdict"], "expected", t["expected"], t["effect"])
    print("baseline", baseline)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
