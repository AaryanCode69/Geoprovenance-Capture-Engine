"""Channel 4 — the Processing Toolbox dialog.

No QGIS. A fake `processing.gui.algorithm_widget` module is installed into
`sys.modules`, so the installer patches a stand-in that behaves like the real
one: `QgsProcessingAlgRunnerTask` for threaded algorithms, `execute()` for
FlagNoThreading ones.

    Why this channel exists (measured 26 Aug 2026, QGIS 4.2.1). A Buffer and a
    Convex hull run from the Toolbox were caught ONLY by `history_signal`. The
    Toolbox does not go through `processing.run()`, so `run_wrapper` never
    fired, and QGIS 4 has no post-execution hook. The history channel holds no
    QgsProcessingAlgorithm, so it lifts no files and has no start time: the
    database held 2 jobs, **0 entities and 0 durations** — on the one
    invocation path a person actually uses.
"""

from __future__ import annotations

import sys
import types

import pytest

from geoprovenance.capture import hooks

from fakes import FakeAlgorithmDefinitions

MODULE = "processing.gui.algorithm_widget"

BUFFER_PARAMS = {
    "INPUT": "/data/roads.shp",
    "OUTPUT": "/out/buffered.shp",
    "DISTANCE": 10,
    "SEGMENTS": 5,
    "DISSOLVE": False,
}


class FakeAlgorithm:
    """A QgsProcessingAlgorithm, as much of one as hooks.py touches."""

    def __init__(self, algorithm_id="native:buffer", definitions=None):
        self._id = algorithm_id
        self._definitions = definitions or FakeAlgorithmDefinitions.BUFFER

    def id(self):
        return self._id

    def displayName(self):  # noqa: N802 — QGIS name
        return "Buffer"

    def provider(self):
        return types.SimpleNamespace(id=lambda: "qgis")

    def parameterDefinitions(self):  # noqa: N802 — QGIS name
        return [
            types.SimpleNamespace(name=lambda n=name: n, type=lambda t=kind: t)
            for name, kind in self._definitions.items()
        ]


class FakeSignal:
    """A Qt signal, to the extent `connect` and emission are used."""

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class FakeRunnerTask:
    """QgsProcessingAlgRunnerTask: constructed before the run, emits after."""

    instances: list = []

    def __init__(self, algorithm, parameters, context=None, feedback=None):
        self.algorithm = algorithm
        self.parameters = parameters
        self.executed = FakeSignal()
        FakeRunnerTask.instances.append(self)

    def isCanceled(self):  # noqa: N802 — QGIS name
        return False


@pytest.fixture()
def toolbox(monkeypatch):
    """A stand-in `processing.gui.algorithm_widget`, importable by the installer."""
    FakeRunnerTask.instances = []
    calls = {"execute": []}

    def execute(alg, parameters, context=None, feedback=None):
        calls["execute"].append((alg, parameters))
        return True, {"OUTPUT": "/out/buffered.shp"}

    module = types.ModuleType(MODULE)
    module.QgsProcessingAlgRunnerTask = FakeRunnerTask
    module.execute = execute
    module.calls = calls
    module.original_execute = execute

    package = types.ModuleType("processing.gui")
    package.algorithm_widget = module
    root = sys.modules.get("processing") or types.ModuleType("processing")
    root.gui = package

    monkeypatch.setitem(sys.modules, "processing", root)
    monkeypatch.setitem(sys.modules, "processing.gui", package)
    monkeypatch.setitem(sys.modules, MODULE, module)
    hooks._toolbox_branches_seen.clear()
    return module


def activities(store):
    return store.list_activities_for_session("11111111-1111-4111-8111-111111111111")


# ===========================================================================
# the reason this channel exists: files and durations
# ===========================================================================

