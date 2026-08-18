"""Channel 3 (redundant): QgsHistoryProviderRegistry observer + polling fallback.

Owner: Person A.  Sub-phase: A5.

    ┌──────────────────────────────────────────────────────────────────────┐
    │  UNVERIFIED (RULES.md §11.4, §5.10)                                  │
    │                                                                      │
    │  The QGIS-facing half below has never been run — QGIS is not         │
    │  installed on the machine it was written on. Two informed guesses    │
    │  MUST be checked on first run and recorded in                        │
    │  docs/capture_coverage.md:                                           │
    │                                                                      │
    │    1. The entryAdded signal's ARITY AND ARGUMENT ORDER. It has       │
    │       changed across QGIS releases and is a known crash risk         │
    │       (research doc §12, risk 7). _on_entry_added therefore takes    │
    │       *args and identifies each argument by shape, never by          │
    │       position, and logs the shapes it actually received.            │
    │    2. The key names a Processing history entry uses for the          │
    │       algorithm id and its parameters. parse_history_entry tries     │
    │       every spelling seen in the wild and falls back to reading the  │
    │       recorded python_command.                                       │
    │                                                                      │
    │  The polling fallback is installed REGARDLESS of whether the signal  │
    │  connects (§5.10), so a signature change degrades this channel to    │
    │  "slightly late" rather than "silently dead".                        │
    └──────────────────────────────────────────────────────────────────────┘

    THIS MODULE IMPORTS NO QGIS AT MODULE LEVEL, deliberately — same reason as
    the normalizer and the engine. Every QGIS import is lazy, inside the one
    function that needs it, so the parsing and bookkeeping below are testable
    on a machine with no QGIS (§6.1: extract the mechanism, leave only the
    observation for tests/capture/).

Rules implemented
    §5.1 [HARD]  Nothing here may raise into QGIS. A signal handler that
                 throws inside Qt's event loop is worse than a lost record.
    §5.4 [HARD]  install() hands back the disconnect and the timer stop, so
                 unload() leaves no live connection behind.
    §5.9 [HARD]  An execution the hook already caught arrives here as a
                 CORROBORATION, not an insert. That is handled centrally by
                 the engine's dedup key; this module only has to avoid
                 handing the SAME history entry over twice, which is what the
                 high-water mark below is for.
    §5.10        The polling fallback exists because the signal is untrusted.

Why two channels at all
    The per-channel split — "the hook caught 98%, the history channel caught
    the other 2%" — is a publishable RQ1 result (§8.3), not belt-and-braces.
    ProvenanceStore.channel_statistics() is what reports it.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable

from ..log import INFO, WARNING, log, log_exception
from ..storage.store import utc_now_iso
from .engine import ProvenanceCaptureEngine

#: The provider id QGIS registers its Processing history under. Entries from
#: any other provider (expressions, the query editor) are not algorithm runs
#: and are ignored — capturing them would be outside scope (§9.1).
PROCESSING_PROVIDER_ID = "processing"

#: How often the fallback sweeps for entries the signal did not deliver.
#: Long enough to be invisible in the RQ2 overhead measurement, short enough
#: that a demo does not sit waiting for it.
POLL_INTERVAL_MS = 5000

#: Spellings seen across QGIS releases. Tried in order; first hit wins.
_ALGORITHM_ID_KEYS = ("algorithm_id", "algorithmId", "alg_id", "algorithm")
_PARAMETER_KEYS = ("parameters", "algorithm_parameters", "params")
_COMMAND_KEYS = ("python_command", "command", "pythonCommand")

#: Last resort: dig the algorithm id out of the recorded command string,
#: e.g. processing.run("native:buffer", {...}).
_COMMAND_ALGORITHM = re.compile(r"""run\s*\(\s*["']([^"']+)["']""")


# ---------------------------------------------------------------------------
# parsing one history entry (pure — no QGIS)
# ---------------------------------------------------------------------------

def _first_present(payload: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def parse_history_entry(payload: Any) -> dict | None:
    """Pull the algorithm id and parameters out of a history entry's payload.

    Returns ``None`` when the payload is not a recognisable algorithm run —
    which is the correct outcome for an expression or query-editor entry, not
    an error. Never raises (§5.1).

    Tolerant by design: which keys QGIS uses is UNVERIFIED (§5.10), so every
    spelling seen in the wild is tried and the recorded ``python_command`` is
    parsed as a last resort. Guessing wrong here costs one missed record;
    raising would cost the user their run.
    """
    try:
        if not isinstance(payload, dict):
            return None

        algorithm_id = _first_present(payload, _ALGORITHM_ID_KEYS)
        if not isinstance(algorithm_id, str) or not algorithm_id:
            algorithm_id = None

        command = _first_present(payload, _COMMAND_KEYS)
        if algorithm_id is None and isinstance(command, str):
            match = _COMMAND_ALGORITHM.search(command)
            if match:
                algorithm_id = match.group(1)

        if not algorithm_id:
            return None

        parameters = _first_present(payload, _PARAMETER_KEYS)
        if not isinstance(parameters, dict):
            parameters = {}

        return {
            "algorithm_id": algorithm_id,
            "parameters": parameters,
            "python_command": command if isinstance(command, str) else None,
        }
    except Exception:  # noqa: BLE001 — §5.1 [HARD]
        return None


def entry_timestamp(value: Any) -> str | None:
    """A microsecond ISO 8601 string for a history entry's timestamp, or None.

    Duck-typed rather than isinstance-checked against QDateTime, for the same
    reason the normalizer duck-types QGIS values: the class moves, the shape
    does not. Handles a QDateTime (via toPyDateTime), a datetime, and a string
    that already looks like ISO 8601.
    """
    if value is None:
        return None
    try:
        if isinstance(value, str):
            # Trust it only if it parses. A malformed string recorded as a
            # timestamp would corrupt the dedup bucket (§5.9).
            dt.datetime.fromisoformat(value)
            return value

        moment = value
        converter = getattr(value, "toPyDateTime", None)
        if callable(converter):
            moment = converter()

        if isinstance(moment, dt.datetime):
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=dt.timezone.utc)
            return moment.astimezone(dt.timezone.utc).isoformat(timespec="microseconds")
    except Exception:  # noqa: BLE001 — §5.1
        return None
    return None


# ---------------------------------------------------------------------------
# the observer (pure bookkeeping — no QGIS)
# ---------------------------------------------------------------------------

class HistoryObserver:
    """Turns history entries into engine calls, exactly once each.

    Two different de-duplications are in play and they are not the same job:

      * §5.9's cross-CHANNEL dedup — the hook and this channel both saw one
        execution. Handled centrally by the engine's dedup key, which is what
        keeps the corroboration counter honest. Not this class's business.
      * Per-ENTRY dedup — the signal delivered entry 41 and then the polling
        sweep found entry 41 again. That is this class's business, and it is
        what ``_high_water`` is for.

    A high-water mark rather than a set of seen ids: history ids are
    monotonic, so one integer answers the question and a long QGIS session
    does not accumulate an ever-growing set in memory.
    """

    def __init__(self, engine: ProvenanceCaptureEngine, *, last_seen_id: int = 0):
        self._engine = engine
        self._high_water = last_seen_id
        #: RQ1 bookkeeping — how many entries this channel actually offered.
        self.offered = 0
        self.skipped = 0

    @property
    def last_seen_id(self) -> int:
        return self._high_water

    def handle_entry(self, entry_id: Any, payload: Any, timestamp: Any = None) -> bool:
        """Offer one history entry to the engine. Never raises (§5.1).

        Returns True when the entry reached the engine — as a new record or as
        a corroboration of one the hook got first. False means it was a
        duplicate delivery, not an algorithm run, or unparseable.
        """
        try:
            numeric_id = _as_int(entry_id)
            if numeric_id is not None and numeric_id <= self._high_water:
                self.skipped += 1
                return False

            parsed = parse_history_entry(payload)
            if parsed is None:
                # Not an algorithm run. Still advance the mark: re-examining
                # an expression entry on every sweep forever is pure waste.
                if numeric_id is not None:
                    self._high_water = numeric_id
                self.skipped += 1
                return False

            started_at = entry_timestamp(timestamp) or utc_now_iso()
            self._engine.record_algorithm_execution(
                algorithm_id=parsed["algorithm_id"],
                parameters=parsed["parameters"],
                # No QgsProcessingAlgorithm in hand, so no parameter type map.
                # Every parameter therefore stays a scalar in `parameters`
                # rather than being lifted into inputs/outputs (§3.3) — this
                # channel corroborates that a run HAPPENED; the hook channel
                # is the one that sees the datasets. Recorded as a limitation
                # in docs/capture_coverage.md §2.
                parameter_definitions=None,
                started_at=started_at,
                ended_at=started_at,
                source="history_signal",
                execution_log=parsed["python_command"],
            )
            if numeric_id is not None:
                self._high_water = numeric_id
            self.offered += 1
            return True
        except Exception as exc:  # noqa: BLE001 — §5.1 [HARD]
            log_exception("history observer", exc)
            return False

    def poll(self, entries: Any) -> int:
        """Sweep a batch of history entries. Returns how many reached the engine.

        Takes the already-fetched list rather than querying, so the sweep logic
        is testable without QGIS; ``_query_entries`` does the QGIS part.
        """
        handled = 0
        try:
            for entry in entries or []:
                entry_id, payload, timestamp, provider = _unpack_entry(entry)
                if provider is not None and provider != PROCESSING_PROVIDER_ID:
                    continue
                if self.handle_entry(entry_id, payload, timestamp):
                    handled += 1
        except Exception as exc:  # noqa: BLE001 — §5.1
            log_exception("history polling sweep", exc)
        return handled


def _as_int(value: Any) -> int | None:
    """An int for a history entry id, or None. Ids may arrive as int or str."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def unpack_signal_args(*args: Any) -> tuple[Any, Any, Any]:
    """(entry_id, payload, timestamp) from whatever entryAdded handed us.

    §5.10 — the signal's arity and argument ORDER have changed across QGIS
    releases and are UNVERIFIED here, so each argument is identified by shape
    rather than by position. Extracted to module level, rather than living in
    the handler closure, precisely so the riskiest logic in this module is
    testable without QGIS (§6.1).

    Two rules earn their keep:

      * An id carried BY the entry object beats a positional integer. An
        options flag is also an integer, and reading one as an id would
        corrupt the high-water mark and silently stop this channel.
      * A bare integer is only accepted as the id in first position, which is
        where every signature seen so far puts it.
    """
    entry_id = payload = timestamp = None
    for index, arg in enumerate(args):
        if isinstance(arg, dict) and payload is None:
            payload = arg
            continue

        unpacked_id, unpacked_payload, unpacked_time, _ = _unpack_entry(arg)
        if unpacked_payload is not None:
            if payload is None:
                payload, timestamp = unpacked_payload, unpacked_time
            if unpacked_id is not None:
                entry_id = unpacked_id
        elif index == 0 and entry_id is None and _as_int(arg) is not None:
            entry_id = arg

    return entry_id, payload, timestamp


def _unpack_entry(entry: Any) -> tuple[Any, Any, Any, Any]:
    """(id, payload, timestamp, provider_id) from a QgsHistoryEntry or a tuple.

    Duck-typed: QgsHistoryEntry exposes .id/.entry/.timestamp/.providerId as
    ATTRIBUTES, but the signal has also delivered plain tuples across
    releases, and tests hand in plain dicts. Shape, not class (§5.10).
    """
    if isinstance(entry, dict):
        return (entry.get("id"), entry.get("entry", entry.get("payload")),
                entry.get("timestamp"), entry.get("providerId"))
    if isinstance(entry, (tuple, list)):
        padded = list(entry) + [None] * 4
        return padded[0], padded[1], padded[2], padded[3]
    return (getattr(entry, "id", None), getattr(entry, "entry", None),
            getattr(entry, "timestamp", None), getattr(entry, "providerId", None))


# ---------------------------------------------------------------------------
# the QGIS-facing half — every import lazy, everything below UNVERIFIED
# ---------------------------------------------------------------------------

def _history_registry():
    """QgsHistoryProviderRegistry, or None when it is unavailable.

    Added in QGIS 3.24. metadata.txt declares 3.34 as the minimum, so it
    should always be present — but §2.5 says feature-detect rather than
    assume, and a missing registry must degrade, not raise.
    """
    try:
        from qgis.gui import QgsGui
        return QgsGui.historyProviderRegistry()
    except Exception as exc:  # noqa: BLE001 — §5.1
        log(f"history registry unavailable, channel 3 not connected: "
            f"{type(exc).__name__}: {exc}", WARNING)
        return None


def _query_entries(registry) -> list:
    """Every Processing history entry the registry will give us."""
    try:
        return list(registry.queryEntries(providerId=PROCESSING_PROVIDER_ID))
    except TypeError:
        # Older signatures took positional arguments only.
        try:
            return list(registry.queryEntries())
        except Exception as exc:  # noqa: BLE001 — §5.1
            log_exception("history queryEntries", exc)
            return []
    except Exception as exc:  # noqa: BLE001 — §5.1
        log_exception("history queryEntries", exc)
        return []


def install_history_observer(
    engine: ProvenanceCaptureEngine,
) -> list[tuple[str, Callable[[], None]]]:
    """Connect the signal and start the polling sweep (§5.10).

    Returns (description, undo) pairs for the plugin's cleanup stack, in the
    same shape as hooks.install_all, so §5.4's teardown is uniform.

    Both mechanisms are installed. The signal is the fast path; the timer is
    the one that still works when the signal's signature has drifted out from
    under us, which §5.10 treats as likely rather than hypothetical.
    """
    registry = _history_registry()
    if registry is None:
        return []

    # Start from whatever is already recorded, so a plugin load does not
    # re-import the user's entire back catalogue as though it just happened.
    existing = _query_entries(registry)
    start_from = 0
    for entry in existing:
        numeric = _as_int(_unpack_entry(entry)[0])
        if numeric is not None:
            start_from = max(start_from, numeric)

    observer = HistoryObserver(engine, last_seen_id=start_from)
    undos: list[tuple[str, Callable[[], None]]] = []
    logged_shape = [False]

    def _on_entry_added(*args) -> None:
        """Signal handler. Takes *args because the signature is UNVERIFIED.

        §5.10 — entryAdded's arity and argument order have changed across
        releases. Rather than pin to one of them, unpack_signal_args identifies
        each argument by shape, and the arity is logged the first time so the
        real signature lands in docs/capture_coverage.md §4 instead of being
        guessed at forever.
        """
        try:
            if not logged_shape[0]:
                log(f"history entryAdded delivered {len(args)} argument(s): "
                    f"{[type(a).__name__ for a in args]}. Record this in "
                    f"docs/capture_coverage.md §4 (§5.10).", INFO)
                logged_shape[0] = True

            observer.handle_entry(*unpack_signal_args(*args))
        except Exception as exc:  # noqa: BLE001 — §5.1 [HARD] never raise into Qt
            log_exception("history entryAdded handler", exc)

    try:
        registry.entryAdded.connect(_on_entry_added)
    except Exception as exc:  # noqa: BLE001 — §5.1
        log(f"could not connect entryAdded ({type(exc).__name__}: {exc}) — "
            f"the polling fallback below still covers this channel (§5.10)", WARNING)
    else:
        def disconnect() -> None:
            try:
                registry.entryAdded.disconnect(_on_entry_added)
            except Exception as exc:  # noqa: BLE001 — §5.4 must not strand teardown
                log_exception("disconnecting entryAdded", exc)

        undos.append(("disconnect the history signal", disconnect))
        log("history entryAdded connected (channel 3)", INFO)

    timer_undo = _install_poll_timer(registry, observer)
    if timer_undo is not None:
        undos.append(("stop the history polling timer", timer_undo))

    return undos


def _install_poll_timer(registry, observer: HistoryObserver):
    """QTimer sweeping for entries the signal missed. Returns the stop, or None."""
    try:
        from qgis.PyQt.QtCore import QTimer
    except Exception as exc:  # noqa: BLE001 — §5.1
        log_exception("history polling timer not installed", exc)
        return None

    timer = QTimer()
    timer.setInterval(POLL_INTERVAL_MS)

    def sweep() -> None:
        try:
            handled = observer.poll(_query_entries(registry))
            if handled:
                log(f"history sweep picked up {handled} run(s) the signal "
                    f"did not deliver (§5.10)", INFO)
        except Exception as exc:  # noqa: BLE001 — §5.1 [HARD]
            log_exception("history polling sweep", exc)

    timer.timeout.connect(sweep)
    timer.start()
    log(f"history polling fallback started ({POLL_INTERVAL_MS} ms)", INFO)

    def stop() -> None:
        try:
            timer.stop()
            timer.timeout.disconnect(sweep)
        except Exception as exc:  # noqa: BLE001 — §5.4
            log_exception("stopping the history polling timer", exc)

    return stop
