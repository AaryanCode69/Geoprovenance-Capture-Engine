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


def _qt_enum(enum_name: str, member: str):
    """One enum member, however this Qt chooses to expose it.

    RULES.md §2.5 — feature-detect, do not assume. Qt 6 scopes enum members
    under their enum type (``Qt.DockWidgetArea.RightDockWidgetArea``) and
    removed the flat spelling; Qt 5 exposes them flat on ``Qt`` itself
    (``Qt.RightDockWidgetArea``). Reading the scoped form first and falling back
    to the flat one covers both, so the plugin loads on a PyQt5 QGIS 3.x and a
    PyQt6 QGIS 4.x without a version test.
    """
    scope = getattr(Qt, enum_name, None)
    if scope is not None:
        value = getattr(scope, member, None)
        if value is not None:
            return value
    return getattr(Qt, member)


DOCK_OBJECT_NAME = "GeoProvenanceDock"
DOCK_TITLE = "GeoProvenance"
DEFAULT_DOCK_AREA = _qt_enum("DockWidgetArea", "RightDockWidgetArea")

_ALIGN_TOP = _qt_enum("AlignmentFlag", "AlignTop")
_ALIGN_LEFT = _qt_enum("AlignmentFlag", "AlignLeft")

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
        self._placeholder.setAlignment(_ALIGN_TOP | _ALIGN_LEFT)
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
