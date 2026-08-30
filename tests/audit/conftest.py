"""Fixtures for Person C's audit suite.

RULES.md §6.1 — nothing in this directory may import QGIS. Run it with:

    make test-audit
"""

from __future__ import annotations

import pytest

from geoprovenance.storage.store import ProvenanceStore


@pytest.fixture()
def store(tmp_path):
    s = ProvenanceStore(tmp_path / "prov.db")
    yield s
    s.close()
