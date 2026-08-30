"""A1 exit criteria, inside a real QGIS — RULES.md §5.4.

    ┌──────────────────────────────────────────────────────────────────┐
    │  UNVERIFIED (RULES.md §11.4)                                     │
    │                                                                  │
    │  This file has NEVER BEEN RUN. QGIS is not installed on the      │
    │  machine it was written on, so pytest-qgis cannot even import.   │
    │                                                                  │
    │  Run it first thing in the dev profile:                          │
    │      make test-capture                                           │
    │                                                                  │
    │  Expect to fix the qgis_iface surface below — pytest-qgis's      │
    │  interface stub does not implement every QgisInterface method,   │
    │  and which ones it provides has changed between releases. If a   │
    │  method is missing, that is a fact about the test harness, not   │
    │  about the plugin. Record what you find in                       │
    │  docs/capture_coverage.md §4 so nobody rediscovers it.           │
    └──────────────────────────────────────────────────────────────────┘

What these tests are actually for: the A1 "done when" is *plugin loads and
unloads cleanly, no errors in the QGIS log, unload() disconnects everything*,
and that can only be observed inside QGIS. The mechanism behind it
(CleanupStack) is fully tested without QGIS in tests/plugin/test_lifecycle.py.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("qgis.core", reason="needs QGIS; run with make test-capture")

from geoprovenance import classFactory  # noqa: E402
from geoprovenance.plugin import GeoProvenancePlugin  # noqa: E402
from geoprovenance.storage.store import SCHEMA_VERSION  # noqa: E402
from geoprovenance.ui.dock import DOCK_OBJECT_NAME  # noqa: E402

pytestmark = pytest.mark.qgis


@pytest.fixture()
def plugin(qgis_iface, tmp_path, monkeypatch):
    """A plugin instance pointed at a throwaway database.

    The path override goes through paths.resolve_db_path so the test exercises
    the §4.8 single-config-value path rather than reaching around it.
    """
    from geoprovenance import paths

    db = tmp_path / "provenance.db"
    monkeypatch.setattr(paths, "resolve_db_path", lambda override=None, settings=None: db)

    instance = GeoProvenancePlugin(qgis_iface)
    yield instance
    if instance._cleanup:
        instance.unload()


def test_class_factory_returns_the_plugin(qgis_iface):
    assert isinstance(classFactory(qgis_iface), GeoProvenancePlugin)


def test_a_session_id_is_minted_at_construction(plugin):
    """Appendix B.5 — every activity captured in this QGIS session carries it,
    which is what makes A6's workflow auto-grouping possible."""
    assert uuid.UUID(plugin.session_id)


def test_each_session_gets_its_own_id(qgis_iface):
    assert GeoProvenancePlugin(qgis_iface).session_id != \
           GeoProvenancePlugin(qgis_iface).session_id


def test_init_gui_opens_the_database(plugin):
    plugin.initGui()
    assert plugin.store is not None
    # Against the constant, never a literal. This said `== 1` from the A1
    # commit until 30 Aug 2026 — four days after the schema went to 2 — because
    # it only runs inside QGIS and nothing outside QGIS could see it go red.
    assert plugin.store.schema_version() == SCHEMA_VERSION
    assert plugin.db_path.exists()


def test_init_gui_registers_the_dock_with_the_agreed_object_name(plugin):
    """The name Person C builds against (geoprovenance/ui/dock.py)."""
    plugin.initGui()
    assert plugin.dock is not None
    assert plugin.dock.objectName() == DOCK_OBJECT_NAME


def test_the_dock_starts_hidden(plugin):
    """Opt-in: a plugin that seizes screen space on first load is a plugin
    users disable."""
    plugin.initGui()
    assert not plugin.dock.isVisible()


def test_person_c_can_install_content_into_the_dock(plugin):
    from qgis.PyQt.QtWidgets import QLabel

    plugin.initGui()
    widget = QLabel("Person C's DAG viewer goes here")
    plugin.dock.set_content(widget)
    assert plugin.dock.content() is widget

    plugin.dock.clear_content()
    assert plugin.dock.content() is None


def test_unload_drains_every_registered_cleanup(plugin):
    """§5.4 [HARD] — the A1 exit criterion."""
    plugin.initGui()
    assert len(plugin._cleanup) > 0

    plugin.unload()

    assert len(plugin._cleanup) == 0
    assert plugin.store is None
    assert plugin.dock is None


def test_load_unload_load_leaves_no_residue(qgis_iface, plugin):
    """§5.4 — the Plugin Reloader loop. Two menu entries after a reload is the
    classic symptom of an unload that missed something."""
    plugin.initGui()
    first = len(plugin._cleanup)
    plugin.unload()

    plugin.initGui()
    assert len(plugin._cleanup) == first
    plugin.unload()
    assert len(plugin._cleanup) == 0


def test_unload_is_safe_to_call_twice(plugin):
    plugin.initGui()
    plugin.unload()
    plugin.unload()  # must not raise or double-remove


def test_init_gui_does_not_raise_when_the_database_cannot_be_opened(
    qgis_iface, tmp_path, monkeypatch
):
    """§5.1 [HARD] — a plugin that throws during load leaves QGIS in a
    half-initialised state and blames us in a modal dialog. It must come up
    degraded instead, with the reason in the log."""
    from geoprovenance import paths

    # A directory where the database file should be: opening it must fail.
    blocked = tmp_path / "provenance.db"
    blocked.mkdir()
    monkeypatch.setattr(paths, "resolve_db_path",
                        lambda override=None, settings=None: blocked)

    instance = GeoProvenancePlugin(qgis_iface)
    instance.initGui()  # must not raise

    assert instance.store is None
    assert instance.dock is not None  # the rest of the plugin still came up
    instance.unload()
