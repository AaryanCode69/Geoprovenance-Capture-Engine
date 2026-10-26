"""E1 — the controlled perturbation suite (manuscript §5.2, Tables 6 and 7).

    evaluation/qgis.sh gp-q42 evaluation/perturb_suite/run_suite.py

Three source datasets per format. Every perturbation in expected.json is
applied, alone, to a fresh copy of each source, and the copy is classified
against the SOURCE's fingerprint set without being told what was done. Writes
results/trials.csv (one row per trial) and keeps every perturbed file under
work/ for the baselines (E2) to read.

Randomised perturbations (which feature, which vertex, which pixel, which
field) run TRIALS seeded times; deterministic ones (re-saves, retype, reorder,
CRS, add-field, no-op) run once per write path, because repeating a
deterministic operation measures nothing new.

GDAL write paths use GDAL as shipped with the QGIS environment; the QGIS write
path is QgsVectorFileWriter / QgsRasterFileWriter, i.e. what "Save As" calls.
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import random
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "src"))

from osgeo import gdal, ogr, osr  # noqa: E402

gdal.UseExceptions()
ogr.UseExceptions()

WORK = HERE / "work"
RESULTS = HERE / "results"
TRIALS = 5
COAST = ROOT / "evaluation" / "case_cuddalore"


def _sources() -> dict[str, list[pathlib.Path]]:
    base = COAST / "run" / "baseline"
    return {
        "Shapefile": [ROOT / "tests/fixtures/data/sample_points.shp",
                      WORK / "sources" / "transects_dense.shp",
                      WORK / "sources" / "water_polygons.shp"],
        "GeoPackage": [ROOT / "tests/fixtures/data/sample_areas.gpkg",
                       WORK / "sources" / "transects_dense.gpkg",
                       base / "2026_water_poly.gpkg"],
        "GeoTIFF": [COAST / "data" / "recent_B3.tif",
                    base / "2026_mndwi.tif",
                    base / "2026_water.tif"],
    }


def _prepare_sources() -> None:
    """Sources made once, before any trial.

    The transects are two-vertex lines, which have no interior vertex to move,
    so the line sources are the transects densified every 100 m (ogr2ogr
    -segmentize), in both formats. The development run used the raw
    transects and could not run the vertex trials on them.
    """
    out = WORK / "sources"
    out.mkdir(parents=True, exist_ok=True)
    base = COAST / "run" / "baseline"
    gdal.VectorTranslate(str(out / "transects_dense.gpkg"), str(base / "transects.gpkg"),
                         options=["-f", "GPKG", "-segmentize", "100", "-nln", "transects_dense"])
    gdal.VectorTranslate(str(out / "transects_dense.shp"), str(out / "transects_dense.gpkg"),
                         options=["-f", "ESRI Shapefile"])
    gdal.VectorTranslate(str(out / "water_polygons.shp"), str(base / "2026_water_poly.gpkg"),
                         options=["-f", "ESRI Shapefile"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sidecars(path: pathlib.Path) -> list[pathlib.Path]:
    if path.suffix.lower() != ".shp":
        return [path]
    return [p for p in (path.with_suffix(s) for s in (".shp", ".shx", ".dbf", ".prj", ".cpg"))
            if p.exists()]


def _copy(src: pathlib.Path, dst_dir: pathlib.Path) -> pathlib.Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for part in _sidecars(src):
        shutil.copy2(part, dst_dir / part.name)
    return dst_dir / src.name


def _driver(path: pathlib.Path) -> str:
    return {"shp": "ESRI Shapefile", "gpkg": "GPKG"}[path.suffix.lower().lstrip(".")]


def _layer_name(path: pathlib.Path) -> str:
    ds = ogr.Open(str(path))
    name = ds.GetLayer(0).GetName()
    ds = None
    return name


def _fingerprints(path: pathlib.Path) -> dict[str, str]:
    from geoprovenance.fingerprint import hash as hashing

    return {f.hash_strategy: f.hash_value for f in hashing.fingerprint_dataset(path)}


def _classify(before: dict[str, str], path: pathlib.Path) -> tuple[str, list[str]]:
    from geoprovenance.fingerprint import compare

    result = compare.compare_fingerprint_sets(before, _fingerprints(path))
    return result.verdict, sorted(result.moved)


def _extent(path: pathlib.Path) -> tuple[float, ...]:
    ds = ogr.Open(str(path))
    extent = tuple(round(v, 9) for v in ds.GetLayer(0).GetExtent(force=1))
    ds = None
    return extent


def _other_epsg(code: int) -> int:
    return {4326: 4269, 32644: 32643}.get(code, 4326)


def _epsg_of(path: pathlib.Path) -> int:
    if path.suffix.lower() == ".tif":
        ds = gdal.Open(str(path))
        ref = osr.SpatialReference(wkt=ds.GetProjection())
    else:
        ds = ogr.Open(str(path))
        ref = ds.GetLayer(0).GetSpatialRef().Clone()
    ds = None
    ref.AutoIdentifyEPSG()
    return int(ref.GetAuthorityCode(None))


# ---------------------------------------------------------------------------
# vector perturbations — each takes (copy path, rng) and edits the copy
# ---------------------------------------------------------------------------

def _edit(path: pathlib.Path):
    ds = ogr.Open(str(path), 1)
    return ds, ds.GetLayer(0)


def v_attribute_edit(path, rng):
    ds, layer = _edit(path)
    defn = layer.GetLayerDefn()
    fids = [f.GetFID() for f in layer]
    feature = layer.GetFeature(rng.choice(fids))
    index = rng.randrange(defn.GetFieldCount())
    field = defn.GetFieldDefn(index)
    kind = field.GetType()
    if kind == ogr.OFTString:
        feature.SetField(index, (feature.GetField(index) or "") + "_x")
    elif kind == ogr.OFTInteger or kind == ogr.OFTInteger64:
        feature.SetField(index, (feature.GetField(index) or 0) + 1)
    else:
        feature.SetField(index, (feature.GetField(index) or 0.0) + 0.5)
    layer.SetFeature(feature)
    return f"field {field.GetName()} of feature {feature.GetFID()}"


def v_field_add(path, rng):
    ds, layer = _edit(path)
    layer.CreateField(ogr.FieldDefn("added", ogr.OFTString))
    return "new empty string field 'added'"


def v_field_drop(path, rng):
    ds, layer = _edit(path)
    defn = layer.GetLayerDefn()
    index = rng.randrange(defn.GetFieldCount())
    name = defn.GetFieldDefn(index).GetName()
    layer.DeleteField(index)
    return f"dropped field {name}"


def v_field_retype(path, rng):
    ds = ogr.Open(str(path))
    defn = ds.GetLayer(0).GetLayerDefn()
    kinds = {defn.GetFieldDefn(i).GetType() for i in range(defn.GetFieldCount())}
    ds = None
    numeric = kinds & {ogr.OFTInteger, ogr.OFTInteger64, ogr.OFTReal}
    mapping = "Integer=String,Integer64=String,Real=String" if numeric else "String=Integer"
    tmp = path.with_name("retyped" + path.suffix)
    gdal.VectorTranslate(str(tmp), str(path), options=["-f", _driver(path), "-mapFieldType", mapping])
    _replace(path, tmp)
    return f"-mapFieldType {mapping}"


def v_crs_reassign(path, rng):
    code = _other_epsg(_epsg_of(path))
    tmp = path.with_name("reassigned" + path.suffix)
    gdal.VectorTranslate(str(tmp), str(path), options=["-f", _driver(path), "-a_srs", f"EPSG:{code}"])
    _replace(path, tmp)
    return f"CRS reassigned to EPSG:{code}, coordinates untouched"


def v_feature_add(path, rng):
    ds, layer = _edit(path)
    fids = [f.GetFID() for f in layer]
    source = layer.GetFeature(rng.choice(fids))
    new = ogr.Feature(layer.GetLayerDefn())
    new.SetFrom(source)
    geom = source.GetGeometryRef().Clone()
    step = 1e-4 if _epsg_of(path) == 4326 else 10.0
    _translate(geom, step, step)
    new.SetGeometry(geom)
    layer.CreateFeature(new)
    return f"copy of feature {source.GetFID()} shifted by {step}"


def v_feature_delete(path, rng):
    ds, layer = _edit(path)
    fids = [f.GetFID() for f in layer]
    fid = rng.choice(fids)
    layer.DeleteFeature(fid)
    return f"deleted feature {fid}"


def v_vertex_move(path, rng):
    """One vertex moved a small distance, the layer's extent held."""
    before = _extent(path)
    step = 1e-6 if _epsg_of(path) == 4326 else 0.5
    for _ in range(200):
        ds, layer = _edit(path)
        fids = [f.GetFID() for f in layer]
        feature = layer.GetFeature(rng.choice(fids))
        geom = feature.GetGeometryRef()
        moved = _move_one_interior_vertex(geom, rng, step, before)
        if moved is None:
            ds = None
            continue
        feature.SetGeometry(geom)
        layer.SetFeature(feature)
        ds = None
        if _extent(path) == before:
            return f"vertex {moved} of feature {feature.GetFID()} moved by {step}"
        raise RuntimeError("vertex move changed the extent")
    raise RuntimeError("no movable interior vertex found")


