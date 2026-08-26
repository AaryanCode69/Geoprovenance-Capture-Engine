"""A new QGIS project starts a new record.

No QGIS — `geoprovenance/plugin.py` is the one module that legitimately imports
PyQGIS (the §4.1 guard test lists the modules that may not, and this is not one
of them), so the QGIS surface it touches is stubbed into `sys.modules` for the
duration of these tests. Everything actually exercised below is plain Python.

    Why this exists (26 Aug 2026). Nothing in the plugin knew QGIS had projects.
    One database lives per PROFILE, the session id was minted once at plugin
    load, and `_show_database_info` reported `ProvenanceStore.counts()` — which
    is `SELECT count(*)` over the whole database, on purpose, because it exists
    for the RQ2 storage measurement (§8.6). So a brand new project reported
    every job the profile had ever seen, and workflow grouping kept
    accumulating across projects that had nothing to do with each other.

The mechanism under test is deliberately one that already existed: a project
change mints a new `session_id`, and `session_id` is ALREADY the grouping key
(Appendix B.5). No schema change, no second idea for the same thing.
"""

from __future__ import annotations

import sys
import types

import pytest

from geoprovenance.capture.engine import ProvenanceCaptureEngine
from geoprovenance.storage.store import ProvenanceStore


# ---------------------------------------------------------------------------
# the QGIS surface plugin.py imports, stubbed
# ---------------------------------------------------------------------------

class FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, slot):
        self._slots.remove(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)

    def connections(self):
        return len(self._slots)


class FakeProject:
    """QgsProject.instance()."""

    def __init__(self, file_name=""):
        self.cleared = FakeSignal()
        self.readProject = FakeSignal()  # noqa: N815 — QGIS name
        self._file_name = file_name

    def fileName(self):  # noqa: N802 — QGIS name
        return self._file_name


@pytest.fixture()
def plugin_module(monkeypatch):
    """Import geoprovenance.plugin against a stubbed QGIS."""
    project = FakeProject()

    core = types.ModuleType("qgis.core")
    core.QgsProject = types.SimpleNamespace(instance=lambda: project)
    core.QgsApplication = types.SimpleNamespace(qgisSettingsDirPath=lambda: "/tmp")

    qtcore = types.ModuleType("qgis.PyQt.QtCore")
    settings_value = {"path": ""}

    qtcore.QSettings = lambda *a, **k: types.SimpleNamespace(
        value=lambda key, default="": settings_value["path"] or default)
    # Qt 6 scopes enum members under their type; ui/dock.py feature-detects for
    # exactly this (§2.5), so the stub is shaped the Qt 6 way.
    qtcore.Qt = types.SimpleNamespace(
        DockWidgetArea=types.SimpleNamespace(RightDockWidgetArea=2),
        AlignmentFlag=types.SimpleNamespace(AlignTop=32, AlignLeft=1),
    )
    qtgui = types.ModuleType("qgis.PyQt.QtGui")
    qtgui.QIcon = lambda *a, **k: None
    qtgui.QAction = object
    qtwidgets = types.ModuleType("qgis.PyQt.QtWidgets")
    qtwidgets.QInputDialog = object
    qtwidgets.QMessageBox = object
    # Real enough that initGui() completes cleanly. A stub that merely fails
    # would send the plugin down its "degraded" path (§5.1), where a broken
    # load looks like a passing test.
    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self._visible = False

        def setParent(self, parent):  # noqa: N802 — Qt name
            pass

        def deleteLater(self):  # noqa: N802
            pass

        def hide(self):
            self._visible = False

        def show(self):
            self._visible = True

        def setVisible(self, visible):  # noqa: N802
            self._visible = visible

        def isVisible(self):  # noqa: N802
            return self._visible

        def setObjectName(self, name):  # noqa: N802
            pass

        def setWidget(self, widget):  # noqa: N802
            pass

        def setWordWrap(self, wrap):  # noqa: N802
            pass

        def setAlignment(self, alignment):  # noqa: N802
            pass

    class FakeLayout(FakeWidget):
        def setContentsMargins(self, *margins):  # noqa: N802
            pass

        def addWidget(self, widget):  # noqa: N802
            pass

        def removeWidget(self, widget):  # noqa: N802
            pass

    qtwidgets.QDockWidget = FakeWidget
    qtwidgets.QLabel = FakeWidget
    qtwidgets.QWidget = FakeWidget
    qtwidgets.QVBoxLayout = FakeLayout

    class FakeAction:
        def __init__(self, *args, **kwargs):
            self.triggered = FakeSignal()

        def setStatusTip(self, text):  # noqa: N802 — Qt name
            pass

    qtwidgets.QAction = FakeAction
    qtgui.QAction = FakeAction
    pyqt = types.ModuleType("qgis.PyQt")
    pyqt.QtCore, pyqt.QtGui, pyqt.QtWidgets = qtcore, qtgui, qtwidgets
    root = types.ModuleType("qgis")
    root.core, root.PyQt = core, pyqt

    for name, module in (("qgis", root), ("qgis.core", core), ("qgis.PyQt", pyqt),
                         ("qgis.PyQt.QtCore", qtcore), ("qgis.PyQt.QtGui", qtgui),
                         ("qgis.PyQt.QtWidgets", qtwidgets)):
        monkeypatch.setitem(sys.modules, name, module)
    for cached in ("geoprovenance.plugin", "geoprovenance.ui.dock",
                   "geoprovenance.ui"):
        monkeypatch.delitem(sys.modules, cached, raising=False)

    import geoprovenance.plugin as plugin_mod

    monkeypatch.delitem(sys.modules, "geoprovenance.plugin", raising=False)
    plugin_mod.__test_project__ = project
    plugin_mod.__test_settings__ = settings_value
    return plugin_mod


