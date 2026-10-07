"""Run the Cuddalore shoreline pipeline inside a real QGIS, captured by
GeoProvenance — mirrors ``qgis_demo/run_in_qgis.py``'s pattern.

    PYTHONPATH=/usr/share/qgis/python/plugins:<repo root> \\
      QT_QPA_PLATFORM=offscreen python3 experiments/coastal-shoreline/run_in_qgis.py

Protocol: ``coastal-reproducibility-experiment-protocol.md``. Phase 1 only —
per-date shoreline extraction (clip -> MNDWI -> threshold -> polygonize ->
boundary lines) for both the 2015 and 2026 scenes. Baseline/transects/EPR and
the P1-P5 perturbation runs come once this phase's outputs are inspected.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qgis.core import Qgis, QgsApplication                    # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import scenario                                                # noqa: E402

FINDINGS: list[str] = []


def note(line: str) -> None:
    FINDINGS.append(line)
    print(f"  {line}")


def _start_processing():
    import processing
    from processing.core.Processing import Processing
    Processing.initialize()
    return processing


def _check_inputs() -> None:
    missing = [p for p in scenario.INPUT_PATHS if not p.exists()]
    if missing:
        raise SystemExit(
            "missing input band(s), extract the scene tar(s) first:\n"
            + "\n".join(f"  {p}" for p in missing)
        )


def _reset_outputs() -> None:
    if scenario.OUT_DIR.exists():
        shutil.rmtree(scenario.OUT_DIR)
    scenario.OUT_DIR.mkdir(parents=True, exist_ok=True)


def _reset_database() -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = scenario.DB_PATH.with_name(scenario.DB_PATH.name + suffix)
        if candidate.exists():
            candidate.unlink()


def run() -> int:
    from geoprovenance.capture import hooks
    from geoprovenance.capture.engine import ProvenanceCaptureEngine
    from geoprovenance.storage.store import ProvenanceStore

    note(f"QGIS version: {Qgis.QGIS_VERSION}")
    _check_inputs()

    processing = _start_processing()
    note(f"Processing initialised, "
         f"{len(QgsApplication.processingRegistry().algorithms())} algorithms available")

    _reset_outputs()
    _reset_database()

    store = ProvenanceStore(scenario.DB_PATH)
    engine = ProvenanceCaptureEngine.start(store)
    hook_dir = scenario.EXPERIMENT_ROOT / "_hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)

    undo = []
    try:
        for description, undo_fn in hooks.install_all(engine, hook_dir):
            note(f"installed: {description}")
            undo.append(undo_fn)

        print()
        for index, step in enumerate(scenario.STEPS, start=1):
            print(f"  step {index}/{len(scenario.STEPS)}: "
                  f"{step['algorithm_name']} — {step['plain']}")
            try:
                results = processing.run(step["algorithm_id"], dict(step["parameters"]))
            except Exception as exc:
                note(f"STEP {index} FAILED ({step['algorithm_id']}): {exc!r}")
                raise
            produced = results.get("OUTPUT")
            print(f"           produced {produced}")

        print()
        engine.group_session()
        counts = store.counts()
        note(f"jobs recorded     : {counts['activities']}")
        note(f"files known about : {counts['entities']}")
        note(f"connections drawn : {counts['relations']}")
    finally:
        for undo_fn in reversed(undo):
            try:
                undo_fn()
            except Exception as exc:               # pragma: no cover - reported
                note(f"teardown failed: {exc!r}")
        ProvenanceCaptureEngine.stop()
        store.close()

    _write_findings()
    return 0


def _write_findings() -> None:
    target = scenario.EXPERIMENT_ROOT / "findings.txt"
    target.write_text("\n".join(FINDINGS) + "\n")
    print()
    print(f"  measurements written to {target.relative_to(REPO_ROOT)}")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        return run()
    finally:
        app.exitQgis()


if __name__ == "__main__":
    sys.exit(main())