def test_a_threaded_toolbox_run_records_the_files_the_history_channel_cannot(
        engine, store, toolbox):
    """The 26 Aug failure, inverted. `entities` must no longer be 0."""
    hooks.install_toolbox_wrapper(engine)

    task = toolbox.QgsProcessingAlgRunnerTask(FakeAlgorithm(), dict(BUFFER_PARAMS))
    task.executed.emit(True, {"OUTPUT": "/out/buffered.shp"})

    counts = store.counts()
    assert counts["activities"] == 1
    assert counts["entities"] == 2          # roads.shp in, buffered.shp out
    relations = {r["relation_type"]
                 for r in store.get_relations_for(activities(store)[0]["id"], "both")}
    assert relations == {"used", "wasGeneratedBy", "wasAssociatedWith"}


def test_the_run_is_bracketed_so_the_duration_is_real(engine, store, toolbox):
    """RQ2 needs a start taken BEFORE the run. The history channel has none, so
    every Toolbox row it wrote had started_at == ended_at."""
    hooks.install_toolbox_wrapper(engine)

    task = toolbox.QgsProcessingAlgRunnerTask(FakeAlgorithm(), dict(BUFFER_PARAMS))
    task.executed.emit(True, {})

    row = activities(store)[0]
    assert row["started_at"] < row["ended_at"]


def test_it_is_labelled_as_its_own_channel_for_RQ1(engine, store, toolbox):  # noqa: N802
    hooks.install_toolbox_wrapper(engine)
    toolbox.QgsProcessingAlgRunnerTask(FakeAlgorithm(), dict(BUFFER_PARAMS)) \
        .executed.emit(True, {})

    assert activities(store)[0]["capture_channel"] == "toolbox"
    assert store.channel_statistics()["toolbox"]["first"] == 1


# ===========================================================================
# the synchronous branch — FlagNoThreading algorithms
# ===========================================================================

def test_the_synchronous_branch_is_captured_too(engine, store, toolbox):
    """QGIS picks the branch from the algorithm's flags, not from the Toolbox,
    so both have to be covered or coverage depends on the algorithm."""
    hooks.install_toolbox_wrapper(engine)

    toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert store.counts()["activities"] == 1
    assert activities(store)[0]["capture_channel"] == "toolbox"


def test_the_synchronous_wrapper_returns_the_pair_untouched(engine, toolbox):
    """§5.2 [HARD] — the caller does `ok, results = execute(...)`. Anything else
    breaks the Toolbox dialog."""
    hooks.install_toolbox_wrapper(engine)

    ok, results = toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert ok is True
    assert results == {"OUTPUT": "/out/buffered.shp"}


def test_an_algorithm_failure_is_recorded_and_re_raised_untouched(engine, store, toolbox):
    """§5.2 [HARD] — the user's exception is theirs; we only watch. §4.10 — the
    failed run is still persisted."""
    boom = RuntimeError("the algorithm failed")

    def explode(alg, parameters, context=None, feedback=None):
        raise boom

    toolbox.execute = explode
    hooks.install_toolbox_wrapper(engine)

    with pytest.raises(RuntimeError) as raised:
        toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert raised.value is boom
    assert activities(store)[0]["status"] == "failed"


def test_an_unsuccessful_run_is_recorded_as_failed(engine, store, toolbox):
    """`execute` reports failure by returning ok=False, not by raising."""
    toolbox.execute = lambda alg, parameters, context=None, feedback=None: (False, {})
    hooks.install_toolbox_wrapper(engine)

    toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert activities(store)[0]["status"] == "failed"


def test_a_cancelled_threaded_run_is_recorded_as_failed(engine, store, toolbox):
    hooks.install_toolbox_wrapper(engine)

    toolbox.QgsProcessingAlgRunnerTask(FakeAlgorithm(), dict(BUFFER_PARAMS)) \
        .executed.emit(False, {})

    assert activities(store)[0]["status"] == "failed"


# ===========================================================================
# §5.1 — never break the user's QGIS
# ===========================================================================

