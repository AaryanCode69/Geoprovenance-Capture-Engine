"""E7 — capture completeness by invocation path (manuscript §5.4, Table 9).

    evaluation/qgis.sh gp-q42  evaluation/completeness/run_paths.py
    evaluation/qgis.sh gp-q334 evaluation/completeness/run_paths.py

Three workflows x four invocation paths x REPEATS, with the real plugin loaded.
QGIS runs headless on an offscreen display, so the Toolbox, batch and Modeler
paths are DRIVEN PROGRAMMATICALLY through the dialogs QGIS itself opens for
them — the same execution code a click reaches — not by a person clicking:

    script   processing.run(...) for each step
    toolbox  processing.createAlgorithmDialog(alg, params).runAlgorithm()
    batch    BatchAlgorithmDialog, one row filled per step the way its own
             load() fills rows, then runAlgorithm()
    modeler  the steps saved as one Processing model and run from its
             algorithm dialog, as the Modeler's "Run" does; the steps run as
             the model's child algorithms

For each run: jobs run (steps), jobs recorded (new activity rows naming those
algorithms), the channel that recorded each first, and corroborations. Writes
results/<qgis version>.json.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT))

from common import qgis_session  # noqa: E402

REPEATS = 3
WORK = HERE / "work"
COAST = ROOT / "evaluation" / "case_cuddalore"
HYDRO = ROOT / "evaluation" / "case_hydro"


def workflows(out: pathlib.Path) -> dict[str, list[tuple[str, dict]]]:
    """Each workflow as (algorithm id, parameters) steps writing under `out`."""
    from qgis_demo import scenario

    demo = []
    rename = {}
    for step in scenario.STEPS:
        params = dict(step["parameters"])
        for key, value in list(params.items()):
            if isinstance(value, str) and value in {str(p) for p in scenario.OUTPUT_PATHS}:
                params[key] = str(out / "demo" / pathlib.Path(value).name)
                rename[value] = params[key]
        for key, value in list(params.items()):
            if isinstance(value, str) and value in rename and key not in ("OUTPUT",):
                params[key] = rename[value]
        demo.append((step["algorithm_id"], params))
    c = out / "coast"
    green, swir = COAST / "data" / "recent_B3.tif", COAST / "data" / "recent_B6.tif"
    extent = "360000,370000,1290000,1300000 [EPSG:32644]"
    coast = [
        ("gdal:cliprasterbyextent", {"INPUT": str(green), "PROJWIN": extent, "OVERCRS": False,
                                     "DATA_TYPE": 0, "OUTPUT": str(c / "green.tif")}),
        ("gdal:cliprasterbyextent", {"INPUT": str(swir), "PROJWIN": extent, "OVERCRS": False,
                                     "DATA_TYPE": 0, "OUTPUT": str(c / "swir.tif")}),
        ("gdal:rastercalculator", {"INPUT_A": str(c / "green.tif"), "BAND_A": 1,
                                   "INPUT_B": str(c / "swir.tif"), "BAND_B": 1,
                                   "FORMULA": "(A-B)/(A+B+1e-9)", "RTYPE": 5, "EXTENT_OPT": 0,
                                   "OUTPUT": str(c / "mndwi.tif")}),
        ("gdal:polygonize", {"INPUT": str(c / "mndwi.tif"), "BAND": 1, "FIELD": "DN",
                             "EIGHT_CONNECTEDNESS": False, "OUTPUT": str(c / "poly.gpkg")}),
    ]
    h = out / "hydro"
    hydro = [
        ("gdal:cliprasterbyextent", {"INPUT": str(HYDRO / "data" / "dem_window.tif"),
                                     "PROJWIN": "79.5,79.7,11.6,11.8 [EPSG:4326]", "OVERCRS": False,
                                     "DATA_TYPE": 0, "OUTPUT": str(h / "dem_clip.tif")}),
        ("gdal:warpreproject", {"INPUT": str(h / "dem_clip.tif"), "TARGET_CRS": "EPSG:32644",
                                "RESAMPLING": 1, "TARGET_RESOLUTION": 30.0, "DATA_TYPE": 0,
                                "OUTPUT": str(h / "dem_utm.tif")}),
        ("native:fillsinkswangliu", {"INPUT": str(h / "dem_utm.tif"), "BAND": 1, "MIN_SLOPE": 0.01,
                                     "OUTPUT_FILLED_DEM": str(h / "dem_filled.tif")}),
    ]
    return {"demo_vector": demo, "coastal_raster": coast, "hydro_raster": hydro}


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def _wait_for_tasks(timeout=600):
    from qgis.core import QgsApplication

    start = time.time()
    manager = QgsApplication.taskManager()
    while time.time() - start < timeout:
        QgsApplication.processEvents()
        if manager.countActiveTasks() == 0:
            for _ in range(20):
                QgsApplication.processEvents()
                time.sleep(0.01)
            return
        time.sleep(0.02)
    raise TimeoutError("Processing tasks did not finish")


def run_script(steps):
    import processing

    for alg, params in steps:
        processing.run(alg, params)


def run_toolbox(steps):
    import processing

    for alg, params in steps:
        dialog = processing.createAlgorithmDialog(alg, params)
        dialog.runAlgorithm()
        _wait_for_tasks()
        dialog.close()


def run_batch(steps):
    from processing.gui.BatchAlgorithmDialog import BatchAlgorithmDialog
    from processing.tools import dataobjects
    from qgis.core import QgsApplication, QgsProcessingParameterDefinition

    hidden = getattr(QgsProcessingParameterDefinition, "Flag", QgsProcessingParameterDefinition).FlagHidden
    for alg_id, params in steps:
        alg = QgsApplication.processingRegistry().createAlgorithmById(alg_id)
        dialog = BatchAlgorithmDialog(alg)
        panel = dialog.mainWidget()
        context = dataobjects.createContext()
        panel.clear()
        panel.addRow()
        for param in alg.parameterDefinitions():
            if param.isDestination() or param.name() not in params:
                continue
            column = panel.parameter_to_column[param.name()]
            panel.wrappers[0][column].setParameterValue(params[param.name()], context)
        for out in alg.destinationParameterDefinitions():
            if out.flags() & hidden or out.name() not in params:
                continue
            column = panel.parameter_to_column[out.name()]
            panel.tblParameters.cellWidget(1, column).setValue(params[out.name()])
        dialog.runAlgorithm()
        _wait_for_tasks()
        dialog.close()


def run_modeler(steps, name):
    """The steps as one model, run from its algorithm dialog (Modeler 'Run')."""
    import processing
    from qgis.core import (QgsApplication, QgsProcessingModelAlgorithm,
                           QgsProcessingModelChildAlgorithm, QgsProcessingModelChildParameterSource)

    model = QgsProcessingModelAlgorithm(name, "geoprovenance-eval")
    previous = None
    for i, (alg_id, params) in enumerate(steps):
        child = QgsProcessingModelChildAlgorithm(alg_id)
        child.setChildId(f"step{i}")
        child.generateChildId(model)
        for key, value in params.items():
            child.addParameterSources(key, [QgsProcessingModelChildParameterSource.fromStaticValue(value)])
        if previous is not None:
            from qgis.core import QgsProcessingModelChildDependency

            child.setDependencies([QgsProcessingModelChildDependency(previous)])
        model.addChildAlgorithm(child)
        previous = child.childId()
    dialog = processing.createAlgorithmDialog(model, {})
    dialog.runAlgorithm()
    _wait_for_tasks()
    dialog.close()


# ---------------------------------------------------------------------------

def _counts(db: pathlib.Path) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM activities").fetchone()[0]


def _new_rows(db: pathlib.Path, since: int) -> list[dict]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT algorithm_id, capture_channel, corroborations, status, "
                            "started_at, ended_at, rowid FROM activities ORDER BY rowid").fetchall()
    return [dict(r) for r in rows[since:]]


def main() -> int:
    qgis_session.start_qgis()
    versions = qgis_session.versions()
    tag = versions["qgis_version"]
    shutil.rmtree(WORK / tag, ignore_errors=True)
    db = WORK / tag / "provenance.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    plugin = qgis_session.load_plugin(db)
    results = []
    for path in ("script", "toolbox", "batch", "modeler"):
        for repeat in range(1, REPEATS + 1):
            for wf_name in ("demo_vector", "coastal_raster", "hydro_raster"):
                out = WORK / tag / path / f"r{repeat}"
                steps = workflows(out)[wf_name]
                for sub in ("demo", "coast", "hydro"):
                    (out / sub).mkdir(parents=True, exist_ok=True)
                before = _counts(db)
                error = ""
                try:
                    if path == "script":
                        run_script(steps)
                    elif path == "toolbox":
                        run_toolbox(steps)
                    elif path == "batch":
                        run_batch(steps)
                    else:
                        run_modeler(steps, f"{wf_name}_{repeat}")
                except Exception as exc:  # noqa: BLE001 — a path that cannot be driven is reported
                    error = f"{type(exc).__name__}: {exc}"[:300]
                time.sleep(0.5)
                from qgis.core import QgsApplication

                for _ in range(50):
                    QgsApplication.processEvents()
                rows = _new_rows(db, before)
                step_ids = [alg for alg, _ in steps]
                outputs = [v for _, p in steps for k, v in p.items()
                           if k.startswith("OUTPUT") and isinstance(v, str)]
                ran = sum(1 for o in outputs if pathlib.Path(o).exists())
                recorded_steps = [r for r in rows if r["algorithm_id"] in step_ids]
                recorded_model = [r for r in rows if r["algorithm_id"].startswith("model")]
                results.append({
                    "path": path, "repeat": repeat, "workflow": wf_name,
                    "steps": len(steps), "outputs_written": ran,
                    "recorded_steps": len(recorded_steps),
                    "recorded_model_jobs": len(recorded_model),
                    "channels": sorted({r["capture_channel"] for r in rows}),
                    "first_channel_counts": {c: sum(1 for r in rows if r["capture_channel"] == c)
                                             for c in {r["capture_channel"] for r in rows}},
                    "corroborations": sum(r["corroborations"] for r in rows),
                    "with_duration": sum(1 for r in recorded_steps if r["started_at"] != r["ended_at"]),
                    "error": error,
                })
                print(f"{tag} {path:8} r{repeat} {wf_name:15} ran {ran}/{len(outputs)} outputs, "
                      f"recorded {len(recorded_steps)}/{len(steps)} steps "
                      f"(+{len(recorded_model)} model) via {sorted({r['capture_channel'] for r in rows})} "
                      f"{error}")
    plugin.engine.finish_hook_probe()
    with sqlite3.connect(db) as conn:
        capabilities = conn.execute("SELECT capabilities_json FROM agents").fetchall()
        files = conn.execute("SELECT count(*) FROM entities").fetchone()[0]
    plugin.unload()
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"qgis_{tag}.json").write_text(json.dumps({
        "versions": versions, "runs": results,
        "agent_capabilities": [c[0] for c in capabilities], "files_recorded": files,
    }, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
