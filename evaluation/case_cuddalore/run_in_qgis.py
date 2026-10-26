"""Case study 1, run live: the Cuddalore workflow inside QGIS with the plugin on.

    evaluation/qgis.sh gp-q42 evaluation/case_cuddalore/run_in_qgis.py baseline
    evaluation/qgis.sh gp-q42 evaluation/case_cuddalore/run_in_qgis.py perturb

`baseline` deletes and rebuilds run/ and provenance.db, loads the real plugin
(evaluation/common/qgis_session.py), runs the whole chain in workflow.py, and
writes results/baseline.json: what the record holds, and the rates.

`perturb` runs P1-P5 against the baseline record (see perturb.py for P1, P4,
P5, which edit files outside QGIS; P2 and P3 are re-runs through captured
Processing calls, so they live here) and writes results/perturbations.json.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from common import qgis_session  # noqa: E402

DATA = HERE / "data"
RUN = HERE / "run"
RESULTS = HERE / "results"
DB = HERE / "provenance.db"
AOI_LONLAT = (79.70, 11.60, 79.85, 11.85)


def aoi_extent() -> str:
    from pyproj import Transformer

    tr = Transformer.from_crs(4326, 32644, always_xy=True)
    w, s, e, n = AOI_LONLAT
    xs, ys = zip(*(tr.transform(lon, lat) for lon, lat in ((w, s), (w, n), (e, s), (e, n))))
    return f"{min(xs):.3f},{max(xs):.3f},{min(ys):.3f},{max(ys):.3f} [EPSG:32644]"


def scenes() -> dict:
    return json.loads((DATA / "scenes.json").read_text())


def record_summary(db: pathlib.Path) -> dict:
    conn = sqlite3.connect(db)
    try:
        q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
        return {
            "jobs": q("SELECT count(*) FROM activities")[0][0],
            "jobs_completed": q("SELECT count(*) FROM activities WHERE status='completed'")[0][0],
            "files": q("SELECT count(*) FROM entities")[0][0],
            "relations": dict(q("SELECT relation_type, count(*) FROM relations GROUP BY 1")),
            "channels": dict(q("SELECT capture_channel, count(*) FROM activities GROUP BY 1")),
            "corroborations": q("SELECT coalesce(sum(corroborations),0) FROM activities")[0][0],
            "fingerprints": q("SELECT count(*) FROM fingerprints")[0][0],
            "agents": [
                dict(zip(("qgis", "gdal", "proj", "geos", "python", "capabilities"), row))
                for row in q("SELECT qgis_version, gdal_version, proj_version, geos_version, "
                             "python_version, capabilities_json FROM agents")
            ],
            "registry_snapshot_algorithms": [r[0] for r in q(
                "SELECT algorithm_count FROM registry_snapshots")],
            "db_bytes": db.stat().st_size,
        }
    finally:
        conn.close()


def epr_values(path: pathlib.Path) -> dict[int, tuple[float, str]]:
    conn = sqlite3.connect(path)
    try:
        table = conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
        ).fetchone()[0]
        return {
            int(tr): (float(epr), cls)
            for tr, epr, cls in conn.execute(f'SELECT "TR_ID", "epr", "epr_class" FROM "{table}"')
        }
    finally:
        conn.close()


def full_chain(out: pathlib.Path, *, recent_green: str, recent_swir: str,
               recent_scene: str, threshold_recent: float = 0.0) -> dict:
    import workflow as w

    s = scenes()["scenes"]
    out.mkdir(parents=True, exist_ok=True)
    extent = aoi_extent()
    _, inner = w.aoi_layers(out, extent)
    early = w.shoreline(out, "2015", str(DATA / s["baseline"]["files"]["B3"]["path"]),
                        str(DATA / s["baseline"]["files"]["B6"]["path"]), extent, inner, 0.0,
                        s["baseline"]["product_id"])
    late = w.shoreline(out, "2026", recent_green, recent_swir, extent, inner, threshold_recent,
                       recent_scene)
    tr = w.transects(out, early)
    c_early = w.crossings(out, "2015", tr, early)
    c_late = w.crossings(out, "2026", tr, late)
    years = w.years_between(s["baseline"]["datetime"], s["recent"]["datetime"])
    classified = w.rates(out, c_early, c_late, years)
    return {"shoreline_2015": early, "shoreline_2026": late, "transects": tr,
            "epr": classified}


def baseline() -> int:
    s = scenes()["scenes"]
    shutil.rmtree(RUN, ignore_errors=True)
    for suffix in ("", "-wal", "-shm"):
        pathlib.Path(str(DB) + suffix).unlink(missing_ok=True)
    RESULTS.mkdir(exist_ok=True)
    qgis_session.start_qgis()
    plugin = qgis_session.load_plugin(DB)
    sys.path.insert(0, str(HERE))
    paths = full_chain(
        RUN / "baseline",
        recent_green=str(DATA / s["recent"]["files"]["B3"]["path"]),
        recent_swir=str(DATA / s["recent"]["files"]["B6"]["path"]),
        recent_scene=s["recent"]["product_id"],
    )
    plugin.engine.finish_hook_probe()
    summary = record_summary(DB)
    values = epr_values(pathlib.Path(paths["epr"]))
    classes: dict[str, int] = {}
    for _, cls in values.values():
        classes[cls] = classes.get(cls, 0) + 1
    with sqlite3.connect(paths["transects"]) as conn:
        table = conn.execute("SELECT table_name FROM gpkg_contents").fetchone()[0]
        n_transects = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    eprs = [v for v, _ in values.values()]
    result = {
        "versions": qgis_session.versions(),
        "record": summary,
        "paths": {k: str(pathlib.Path(v).relative_to(HERE)) if isinstance(v, str) else v
                  for k, v in paths.items()},
        "transects": n_transects,
        "transects_with_rate": len(values),
        "years": __import__("workflow").years_between(s["baseline"]["datetime"], s["recent"]["datetime"]),
        "epr_mean": sum(eprs) / len(eprs),
        "epr_min": min(eprs),
        "epr_max": max(eprs),
        "classes": classes,
    }
    (RESULTS / "baseline.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    plugin.unload()
    return 0


# ---------------------------------------------------------------------------
# perturbations
# ---------------------------------------------------------------------------

def _recorded_set(store, path: pathlib.Path) -> dict[str, str]:
    """The fingerprint set the record holds for the file at `path`."""
    entity = store.find_entity_by_path(str(path))
    if entity is None:
        raise RuntimeError(f"no entity recorded for {path}")
    return {k: v["hash_value"] for k, v in store.get_fingerprint_set(entity["id"]).items()}


def _classify(recorded: dict[str, str], candidate: pathlib.Path) -> dict:
    from geoprovenance.fingerprint import compare, hash as hashing

    fresh = {f.hash_strategy: f.hash_value for f in hashing.fingerprint_dataset(candidate)}
    result = compare.compare_fingerprint_sets(recorded, fresh)
    return {"verdict": result.verdict, "moved": sorted(result.moved),
            "held": sorted(result.held), "unavailable": sorted(result.unavailable)}


def _effect(baseline_epr: dict, other: dict) -> dict:
    common = sorted(set(baseline_epr) & set(other))
    deltas = [other[t][0] - baseline_epr[t][0] for t in common]
    changed_class = sum(1 for t in common if other[t][1] != baseline_epr[t][1])
    return {
        "transects_compared": len(common),
        "transects_baseline": len(baseline_epr),
        "transects_other": len(other),
        "identical": all(abs(d) < 1e-9 for d in deltas) and len(other) == len(baseline_epr),
        "mean_delta_epr": sum(deltas) / len(deltas) if deltas else None,
        "mean_abs_delta_epr": sum(abs(d) for d in deltas) / len(deltas) if deltas else None,
        "class_changed": changed_class,
        "class_changed_pct": 100.0 * changed_class / len(common) if common else None,
    }


def _rerun_rates(out: pathlib.Path, late_shoreline: pathlib.Path, years: float) -> dict:
    import workflow as w

    base = RUN / "baseline"
    out.mkdir(parents=True, exist_ok=True)
    late = w.crossings(out, "2026", str(base / "transects.gpkg"), str(late_shoreline))
    return epr_values(pathlib.Path(w.rates(out, str(base / "2015_cross.gpkg"), late, years)))


def _gdal_resave(src: pathlib.Path, dst: pathlib.Path, *, options: list[str]) -> str:
    from osgeo import gdal

    gdal.UseExceptions()
    gdal.VectorTranslate(str(dst), str(src), options=options)
    return "ogr2ogr " + " ".join(options)


def _qgis_resave(src: pathlib.Path, dst: pathlib.Path) -> str:
    from qgis.core import QgsCoordinateTransformContext, QgsVectorFileWriter, QgsVectorLayer

    layer = QgsVectorLayer(str(src), "shoreline", "ogr")
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(dst), QgsCoordinateTransformContext(), opts
    )
    no_error = getattr(QgsVectorFileWriter, "WriterError", QgsVectorFileWriter).NoError
    if result[0] != no_error:
        raise RuntimeError(f"QgsVectorFileWriter failed: {result}")
    return "QgsVectorFileWriter.writeAsVectorFormatV3 (QGIS 'Save As')"


def perturb() -> int:
    import workflow as w
    from geoprovenance.storage.store import ProvenanceStore

    s = scenes()["scenes"]
    years = w.years_between(s["baseline"]["datetime"], s["recent"]["datetime"])
    out_root = RUN / "perturb"
    shutil.rmtree(out_root, ignore_errors=True)
    out_root.mkdir(parents=True)
    expected = json.loads((HERE / "expected.json").read_text())

    qgis_session.start_qgis()
    plugin = qgis_session.load_plugin(DB)  # perturbation re-runs are captured too
    store = plugin.store
    base = RUN / "baseline"
    shoreline_2026 = base / "2026_shoreline.gpkg"
    recorded_shore = _recorded_set(store, shoreline_2026)
    recorded_green = _recorded_set(store, DATA / s["recent"]["files"]["B3"]["path"])
    baseline_epr = epr_values(base / "epr_classified.gpkg")
    trials = []

    def record(pid, trial, how, target, verdict, effect):
        trials.append({"id": pid, "trial": trial, "how": how, "target": target,
                       "expected": expected[pid], **verdict, "effect": effect})
        print(f"{pid}.{trial}: {verdict['verdict']} (expected {expected[pid]}) — {how}")

    # P1 — silent re-save through three different write paths.
    for k, writer in enumerate((
        lambda src, dst: _gdal_resave(src, dst, options=["-f", "GPKG"]),
        lambda src, dst: _gdal_resave(src, dst, options=["-f", "GPKG", "-unsetFid",
                                                          "-lco", "SPATIAL_INDEX=NO"]),
        _qgis_resave,
    ), start=1):
        d = out_root / f"P1_{k}"
        d.mkdir()
        copy = d / "2026_shoreline.gpkg"
        how = writer(shoreline_2026, copy)
        record("P1", k, how, "2026 shoreline (GeoPackage)", _classify(recorded_shore, copy),
               _effect(baseline_epr, _rerun_rates(d / "rerun", copy, years)))

    # P2 — re-threshold the 2026 water index, 0.0 -> 0.02, re-derived through
    # captured Processing calls.
    d = out_root / "P2_1"
    d.mkdir()
    extent = aoi_extent()
    p2_shore = pathlib.Path(w.shoreline(
        d, "2026", str(DATA / s["recent"]["files"]["B3"]["path"]),
        str(DATA / s["recent"]["files"]["B6"]["path"]), extent,
        str(base / "aoi_inner.gpkg"), 0.02, s["recent"]["product_id"]))
    record("P2", 1, "MNDWI threshold t = 0.0 -> 0.02, 2026 chain re-run in QGIS",
           "2026 shoreline (GeoPackage)", _classify(recorded_shore, p2_shore),
           _effect(baseline_epr, _rerun_rates(d / "rerun", p2_shore, years)))

    # P3 — imagery-vintage swap: a differently dated scene stands in for the
    # 2026 scene, under the 2026 file names, and the chain is re-run.
    for k, alt in enumerate(("alt1", "alt2", "alt3"), start=1):
        d = out_root / f"P3_{k}"
        d.mkdir()
        green = d / "recent_B3.tif"
        swir = d / "recent_B6.tif"
        shutil.copy2(DATA / s[alt]["files"]["B3"]["path"], green)
        shutil.copy2(DATA / s[alt]["files"]["B6"]["path"], swir)
        verdict = _classify(recorded_green, green)
        alt_shore = pathlib.Path(w.shoreline(d, "2026", str(green), str(swir), extent,
                                             str(base / "aoi_inner.gpkg"), 0.0,
                                             s["recent"]["product_id"]))
        record("P3", k, f"2026 scene replaced by {s[alt]['product_id']}",
               "2026 green band (GeoTIFF)", verdict,
               _effect(baseline_epr, _rerun_rates(d / "rerun", alt_shore, years)))

    # P4 — attribute edit: source_scene on one shoreline feature.
    for k in (1, 2, 3):
        d = out_root / f"P4_{k}"
        d.mkdir()
        copy = d / "2026_shoreline.gpkg"
        shutil.copy2(shoreline_2026, copy)
        from osgeo import ogr

        ds = ogr.Open(str(copy), 1)
        layer = ds.GetLayer(0)
        fids = sorted(f.GetFID() for f in layer)
        fid = fids[(k - 1) % len(fids)]
        feature = layer.GetFeature(fid)
        feature.SetField("source_scene", f"edited-{k}")
        layer.SetFeature(feature)
        feature = None
        ds = None  # an attribute edit through GDAL, as an editing tool would make it
        record("P4", k, f"source_scene edited on feature fid={fid}",
               "2026 shoreline (GeoPackage)", _classify(recorded_shore, copy),
               _effect(baseline_epr, _rerun_rates(d / "rerun", copy, years)))

    # P5 — control: an untouched copy.
    for k in (1, 2, 3):
        d = out_root / f"P5_{k}"
        d.mkdir()
        copy = d / "2026_shoreline.gpkg"
        shutil.copy2(shoreline_2026, copy)
        record("P5", k, "byte-identical copy", "2026 shoreline (GeoPackage)",
               _classify(recorded_shore, copy),
               _effect(baseline_epr, _rerun_rates(d / "rerun", copy, years)))

    plugin.unload()
    (RESULTS / "perturbations.json").write_text(json.dumps(
        {"expected": expected, "trials": trials, "years": years}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    sys.path.insert(0, str(HERE))
    code = {"baseline": baseline, "perturb": perturb}[mode]()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # QGIS's own teardown can abort after the work is done
