"""Fetch the Landsat inputs for case study 1 (Cuddalore shoreline change).

Run with a QGIS environment's Python (it uses GDAL's /vsicurl/):
    evaluation/qgis.sh gp-q42 evaluation/case_cuddalore/download.py

Source: Landsat Collection 2 Level-2 surface reflectance, served as Cloud
Optimized GeoTIFFs by the Microsoft Planetary Computer STAC API with an
anonymous SAS token. Only a window around the area of interest is read, on the
scene's native 30 m UTM grid (EPSG:32644) — no resampling — so the windows of
different scenes share one pixel grid.

Writes data/<scene>_<band>.tif and data/scenes.json (product ids from the MTL
files, acquisition dates, cloud cover, SHA-256 of every file written).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import urllib.request

from osgeo import gdal

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/landsat-c2-l2"

#: The fixed area of interest, 11°36'-11°51' N, 79°42'-79°51' E.
AOI_LONLAT = (79.70, 11.60, 79.85, 11.85)  # west, south, east, north
#: Read this much more than the AOI, so the in-QGIS clip is a real step.
MARGIN_M = 1500.0

#: role -> STAC item id. "baseline" and "recent" are the two dates the paper
#: measures; the three "alt" scenes replace the recent scene in perturbation P3.
SCENES = {
    "baseline": "LC08_L2SP_142052_20150624_02_T1",
    "recent": "LC09_L2SP_142052_20260801_02_T1",
    "alt1": "LC09_L2SP_142052_20250729_02_T1",
    "alt2": "LC08_L2SP_142052_20250806_02_T1",
    "alt3": "LC08_L2SP_142052_20240531_02_T1",
}
BANDS = {"green": "B3", "swir16": "B6"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _aoi_window_utm() -> tuple[float, float, float, float]:
    """The AOI's bounding box in EPSG:32644, widened by MARGIN_M, snapped to 30 m."""
    from pyproj import Transformer

    tr = Transformer.from_crs(4326, 32644, always_xy=True)
    w, s, e, n = AOI_LONLAT
    xs, ys = [], []
    for lon, lat in ((w, s), (w, n), (e, s), (e, n)):
        x, y = tr.transform(lon, lat)
        xs.append(x)
        ys.append(y)
    xmin, xmax = min(xs) - MARGIN_M, max(xs) + MARGIN_M
    ymin, ymax = min(ys) - MARGIN_M, max(ys) + MARGIN_M
    # Landsat C2 pixel edges sit on multiples of 15 m (UTM grid, 30 m pixels).
    snap = lambda v: round(v / 30.0) * 30.0 + 15.0  # noqa: E731
    return snap(xmin), snap(ymax), snap(xmax), snap(ymin)  # ulx, uly, lrx, lry


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    token = json.loads(_get(TOKEN_URL))["token"]
    window = _aoi_window_utm()
    gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    record = {"source": STAC, "aoi_lonlat": AOI_LONLAT, "window_epsg32644": window, "scenes": {}}
    for role, item_id in SCENES.items():
        item = json.loads(_get(f"{STAC}/collections/landsat-c2-l2/items/{item_id}"))
        mtl = _get(item["assets"]["mtl.txt"]["href"] + "?" + token).decode("utf-8", "replace")
        product_id = next(
            line.split("=", 1)[1].strip().strip('"')
            for line in mtl.splitlines()
            if line.strip().startswith("LANDSAT_PRODUCT_ID")
        )
        entry = {
            "stac_id": item_id,
            "product_id": product_id,
            "datetime": item["properties"]["datetime"],
            "cloud_cover": item["properties"].get("eo:cloud_cover"),
            "platform": item["properties"].get("platform"),
            "files": {},
        }
        for asset, band in BANDS.items():
            href = item["assets"][asset]["href"] + "?" + token
            out = DATA / f"{role}_{band}.tif"
            src = gdal.Open("/vsicurl/" + href)
            if src is None:
                print(f"could not open {item_id} {asset}", file=sys.stderr)
                return 1
            if src.GetSpatialRef().GetAuthorityCode(None) != "32644":
                print(f"{item_id} is not on EPSG:32644", file=sys.stderr)
                return 1
            gdal.Translate(str(out), src, projWin=list(window), creationOptions=["TILED=NO"])
            src = None
            entry["files"][band] = {"path": out.name, "sha256": _sha256(out)}
            print(f"{role:9} {product_id} {band} -> {out.name}")
        record["scenes"][role] = entry
    (DATA / "scenes.json").write_text(json.dumps(record, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
