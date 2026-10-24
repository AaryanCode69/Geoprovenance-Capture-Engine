"""E3 — runtime and storage overhead (manuscript §5.5, Table 10).

    evaluation/qgis.sh gp-q42  evaluation/overhead/run_overhead.py
    evaluation/qgis.sh gp-q334 evaluation/overhead/run_overhead.py

Three fixed workflows are each run RUNS times: the coastal and hydrology
subsets E7 also uses (short jobs on small clips) and `dem_full`, three jobs
that each write about 100 MB on the whole DEM. Each is run RUNS times under each of three conditions, interleaved
per repeat so drift in the machine's state lands on all three alike:

    off       QGIS's own processing.run, captured before the plugin wrapped it
    capture   the plugin's wrapper with enrich=False (record only)
    full      the plugin's wrapper with fingerprinting and derivation on

One warm-up repeat is run first and discarded. Stage timers wrap the engine's
own methods from outside (the plugin code is not instrumented):

    capture and write  record_algorithm_execution minus the two passes below
    fingerprinting     ProvenanceCaptureEngine._fingerprint
    derivation         ProvenanceCaptureEngine._infer_derivations

Database growth is the database's page count x page size after a WAL
checkpoint, read before and after each full-condition workflow; the one-off
registry snapshot written at load is reported separately.
Writes results/overhead_<qgis version>.json.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "completeness"))
sys.path.insert(0, str(ROOT))

from common import qgis_session  # noqa: E402

RUNS = 10
WORKFLOWS = ("coastal_raster", "hydro_raster", "dem_full")
DEM = ROOT / "evaluation" / "case_hydro" / "data" / "dem_window.tif"


def dem_full(out: pathlib.Path) -> list[tuple[str, dict]]:
    """Three jobs that each write about 100 MB: the whole case-study-2 DEM
    (3061 x 1945 cells) warped to UTM 44N at 15 m, then slope and hillshade of
    it. The other two workflows touch small clips; this one shows how the cost
    scales with the data a job touches."""
    d = out / "dem"
    return [
        ("gdal:warpreproject", {"INPUT": str(DEM), "TARGET_CRS": "EPSG:32644", "RESAMPLING": 1,
                                "TARGET_RESOLUTION": 15.0, "DATA_TYPE": 0, "OUTPUT": str(d / "dem_utm15.tif")}),
        ("gdal:slope", {"INPUT": str(d / "dem_utm15.tif"), "BAND": 1, "SCALE": 1.0, "AS_PERCENT": False,
                        "COMPUTE_EDGES": True, "ZEVENBERGEN": False, "OUTPUT": str(d / "slope.tif")}),
        ("gdal:hillshade", {"INPUT": str(d / "dem_utm15.tif"), "BAND": 1, "Z_FACTOR": 1.0, "SCALE": 1.0,
                            "AZIMUTH": 315.0, "ALTITUDE": 45.0, "COMPUTE_EDGES": True,
                            "ZEVENBERGEN": False, "OUTPUT": str(d / "hillshade.tif")}),
    ]
WORK = HERE / "work"


def _db_bytes(db: pathlib.Path) -> int:
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        size = conn.execute("PRAGMA page_size").fetchone()[0]
    return pages * size


def _snapshot_bytes(db: pathlib.Path) -> int:
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT coalesce(sum(length(algorithms_z)), 0) FROM registry_snapshots").fetchone()
    return row[0]


class StageTimer:
    """Wraps three engine methods on the instance and accumulates seconds."""

    def __init__(self, engine):
        self.totals = {"record": 0.0, "fingerprint": 0.0, "derivation": 0.0}
        for attr, key in (("record_algorithm_execution", "record"),
                          ("_fingerprint", "fingerprint"),
                          ("_infer_derivations", "derivation")):
            setattr(engine, attr, self._timed(getattr(engine, attr), key))

    def _timed(self, method, key):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return method(*args, **kwargs)
            finally:
                self.totals[key] += time.perf_counter() - start
        return wrapper

    def take(self) -> dict:
        out = dict(self.totals)
        for key in self.totals:
            self.totals[key] = 0.0
        return out


def _summary(values: list[float]) -> dict:
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    # 95 % CI of the mean, t(9) = 2.262 for ten runs.
    t = {10: 2.262}.get(len(values), 1.96)
    return {"mean": mean, "sd": sd, "ci95": t * sd / len(values) ** 0.5, "n": len(values)}


def main() -> int:
    import run_paths

    qgis_session.start_qgis()
    import processing

    original_run = processing.run  # before the plugin wraps it
    versions = qgis_session.versions()
    tag = versions["qgis_version"]
    shutil.rmtree(WORK / tag, ignore_errors=True)
    db = WORK / tag / "provenance.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    plugin = qgis_session.load_plugin(db)
    engine = plugin.engine
    timer = StageTimer(engine)
    load_bytes = _db_bytes(db)

    def run_once(workflow: str, condition: str, repeat: int) -> dict:
        out = WORK / tag / workflow / condition / f"r{repeat}"
        for sub in ("coast", "hydro", "dem"):
            (out / sub).mkdir(parents=True, exist_ok=True)
        steps = dem_full(out) if workflow == "dem_full" else run_paths.workflows(out)[workflow]
        engine.enrich = condition == "full"
        engine.begin_new_workflow()
        before = _db_bytes(db)
        timer.take()
        job_seconds = []
        for alg, params in steps:
            start = time.perf_counter()
            (original_run if condition == "off" else processing.run)(alg, params)
            job_seconds.append(time.perf_counter() - start)
        stages = timer.take()
        stages["capture_write"] = stages["record"] - stages["fingerprint"] - stages["derivation"]
        growth = _db_bytes(db) - before
        shutil.rmtree(out / "dem", ignore_errors=True)  # ~300 MB a run; measured already
        return {"workflow": workflow, "condition": condition, "repeat": repeat, "jobs": len(steps),
                "job_seconds": job_seconds, "stages_s": stages,
                "db_growth_bytes": growth}

    runs = []
    for repeat in range(0, RUNS + 1):  # repeat 0 is the discarded warm-up
        for workflow in WORKFLOWS:
            for condition in ("off", "capture", "full"):
                result = run_once(workflow, condition, repeat)
                result["warmup"] = repeat == 0
                runs.append(result)
                print(f"{tag} {workflow} r{repeat:2} {condition:8} per-job "
                      f"{statistics.fmean(result['job_seconds']):.3f}s  "
                      f"stages {json.dumps({k: round(v * 1000, 1) for k, v in result['stages_s'].items()})} ms  "
                      f"db +{result['db_growth_bytes']} B", flush=True)

    summaries = {workflow: summarise([r for r in runs if not r["warmup"] and r["workflow"] == workflow])
                 for workflow in WORKFLOWS}

    plugin.unload()
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"overhead_{tag}.json").write_text(json.dumps({
        "versions": versions, "runs_per_condition": RUNS, "workflows": WORKFLOWS,
        "db_bytes_after_load": load_bytes, "registry_snapshot_bytes": _snapshot_bytes(db),
        "summary": summaries, "runs": runs,
    }, indent=2) + "\n")
    return 0


def summarise(kept: list[dict]) -> dict:
    summary = {}
    for condition in ("off", "capture", "full"):
        rows = [r for r in kept if r["condition"] == condition]
        per_job = [statistics.fmean(r["job_seconds"]) for r in rows]
        summary[condition] = {"per_job_s": _summary(per_job)}
        if condition != "off":
            for stage in ("capture_write", "fingerprint", "derivation"):
                summary[condition][f"{stage}_ms_per_job"] = _summary(
                    [r["stages_s"][stage] * 1000 / r["jobs"] for r in rows])
        if condition == "full":
            growth = [r["db_growth_bytes"] for r in rows]
            summary[condition]["db_growth_per_workflow_bytes"] = _summary(growth)
            summary[condition]["db_growth_per_job_bytes"] = _summary([g / rows[0]["jobs"] for g in growth])
    off = summary["off"]["per_job_s"]["mean"]
    for condition in ("capture", "full"):
        summary[condition]["relative_overhead_pct"] = 100 * (summary[condition]["per_job_s"]["mean"] - off) / off
    return summary


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
