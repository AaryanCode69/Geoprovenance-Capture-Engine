"""Person C's panel, built and driven for real inside QGIS.

Owner: Person C. Written by Person A under the explicit written override of
RULES.md §1.2 [HARD] requested on 30 Aug 2026.

Why these live here and not in tests/ui/
    Everything about the panel that can be checked without Qt already is —
    tests/ui/ covers the arrangement, tests/audit/ covers the colours. What is
    left needs a real QGraphicsScene and a real QWidget, so it is marked `qgis`
    and runs under `make test-qgis` (RULES.md §6.1).

Why they are worth having
    `from geoprovenance.ui.panel import GeoProvenancePanel` succeeded on
    PyQt6 while the panel was still unbuildable: `RenderHint` was being looked
    up on `Qt`, where it does not live on either binding, and that only throws
    when a QGraphicsView is actually constructed. An import check would have
    passed it straight through to a blank dock in a review room.
"""

from __future__ import annotations

import pathlib
import shutil

import pytest

pytestmark = pytest.mark.qgis

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def store(tmp_path):
    """The committed record, on a writable copy."""
    from geoprovenance.storage.store import ProvenanceStore

    shutil.copyfile(FIXTURES / "mock_provenance.db", tmp_path / "p.db")
    s = ProvenanceStore(tmp_path / "p.db")
    yield s
    s.close()


@pytest.fixture()
def panel(store, qgis_app):
    from geoprovenance.ui.panel import GeoProvenancePanel

    return GeoProvenancePanel(store)


def test_the_panel_can_actually_be_built(panel):
    """Constructing it is the check — importing it is not.

    Every enum this file touches is resolved during __init__, so a member looked
    up on the wrong class fails here and nowhere earlier.
    """
    assert panel._picker.count() == 3


def test_every_recorded_piece_of_work_draws_something(panel):
    for index in range(panel._picker.count()):
        panel._picker.setCurrentIndex(index)
        assert panel._scene.items(), panel._picker.itemText(index)


def test_it_goes_into_the_dock_through_the_seam_agreed_with_person_a(panel, qgis_app):
    """The A1 exit-gate contract: dock.set_content(widget)."""
    from geoprovenance.ui.dock import GeoProvenanceDockWidget

    dock = GeoProvenanceDockWidget()
    dock.set_content(panel)
    assert dock.content() is panel
    dock.clear_content()
    assert dock.content() is None


def test_checking_a_workflow_scores_it_and_stores_the_result(panel, store):
    """The fixture's paths do not exist on disk, so this scores badly — which is
    the correct answer, and it must be reached without throwing."""
    panel._run_audit()

    assert "Sorry" not in panel._status.text(), panel._status.text()
    assert "Reproducibility Audit Report" in panel._report.toPlainText()
    stored = store.list_audit_results(panel.current_workflow_id())
    assert len(stored) == 1
    assert stored[0]["input_exists_score"] == 0.0


def test_refreshing_keeps_the_piece_of_work_you_were_looking_at(panel):
    panel._picker.setCurrentIndex(1)
    chosen = panel.current_workflow_id()
    panel.reload()
    panel.reload()
    assert panel.current_workflow_id() == chosen


def test_an_empty_record_says_so_instead_of_drawing_nothing(tmp_path, qgis_app):
    from geoprovenance.storage.store import ProvenanceStore
    from geoprovenance.ui.panel import GeoProvenancePanel

    empty = ProvenanceStore(tmp_path / "empty.db")
    try:
        panel = GeoProvenancePanel(empty)
        assert panel.current_workflow_id() is None
        assert "Nothing recorded yet" in panel._status.text()
    finally:
        empty.close()
