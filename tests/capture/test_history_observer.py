"""Channel 3 — the history registry observer (A5).

No QGIS. RULES.md §6.1 — the mechanism (parsing, per-entry dedup, the sweep)
is extracted into plain Python and tested here; only the observation that the
signal actually fires is left for tests/capture/ under pytest-qgis, because
only a running QGIS can answer it.

What is deliberately NOT tested here: the entryAdded signature. It is
UNVERIFIED (§5.10) and the handler is written to survive not knowing it, which
is the most that can be checked without QGIS.
"""

from __future__ import annotations

import datetime as dt

import pytest

from geoprovenance.capture import history_observer as h

WHEN = "2026-08-08T10:14:22.481903+00:00"

BUFFER_ENTRY = {
    "algorithm_id": "native:buffer",
    "parameters": {"INPUT": "/data/roads.shp", "DISTANCE": 500},
    "python_command": 'processing.run("native:buffer", {"DISTANCE": 500})',
}


class FakeHistoryEntry:
    """QgsHistoryEntry-shaped. Attributes, not methods (§5.10 — shape, not class)."""

    def __init__(self, entry_id=3, payload=None, timestamp=WHEN):
        self.id = entry_id
        self.entry = payload if payload is not None else BUFFER_ENTRY
        self.timestamp = timestamp
        self.providerId = "processing"  # noqa: N815 — QGIS name


# ===========================================================================
# parse_history_entry — tolerant, because the keys are UNVERIFIED (§5.10)
# ===========================================================================

def test_a_processing_entry_yields_its_algorithm_and_parameters():
    parsed = h.parse_history_entry(BUFFER_ENTRY)
    assert parsed["algorithm_id"] == "native:buffer"
    assert parsed["parameters"] == {"INPUT": "/data/roads.shp", "DISTANCE": 500}


@pytest.mark.parametrize("key", ["algorithm_id", "algorithmId", "alg_id"])
def test_every_spelling_of_the_algorithm_key_is_accepted(key):
    """§5.10 — the key names have drifted across releases, so all of them are
    tried rather than pinning to the one this was written against."""
    assert h.parse_history_entry({key: "native:clip"})["algorithm_id"] == "native:clip"


def test_the_algorithm_id_is_recovered_from_the_command_when_the_key_is_missing():
    """The last resort. A release that renames the key again still gets
    captured, because the recorded command still names the algorithm."""
    entry = {"python_command": 'processing.run("qgis:dissolve", {})'}
    assert h.parse_history_entry(entry)["algorithm_id"] == "qgis:dissolve"


def test_an_entry_that_is_not_an_algorithm_run_is_ignored_not_guessed():
    """Expression and query-editor entries share the registry. Capturing them
    would be outside scope (§9.1), and inventing an algorithm id for them
    would put a fabricated job in Person C's graph."""
    assert h.parse_history_entry({"expression": "1 + 1"}) is None


@pytest.mark.parametrize("payload", [None, "", 42, [], {"parameters": {}}])
def test_junk_payloads_return_none_rather_than_raising(payload):
    """§5.1 — this runs inside a Qt signal handler."""
    assert h.parse_history_entry(payload) is None


def test_non_dict_parameters_degrade_to_empty_rather_than_raising():
    parsed = h.parse_history_entry({"algorithm_id": "native:buffer", "parameters": "?"})
    assert parsed["parameters"] == {}


# ===========================================================================
# entry_timestamp
# ===========================================================================

def test_a_qdatetime_like_object_is_converted():
    class FakeQDateTime:
        def toPyDateTime(self):  # noqa: N802 — Qt name
            return dt.datetime(2026, 8, 8, 10, 14, 22, 481903, tzinfo=dt.timezone.utc)

    assert h.entry_timestamp(FakeQDateTime()) == WHEN


def test_a_naive_datetime_is_assumed_utc_rather_than_dropped():
    naive = dt.datetime(2026, 8, 8, 10, 14, 22, 481903)
    assert h.entry_timestamp(naive) == WHEN


def test_an_iso_string_passes_through():
    assert h.entry_timestamp(WHEN) == WHEN