def v_extent_edit(path, rng):
    """Move the easternmost vertex further east: the extent must change."""
    ds, layer = _edit(path)
    best = None
    for feature in layer:
        for (geom, i, x, y) in _vertices(feature.GetGeometryRef()):
            if best is None or x > best[3]:
                best = (feature.GetFID(), geom, i, x, y)
    fid = best[0]
    feature = layer.GetFeature(fid)
    step = 1e-4 if _epsg_of(path) == 4326 else 10.0
    for (geom, i, x, y) in _vertices(feature.GetGeometryRef()):
        if x == best[3] and y == best[4]:
            geom.SetPoint_2D(i, x + step, y)
            break
    layer.SetFeature(feature)
    return f"easternmost vertex of feature {fid} moved east by {step}"


def v_row_reorder(path, rng):
    name = _layer_name(path)
    tmp = path.with_name("reordered" + path.suffix)
    fid = "FID" if path.suffix.lower() == ".shp" else "fid"
    gdal.VectorTranslate(str(tmp), str(path), options=[
        "-f", _driver(path), "-sql", f'SELECT * FROM "{name}" ORDER BY {fid} DESC', "-nln", name])
    _replace(path, tmp)
    return "rows written in reverse order"


def v_resave_gdal(path, rng):
    tmp = path.with_name("resaved" + path.suffix)
    gdal.VectorTranslate(str(tmp), str(path), options=["-f", _driver(path), "-nln", _layer_name(path)])
    _replace(path, tmp)
    return f"ogr2ogr -f {_driver(path)} (GDAL {gdal.VersionInfo('RELEASE_NAME')})"


