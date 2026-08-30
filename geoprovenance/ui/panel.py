"""The workflow panel: a family tree of files, and a score beside it.

Owner: Person C (README "Person C — Visualization & Reproducibility Audit").
Written by Person A under the explicit written override of RULES.md §1.2 [HARD]
requested on 30 Aug 2026, so that the workflow section could be demonstrated.
Person C owns this file; A owns nothing in it.

This is the ONLY half of Person C's work that needs Qt. Where every node sits is
decided in `ui/layout.py`, and what colour it is comes from `geoprovenance.audit`
— both of which import no Qt and are covered by `make test`. What is left here
is drawing, which is the part that genuinely cannot be checked without a
running Qt.

    Qt 5 and Qt 6 both. Enum members moved under their enum type in Qt 6 and the
    flat spelling was removed, which on QGIS 4 stops a plugin loading outright
    (CLAUDE.md records exactly that happening to `Qt.RightDockWidgetArea`).
    `_qt_enum` in ui/dock.py solves that for the dock, but it cannot be reused
    here: it hardcodes `Qt` as the owner, and the members this file needs are
    owned by other classes — `RenderHint` by QPainter, `DragMode` by
    QGraphicsView. Asking `Qt` for either raises on both bindings. `_member`
    below takes the owner as an argument for that reason, and every enum member
    in this file goes through it (RULES.md §2.5).

    The version that did import `_qt_enum` imported cleanly and threw only when
    the panel was constructed, so an import-only check passed it straight
    through. That is why tests/capture/test_panel.py builds the widget.

Installs itself through the seam agreed at the A1 exit gate:

    dock.set_content(GeoProvenancePanel(store))
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import audit
from ..log import INFO, log, log_exception
from ..prov import ProvGraph
from . import layout as L

try:  # QPointF moved package between bindings generations in some builds
    from qgis.PyQt.QtCore import QPointF
except ImportError:  # pragma: no cover - defensive, per §2.5
    from qgis.PyQt.QtGui import QPointF


def _member(owner, enum_name: str, member: str):
    """One enum member, however this Qt exposes it — and off the RIGHT class.

    ui/dock.py has the same idea but hardcodes Qt as the owner, and only some of
    these enums live there. RenderHint belongs to QPainter and DragMode to
    QGraphicsView; asking Qt for either raises AttributeError on BOTH bindings,
    so the dock's helper cannot be reused here.

    Found the hard way. The Qt-only version imported perfectly and then threw
    when the panel was actually built — which would have been a blank dock in
    the review room rather than a failed import somebody noticed (RULES.md
    §2.5: feature-detect, and detect it on the class that owns the feature).
    """
    scope = getattr(owner, enum_name, None)
    if scope is not None and hasattr(scope, member):
        return getattr(scope, member)   # Qt 6: scoped under the enum type
    return getattr(owner, member)       # Qt 5: flat on the owning class

#: Geometry of the drawing, in scene units. Fixed rather than measured from the
#: text: a label is elided to fit, which keeps the picture readable when an
#: algorithm has a long name and keeps the layout honest about its own size.
BOX_W, BOX_H = 170, 38
COL_GAP, ROW_GAP = 200, 86

#: research doc §4.3 Layer 4 — "colour coding for status (verified/changed/
#: missing)". Chosen to stay distinguishable for the commonest colour vision
#: deficiency: the amber and the green differ in lightness as well as in hue,
#: and every node also carries the status in its tooltip as words.
_STATUS_COLOUR = {
    audit.VERIFIED: "#2e7d32",
    audit.CHANGED: "#ef6c00",
    audit.MISSING: "#c62828",
    L.UNKNOWN: "#78909c",
}

_STATUS_WORDS = {
    audit.VERIFIED: "unchanged since it was recorded",
    audit.CHANGED: "this file has changed since it was recorded",
    audit.MISSING: "this file is no longer where we left it",
    L.UNKNOWN: "not checked yet",
}


def _pen(colour: str, width: int = 2, dashed: bool = False) -> QPen:
    pen = QPen(QColor(colour))
    pen.setWidth(width)
    if dashed:
        pen.setStyle(_member(Qt, "PenStyle", "DashLine"))
    return pen


class WorkflowScene(QGraphicsScene):
    """One workflow, drawn. Files are rectangles, jobs are circles."""

    def draw(self, plan: L.Layout) -> None:
        self.clear()
        if not plan.nodes:
            self.addText("Nothing recorded for this piece of work yet.")
            return

        centres: dict[str, QPointF] = {}
        for node in plan.nodes:
            x = node.column * COL_GAP
            y = node.rank * ROW_GAP
            centres[node.id] = QPointF(x + BOX_W / 2, y + BOX_H / 2)

        # Edges first, so a node is never drawn under its own connections.
        for edge in plan.edges:
            if edge.source not in centres or edge.target not in centres:
                continue
            self._draw_edge(centres[edge.source], centres[edge.target], edge)

        for node in plan.nodes:
            self._draw_node(node)

    # -- pieces ------------------------------------------------------------

    def _draw_edge(self, start: QPointF, end: QPointF, edge: L.Edge) -> None:
        derived = edge.kind == L.DERIVED
        colour = "#90a4ae" if derived else "#455a64"
        self.addLine(start.x(), start.y(), end.x(), end.y(),
                     _pen(colour, 1 if derived else 2, dashed=derived))
        if not derived:
            # A derivation runs alongside the job links it was inferred from, so
            # a second arrowhead on the same path is noise, not information.
            self._draw_arrow(start, end, colour)
        if edge.label:
            label = self.addText(edge.label)
            label.setDefaultTextColor(QColor("#607d8b"))
            font = label.font()
            font.setPointSize(7)
            label.setFont(font)
            label.setPos((start.x() + end.x()) / 2 + 4, (start.y() + end.y()) / 2 - 10)

    def _draw_arrow(self, start: QPointF, end: QPointF, colour: str) -> None:
        """A small head, stopped short of the target so it sits on the border."""
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1:
            return
        ux, uy = dx / length, dy / length
        tip_x, tip_y = end.x() - ux * (BOX_H / 2 + 2), end.y() - uy * (BOX_H / 2 + 2)
        size = 7
        head = QPolygonF([
            QPointF(tip_x, tip_y),
            QPointF(tip_x - ux * size + uy * size * 0.5,
                    tip_y - uy * size - ux * size * 0.5),
            QPointF(tip_x - ux * size - uy * size * 0.5,
                    tip_y - uy * size + ux * size * 0.5),
        ])
        self.addPolygon(head, _pen(colour, 1), QBrush(QColor(colour)))

    def _draw_node(self, node: L.Node) -> None:
        x, y = node.column * COL_GAP, node.rank * ROW_GAP
        colour = _STATUS_COLOUR.get(node.status, _STATUS_COLOUR[L.UNKNOWN])

        if node.kind == L.FILE:
            path = QPainterPath()
            path.addRoundedRect(x, y, BOX_W, BOX_H, 6, 6)
            shape = self.addPath(path, _pen(colour), QBrush(QColor("#ffffff")))
        else:
            shape = self.addEllipse(x, y, BOX_W, BOX_H,
                                    _pen("#37474f"), QBrush(QColor("#eceff1")))

        what = "file" if node.kind == L.FILE else "job QGIS ran"
        shape.setToolTip(
            f"{node.label}\n{what}\n{node.detail}\n"
            f"{_STATUS_WORDS.get(node.status, '')}".strip()
        )

        text = self.addText(_elide(node.label, 24))
        font = QFont()
        font.setPointSize(8)
        if node.kind == L.JOB:
            font.setBold(True)
        text.setFont(font)
        text.setDefaultTextColor(QColor("#212121"))
        bounds = text.boundingRect()
        text.setPos(x + (BOX_W - bounds.width()) / 2,
                    y + (BOX_H - bounds.height()) / 2)
        text.setToolTip(shape.toolTip())


def _elide(label: str, limit: int) -> str:
    return label if len(label) <= limit else label[: limit - 1] + "…"


class GeoProvenancePanel(QWidget):
    """Pick a piece of work; see how its files relate, and whether it still holds.

    Reads through `ProvenanceStore` only — RULES.md §1.3, Person C never runs
    SQL. Every button is wrapped: a panel that throws inside QGIS is a panel
    that takes the message log with it, and §5.1's reasoning applies to anything
    living in the same process as the user's real work.
    """

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store
        self._result: audit.AuditResult | None = None

        self._picker = QComboBox(self)
        self._picker.currentIndexChanged.connect(self._show_selected)

        self._refresh = QPushButton("Refresh", self)
        self._refresh.clicked.connect(self.reload)
        self._check = QPushButton("Check it still holds", self)
        self._check.clicked.connect(self._run_audit)

        top = QHBoxLayout()
        top.addWidget(self._picker, 1)
        top.addWidget(self._refresh)

        self._scene = WorkflowScene(self)
        view = QGraphicsView(self._scene, self)
        view.setRenderHint(_member(QPainter, "RenderHint", "Antialiasing"))
        view.setDragMode(_member(QGraphicsView, "DragMode", "ScrollHandDrag"))

        self._report = QPlainTextEdit(self)
        self._report.setReadOnly(True)
        self._report.setFont(QFont("monospace"))

        self._tabs = QTabWidget(self)
        self._tabs.addTab(view, "How the files relate")
        self._tabs.addTab(self._report, "Can we run it again?")

        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 6, 6)
        box.addLayout(top)
        box.addWidget(self._tabs, 1)
        box.addWidget(self._check)
        box.addWidget(self._status)

        self.reload()

    # -- public ------------------------------------------------------------

    def reload(self) -> None:
        """Re-read the list of recorded work. Keeps the current choice if it survives."""
        try:
            wanted = self._picker.currentData()
            self._picker.blockSignals(True)
            self._picker.clear()
            for workflow in self._store.list_workflows():
                steps = workflow["activity_count"]
                plural = "" if steps == 1 else "s"
                self._picker.addItem(f"{workflow['name']}  ({steps} job{plural})",
                                     workflow["id"])
            self._picker.blockSignals(False)

            if self._picker.count() == 0:
                self._scene.clear()
                self._report.setPlainText("")
                self._status.setText(
                    "Nothing recorded yet. Run something in QGIS and it will "
                    "appear here."
                )
                return

            index = self._picker.findData(wanted)
            self._picker.setCurrentIndex(max(index, 0))
            self._show_selected()
        except Exception as exc:  # noqa: BLE001 — a panel reports, it never throws
            self._fail("could not read the recorded work", exc)

    def current_workflow_id(self) -> str | None:
        return self._picker.currentData() if self._picker.count() else None

    # -- internals ---------------------------------------------------------

    def _show_selected(self) -> None:
        workflow_id = self.current_workflow_id()
        if workflow_id is None:
            return
        try:
            graph = ProvGraph.load(self._store, workflow_id)
            statuses = (
                self._result.file_status
                if self._result and self._result.workflow_id == workflow_id
                else None
            )
            self._scene.draw(L.build_layout(graph, statuses=statuses))
            if statuses is None:
                self._report.setPlainText(
                    'Not checked yet. Press "Check it still holds".'
                )
            self._status.setText(
                f"{len(graph.activities)} job(s), {len(graph.entities)} file(s)."
            )
        except Exception as exc:  # noqa: BLE001
            self._fail("could not draw this piece of work", exc)

    def _run_audit(self) -> None:
        workflow_id = self.current_workflow_id()
        if workflow_id is None:
            return
        try:
            self._status.setText("Checking every file…")
            self._result = audit.audit_workflow(self._store, workflow_id)
            audit.persist(self._store, self._result)
            self._report.setPlainText(audit.report(self._result))
            self._show_selected()
            self._tabs.setCurrentIndex(1)
            self._status.setText(
                f"Score {self._result.overall:.0f} out of 100 "
                f"({self._result.band.lower()})."
            )
            log(f"audited workflow {workflow_id}: {self._result.overall}", INFO)
        except Exception as exc:  # noqa: BLE001
            self._fail("could not check this piece of work", exc)

    def _fail(self, what: str, exc: Exception) -> None:
        log_exception(f"GeoProvenance panel — {what}", exc)
        self._status.setText(f"Sorry — {what}. The details are in the message log.")