@pytest.mark.parametrize("value", [None, "not a date", object(), 12345])
def test_an_unusable_timestamp_becomes_none_not_a_guess(value):
    """§5.6 — the caller then falls back to 'now', which is honest. A
    malformed string trusted as a timestamp would corrupt the §5.9 bucket."""
    assert h.entry_timestamp(value) is None


# ===========================================================================
# HistoryObserver — per-entry dedup (NOT §5.9's cross-channel dedup)
# ===========================================================================

def test_an_entry_reaches_the_engine_and_is_recorded(engine, store):
    observer = h.HistoryObserver(engine)
    assert observer.handle_entry(1, BUFFER_ENTRY, WHEN) is True

    activities = store.list_activities_for_session(engine.session_id)
    assert len(activities) == 1
    assert activities[0]["algorithm_id"] == "native:buffer"
    assert activities[0]["capture_channel"] == "history_signal"


def test_the_same_entry_delivered_twice_is_only_offered_once(engine, store):
    """The signal delivered entry 1, then the polling sweep found entry 1
    again. Different problem from §5.9's cross-channel dedup, and the reason
    the observer keeps a high-water mark of its own."""
    observer = h.HistoryObserver(engine)
    observer.handle_entry(1, BUFFER_ENTRY, WHEN)
    assert observer.handle_entry(1, BUFFER_ENTRY, WHEN) is False

    assert len(store.list_activities_for_session(engine.session_id)) == 1
    assert observer.offered == 1
    assert observer.skipped == 1


def test_an_older_entry_arriving_late_is_ignored(engine):
    observer = h.HistoryObserver(engine, last_seen_id=10)
    assert observer.handle_entry(4, BUFFER_ENTRY, WHEN) is False


def test_a_non_algorithm_entry_still_advances_the_mark(engine):
    """Otherwise every sweep re-examines the same expression entry forever."""
    observer = h.HistoryObserver(engine)
    observer.handle_entry(7, {"expression": "1 + 1"}, WHEN)
    assert observer.last_seen_id == 7


def test_the_observer_never_raises_however_bad_the_entry(engine):
    """§5.1 [HARD] — this runs inside Qt's event loop."""

    class Explosive:
        def __getattr__(self, name):
            raise RuntimeError(f"exploded on {name}")

    assert h.HistoryObserver(engine).handle_entry(1, Explosive(), WHEN) is False