def v_resave_qgis(path, rng):
    from qgis.core import QgsCoordinateTransformContext, QgsVectorFileWriter, QgsVectorLayer

    layer = QgsVectorLayer(str(path), _layer_name(path), "ogr")
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = _driver(path)
    opts.layerName = _layer_name(path)
    tmp = path.with_name("resaved_q" + path.suffix)
    result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(tmp), QgsCoordinateTransformContext(), opts)
    no_error = getattr(QgsVectorFileWriter, "WriterError", QgsVectorFileWriter).NoError
    if result[0] != no_error:
        raise RuntimeError(f"QgsVectorFileWriter: {result}")
    layer = None
    _replace(path, tmp)
    return "QgsVectorFileWriter (QGIS 'Save As')"


def noop(path, rng):
    return "untouched copy"


def _replace(path: pathlib.Path, tmp: pathlib.Path) -> None:
    for part in _sidecars(path):
        part.unlink()
    for part in _sidecars(tmp):
        part.rename(path.with_suffix(part.suffix))


def _translate(geom, dx, dy):
    for (g, i, x, y) in _vertices(geom):
        g.SetPoint_2D(i, x + dx, y + dy)


def _vertices(geom):
    """(geometry holding the vertex, index, x, y) for every vertex."""
    count = geom.GetGeometryCount()
    if count:
        for k in range(count):
            yield from _vertices(geom.GetGeometryRef(k))
        return
    for i in range(geom.GetPointCount()):
        x, y = geom.GetX(i), geom.GetY(i)
        yield (geom, i, x, y)


