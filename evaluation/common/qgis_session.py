"""Headless QGIS with the real GeoProvenance plugin loaded — for the evaluation.

Every live measurement in `evaluation/` starts here, so the plugin is exercised
through `plugin.py` itself — initGui, the four channels, the registry snapshot
and the hook probe — rather than through a hand-assembled copy of its wiring.

    QGIS runs with an offscreen Qt platform and pytest-qgis's stub interface
    (the same one `tests/capture/test_plugin_lifecycle.py` uses), and the
    database path is redirected the way those tests redirect it.

Run with a QGIS environment's own Python, e.g.:
    evaluation/qgis.sh gp-q42 evaluation/case_cuddalore/run_in_qgis.py
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import Qgis, QgsApplication  # noqa: E402

_APP = None


def start_qgis() -> QgsApplication:
    """One QgsApplication per process, with Processing initialised."""
    global _APP
    if _APP is not None:
        return _APP
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", sys.prefix), True)
    _APP = QgsApplication([], True)
    _APP.initQgis()
    from processing.core.Processing import Processing

    Processing.initialize()
    return _APP


def make_iface():
    """pytest-qgis's stub QgisInterface, installed as qgis.utils.iface."""
    from pytest_qgis.mock_qgis_classes import MockMessageBar
    from pytest_qgis.qgis_interface import QgisInterface
    from qgis.gui import QgsMapCanvas
    from qgis.PyQt.QtWidgets import QMainWindow
    import qgis.utils

    # On QGIS 3.34 (PyQt5) the stub's @pyqtSlot("QList<QgsMapLayer*>") cannot
    # be matched to QgsProject.layersAdded outside pytest; connected as a plain
    # callable it behaves the same.
    if hasattr(QgisInterface.addLayers, "__pyqtSignature__"):
        try:
            del QgisInterface.addLayers.__pyqtSignature__
        except (AttributeError, TypeError):
            pass
    window = QMainWindow()
    canvas = QgsMapCanvas(window)
    iface = QgisInterface(canvas, MockMessageBar(), window)
    # The stub's layer tree is a MagicMock, which QGIS's own result handling
    # (adding output layers to the project) rejects; give it a real one.
    from qgis.core import QgsLayerTreeModel, QgsProject
    from qgis.gui import QgsLayerTreeView

    tree = QgsLayerTreeView(window)
    tree.setModel(QgsLayerTreeModel(QgsProject.instance().layerTreeRoot(), tree))
    iface.layerTreeView = lambda: tree
    from qgis.gui import QgsBrowserGuiModel

    browser = QgsBrowserGuiModel(window)
    iface.browserModel = lambda: browser
    qgis.utils.iface = iface
    # Processing modules did `from qgis.utils import iface` when they were
    # imported, before this stub existed; point their copies at it too.
    for name, module in list(sys.modules.items()):
        if name.startswith("processing") and getattr(module, "iface", 0) is None:
            module.iface = iface
    return iface


def load_plugin(db_path: pathlib.Path):
    """The real plugin, initGui'd, writing to ``db_path``. Returns the plugin."""
    from geoprovenance import paths
    from geoprovenance.plugin import GeoProvenancePlugin

    db_path = pathlib.Path(db_path)
    paths.resolve_db_path = lambda override=None, settings=None: db_path
    plugin = GeoProvenancePlugin(make_iface())
    plugin.initGui()
    if plugin.engine is None:
        raise RuntimeError("the plugin did not start capture — see the log")
    return plugin


def versions() -> dict[str, str]:
    from geoprovenance.capture import environment

    probe = environment.probe()
    probe.pop("plugin_versions", None)
    probe["qgis_version_full"] = Qgis.QGIS_VERSION
    from qgis.PyQt.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    probe["qt_version"] = QT_VERSION_STR
    probe["pyqt_version"] = PYQT_VERSION_STR
    return probe