@pytest.fixture()
def plugin(plugin_module, tmp_path):
    """A plugin wired to a real store and engine, with no GUI."""
    instance = plugin_module.GeoProvenancePlugin(iface=object())
    instance.store = ProvenanceStore(tmp_path / "provenance.db")
    instance.db_path = tmp_path / "provenance.db"
    instance.engine = ProvenanceCaptureEngine.start(
        instance.store, instance.session_id)
    instance._project_sessions = [instance.session_id]
    instance._watch_project()
    yield instance
    ProvenanceCaptureEngine.stop()
    instance.store.close()


def run_job(plugin, algorithm="native:buffer", output="/out/a.shp"):
    return plugin.engine.record_algorithm_execution(
        algorithm_id=algorithm,
        parameters={"INPUT": "/data/roads.shp", "OUTPUT": output, "DISTANCE": 10},
        parameter_definitions={"INPUT": "source", "OUTPUT": "sink",
                               "DISTANCE": "distance"},
        source="toolbox",
    )


def project(plugin_module):
    return plugin_module.__test_project__


# ===========================================================================
# the boundary
# ===========================================================================

def test_a_new_project_starts_a_new_session(plugin, plugin_module):
    """The whole point. Work done after File -> New must not land in the
    previous project's workflows."""
    run_job(plugin)
    before = plugin.engine.session_id

    project(plugin_module).cleared.emit()

    assert plugin.engine.session_id != before
    assert plugin._project_sessions == [plugin.engine.session_id]


def test_jobs_either_side_of_a_project_change_are_grouped_separately(
        plugin, plugin_module):
    """Grouping falls out of the session id (Appendix B.5) — which is why this
    needed no schema change."""
    run_job(plugin)
    project(plugin_module).cleared.emit()
    run_job(plugin, algorithm="native:convexhull")

    after_the_boundary = plugin.store.list_activities_for_session(
        plugin.engine.session_id)

    assert plugin.store.counts()["activities"] == 2, "both jobs are on file"
    assert len(after_the_boundary) == 1, "but only one belongs to this project"
    assert after_the_boundary[0]["algorithm_id"] == "native:convexhull"


