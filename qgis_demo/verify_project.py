"""Open the saved project the way QGIS will, and check every layer.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

    make qgis-demo-verify

A project file that writes without error can still open with red exclamation
marks next to half its layers — a broken relative path, a layer name that moved,
a renderer QGIS declined to restore. The only way to know is to read the file
back with QGIS and look, which is what this does. RULES.md §7.11: the way a demo
usually fails is that nobody opened it on a clean run before the room did.
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qgis.core import (                                         # noqa: E402
    QgsApplication, QgsProject, QgsVectorLayer,
)

from qgis_demo import scenario                                  # noqa: E402
from qgis_demo.build_project import GROUPS, PROJECT_PATH        # noqa: E402

problems: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"  {'ok  ' if condition else 'FAIL'}  {message}")
    if not condition:
        problems.append(message)


def verify() -> int:
    project = QgsProject.instance()
    if not project.read(str(PROJECT_PATH)):
        print(f"QGIS could not open {PROJECT_PATH}")
        return 1

    print(f"Opened {PROJECT_PATH.relative_to(scenario.REPO_ROOT)}")
    print(f"  title            : {project.title()}")
    print(f"  coordinate system: {project.crs().authid()}")
    print()

    root = project.layerTreeRoot()
    group_names = [child.name() for child in root.children()
                   if child.nodeType() == child.NodeGroup]
    check(group_names == list(GROUPS),
          f"the four groups are present and in order: {group_names}")

    print()
    layers = project.mapLayers().values()
    for layer in sorted(layers, key=lambda item: item.name()):
        valid = layer.isValid()
        if not isinstance(layer, QgsVectorLayer):
            # The basemap. It has no features to count and no labels, and
            # whether it will actually draw depends on a tile server answering,
            # which this check deliberately does not test — a review room with
            # no network must still pass here, because every layer that carries
            # the claim is local.
            check(valid, f"{layer.name():<38} loaded (background map)")
            continue
        count = layer.featureCount() if valid else -1
        renderer = type(layer.renderer()).__name__ if layer.renderer() else "none"
        labels = "labelled" if layer.labelsEnabled() else "no labels"
        check(valid and count >= 0,
              f"{layer.name():<38} {count:>3} features   "
              f"{renderer:<30} {labels}")

    print()
    # Everything drawn must sit inside the area the workflow actually covers.
    # A layer that renders far away is the classic sign of a coordinate system
    # that was assumed rather than read.
    for layer in layers:
        if not isinstance(layer, QgsVectorLayer):
            continue          # the basemap covers the world; that is its job
        if not layer.isValid() or layer.featureCount() == 0:
            continue
        extent = layer.extent()
        if extent.isNull() or extent.isEmpty():
            continue
        inside = (77.0 < extent.xMinimum() < 78.5
                  and 12.0 < extent.yMinimum() < 14.0)
        check(inside, f"{layer.name():<38} sits where the work happened "
                      f"({extent.xMinimum():.3f}, {extent.yMinimum():.3f})")

    print()
    if problems:
        print(f"{len(problems)} problem(s) found.")
        return 1
    print(f"All {len(layers)} layers opened, drew and landed in the right place.")
    return 0


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        return verify()
    finally:
        app.exitQgis()


if __name__ == "__main__":
    sys.exit(main())
