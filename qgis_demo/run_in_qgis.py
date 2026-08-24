"""Run the demo workflow inside a real QGIS, with capture switched on.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

    make qgis-demo-run

This is the half of the demo that needs QGIS, and it is the only thing in the
repository that has ever put the capture code in front of the software it was
written for. Two things come out of it:

1. The four output files, produced by QGIS actually doing the work — so every
   file the record mentions is really on disk and can be drawn on the map.
2. Evidence for ``docs/capture_coverage.md``. The script reports, from the
   running QGIS rather than from documentation, whether the hook constants
   exist, whether the hook installed, what the hook script's namespace really
   contains, and which channel caught each of the four jobs.

What it does NOT cover
    This drives Processing through ``processing.run()``. The Toolbox dialog,
    the Graphical Modeler and batch mode are separate code paths inside QGIS
    and have to be exercised by hand, in the desktop application, with the
    plugin loaded. Those rows of the coverage table are filled in that way, not
    by this script. RULES.md §5.11 — which paths fire the hook is an empirical
    question, and answering part of it here does not answer the rest.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qgis.core import Qgis, QgsApplication                    # noqa: E402

from qgis_demo import scenario                                # noqa: E402

FINDINGS: list[str] = []


def note(line: str) -> None:
    FINDINGS.append(line)
    print(f"  {line}")


def _start_processing():
    """Bring up the Processing framework outside the desktop application."""
    import processing
    from processing.core.Processing import Processing
    Processing.initialize()
    return processing


def _probe_hook_constants() -> None:
    """Do the constants A3/A5 assume actually exist? (capture_coverage.md §4)"""
    try:
        from processing.core.ProcessingConfig import ProcessingConfig
    except Exception as exc:                       # pragma: no cover - reported
        note(f"ProcessingConfig could not be imported: {exc!r}")
        return
    for name in ("PRE_EXECUTION_SCRIPT", "POST_EXECUTION_SCRIPT"):
        if hasattr(ProcessingConfig, name):
            note(f"ProcessingConfig.{name} exists, value "
                 f"{getattr(ProcessingConfig, name)!r}")
        else:
            note(f"ProcessingConfig.{name} DOES NOT EXIST on QGIS "
                 f"{Qgis.QGIS_VERSION}")


def _environment() -> None:
    import platform
    note(f"QGIS version          : {Qgis.QGIS_VERSION}")
    note(f"Python version        : {platform.python_version()}")
    note(f"Operating system      : {platform.platform()}")
    try:
        from qgis.PyQt.QtCore import QT_VERSION_STR
        note(f"Qt version            : {QT_VERSION_STR}")
    except Exception:
        pass
    try:
        import qgis.utils
        available = getattr(qgis.utils, "available_plugins", None)
        if available is None:
            note("qgis.utils.available_plugins DOES NOT EXIST — A6 assumed it does")
        else:
            note(f"qgis.utils.available_plugins exists, {len(available)} installed")
    except Exception as exc:
        note(f"qgis.utils could not be inspected: {exc!r}")


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

    _environment()
    _probe_hook_constants()

    processing = _start_processing()
    note(f"Processing initialised, {len(QgsApplication.processingRegistry().algorithms())} "
         f"algorithms available")

    _reset_outputs()
    _reset_database()

    store = ProvenanceStore(scenario.DB_PATH)
    engine = ProvenanceCaptureEngine.start(store)
    hook_dir = scenario.DEMO_ROOT / "_hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)

    undo = []
    try:
        for description, undo_fn in hooks.install_all(engine, hook_dir):
            note(f"installed: {description}")
            undo.append(undo_fn)

        # The third channel (A5). Installed separately because it lives in
        # history_observer.py, not hooks.py — and because whether it can attach
        # at all outside the desktop application is itself a finding.
        from geoprovenance.capture import history_observer
        try:
            for description, undo_fn in history_observer.install_history_observer(engine):
                note(f"installed: {description}")
                undo.append(undo_fn)
        except Exception as exc:
            note(f"history channel could not be installed: {exc!r}")

        print()
        for index, step in enumerate(scenario.STEPS, start=1):
            print(f"  step {index}: {step['algorithm_name']} — {step['plain']}")
            results = processing.run(step["algorithm_id"], dict(step["parameters"]))
            produced = results.get("OUTPUT")
            print(f"           produced {produced}")

        print()
        engine.group_session()
        counts = store.counts()
        channels = store.channel_statistics()
        note(f"jobs recorded         : {counts['activities']}")
        note(f"files known about     : {counts['entities']}")
        note(f"connections drawn     : {counts['relations']}")
        note(f"groups of work        : {counts['workflows']}")
        note(f"per-channel           : {channels}")

        for activity in sorted(store.list_activities_for_session(engine.session_id),
                               key=lambda a: a.get("started_at") or ""):
            note(f"  {activity['algorithm_id']:<32} "
                 f"caught by {activity.get('capture_channel')!r}, "
                 f"confirmed {activity.get('corroborations')} more time(s)")
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
    """Leave the measurements somewhere the coverage table can be filled from.

    RULES.md §8.7 — a number that appears in a document has to trace back to
    something runnable in this repository. This file is that trace.
    """
    target = scenario.DEMO_ROOT / "findings.txt"
    target.write_text("\n".join(FINDINGS) + "\n")
    print()
    print(f"  measurements written to {target.relative_to(scenario.REPO_ROOT)}")


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