def _move_one_interior_vertex(geom, rng, step, extent):
    xmin, xmax, ymin, ymax = extent
    candidates = []
    for (g, i, x, y) in _vertices(geom):
        n = g.GetPointCount()
        closing = g.GetGeometryType() in (ogr.wkbLinearRing,) or (n > 2 and (g.GetX(0), g.GetY(0)) == (g.GetX(n - 1), g.GetY(n - 1)))
        if n > 1 and (i == 0 or i == n - 1) and closing:
            continue  # first/last of a ring: moving one breaks closure
        if n > 1 and (i == 0 or i == n - 1) and g.GetGeometryType() in (ogr.wkbLineString, ogr.wkbLineString25D):
            continue  # an end, not an interior vertex
        if xmin + 2 * step < x < xmax - 2 * step and ymin + 2 * step < y < ymax - 2 * step:
            candidates.append((g, i, x, y))
    if not candidates:
        return None
    g, i, x, y = rng.choice(candidates)
    g.SetPoint_2D(i, x + step, y + step)
    return i


# ---------------------------------------------------------------------------
# raster perturbations
# ---------------------------------------------------------------------------

def r_resave_deflate(path, rng):
    ds = gdal.Open(str(path))
    is_float = ds.GetRasterBand(1).DataType in (gdal.GDT_Float32, gdal.GDT_Float64)
    opts = ["COMPRESS=DEFLATE", "TILED=YES", f"PREDICTOR={1 if is_float else 2}"]
    tmp = path.with_name("resaved.tif")
    gdal.Translate(str(tmp), ds, creationOptions=opts)
    ds = None
    _replace(path, tmp)
    return "gdal_translate -co " + " -co ".join(opts)


def r_resave_bigtiff(path, rng):
    opts = ["BIGTIFF=YES", "TILED=YES", "BLOCKXSIZE=128", "BLOCKYSIZE=128"]
    tmp = path.with_name("resaved.tif")
    gdal.Translate(str(tmp), str(path), creationOptions=opts)
    _replace(path, tmp)
    return "gdal_translate -co " + " -co ".join(opts)


def r_resave_qgis(path, rng):
    from qgis.core import QgsRasterFileWriter, QgsRasterLayer, QgsRasterPipe

    layer = QgsRasterLayer(str(path), "r")
    provider = layer.dataProvider()
    pipe = QgsRasterPipe()
    pipe.set(provider.clone())
    tmp = path.with_name("resaved.tif")
    writer = QgsRasterFileWriter(str(tmp))
    error = writer.writeRaster(pipe, provider.xSize(), provider.ySize(), provider.extent(), provider.crs())
    no_error = getattr(QgsRasterFileWriter, "WriterError", QgsRasterFileWriter).NoError
    if error != no_error:
        raise RuntimeError(f"QgsRasterFileWriter: {error}")
    layer = None
    _replace(path, tmp)
    return "QgsRasterFileWriter (QGIS 'Save As')"


