"""Fig. 4 — the GeoProvenance panel, captured from a live QGIS session.

    evaluation/qgis.sh gp-q42 evaluation/figures/panel_shot.py

The real plugin records a two-job chain (Buffer, then Clip) run on copies of the
qgis_demo inputs; the two starting files are then moved away from their
recorded paths, and the panel's own "Check it still holds" is pressed. The
panel is rendered offscreen with QWidget.grab() — no window manager, no
screenshot of a desktop — and its two tabs are placed side by side.
Writes docs/Journal/array/figures/fig_qgis_panel.png and results/panel.json.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

from common import qgis_session  # noqa: E402

WORK = HERE / "work"
OUT = ROOT / "docs" / "Journal" / "array" / "figures" / "fig_qgis_panel.png"


def main() -> int:
    qgis_session.start_qgis()
    shutil.rmtree(WORK, ignore_errors=True)
    data = WORK / "data"
    data.mkdir(parents=True)
    for name in ("roads", "city_boundary"):
        for src in (ROOT / "qgis_demo" / "data").glob(f"{name}.*"):
            shutil.copy2(src, data / src.name)
    boundary = data / "city_boundary.gpkg"
    plugin = qgis_session.load_plugin(WORK / "provenance.db")

    import processing
    from qgis.core import QgsApplication
    from qgis.PyQt.QtCore import QPoint
    from qgis.PyQt.QtGui import QColor, QImage, QPainter

    buffered = WORK / "roads_buffered.gpkg"
    clipped = WORK / "roads_in_city.gpkg"
    processing.run("native:buffer", {"INPUT": str(data / "roads.shp"), "DISTANCE": 0.0045,
                                     "SEGMENTS": 5, "END_CAP_STYLE": 0, "JOIN_STYLE": 0,
                                     "MITER_LIMIT": 2, "DISSOLVE": False, "OUTPUT": str(buffered)})
    processing.run("native:clip", {"INPUT": str(buffered), "OVERLAY": str(boundary), "OUTPUT": str(clipped)})

    moved = WORK / "moved"
    moved.mkdir()
    for f in data.iterdir():
        shutil.move(str(f), moved / f.name)

    from geoprovenance.ui.panel import GeoProvenancePanel

    panel = GeoProvenancePanel(plugin.store)
    panel.resize(620, 560)
    panel.show()
    panel.reload()
    panel._run_audit()  # what the "Check it still holds" button calls
    for _ in range(20):
        QgsApplication.processEvents()
    result = panel._result
    report_tab = panel.grab()
    panel._tabs.setCurrentIndex(0)
    for _ in range(20):
        QgsApplication.processEvents()
    tree_tab = panel.grab()

    gap = 16
    image = QImage(tree_tab.width() + report_tab.width() + gap,
                   max(tree_tab.height(), report_tab.height()), QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.drawPixmap(QPoint(0, 0), tree_tab)
    painter.drawPixmap(QPoint(tree_tab.width() + gap, 0), report_tab)
    painter.end()
    image.save(str(OUT))

    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "panel.json").write_text(json.dumps({
        "versions": qgis_session.versions(),
        "score": result.overall, "band": result.band, "components": result.components,
        "excluded": [n for n, v in result.components.items() if v is None],
        "report": panel._report.toPlainText(),
    }, indent=2) + "\n")
    print(result.overall, result.band, result.components)
    plugin.unload()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