def test_a_capture_failure_does_not_reach_the_user(engine, store, toolbox, monkeypatch):
    """§5.1 [HARD] outranks correctness of capture. Losing one record is
    acceptable; aborting somebody's analysis is not."""
    monkeypatch.setattr(
        hooks, "_record",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("capture is broken")))
    hooks.install_toolbox_wrapper(engine)

    ok, results = toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert ok is True
    assert results == {"OUTPUT": "/out/buffered.shp"}


def test_the_real_task_is_returned_not_a_stand_in(engine, toolbox):
    """§5.2 — the dialog calls isCanceled() on it and connects its own slot."""
    hooks.install_toolbox_wrapper(engine)

    task = toolbox.QgsProcessingAlgRunnerTask(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert isinstance(task, FakeRunnerTask)
    assert task.isCanceled() is False


def test_a_broken_task_signal_does_not_break_construction(engine, toolbox):
    """If connecting fails, the user still gets their task."""
    class NoSignal(FakeRunnerTask):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.executed = None

    toolbox.QgsProcessingAlgRunnerTask = NoSignal
    hooks.install_toolbox_wrapper(engine)

    task = toolbox.QgsProcessingAlgRunnerTask(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert isinstance(task, NoSignal)


def test_a_missing_toolbox_module_degrades_quietly(engine, monkeypatch):
    """A headless QGIS has no Toolbox. Not an error."""
    monkeypatch.setitem(sys.modules, MODULE, None)
    monkeypatch.setattr(
        hooks, "install_toolbox_wrapper", hooks.install_toolbox_wrapper)

    import builtins
    real_import = builtins.__import__

    def no_toolbox(name, *args, **kwargs):
        if name.startswith("processing"):
            raise ImportError("no Processing here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_toolbox)
    undo = hooks.install_toolbox_wrapper(engine)

    assert callable(undo)
    undo()


# ===========================================================================
# §5.4 — teardown leaves no residue
# ===========================================================================

def test_uninstall_restores_both_branches_exactly(engine, toolbox):
    original_task = toolbox.QgsProcessingAlgRunnerTask
    original_execute = toolbox.execute

    undo = hooks.install_toolbox_wrapper(engine)
    assert toolbox.QgsProcessingAlgRunnerTask is not original_task
    assert toolbox.execute is not original_execute

    undo()

    assert toolbox.QgsProcessingAlgRunnerTask is original_task
    assert toolbox.execute is original_execute


def test_install_uninstall_install_leaves_no_residue(engine, store, toolbox):
    """The load -> unload -> load cycle §5.4 exists for. A second wrapper layered
    on the first would record every run twice."""
    hooks.install_toolbox_wrapper(engine)()
    hooks.install_toolbox_wrapper(engine)

    toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert store.counts()["activities"] == 1


def test_it_refuses_to_wrap_itself_twice(engine, store, toolbox):
    hooks.install_toolbox_wrapper(engine)
    hooks.install_toolbox_wrapper(engine)

    toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))

    assert store.counts()["activities"] == 1


# ===========================================================================
# §5.9 — the Toolbox channel and the history channel see the SAME run
#
# The 19 Aug lesson applies directly: three pre-existing dedup tests all passed
# against dedup that never once fired in production, because each was built on
# the one shape where the defect is invisible. So this is built from the way
# the two channels ACTUALLY differ on QGIS 4.2.1, measured 26 Aug 2026:
#
#   toolbox          holds the algorithm -> parameter type map -> INPUT and
#                    OUTPUT lifted out of `parameters`; start stamped BEFORE
#                    the run.
#   history_signal   no algorithm, no type map, nothing lifted; timestamp
#                    written AFTER the run; and its raw parameters arrive
#                    wrapped -- {"area_units":…, "inputs": {the real dict}} --
#                    which is the shape that made the digests differ.
# ===========================================================================

HISTORY_ENVELOPE = {
    "area_units": "m2",
    "distance_units": "meters",
    "ellipsoid": "EPSG:7030",
    "inputs": dict(BUFFER_PARAMS),
}


def as_history(engine, *, started_at, payload=None):
    """One history sighting, parsed the way the observer parses a real entry."""
    from geoprovenance.capture import history_observer

    parsed = history_observer.parse_history_entry(payload or {
        "algorithm_id": "native:buffer",
        "parameters": dict(HISTORY_ENVELOPE),
        "python_command": 'processing.run("native:buffer", {})',
    })
    return engine.record_algorithm_execution(
        algorithm_id=parsed["algorithm_id"],
        parameters=parsed["parameters"],
        parameter_definitions=None,          # the whole point
        started_at=started_at,
        ended_at=started_at,
        source="history_signal",
    )


def test_one_toolbox_run_seen_twice_is_one_row_with_a_corroboration(
        engine, store, toolbox):
    """§5.9 [HARD]. Both channels are installed at once in the real plugin, so
    every Toolbox run IS seen twice. Two rows here would double the RQ1
    denominator and leave the per-channel split unmeasurable."""
    hooks.install_toolbox_wrapper(engine)

    toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))
    row = activities(store)[0]
    second = as_history(engine, started_at=row["ended_at"])

    assert second.corroborated and not second.recorded
    assert store.counts()["activities"] == 1
    assert store.get_activity(row["id"])["corroborations"] == 1


