"""Fixtures for the capture suite.

RULES.md §6.1 — these run with no QGIS. The QGIS-shaped stand-ins live in
fakes.py alongside; see that module for why duck typing is what makes this
possible.
"""

from __future__ import annotations

import pytest

from geoprovenance.storage.store import ProvenanceStore


@pytest.fixture()
def store(tmp_path):
    s = ProvenanceStore(tmp_path / "capture.db")
    yield s
    s.close()


@pytest.fixture()
def engine(store):
    from geoprovenance.capture.engine import ProvenanceCaptureEngine

    instance = ProvenanceCaptureEngine.start(
        store, session_id="11111111-1111-4111-8111-111111111111"
    )
    yield instance
    ProvenanceCaptureEngine.stop()


@pytest.fixture()
def agent_block():
    return {
        "qgis_version": "3.34.8",
        "os_info": "Linux-6.1.0-x86_64",
        "python_version": "3.10.12",
        "plugin_versions": {"GeoProvenance": "0.1.0"},
    }
