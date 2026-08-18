"""Plugin lifecycle: load, unload, menu, toolbar, dock registration.

Owner: Person A.  Sub-phase: A1.

Responsibilities
    - Register the menu actions, toolbar button, and the dock widget shell that
      Person C will fill (agreed names in geoprovenance/ui/dock.py).
    - Mint the session UUID at startup (RULES.md §3.2 decision 5) — every
      activity captured in this QGIS session carries it, which is what makes
      A6's workflow auto-grouping possible without asking the user to declare
      workflow boundaries.
    - Resolve the database location and open the ProvenanceStore. The default
      comes from QgsApplication.qgisSettingsDirPath(), which is why it lives in
      geoprovenance/paths.py and not in storage/ (§4.1, §4.8).

Critical rules
    §5.4 [HARD]  unload() must disconnect every signal, stop every QTimer,
                 un-patch every monkeypatch, close the database connection and
                 restore the user's POST_EXECUTION_SCRIPT. Load -> unload ->
                 load must leave no residue and log no errors.

                 Enforced structurally rather than by memory: every setup step
                 registers its own undo on self._cleanup the moment it
                 succeeds, and unload() unwinds the stack in reverse. Adding a
                 setup step without its undo is then a visible omission on the
                 same line, not a silent one forty lines away.

    §5.1 [HARD]  initGui() must not raise into QGIS. A plugin that throws
                 during load leaves QGIS in a half-initialised state and blames
                 us in a modal dialog. Failures are logged; the plugin comes up
                 degraded rather than not at all.

Not in A1 (deliberate seams)
    §5.3  Installing the post-execution hook and saving/restoring the user's
          ProcessingConfig POST_EXECUTION_SCRIPT is A3. When it lands, register
          the restore on self._cleanup at the point the setting is changed.
    §5.10 Connecting QgsHistoryProviderRegistry.entryAdded and its QTimer
          polling fallback is A5. Same rule: register the disconnect and the
          timer stop as they are created.
    A6    "Start new workflow" / "Name this workflow" menu actions.
"""

from __future__ import annotations

import os
import uuid

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from . import paths
from .lifecycle import CleanupStack
from .log import CRITICAL, INFO, WARNING, log, log_exception
from .storage.store import ProvenanceStore
from .ui.dock import DEFAULT_DOCK_AREA, GeoProvenanceDockWidget

MENU_TITLE = "&GeoProvenance"
PLUGIN_NAME = "GeoProvenance"

_ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.png")


class GeoProvenancePlugin:
    """The QGIS plugin object. One instance per QGIS session."""

    def __init__(self, iface):
        self.iface = iface
        self._cleanup = CleanupStack()

        #: Appendix B.5 — minted once, stamped on every activity captured in
        #: this session. A6 groups activities into workflows by it.
        self.session_id = str(uuid.uuid4())

        self.store: ProvenanceStore | None = None
        self.dock: GeoProvenanceDockWidget | None = None
        self.db_path = None

    # -- load --------------------------------------------------------------

    def initGui(self):  # noqa: N802 — required by the QGIS plugin API
        """Called by QGIS on plugin load. Must not raise (§5.1)."""
        log(f"{PLUGIN_NAME} loading. Session {self.session_id}", INFO)
        try:
            self._open_store()
            self._build_dock()
            self._build_actions()
        except Exception as exc:  # noqa: BLE001 — §5.1
            log_exception(f"{PLUGIN_NAME} failed to initialise", exc)
            log(
                "GeoProvenance loaded in a degraded state — see the messages "
                "above. QGIS itself is unaffected.",
                WARNING,
            )

    def _open_store(self) -> None:
        """Resolve the database path (§4.8) and open it.

        A storage failure is not fatal to the plugin: the panel and menu still
        load, and the reason is in the log. Refusing to load at all would make
        a corrupt database look like a broken QGIS.
        """
        self.db_path = paths.resolve_db_path(settings=QSettings())
        try:
            self.store = ProvenanceStore(self.db_path)
        except Exception as exc:  # noqa: BLE001 — §5.1
            log_exception(f"could not open the database at {self.db_path}", exc)
            self.store = None
            return

        self._cleanup.defer("close the database", self.store.close)
        log(f"database ready at {self.db_path} "
            f"(schema version {self.store.schema_version()})", INFO)

    def _build_dock(self) -> None:
        self.dock = GeoProvenanceDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(DEFAULT_DOCK_AREA, self.dock)
        self.dock.hide()  # opt-in: do not steal screen space on first load

        def remove_dock() -> None:
            self.iface.removeDockWidget(self.dock)
            self.dock.setParent(None)
            self.dock.deleteLater()
            self.dock = None

        self._cleanup.defer("remove the dock widget", remove_dock)

    def _build_actions(self) -> None:
        icon = QIcon(_ICON_PATH)
        self._add_action(
            icon, "Show GeoProvenance panel", self._toggle_dock, toolbar=True,
            tip="Show or hide the GeoProvenance panel",
        )
        self._add_action(
            icon, "Provenance database…", self._show_database_info,
            tip="Where the provenance record is being written",
        )

    def _add_action(self, icon, text, handler, *, toolbar=False, tip=None) -> QAction:
        """Create one action and register everything needed to undo it."""
        action = QAction(icon, text, self.iface.mainWindow())
        action.triggered.connect(handler)
        self._cleanup.defer(f"disconnect {text!r}",
                            lambda: action.triggered.disconnect(handler))

        if tip:
            action.setStatusTip(tip)

        self.iface.addPluginToMenu(MENU_TITLE, action)
        self._cleanup.defer(f"remove {text!r} from the menu",
                            lambda: self.iface.removePluginMenu(MENU_TITLE, action))

        if toolbar:
            self.iface.addToolBarIcon(action)
            self._cleanup.defer(f"remove {text!r} from the toolbar",
                                lambda: self.iface.removeToolBarIcon(action))

        return action

    # -- actions -----------------------------------------------------------

    def _toggle_dock(self) -> None:
        if self.dock is None:
            return
        self.dock.setVisible(not self.dock.isVisible())

    def _show_database_info(self) -> None:
        """Deliberately plain language — this dialog is demo surface (§7.5)."""
        if self.store is None:
            QMessageBox.warning(
                self.iface.mainWindow(), PLUGIN_NAME,
                f"The record could not be opened.\n\nExpected location:\n"
                f"{self.db_path}\n\nSee the GeoProvenance tab of the Log "
                f"Messages panel for the reason.",
            )
            return

        counts = self.store.counts()
        QMessageBox.information(
            self.iface.mainWindow(), PLUGIN_NAME,
            f"Where the record is kept:\n{self.db_path}\n\n"
            f"Jobs written down so far: {counts['activities']}\n"
            f"Files being tracked: {counts['entities']}\n",
        )

    # -- unload ------------------------------------------------------------

    def unload(self):
        """Called by QGIS on plugin unload or reload. Must leave no residue.

        §5.4 — unwinding is last-in-first-out and never raises, so one broken
        teardown step cannot strand the rest. Anything that does fail is logged
        loudly: a silent failure here is how a reloaded plugin ends up with two
        menu entries and a stale signal connection.
        """
        log(f"{PLUGIN_NAME} unloading ({len(self._cleanup)} steps)", INFO)
        failures = self._cleanup.unwind()
        self.store = None

        for description, exc in failures:
            log(f"unload step failed — {description}: "
                f"{type(exc).__name__}: {exc}", CRITICAL)
        if not failures:
            log(f"{PLUGIN_NAME} unloaded cleanly", INFO)
