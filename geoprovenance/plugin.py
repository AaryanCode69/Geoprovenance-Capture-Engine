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
          ProcessingConfig POST_EXECUTION_SCRIPT — landed in A3.
    §5.10 Connecting QgsHistoryProviderRegistry.entryAdded and its QTimer
          polling fallback — landed in A5; the disconnect and the timer stop
          are registered as they are created, same as everything else.
    A6    "Start new workflow" / "Name this workflow" menu actions — landed
          in A6. Both are thin: the mechanism is the engine's session id and
          storage/workflows.py, and nothing about grouping is decided here.

Project awareness (26 Aug 2026)
    This is the ONLY layer that knows QGIS has projects. capture/ and storage/
    stay project-agnostic — engine.py still imports no QGIS — because the
    mechanism is one that already existed: a project change mints a new
    session_id, and session_id is already the grouping key (Appendix B.5).
    See _watch_project.
"""

from __future__ import annotations

import os
import uuid

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox

try:  # Qt 5
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # Qt 6 moved QAction from QtWidgets to QtGui
    # RULES.md §2.5 — feature-detect rather than test the QGIS version. This is
    # the only class the plugin uses that changed module between Qt 5 and Qt 6.
    from qgis.PyQt.QtGui import QAction

from . import paths
from .capture import history_observer, hooks
from .capture.engine import ProvenanceCaptureEngine
from .lifecycle import CleanupStack
from .log import CRITICAL, INFO, WARNING, log, log_exception
from .storage import workflows
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

        #: Every session id belonging to the CURRENT QGIS project. Usually one;
        #: more when the user hits "Start new workflow" without changing
        #: project. Reset when the project changes — that is what makes the
        #: counts in _show_database_info mean "this project" rather than
        #: "everything this profile has ever seen".
        self._project_sessions: list[str] = [self.session_id]

        self.store: ProvenanceStore | None = None
        self.engine: ProvenanceCaptureEngine | None = None
        self.dock: GeoProvenanceDockWidget | None = None
        self.db_path = None

    # -- load --------------------------------------------------------------

    def initGui(self):  # noqa: N802 — required by the QGIS plugin API
        """Called by QGIS on plugin load. Must not raise (§5.1)."""
        log(f"{PLUGIN_NAME} loading. Session {self.session_id}", INFO)
        try:
            self._open_store()
            self._start_capture()
            self._watch_project()
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

    def _start_capture(self) -> None:
        """Start the engine and install all three capture channels (A3, A5).

        Without a database there is nowhere to write, so capture stays off
        rather than failing on every algorithm the user runs.
        """
        if self.store is None:
            log("capture not started — no database (see above)", WARNING)
            return

        self.engine = ProvenanceCaptureEngine.start(self.store, self.session_id)
        self._cleanup.defer("stop the capture engine", ProvenanceCaptureEngine.stop)

        # §5.3 / §5.4 — each channel hands back its own undo, registered here
        # at the moment it is installed rather than remembered later.
        for description, undo in hooks.install_all(
            self.engine, self.db_path.parent / "hooks"
        ):
            self._cleanup.defer(description, undo)

        # A5, channel 3. Installed after the hooks so that when both see one
        # execution the hook wins the §5.9 race and the history entry arrives
        # as the corroboration — which is the direction the RQ1 split is
        # phrased in ("the hook caught 98%, the history channel the rest").
        for description, undo in history_observer.install_history_observer(self.engine):
            self._cleanup.defer(description, undo)

    def _watch_project(self) -> None:
        """A new or opened project starts a new record (26 Aug 2026).

        Before this, nothing in the plugin knew QGIS had projects at all. One
        database lives per PROFILE, the session id was minted once at load, and
        so a fresh project kept accumulating into the previous one's workflows
        and reported every job the profile had ever seen.

        The mechanism is deliberately the one that already exists: a project
        change mints a new ``session_id`` via engine.begin_new_workflow(), and
        ``session_id`` is ALREADY the grouping key (Appendix B.5). So grouping
        stops spanning projects for free — no schema change, no second idea for
        the same thing (§3.4 would otherwise make this a breaking change to two
        other people's work).

        Nothing is deleted. The past stays on disk and simply stops being shown.
        """
        if self.engine is None:
            return
        try:
            from qgis.core import QgsProject
        except ImportError as exc:  # pragma: no cover — needs a non-QGIS process
            log(f"cannot watch the project, QGIS is unavailable: {exc}", WARNING)
            return

        project = QgsProject.instance()

        # QGIS CLEARS a project and then READS the new one, so opening a file
        # fires both. _begin_project handles the double fire (see below).
        for name in ("cleared", "readProject"):
            signal = getattr(project, name, None)
            if signal is None:
                log(f"QgsProject has no {name!r} signal — project boundaries "
                    f"will be missed on this QGIS", WARNING)
                continue
            handler = self._make_project_handler(name)
            signal.connect(handler)
            self._cleanup.defer(
                f"disconnect QgsProject.{name}",
                lambda s=signal, h=handler: s.disconnect(h),
            )

    def _make_project_handler(self, reason: str):
        """One slot per signal, tolerant of whatever arguments it carries."""
        def handler(*_args) -> None:
            # §5.1 [HARD] — this runs inside QGIS's own project machinery.
            try:
                self._begin_project(reason)
            except Exception as exc:  # noqa: BLE001
                log_exception(f"handling QgsProject.{reason}", exc)
        return handler

    def _begin_project(self, reason: str) -> None:
        """Start a fresh session for a new project, if one is warranted.

        Skipped when the outgoing session recorded nothing. That makes the
        clear-then-read double fire a single boundary instead of two, and stops
        a plain QGIS launch from burning a session id before any work happens.
        """
        if self.engine is None or self.store is None:
            return
        if not self.store.list_activities_for_session(self.engine.session_id):
            # Nothing to separate from. Still re-scope, in case a previous
            # project's sessions are lingering in the list.
            self._project_sessions = [self.engine.session_id]
            return

        self.session_id = self.engine.begin_new_workflow()
        self._project_sessions = [self.session_id]
        log(f"project changed ({reason}) — recording from here as a new piece "
            f"of work (session {self.session_id})", INFO)

    def _project_name(self) -> str:
        """What to call the current project in a dialog a reviewer reads (§7.5)."""
        try:
            from qgis.core import QgsProject

            file_name = QgsProject.instance().fileName()
        except Exception:  # noqa: BLE001 — §5.1
            return "unknown"
        if not file_name:
            return "not saved yet"
        return os.path.basename(file_name)

    def _project_counts(self) -> tuple[int, int]:
        """(jobs, files) for the current project only.

        Composed from store methods that already exist rather than a new one:
        ProvenanceStore is the API Person B and Person C build against (§1.5),
        and this needs nothing it does not already offer.
        """
        jobs = 0
        files: set[str] = set()
        for session_id in self._project_sessions:
            jobs += len(self.store.list_activities_for_session(session_id))
            for row in self.store.list_session_datasets(session_id):
                if row["file_path"]:
                    files.add(row["file_path"])
        return jobs, len(files)

    def _build_dock(self) -> None:
        self.dock = GeoProvenanceDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(DEFAULT_DOCK_AREA, self.dock)
        self.dock.hide()  # opt-in: do not steal screen space on first load
        self._fill_dock()

        def remove_dock() -> None:
            self.iface.removeDockWidget(self.dock)
            self.dock.setParent(None)
            self.dock.deleteLater()
            self.dock = None

        self._cleanup.defer("remove the dock widget", remove_dock)

    def _fill_dock(self) -> None:
        """Install Person C's panel through the seam agreed at the A1 exit gate.

        Kept separate from _build_dock, and separately guarded, because the two
        fail differently and only one of them is Person A's. If the panel cannot
        be built the dock still registers and still tears down cleanly, and the
        placeholder in ui/dock.py says so — which is the §5.1 posture applied to
        the read side: a broken view must not cost the user their capture.
        """
        if self.store is None:
            return
        try:
            from .ui.panel import GeoProvenancePanel

            self.dock.set_content(GeoProvenancePanel(self.store, self.dock))
        except Exception as exc:  # noqa: BLE001 — §5.1
            log_exception("GeoProvenance panel could not be built", exc)

    def _build_actions(self) -> None:
        icon = QIcon(_ICON_PATH)
        self._add_action(
            icon, "Show GeoProvenance panel", self._toggle_dock, toolbar=True,
            tip="Show or hide the GeoProvenance panel",
        )
        self._add_action(
            icon, "Start new workflow", self._start_new_workflow,
            tip="Record what follows as a separate piece of work",
        )
        self._add_action(
            icon, "Name this workflow…", self._name_workflow,
            tip="Give the work recorded so far a name you will recognise",
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

    def _start_new_workflow(self) -> None:
        """A6's manual override — draw a boundary the file paths cannot see.

        Auto-grouping links jobs that share files (§5.12). That is right most
        of the time and wrong exactly when a person moves on to a different
        piece of work that happens to start from the same file. This is how
        they say so.
        """
        if self.engine is None:
            QMessageBox.warning(
                self.iface.mainWindow(), PLUGIN_NAME,
                "Nothing is being recorded at the moment, so there is no work "
                "to separate.\n\nSee the GeoProvenance tab of the Log Messages "
                "panel for the reason.",
            )
            return

        self.engine.begin_new_workflow()
        self.session_id = self.engine.session_id
        # Same project, another piece of work — so this session is ADDED to the
        # project's list rather than replacing it, and the counts below keep
        # covering everything done in this project.
        self._project_sessions.append(self.session_id)
        QMessageBox.information(
            self.iface.mainWindow(), PLUGIN_NAME,
            "Started a new piece of work.\n\nJobs from here on are recorded "
            "separately from what came before, even if they use the same "
            "files. Everything already written down is untouched.",
        )

    def _name_workflow(self) -> None:
        """Give one piece of work a name a person chose.

        Asks WHICH first, because one QGIS session can hold several pieces of
        work — two unrelated jobs, or a job that branched. Picking silently
        would rename the wrong one exactly when it matters.
        """
        if self.store is None or self.engine is None:
            QMessageBox.warning(
                self.iface.mainWindow(), PLUGIN_NAME,
                "Nothing is being recorded at the moment.\n\nSee the "
                "GeoProvenance tab of the Log Messages panel for the reason.",
            )
            return

        choices = self._workflow_choices()
        if not choices:
            QMessageBox.information(
                self.iface.mainWindow(), PLUGIN_NAME,
                "No work has been recorded yet in this QGIS session.\n\nRun "
                "a job from the Processing toolbox and it will appear here.",
            )
            return

        labels = [label for label, _ in choices]
        label, chose = QInputDialog.getItem(
            self.iface.mainWindow(), PLUGIN_NAME,
            "Which piece of work?", labels, 0, False,
        )
        if not chose:
            return
        workflow_id = dict(choices)[label]

        name, confirmed = QInputDialog.getText(
            self.iface.mainWindow(), PLUGIN_NAME, "Call it:",
        )
        if not confirmed:
            return

        # A blank name is dropped rather than stored — name_workflow already
        # guarantees that, and the column is NOT NULL.
        workflows.name_workflow(self.store, workflow_id, name)

    def _workflow_choices(self) -> list[tuple[str, str]]:
        """(what to show the user, workflow id) for this session's work.

        Shown by name and step count rather than by id: an id is not something
        a person can recognise, and this dialog is demo surface (§7.5).
        """
        members: dict[str, int] = {}
        workflow_rows = []
        seen_ids: set[str] = set()
        # Every session in THIS project, not just the current one — otherwise
        # "Start new workflow" hides the work done before it.
        for session_id in self._project_sessions:
            for row in self.store.list_session_workflow_members(session_id):
                members[row["workflow_id"]] = members.get(row["workflow_id"], 0) + 1
            for workflow in self.store.find_workflows_by_session(session_id):
                if workflow["id"] not in seen_ids:
                    seen_ids.add(workflow["id"])
                    workflow_rows.append(workflow)

        choices: list[tuple[str, str]] = []
        seen: dict[str, int] = {}
        for workflow in workflow_rows:
            steps = members.get(workflow["id"], 0)
            plural = "" if steps == 1 else "s"
            label = f"{workflow['name']}  ({steps} job{plural})"

            # Two pieces of work can genuinely look identical — one Buffer
            # each, say. The label is what comes back from the dialog, so a
            # repeat would rename whichever one happened to be first.
            seen[label] = seen.get(label, 0) + 1
            if seen[label] > 1:
                label = f"{label} #{seen[label]}"

            choices.append((label, workflow["id"]))
        return choices

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
        watching = "yes" if self.engine is not None else "no — see the log"
        jobs, files = self._project_counts()

        # This project first, the whole computer second. Reporting only the
        # total is what made a brand new project look like it had inherited
        # four jobs from a project that was closed (26 Aug 2026); reporting
        # only the project would make the rest look deleted, which it is not.
        QMessageBox.information(
            self.iface.mainWindow(), PLUGIN_NAME,
            f"Where the record is kept:\n{self.db_path}\n\n"
            f"Project: {self._project_name()}\n"
            f"Watching for jobs: {watching}\n\n"
            f"In this project:\n"
            f"    Jobs written down so far: {jobs}\n"
            f"    Files being tracked: {files}\n\n"
            f"Everything on this computer:\n"
            f"    Jobs: {counts['activities']}    "
            f"Files: {counts['entities']}\n",
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
        self.engine = None

        for description, exc in failures:
            log(f"unload step failed — {description}: "
                f"{type(exc).__name__}: {exc}", CRITICAL)
        if not failures:
            log(f"{PLUGIN_NAME} unloaded cleanly", INFO)