def test_the_richer_toolbox_record_is_the_one_kept(engine, store, toolbox):
    """First channel wins and `_corroborate` only increments, so the Toolbox
    record must be the one already on file when the history sighting lands.
    Otherwise this whole channel buys nothing: the stored row would still have
    no files on it."""
    hooks.install_toolbox_wrapper(engine)

    toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))
    row = activities(store)[0]
    as_history(engine, started_at=row["ended_at"])

    kept = store.get_activity(row["id"])
    assert kept["capture_channel"] == "toolbox"
    assert store.counts()["entities"] == 2


def test_the_envelope_is_what_used_to_break_the_digest(engine, store):
    """The measured cause, pinned. QGIS 4 wraps the parameters, so the history
    channel's raw dict was {"area_units":…, "inputs": {…}} while every other
    channel held the flat dict -- different digests, no dedup, ever."""
    from geoprovenance.capture import history_observer, normalizer

    parsed = history_observer.parse_history_entry({
        "algorithm_id": "native:buffer",
        "parameters": dict(HISTORY_ENVELOPE),
    })

    assert parsed["parameters"] == BUFFER_PARAMS, "the envelope must be unwrapped"
    assert (normalizer.dedup_group("native:buffer", parsed["parameters"])
            == normalizer.dedup_group("native:buffer", dict(BUFFER_PARAMS)))


def test_an_unwrapped_history_entry_is_left_alone(engine):
    """QGIS 3 is believed to store the flat dict. Feature detection, not a
    version test (§2.5) -- so a flat entry must survive untouched."""
    from geoprovenance.capture import history_observer

    parsed = history_observer.parse_history_entry({
        "algorithm_id": "native:buffer",
        "parameters": dict(BUFFER_PARAMS),
    })

    assert parsed["parameters"] == BUFFER_PARAMS


def test_a_genuinely_separate_toolbox_run_is_not_swallowed(engine, store, toolbox):
    """The other half of §5.9. Collapsing two real runs would understate RQ1
    completeness."""
    hooks.install_toolbox_wrapper(engine)

    toolbox.execute(FakeAlgorithm(), dict(BUFFER_PARAMS))
    row = activities(store)[0]
    much_later = "2026-08-08T11:99:00".replace("99", "30") + ":00+00:00"
    later = as_history(engine, started_at=much_later)

    assert later.recorded, "a separate run must not be folded into the first"
    assert store.counts()["activities"] == 2
    assert store.get_activity(row["id"])["corroborations"] == 0