def test_a_project_change_with_nothing_recorded_does_not_burn_a_session(
        plugin, plugin_module):
    """Launching QGIS and opening a project should not mint a boundary there is
    nothing to draw."""
    before = plugin.engine.session_id

    project(plugin_module).cleared.emit()

    assert plugin.engine.session_id == before


def test_opening_a_project_produces_one_boundary_not_two(plugin, plugin_module):
    """QGIS CLEARS a project and then READS the new one, so both signals fire
    for a single File -> Open. Two boundaries would strand an empty session
    between them."""
    run_job(plugin)
    before = plugin.engine.session_id

    project(plugin_module).cleared.emit()
    project(plugin_module).readProject.emit(object())

    assert plugin.engine.session_id != before
    assert plugin._project_sessions == [plugin.engine.session_id]
    assert len(plugin._project_sessions) == 1


def test_the_handler_survives_whatever_arguments_the_signal_carries(
        plugin, plugin_module):
    """readProject carries a QDomDocument; cleared carries nothing. The slot
    must not care (§5.10's lesson, applied early)."""
    run_job(plugin)

    project(plugin_module).readProject.emit(object(), object(), object())

    assert plugin._project_sessions == [plugin.engine.session_id]


def test_a_broken_boundary_never_reaches_qgis(plugin, plugin_module, monkeypatch):
    """§5.1 [HARD] — this slot runs inside QGIS's own project machinery."""
    monkeypatch.setattr(
        plugin, "_begin_project",
        lambda reason: (_ for _ in ()).throw(RuntimeError("boom")))

    project(plugin_module).cleared.emit()  # must not raise


# ===========================================================================
# what the dialog counts
# ===========================================================================

def test_the_counts_cover_this_project_only(plugin, plugin_module):
    """The reported symptom: a brand new project showed four operations it had
    never run."""
    run_job(plugin)
    run_job(plugin, algorithm="native:convexhull", output="/out/b.shp")
    project(plugin_module).cleared.emit()

    assert plugin._project_counts() == (0, 0)

    run_job(plugin, algorithm="native:centroids", output="/out/c.shp")

    jobs, files = plugin._project_counts()
    assert jobs == 1
    assert files == 2                        # roads.shp in, c.shp out


def test_the_all_time_total_still_sees_everything(plugin, plugin_module):
    """Nothing is deleted — the past stops being SHOWN, not stops existing."""
    run_job(plugin)
    project(plugin_module).cleared.emit()
    run_job(plugin, algorithm="native:convexhull", output="/out/b.shp")

    assert plugin._project_counts()[0] == 1
    assert plugin.store.counts()["activities"] == 2


def test_start_new_workflow_adds_a_session_rather_than_replacing_it(
        plugin, plugin_module):
    """Same project, another piece of work. Replacing would hide everything
    done in this project before the user clicked."""
    run_job(plugin)
    plugin.session_id = plugin.engine.begin_new_workflow()
    plugin._project_sessions.append(plugin.session_id)
    run_job(plugin, algorithm="native:convexhull", output="/out/b.shp")

    assert len(plugin._project_sessions) == 2
    assert plugin._project_counts()[0] == 2


def test_a_project_change_resets_what_start_new_workflow_accumulated(
        plugin, plugin_module):
    run_job(plugin)
    plugin._project_sessions.append(plugin.engine.begin_new_workflow())
    run_job(plugin, algorithm="native:convexhull", output="/out/b.shp")
    assert len(plugin._project_sessions) == 2

    project(plugin_module).cleared.emit()

    assert plugin._project_sessions == [plugin.engine.session_id]
    assert plugin._project_counts() == (0, 0)


# ===========================================================================
# §5.4 — teardown
# ===========================================================================

