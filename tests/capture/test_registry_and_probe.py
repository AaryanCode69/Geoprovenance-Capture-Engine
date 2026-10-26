"""Registry snapshots (C9) and the post-execution hook probe (C6).

Added 24 Oct 2026 with schema v3. No QGIS: the algorithms are fakes with the
three methods `registry.build_snapshot` reads, and the engine's clock is
injected so the probe window can be crossed without sleeping.
"""

from __future__ import annotations

import json

import pytest

from geoprovenance.capture import registry
from geoprovenance.capture.engine import HOOK_PROBE_WINDOW_S, ProvenanceCaptureEngine
from geoprovenance.storage.store import ProvenanceStore


class _Definition:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Provider:
    def id(self):
        return "native"


class _Algorithm:
    def __init__(self, algorithm_id, parameters, *, broken=False):
        self._id, self._parameters, self._broken = algorithm_id, parameters, broken

    def id(self):
        if self._broken:
            raise RuntimeError("a provider that half-loaded")
        return self._id

    def provider(self):
        return _Provider()

    def parameterDefinitions(self):  # noqa: N802 — QGIS API name
        return [_Definition(n) for n in self._parameters]


@pytest.fixture()
def store(tmp_path):
    s = ProvenanceStore(tmp_path / "p.db")
    yield s
    s.close()


def test_a_snapshot_lists_every_algorithm_and_its_parameters():
    snapshot = registry.build_snapshot(
        [_Algorithm("native:buffer", ["OUTPUT", "INPUT", "DISTANCE"]),
         _Algorithm("native:clip", ["INPUT", "OVERLAY", "OUTPUT"])]
    )
    assert snapshot == {
        "native:buffer": {"provider": "native", "parameters": ["DISTANCE", "INPUT", "OUTPUT"]},
        "native:clip": {"provider": "native", "parameters": ["INPUT", "OUTPUT", "OVERLAY"]},
    }


def test_one_unreadable_algorithm_does_not_cost_the_rest():
    snapshot = registry.build_snapshot(
        [_Algorithm("x", [], broken=True), _Algorithm("native:buffer", ["INPUT"])]
    )
    assert list(snapshot) == ["native:buffer"]


def test_recording_a_snapshot_stores_it_against_this_environment(store):
    assert registry.record_snapshot(store, [_Algorithm("native:buffer", ["INPUT"])])
    latest = store.latest_registry_snapshot()
    assert latest["algorithms"]["native:buffer"]["parameters"] == ["INPUT"]
    assert latest["agent"] is not None


def test_outside_qgis_with_nothing_to_read_no_snapshot_is_written(store):
    assert registry.record_snapshot(store) is None
    assert store.latest_registry_snapshot() is None


# --- the probe window ------------------------------------------------------

def _record(engine, started, source="run_wrapper"):
    return engine.record_algorithm_execution(
        algorithm_id="native:buffer",
        parameters={"INPUT": "/data/a.shp", "DISTANCE": 1, "OUTPUT": "/data/b.shp"},
        parameter_definitions={"INPUT": "source", "DISTANCE": "distance", "OUTPUT": "sink"},
        started_at=started, ended_at=started, source=source,
        agent={"qgis_version": "4.2.3", "os_info": "Linux", "python_version": "3.14.0"},
    )


def _hook_state(store):
    rows = store._connection().execute("SELECT capabilities_json FROM agents").fetchall()
    states = [json.loads(r[0]).get("post_execution_hook") for r in rows if r[0]]
    return states[0] if states else None


def test_the_probe_settles_once_the_window_has_passed(store):
    engine = ProvenanceCaptureEngine(store, enrich=False)
    engine.hook_installed = True
    now = [100.0]
    engine.clock = lambda: now[0]
    _record(engine, "2026-10-24T10:00:00.000000+00:00")
    assert _hook_state(store) is None  # inside the window: not decided yet
    now[0] += HOOK_PROBE_WINDOW_S + 0.1
    _record(engine, "2026-10-24T10:10:00.000000+00:00")
    assert _hook_state(store) == "inactive"


def test_a_session_that_ends_inside_the_window_is_settled_on_finish(store):
    engine = ProvenanceCaptureEngine(store, enrich=False)
    engine.hook_installed = True
    _record(engine, "2026-10-24T10:00:00.000000+00:00")
    assert engine.finish_hook_probe() == "inactive"
    assert engine.finish_hook_probe() is None  # once only


def test_without_being_told_about_the_hook_the_probe_records_nothing(store):
    engine = ProvenanceCaptureEngine(store, enrich=False)
    _record(engine, "2026-10-24T10:00:00.000000+00:00")
    assert engine.finish_hook_probe() is None
    assert _hook_state(store) is None