def r_pixel_edit(path, rng):
    ds = gdal.Open(str(path), gdal.GA_Update)
    band = ds.GetRasterBand(1)
    x, y = rng.randrange(ds.RasterXSize), rng.randrange(ds.RasterYSize)
    value = band.ReadAsArray(x, y, 1, 1)
    if band.DataType == gdal.GDT_Byte:
        value[0, 0] = 1 - min(int(value[0, 0]), 1)
    elif band.DataType in (gdal.GDT_Float32, gdal.GDT_Float64):
        value[0, 0] = value[0, 0] + 0.01
    else:
        value[0, 0] = value[0, 0] + 1
    band.WriteArray(value, x, y)
    ds = None
    return f"pixel ({x}, {y}) changed"


def r_crs_reassign(path, rng):
    code = _other_epsg(_epsg_of(path))
    ref = osr.SpatialReference()
    ref.ImportFromEPSG(code)
    ds = gdal.Open(str(path), gdal.GA_Update)
    ds.SetProjection(ref.ExportToWkt())
    ds = None
    return f"CRS reassigned to EPSG:{code}"


VECTOR = {
    "resave": [v_resave_gdal, v_resave_qgis],
    "attribute_edit": [v_attribute_edit],
    "field_add": [v_field_add],
    "field_drop": [v_field_drop],
    "field_retype": [v_field_retype],
    "crs_reassign": [v_crs_reassign],
    "feature_add": [v_feature_add],
    "feature_delete": [v_feature_delete],
    "vertex_move": [v_vertex_move],
    "extent_edit": [v_extent_edit],
    "row_reorder": [v_row_reorder],
    "noop": [noop],
}
RASTER = {
    "resave": [r_resave_deflate, r_resave_bigtiff, r_resave_qgis],
    "pixel_edit": [r_pixel_edit],
    "crs_reassign": [r_crs_reassign],
    "noop": [noop],
}
RANDOMISED = {"attribute_edit", "field_drop", "feature_add", "feature_delete",
              "vertex_move", "pixel_edit"}


def main() -> int:
    from common import qgis_session

    qgis_session.start_qgis()
    expected = json.loads((HERE / "expected.json").read_text())
    shutil.rmtree(WORK, ignore_errors=True)
    RESULTS.mkdir(exist_ok=True)
    _prepare_sources()
    rows = []
    for fmt, sources in _sources().items():
        table = RASTER if fmt == "GeoTIFF" else VECTOR
        for s_index, source in enumerate(sources, start=1):
            before = _fingerprints(source)
            for kind, functions in table.items():
                runs = TRIALS if kind in RANDOMISED else 1
                for fn in functions:
                    for trial in range(1, runs + 1):
                        # "final/": seeds distinct from the development run's,
                        # so the reported trials are not the ones the four
                        # canonicalisation fixes were diagnosed on.
                        rng = random.Random(f"final/{fmt}/{s_index}/{kind}/{fn.__name__}/{trial}")
                        trial_dir = WORK / fmt / f"s{s_index}" / f"{kind}_{fn.__name__}_{trial}"
                        copy = _copy(source, trial_dir)
                        try:
                            how = fn(copy, rng)
                            verdict, moved = _classify(before, copy)
                            error = ""
                        except Exception as exc:  # noqa: BLE001 — a failed perturbation is reported
                            how, verdict, moved, error = "", "", [], f"{type(exc).__name__}: {exc}"
                        rows.append({
                            "format": fmt, "source": s_index, "source_path": str(source.relative_to(ROOT)),
                            "perturbation": kind, "variant": fn.__name__, "trial": trial,
                            "expected": expected[kind if fmt != "GeoTIFF" or kind != "resave" else "resave"],
                            "assigned": verdict, "moved": ";".join(moved), "how": how,
                            "copy": str(copy.relative_to(ROOT)), "error": error,
                        })
                        flag = "" if verdict == expected[kind] else "  <-- MISMATCH"
                        print(f"{fmt:10} s{s_index} {kind:15} {fn.__name__:18} t{trial}: {verdict or error}{flag}")
    with (RESULTS / "trials.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (RESULTS / "environment.json").write_text(json.dumps(qgis_session.versions(), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
