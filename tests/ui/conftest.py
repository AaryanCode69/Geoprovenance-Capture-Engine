"""Fixtures for Person C's layout suite.

RULES.md §6.1 — nothing in this directory may import QGIS or Qt. The widget
half lives in tests/capture/, under pytest-qgis.
"""

from __future__ import annotations

import pathlib
import shutil

import pytest

from geoprovenance.storage.store import ProvenanceStore

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture()
def store(tmp_path):
    s = ProvenanceStore(tmp_path / "prov.db")
    yield s
    s.close()


@pytest.fixture()
def recorded_store(tmp_path):
    """The committed fixture record, on a writable copy.

    RULES.md §6.6 requires the fixtures to include a branch — one job making two
    files that then go different ways — precisely so that layout code meets a
    non-linear graph early. This is that.
    """
    copy = tmp_path / "mock_provenance.db"
    shutil.copyfile(FIXTURES / "mock_provenance.db", copy)
    s = ProvenanceStore(copy)
    yield s
    s.close()
