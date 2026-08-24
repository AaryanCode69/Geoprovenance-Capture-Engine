"""Assemble the styled QGIS project. The one part of the demo that needs QGIS.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

    make qgis-demo-project

Writes ``qgis_demo/project/GeoProvenance.qgz``.

Why this uses QGIS rather than writing project XML by hand
    A ``.qgz`` is a zip around a large XML document describing every layer,
    renderer, label rule and layout item. Hand-writing it is possible and is a
    reliable way to produce a file that *almost* opens. Building it with
    ``QgsProject`` means QGIS itself writes the format it will later read, so
    the styling is either applied or it raises here, on this machine, rather
    than looking wrong in a review room.

    This mirrors how the rest of the project is arranged: the part that can be
    wrong (``export_layers.py``, which decides what goes where) imports no QGIS
    and runs anywhere; this is the thin adapter that only decorates.

Plain language
    Every group name, layer name and legend entry a reviewer reads is written in
    ordinary words. RULES.md §7.5 bans the internal vocabulary from anything a
    reviewer looks at, and a layer panel is the first thing they look at.
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qgis.core import (                                       # noqa: E402
    QgsApplication, QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem,
    QgsFillSymbol, QgsLayerTreeGroup, QgsLayerTreeLayer, QgsLineSymbol,
    QgsLayoutExporter, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap,
    QgsLayoutItemScaleBar, QgsLayoutPoint, QgsLayoutSize, QgsMarkerSymbol,
    QgsPalLayerSettings, QgsPrintLayout, QgsProject, QgsRectangle,
    QgsReferencedRectangle, QgsRendererCategory, QgsSingleSymbolRenderer,
    QgsTextFormat, QgsUnitTypes, QgsVectorLayer, QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont                     # noqa: E402

from qgis_demo import scenario                                # noqa: E402

PROJECT_PATH = scenario.PROJECT_DIR / "GeoProvenance.qgz"
MAP_GPKG = scenario.PROJECT_DIR / "provenance_map.gpkg"

# One colour per capture channel. These three are the RQ1 story: which of the
# ways we watch QGIS actually noticed each job.
CHANNEL_COLOURS = {
    "QGIS told us the moment it finished": "#1B7F3B",
    "we were wrapped around the command": "#1F6FB2",
    "we spotted it in the QGIS history list": "#B26A00",
    "not recorded": "#8A8A8A",
}

PRESENT_COLOUR = "#2E7D32"
MISSING_COLOUR = "#B3261E"


def _uri(gpkg: pathlib.Path, layer: str) -> str:
    return f"{gpkg}|layername={layer}"


def _load(gpkg: pathlib.Path, layer_name: str, title: str) -> QgsVectorLayer:
    layer = QgsVectorLayer(_uri(gpkg, layer_name), title, "ogr")
    if not layer.isValid():
        raise SystemExit(f"QGIS could not open {layer_name} from {gpkg}")
    return layer


def _load_file(path: pathlib.Path, title: str) -> QgsVectorLayer | None:
    """Load an input dataset, or return None and say so if it is not there."""
    if not path.exists():
        print(f"  note: {path.name} is not on disk — leaving it out of the project")
        return None
    layer = QgsVectorLayer(str(path), title, "ogr")
    if not layer.isValid():
        print(f"  note: QGIS could not open {path.name} — leaving it out")
        return None
    return layer


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

def _categorised(layer: QgsVectorLayer, field: str,
                 colours: dict[str, str], symbol_maker) -> None:
    """Colour a layer by the values actually present in one of its columns."""
    values = sorted({str(f[field]) for f in layer.getFeatures()
                     if f[field] is not None})
    categories = []
    for value in values:
        symbol = symbol_maker(colours.get(value, "#8A8A8A"))
        categories.append(QgsRendererCategory(value, symbol, value))
    if categories:
        layer.setRenderer(QgsCategorizedSymbolRenderer(field, categories))


def _marker(colour: str, size: float = 4.2) -> QgsMarkerSymbol:
    return QgsMarkerSymbol.createSimple({
        "name": "circle", "color": colour, "size": str(size),
        "outline_color": "#FFFFFF", "outline_width": "0.5",
    })


def _outline_fill(colour: str, width: str = "0.7",
                  style: str = "no") -> QgsFillSymbol:
    return QgsFillSymbol.createSimple({
        "color": colour, "style": style,
        "outline_color": colour, "outline_width": width,
    })


def _text_format(size: float, colour: str, bold: bool = False,
                 halo: bool = False) -> QgsTextFormat:
    text = QgsTextFormat()
    font = QFont("Sans Serif")
    font.setBold(bold)
    text.setFont(font)
    text.setSize(size)
    text.setColor(QColor(colour))
    if halo:
        # A white halo is what keeps a label readable over a filled polygon.
        buffer = text.buffer()
        buffer.setEnabled(True)
        buffer.setSize(1.0)
        buffer.setColor(QColor("#FFFFFF"))
        text.setBuffer(buffer)
    return text


def _label(layer: QgsVectorLayer, expression: str, size: float = 9.0,
           colour: str = "#1A1A1A", bold: bool = False,
           around_point: bool = False) -> None:
    settings = QgsPalLayerSettings()
    settings.fieldName = expression
    settings.isExpression = True
    settings.setFormat(_text_format(size, colour, bold, halo=True))
    if around_point:
        # Four job markers sit close together by nature. Letting QGIS place
        # each label on whichever side is free is what keeps them all readable.
        settings.placement = QgsPalLayerSettings.Placement.AroundPoint
        settings.dist = 2.0
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def style_work_areas(layer: QgsVectorLayer) -> None:
    symbol = QgsFillSymbol.createSimple({
        "color": "31,111,178,26", "style": "solid",
        "outline_color": "#1F6FB2", "outline_width": "0.9",
        "outline_style": "dash",
    })
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    _label(layer, '"group_name"', size=11.0, colour="#1F6FB2", bold=True)


def style_files(layer: QgsVectorLayer) -> None:
    _categorised(layer, "still_on_disk",
                 {"yes": PRESENT_COLOUR, "no": MISSING_COLOUR},
                 lambda c: _outline_fill(c, width="0.26"))
    renderer = layer.renderer()
    for index in range(renderer.categories().__len__()):
        category = renderer.categories()[index]
        readable = ("still on this computer" if category.value() == "yes"
                    else "not on this computer any more")
        renderer.updateCategoryLabel(index, readable)
    # Seven nested rectangles with seven labels on top of each other is not a
    # map anybody can read. The rectangles stay — clicking one is how a
    # reviewer inspects a file — but the labels start switched off and the
    # outlines are thin, so the data underneath stays visible.
    _label(layer, '"file_name"', size=8.0, colour="#2E7D32")
    layer.setLabelsEnabled(False)


def style_jobs(layer: QgsVectorLayer) -> None:
    _categorised(layer, "how_we_noticed", CHANNEL_COLOURS,
                 lambda c: _marker(c, size=5.0))
    _label(layer, '\'Step \' || "step_number" || \': \' || "what_ran"',
           size=9.0, colour="#1A1A1A", bold=True, around_point=True)


def style_roads(layer: QgsVectorLayer) -> None:
    symbol = QgsLineSymbol.createSimple({"color": "#5A5A5A", "width": "0.6"})
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    _label(layer, '"name"', size=8.0, colour="#5A5A5A")


def style_boundary(layer: QgsVectorLayer) -> None:
    symbol = QgsFillSymbol.createSimple({
        "color": "0,0,0,0", "style": "no",
        "outline_color": "#333333", "outline_width": "0.9",
    })
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def style_schools(layer: QgsVectorLayer) -> None:
    symbol = _marker("#7B1FA2", size=2.8)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def style_results(layer: QgsVectorLayer, colour: str, fill: bool) -> None:
    if layer.geometryType() == 0:      # points
        symbol = _marker(colour, size=3.4)
    elif layer.geometryType() == 1:    # lines
        symbol = QgsLineSymbol.createSimple({"color": colour, "width": "0.6"})
    else:
        rgba = QColor(colour)
        rgba.setAlpha(60)
        symbol = QgsFillSymbol.createSimple({
            "color": f"{rgba.red()},{rgba.green()},{rgba.blue()},{rgba.alpha()}",
            "style": "solid" if fill else "no",
            "outline_color": colour, "outline_width": "0.5",
        })
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


# ---------------------------------------------------------------------------
# The printable page
# ---------------------------------------------------------------------------

LAYOUT_NAME = "What QGIS did, and how we knew"


def _text(layout, text, x, y, width, height, size, bold=False, colour="#1A1A1A"):
    label = QgsLayoutItemLabel(layout)
    label.setText(text)
    # setFont/setFontColor were deprecated in favour of setTextFormat in QGIS
    # 3.24; the plugin's floor is 3.28, so the newer call is always available.
    label.setTextFormat(_text_format(size, colour, bold))
    layout.addLayoutItem(label)
    label.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    label.attemptResize(QgsLayoutSize(width, height, QgsUnitTypes.LayoutMillimeters))
    return label


def build_layout(project: QgsProject, extent: QgsRectangle, summary: dict) -> None:
    """One A4 page a reviewer can be handed, with no QGIS on the table.

    Everything on it is written in ordinary words (RULES.md §7.5) and every
    number on it comes from the record, not from a note somebody typed.
    """
    manager = project.layoutManager()
    for existing in manager.printLayouts():
        if existing.name() == LAYOUT_NAME:
            manager.removeLayout(existing)

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(LAYOUT_NAME)

    _text(layout, "Where this data came from", 12, 8, 190, 12, 20, bold=True)
    _text(layout,
          "QGIS ran four jobs. Nobody wrote any of this down by hand \u2014 the "
          "record below was made automatically, while the work was happening.",
          12, 20, 190, 10, 9.5, colour="#555555")

    map_item = QgsLayoutItemMap(layout)
    layout.addLayoutItem(map_item)
    map_item.attemptMove(QgsLayoutPoint(12, 32, QgsUnitTypes.LayoutMillimeters))
    map_item.attemptResize(QgsLayoutSize(140, 118, QgsUnitTypes.LayoutMillimeters))
    padded = QgsRectangle(extent)
    padded.scale(1.12)
    map_item.setExtent(padded)
    map_item.setFrameEnabled(True)

    legend = QgsLayoutItemLegend(layout)
    legend.setLinkedMap(map_item)
    legend.setTitle("What you are looking at")
    layout.addLayoutItem(legend)
    legend.attemptMove(QgsLayoutPoint(157, 32, QgsUnitTypes.LayoutMillimeters))
    legend.attemptResize(QgsLayoutSize(46, 118, QgsUnitTypes.LayoutMillimeters))

    scale = QgsLayoutItemScaleBar(layout)
    scale.setLinkedMap(map_item)
    scale.applyDefaultSettings()
    layout.addLayoutItem(scale)
    scale.setNumberOfSegments(2)
    scale.setNumberOfSegmentsLeft(0)
    # Do NOT set unitsPerSegment here. The project is in degrees, so the number
    # is read as degrees per segment and a value chosen as if it were metres
    # produces a bar wider than the page. applyDefaultSize works it out from
    # the linked map instead. A smaller label font is what stops the numbers
    # colliding.
    scale.setTextFormat(_text_format(7.5, "#444444"))
    scale.applyDefaultSize()
    scale.update()
    scale.attemptMove(QgsLayoutPoint(12, 155, QgsUnitTypes.LayoutMillimeters))

    _text(layout, (
        f"Jobs QGIS ran that we noticed : {summary['jobs']}\n"
        f"Files we are keeping track of : {summary['files']}\n"
        f"Files we could draw on the map: {summary['files_drawn']}\n"
        f"Files we knew about but could not place: {summary['files_not_drawn']}\n"
        f"Computers this work ran on    : {summary['machines']}"
    ), 12, 170, 190, 34, 9.5)

    manager.addLayout(layout)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

#: Numbered so the panel keeps the order of the story, worded so a reviewer who
#: has never opened QGIS knows what each group is (RULES.md §7.5).
GROUPS = (
    "1 - What we started with",
    "2 - What QGIS produced",
    "3 - What we noticed, automatically",
    "4 - Where the record has gaps",
)


def _group(project: QgsProject, name: str) -> QgsLayerTreeGroup:
    return project.layerTreeRoot().addGroup(name)


def _add(project: QgsProject, group: QgsLayerTreeGroup,
         layer: QgsVectorLayer | None, visible: bool = True) -> None:
    if layer is None:
        return
    project.addMapLayer(layer, False)
    node = group.addLayer(layer)
    node.setItemVisibilityChecked(visible)


def build(project_path: pathlib.Path = PROJECT_PATH) -> pathlib.Path:
    if not MAP_GPKG.exists():
        raise SystemExit(
            f"no map layers at {MAP_GPKG} — run 'make qgis-demo-layers' first")

    project = QgsProject.instance()
    project.clear()
    project.setCrs(QgsCoordinateReferenceSystem(scenario.CRS))
    project.setTitle("GeoProvenance - what QGIS did, and how we knew")

    # --- 1. the inputs the workflow started from --------------------------
    started_with = _group(project, GROUPS[0])
    boundary = _load_file(scenario.BOUNDARY_GPKG, "City boundary")
    roads = _load_file(scenario.ROADS_SHP, "Roads")
    schools = _load_file(scenario.SCHOOLS_SHP, "Schools")
    for layer, styler in ((boundary, style_boundary), (roads, style_roads),
                          (schools, style_schools)):
        if layer is not None:
            styler(layer)
    _add(project, started_with, schools)
    _add(project, started_with, roads)
    _add(project, started_with, boundary)

    # --- 2. what the four steps actually produced -------------------------
    produced = _group(project, GROUPS[1])
    # Points first, so they draw on top. A filled corridor added above them
    # hides the very features the last two steps were about.
    outputs = (
        (scenario.SCHOOLS_NEAR_ROADS, "Step 3 - schools near a road", "#D81B60", False),
        (scenario.ROAD_CORRIDOR, "Step 4 - one road corridor", "#8E24AA", True),
        (scenario.ROADS_IN_CITY, "Step 2 - bands, cut to the city", "#00897B", True),
        (scenario.ROADS_BUFFERED, "Step 1 - bands around every road", "#F9A825", True),
    )
    for path, title, colour, fill in outputs:
        layer = _load_file(path, title)
        if layer is not None:
            style_results(layer, colour, fill)
        _add(project, produced, layer)

    # --- 3. the record itself, drawn on the map ---------------------------
    noticed = _group(project, GROUPS[2])
    jobs = _load(MAP_GPKG, "jobs_qgis_ran", "Jobs QGIS ran")
    files = _load(MAP_GPKG, "files_we_track", "Files we are keeping track of")
    areas = _load(MAP_GPKG, "work_areas", "One piece of work")
    style_jobs(jobs)
    style_files(files)
    style_work_areas(areas)
    _add(project, noticed, jobs)
    _add(project, noticed, files)
    _add(project, noticed, areas)

    # --- 4. the honest gaps ----------------------------------------------
    gaps = _group(project, GROUPS[3])
    _add(project, gaps, _load(MAP_GPKG, "files_with_no_place_on_the_map",
                              "Files we know about but cannot draw"))
    _add(project, gaps, _load(MAP_GPKG, "the_computer_it_ran_on",
                              "The computer and software it ran on"))

    _zoom_to(project, areas)

    nowhere = project.mapLayersByName("Files we know about but cannot draw")
    machines = project.mapLayersByName("The computer and software it ran on")
    build_layout(project, areas.extent(), {
        "jobs": jobs.featureCount(),
        "files": files.featureCount() + (nowhere[0].featureCount() if nowhere else 0),
        "files_drawn": files.featureCount(),
        "files_not_drawn": nowhere[0].featureCount() if nowhere else 0,
        "machines": machines[0].featureCount() if machines else 0,
    })

    project_path.parent.mkdir(parents=True, exist_ok=True)
    if not project.write(str(project_path)):
        raise SystemExit(f"QGIS refused to write {project_path}")
    _export_overview(project, project_path.parent / "overview.png")
    return project_path


def _export_overview(project: QgsProject, image_path: pathlib.Path) -> None:
    """Render the page to an image as well as saving it.

    So the demo has something to show on a slide, in a document, or on a
    machine with no QGIS on it at all — the printable page is the artefact that
    survives a review room with a broken projector (RULES.md §7.12).
    """
    layouts = [l for l in project.layoutManager().printLayouts()
               if l.name() == LAYOUT_NAME]
    if not layouts:
        return
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = 130
    result = QgsLayoutExporter(layouts[0]).exportToImage(str(image_path), settings)
    if result == QgsLayoutExporter.Success:
        print(f"  wrote {image_path.relative_to(scenario.REPO_ROOT)}")
    else:
        print(f"  note: the printable page did not render (code {result})")


def _zoom_to(project: QgsProject, layer: QgsVectorLayer) -> None:
    """Save the view so the project opens looking at the right place."""
    extent = QgsRectangle(layer.extent())
    extent.scale(1.15)
    project.viewSettings().setDefaultViewExtent(
        QgsReferencedRectangle(extent, QgsCoordinateReferenceSystem(scenario.CRS)))


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        path = build()
    finally:
        app.exitQgis()

    print(f"  wrote {path.relative_to(scenario.REPO_ROOT)}")
    print()
    print("  Open it with:  make qgis-demo-open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