def test_a_failure_inside_the_engine_does_not_escape(engine, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(engine, "record_algorithm_execution", boom)
    assert h.HistoryObserver(engine).handle_entry(1, BUFFER_ENTRY, WHEN) is False


# ===========================================================================
# poll — the §5.10 fallback sweep
# ===========================================================================

def test_a_sweep_picks_up_only_what_the_signal_missed(engine, store):
    observer = h.HistoryObserver(engine)
    observer.handle_entry(1, BUFFER_ENTRY, WHEN)      # the signal delivered this

    later = {"algorithm_id": "native:clip", "parameters": {"INPUT": "/data/a.shp"}}
    handled = observer.poll([
        {"id": 1, "entry": BUFFER_ENTRY, "timestamp": WHEN, "providerId": "processing"},
        {"id": 2, "entry": later, "timestamp": WHEN, "providerId": "processing"},
    ])

    assert handled == 1
    assert len(store.list_activities_for_session(engine.session_id)) == 2


def test_entries_from_other_providers_are_left_alone(engine, store):
    observer = h.HistoryObserver(engine)
    handled = observer.poll([
        {"id": 1, "entry": {"expression": "1+1"}, "providerId": "expressions"},
    ])
    assert handled == 0
    assert store.list_activities_for_session(engine.session_id) == []


def test_a_sweep_survives_an_entry_it_cannot_unpack(engine):
    observer = h.HistoryObserver(engine)
    assert observer.poll([object(), None]) == 0


def test_a_qgshistoryentry_shaped_object_is_unpacked_by_shape(engine, store):
    """§5.10 — duck-typed, because the class moves and the shape does not."""
    assert h.HistoryObserver(engine).poll([FakeHistoryEntry()]) == 1
    assert len(store.list_activities_for_session(engine.session_id)) == 1


# ===========================================================================
# unpack_signal_args — §5.10, the signature we are not allowed to assume
# ===========================================================================

def test_the_documented_three_argument_signature_is_unpacked():
    entry_id, payload, timestamp = h.unpack_signal_args(
        7, FakeHistoryEntry(entry_id=7), object()
    )
    assert (entry_id, payload, timestamp) == (7, BUFFER_ENTRY, WHEN)


def test_an_entry_only_signature_is_unpacked():
    """A release that drops the separate id argument must still work."""
    entry_id, payload, _ = h.unpack_signal_args(FakeHistoryEntry(entry_id=9))
    assert (entry_id, payload) == (9, BUFFER_ENTRY)


def test_an_id_and_a_plain_dict_are_unpacked():
    entry_id, payload, _ = h.unpack_signal_args(4, BUFFER_ENTRY)
    assert (entry_id, payload) == (4, BUFFER_ENTRY)


def test_an_options_flag_is_never_mistaken_for_the_entry_id():
    """The bug this ordering rule exists to prevent: HistoryEntryOptions is
    also an integer. Reading one as an id would push the high-water mark to a
    nonsense value and silently kill this channel for the rest of the session."""
    entry_id, _, _ = h.unpack_signal_args(FakeHistoryEntry(entry_id=2), 9999)
    assert entry_id == 2


def test_the_entry_object_wins_over_a_positional_integer():
    """Both are present and they disagree — the entry knows its own id."""
    entry_id, _, _ = h.unpack_signal_args(11, FakeHistoryEntry(entry_id=12))
    assert entry_id == 12


def test_an_unrecognisable_signature_yields_nothing_rather_than_raising():
    """§5.1 — a future signature we cannot read costs a record, not a crash."""
    assert h.unpack_signal_args(object(), object()) == (None, None, None)
    assert h.unpack_signal_args() == (None, None, None)


# ===========================================================================
# §5.9 — the two channels meeting, and the RQ1 split that comes out of it
# ===========================================================================

def test_a_run_the_hook_already_caught_arrives_here_as_a_corroboration(engine, store):
    """§5.9 [HARD] — first channel wins; the second increments the counter and
    does NOT insert. This is the whole reason channel 3 is worth having."""
    engine.record_algorithm_execution(
        algorithm_id="native:buffer",
        parameters=BUFFER_ENTRY["parameters"],
        started_at=WHEN,
        ended_at=WHEN,
        source="post_hook",
    )

    h.HistoryObserver(engine).handle_entry(1, BUFFER_ENTRY, WHEN)

    activities = store.list_activities_for_session(engine.session_id)
    assert len(activities) == 1                        # one row, not two
    assert activities[0]["capture_channel"] == "post_hook"   # the hook won
    assert activities[0]["corroborations"] == 1


def test_the_channel_split_is_reportable(engine, store):
    """§5.9 says keep the counter and report it; §8.3 wants the split. This is
    the query behind 'the hook caught most of them, the history channel the
    rest' — the RQ1 number, not bookkeeping."""
    engine.record_algorithm_execution(
        algorithm_id="native:buffer", parameters={"DISTANCE": 500},
        started_at=WHEN, ended_at=WHEN, source="post_hook",
    )
    h.HistoryObserver(engine).handle_entry(
        1, {"algorithm_id": "native:buffer", "parameters": {"DISTANCE": 500}}, WHEN
    )
    h.HistoryObserver(engine).handle_entry(
        2, {"algorithm_id": "native:clip", "parameters": {}}, WHEN
    )

    stats = store.channel_statistics()
    assert stats["post_hook"] == {"first": 1, "corroborations": 1}
    assert stats["history_signal"] == {"first": 1, "corroborations": 0}


def test_a_failed_run_seen_only_by_this_channel_is_still_recorded(engine, store):
    """§4.10 — failed and cancelled runs are never dropped. C's audit needs
    them and RQ1 completeness counts them."""
    engine.record_algorithm_execution(
        algorithm_id="gdal:warpreproject", parameters={}, started_at=WHEN,
        ended_at=WHEN, status="failed", source="history_signal",
    )
    activities = store.list_activities_for_session(engine.session_id)
    assert activities[0]["status"] == "failed"