def test_unload_disconnects_every_project_signal(plugin, plugin_module):
    """Load -> unload -> load must leave no residue. A stale slot here would
    mint a session for a plugin that is no longer loaded."""
    proj = project(plugin_module)
    assert proj.cleared.connections() == 1
    assert proj.readProject.connections() == 1

    assert plugin._cleanup.unwind() == []

    assert proj.cleared.connections() == 0
    assert proj.readProject.connections() == 0


# ===========================================================================
# the wiring itself
#
# Every test above drives _watch_project() directly, so all of them still
# passed when the call was deleted from initGui() — checked, and it is exactly
# the shape of hole this repository has been bitten by three times now
# (capture_coverage.md, 19 Aug: "a green suite was not evidence here").
# This one loads the plugin the way QGIS does.
# ===========================================================================

class FakeIface:
    """QgisInterface, to the extent initGui() touches it."""

    def __init__(self):
        self.docks = []
        self.menu_actions = []
        self.toolbar_actions = []

    def mainWindow(self):  # noqa: N802 — QGIS name
        return object()

    def addDockWidget(self, area, dock):  # noqa: N802
        self.docks.append(dock)

    def removeDockWidget(self, dock):  # noqa: N802
        self.docks.remove(dock)

    def addPluginToMenu(self, title, action):  # noqa: N802
        self.menu_actions.append(action)

    def removePluginMenu(self, title, action):  # noqa: N802
        self.menu_actions.remove(action)

    def addToolBarIcon(self, action):  # noqa: N802
        self.toolbar_actions.append(action)

    def removeToolBarIcon(self, action):  # noqa: N802
        self.toolbar_actions.remove(action)


@pytest.fixture()
def loaded_plugin(plugin_module, tmp_path):
    """A plugin brought up through initGui(), as QGIS brings it up."""
    plugin_module.__test_settings__["path"] = str(tmp_path / "provenance.db")
    ProvenanceCaptureEngine.stop()

    instance = plugin_module.GeoProvenancePlugin(FakeIface())
    instance.initGui()
    yield instance
    instance.unload()
    ProvenanceCaptureEngine.stop()


def test_initGui_connects_the_project_signals(loaded_plugin, plugin_module):  # noqa: N802
    """Loading the plugin must start watching the project. Without this the
    methods above are correct and never called."""
    proj = project(plugin_module)

    assert proj.cleared.connections() == 1
    assert proj.readProject.connections() == 1


def test_the_load_is_clean_not_degraded(loaded_plugin):
    """initGui() swallows its own failures by design (§5.1), so a half-loaded
    plugin passes any test that does not check. Everything must be up."""
    assert loaded_plugin.store is not None
    assert loaded_plugin.engine is not None
    assert loaded_plugin.dock is not None
    assert len(loaded_plugin.iface.menu_actions) == 4
    assert len(loaded_plugin.iface.toolbar_actions) == 1


def test_a_loaded_plugin_draws_the_boundary_for_real(loaded_plugin, plugin_module):
    """End to end through the loaded object: a job, File -> New, and the
    project's counts go back to zero while the database keeps the row."""
    run_job(loaded_plugin)
    assert loaded_plugin._project_counts()[0] == 1

    project(plugin_module).cleared.emit()

    assert loaded_plugin._project_counts() == (0, 0)
    assert loaded_plugin.store.counts()["activities"] == 1


def test_unload_after_initGui_leaves_no_project_slot(plugin_module, tmp_path):  # noqa: N802
    """§5.4 — a stale slot would mint sessions for a plugin QGIS has unloaded."""
    plugin_module.__test_settings__["path"] = str(tmp_path / "provenance.db")
    ProvenanceCaptureEngine.stop()
    instance = plugin_module.GeoProvenancePlugin(FakeIface())

    instance.initGui()
    instance.unload()

    proj = project(plugin_module)
    assert proj.cleared.connections() == 0
    assert proj.readProject.connections() == 0
    ProvenanceCaptureEngine.stop()
