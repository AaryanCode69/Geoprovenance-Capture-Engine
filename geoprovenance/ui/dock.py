"""The dock widget placeholder.

Owner: Person A (the shell).  Sub-phase: A1.
Filled by: Person C (everything inside it).

    ┌────────────────────────────────────────────────────────────────┐
    │  THE AGREED NAMES — Person C builds against these (A1 exit).   │
    │                                                                │
    │      module      geoprovenance.ui.dock                         │
    │      class       GeoProvenanceDockWidget                       │
    │      objectName  "GeoProvenanceDock"                           │
    │      seam        dock.set_content(your_widget)                 │
    │                                                                │
    │  RULES.md §1.5 — these are public API. Renaming one is a       │
    │  breaking change to Person C's work and follows §3.4.          │
    │                                                                │
    │  objectName is fixed because QGIS persists dock geometry and   │
    │  visibility against it; changing it silently resets every      │
    │  user's panel layout.                                          │
    └────────────────────────────────────────────────────────────────┘

Person C: call ``set_content()`` once with your top-level widget — the DAG
viewer, an audit panel, a QTabWidget holding both, whatever you decide. The
internal structure is yours. This class only guarantees you a dock that QGIS
has registered, that survives load/unload cleanly, and that is placed in the
right dock area.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDockWidget, QLabel, QVBoxLayout, QWidget

DOCK_OBJECT_NAME = "GeoProvenanceDock"
DOCK_TITLE = "GeoProvenance"
DEFAULT_DOCK_AREA = Qt.RightDockWidgetArea

_PLACEHOLDER_TEXT = (
    "<b>GeoProvenance</b><br><br>"
    "No workflow to show yet.<br><br>"
    "<span style='color:#888'>Run a Processing algorithm and its record will "
    "appear here.</span>"
)


class GeoProvenanceDockWidget(QDockWidget):
    """The panel shell. Empty until Person C installs content."""

    def __init__(self, parent=None):
        super().__init__(DOCK_TITLE, parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self._container = QWidget(self)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)

        self._placeholder = QLabel(_PLACEHOLDER_TEXT, self._container)
        self._placeholder.setWordWrap(True)
        self._placeholder.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._layout.addWidget(self._placeholder)

        self._content: QWidget | None = None
        self.setWidget(self._container)

    # -- the seam Person C uses -------------------------------------------

    def set_content(self, widget: QWidget) -> None:
        """Install Person C's widget, replacing the placeholder.

        Calling this again replaces the previous content, so a rebuild after a
        new capture does not stack widgets on top of each other.
        """
        self.clear_content()
        self._placeholder.hide()
        self._content = widget
        widget.setParent(self._container)
        self._layout.addWidget(widget)

    def clear_content(self) -> None:
        """Remove Person C's widget and show the placeholder again."""
        if self._content is not None:
            self._layout.removeWidget(self._content)
            self._content.setParent(None)
            self._content.deleteLater()
            self._content = None
        self._placeholder.show()

    def content(self) -> QWidget | None:
        return self._content
