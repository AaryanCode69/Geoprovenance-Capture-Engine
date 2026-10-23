"""E6 — audit behaviour across scenarios (manuscript §5.8, Table 13).

Offline scenarios (no QGIS — the point being made):
    .venv/bin/python evaluation/audit/scenarios.py offline
Cross-version scenario (QGIS 3.34.6 auditing a record made on QGIS 4.2.3):
    evaluation/qgis.sh gp-q334 evaluation/audit/scenarios.py q334

Each scenario puts a perturbed file at the recorded path, audits the workflow
from the provenance database, and restores the original. Results are merged
into results/scenarios.json.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from geoprovenance import audit  # noqa: E402
from geoprovenance.storage.store import ProvenanceStore  # noqa: E402

COAST = ROOT / "evaluation" / "case_cuddalore"
HYDRO = ROOT / "evaluation" / "case_hydro"
OUT = HERE / "results" / "scenarios.json"


def _workflow(store, steps: int) -> str:
    for wf in store.list_workflows():
        if len(store.get_workflow_graph(wf["id"])["activities"]) == steps:
            return wf["id"]
    raise RuntimeError(f"no {steps}-step workflow")


def _sidecars(path: pathlib.Path) -> list[pathlib.Path]:
    if path.suffix.lower() != ".shp":
        return [path]
    return [path.with_suffix(s) for s in (".shp", ".shx", ".dbf", ".prj", ".cpg") if path.with_suffix(s).exists()]


def _audit(db: pathlib.Path, steps: int, swap: tuple[pathlib.Path, pathlib.Path] | None = None) -> dict:
    """Audit with `swap = (recorded path, replacement)` in place, then restore."""
    backup = None
    if swap is not None:
        target, replacement = swap
        backup = target.with_name(target.name + ".audit-backup")
        shutil.copy2(target, backup)
        shutil.copy2(replacement, target)
    try:
        store = ProvenanceStore(db)
        try:
            wid = _workflow(store, steps)
            result = audit.audit_workflow(store, wid)
            return {
                "score": result.overall,
                "band": result.band,
                "components": result.components,
                "excluded": [n for n, v in result.components.items() if v is None],
                "reasons": {n: result.reasons(n)[:3] for n in audit.WEIGHTS if result.reasons(n)},
                "steps": len(result.steps),
            }
        finally:
            store.close()
    finally:
        if backup is not None:
            shutil.copy2(backup, swap[0])
            backup.unlink()


def offline() -> dict:
    base = COAST / "run" / "baseline"
    shore = base / "2026_shoreline.gpkg"
    perturb = COAST / "run" / "perturb"
    scenarios = {
        "coastal_unchanged_offline": _audit(COAST / "provenance.db", 49),
        "coastal_after_P1": _audit(COAST / "provenance.db", 49, (shore, perturb / "P1_1" / "2026_shoreline.gpkg")),
        "coastal_after_P2": _audit(COAST / "provenance.db", 49, (shore, perturb / "P2_1" / "2026_shoreline.gpkg")),
        "coastal_after_P3": _audit(COAST / "provenance.db", 49,
                                   (COAST / "data" / "recent_B3.tif", perturb / "P3_1" / "recent_B3.tif")),
        "hydro_after_H2": _audit(HYDRO / "provenance.db", 16,
                                 (HYDRO / "data" / "dem_window.tif", HYDRO / "run" / "H2" / "dem_window.tif")),
        "hydro_unchanged_offline": _audit(HYDRO / "provenance.db", 16),
    }
    from geoprovenance.capture import environment

    scenarios["_audit_host"] = {"qgis": environment.qgis_version(), "python": environment.python_version()}
    return scenarios


def q334() -> dict:
    sys.path.insert(0, str(ROOT / "evaluation"))
    from common import qgis_session

    qgis_session.start_qgis()
    work = HERE / "scratch"
    work.mkdir(exist_ok=True)
    copy = work / "coastal_q334.db"
    shutil.copy2(COAST / "provenance.db", copy)  # never write to the evidence database
    return {"coastal_audited_on_qgis_3_34": {**_audit(copy, 49), "audit_host": qgis_session.versions()}}


if __name__ == "__main__":
    mode = sys.argv[1]
    found = json.loads(OUT.read_text()) if OUT.exists() else {}
    found.update({"offline": offline, "q334": q334}[mode]())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(found, indent=2, default=str) + "\n")
    print(json.dumps(found, indent=2, default=str)[:4000])
    sys.stdout.flush()
    os._exit(0)
