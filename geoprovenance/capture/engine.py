"""ProvenanceCaptureEngine — the singleton both capture channels report into.

Owner: Person A.  Sub-phase: A3 (one algorithm end-to-end), extended in A4-A6.

    THIS MODULE IMPORTS NO QGIS. Same reasoning as the normalizer: it keeps the
    write path testable, and it is what lets the Review 1 demo exercise the
    real capture code rather than replaying a recorded blob.

    The QGIS-facing surface is capture/hooks.py, which is a thin adapter that
    pulls parameter definitions off a QgsProcessingAlgorithm and calls in here.

Rules implemented
    §5.1 [HARD]  record_algorithm_execution() never raises. A capture failure
                 must be invisible to the person using QGIS. Losing one record
                 is acceptable; aborting a user's real analysis is not.
    §4.3 [HARD]  One execution is ONE transaction. A half-written execution —
                 an activities row with no relations — silently corrupts
                 Person C's graph traversal and is worse than capturing
                 nothing.
    §4.6         One agent row per distinct environment.
    §4.10        Failed and cancelled runs are persisted, never dropped.
    §5.9         First channel wins; the second increments corroborations.

Phase 2 seam
    Person B's fingerprinter is called from here at two moments — inputs before
    execution, outputs after (research doc §5.3). Run hashing on a background
    thread or after the transaction commits so it never adds latency to the
    user's run, and attribute its cost to B, not to A (§8.5).
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from ..log import CRITICAL, INFO, log, log_exception
from ..storage.store import ProvenanceStore, utc_now_iso
from . import environment, normalizer


class CaptureResult:
    """What happened to one observed execution. Returned for logging and tests."""

    __slots__ = ("activity_id", "recorded", "corroborated", "reason")

    def __init__(self, activity_id=None, recorded=False, corroborated=False, reason=None):
        self.activity_id = activity_id
        self.recorded = recorded            # a new activity row was written
        self.corroborated = corroborated    # the other channel had it already
        self.reason = reason                # set when nothing was written

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return (f"CaptureResult(activity_id={self.activity_id!r}, "
                f"recorded={self.recorded}, corroborated={self.corroborated}, "
                f"reason={self.reason!r})")


class ProvenanceCaptureEngine:
    """Receives observed executions from both channels and persists them."""

    _instance: "ProvenanceCaptureEngine | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, store: ProvenanceStore, session_id: str | None = None):
        self.store = store
        self.session_id = session_id or str(uuid.uuid4())
        self._agent_cache: dict[str, str] = {}

    # -- singleton ---------------------------------------------------------
    #
    # The post-execution hook script runs in its own namespace with no
    # reference to the plugin object, so it needs a way to find the live
    # engine. That is the whole reason this is a singleton.

    @classmethod
    def instance(cls) -> "ProvenanceCaptureEngine | None":
        """The active engine, or None when the plugin is not loaded."""
        return cls._instance

    @classmethod
    def set_instance(cls, engine: "ProvenanceCaptureEngine | None") -> None:
        with cls._instance_lock:
            cls._instance = engine

    @classmethod
    def start(cls, store: ProvenanceStore, session_id: str | None = None):
        engine = cls(store, session_id)
        cls.set_instance(engine)
        return engine

    @classmethod
    def stop(cls) -> None:
        """Clear the singleton. Registered on the plugin's cleanup stack (§5.4)."""
        cls.set_instance(None)

    # -- the QGIS-facing entry point ---------------------------------------

    def record_algorithm_execution(
        self,
        *,
        algorithm_id: str,
        parameters: dict | None = None,
        parameter_definitions: dict[str, str] | None = None,
        results: Any = None,
        algorithm_name: str | None = None,
        provider: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        status: str = "completed",
        source: str = "post_hook",
        execution_log: str | None = None,
        agent: dict | None = None,
    ) -> CaptureResult:
        """Observe one algorithm execution. NEVER RAISES (§5.1).

        This is what the post-execution hook and the processing.run wrapper
        both call. Every failure inside it is logged and swallowed: a capture
        bug must not surface as a failed analysis for the user.
        """
        try:
            event = normalizer.build_event(
                algorithm_id=algorithm_id,
                algorithm_name=algorithm_name,
                provider=provider,
                session_id=self.session_id,
                started_at=started_at or utc_now_iso(),
                ended_at=ended_at,
                status=status,
                source=source,
                parameters=parameters,
                parameter_definitions=parameter_definitions,
                results=results,
                execution_log=execution_log,
                agent=agent or environment.probe(),
            )
            return self.record_event(event)
        except Exception as exc:  # noqa: BLE001 — §5.1 [HARD]
            log_exception(f"capture failed for {algorithm_id}", exc)
            return CaptureResult(reason=f"{type(exc).__name__}: {exc}")

    # -- persistence -------------------------------------------------------

    def record_event(self, event: dict) -> CaptureResult:
        """Write one event to the database.

        Raises on failure — the swallowing happens one level up in
        record_algorithm_execution (§5.1), so tests and the demo can see real
        errors instead of a silent no-op.
        """
        key = normalizer.dedup_key(
            event["algorithm_id"], event.get("parameters"), event["started_at"]
        )

        # §5.9 — first channel wins. The second corroborates and does not insert.
        existing = self.store.find_activity_by_dedup_key(key)
        if existing is not None:
            count = self.store.increment_corroboration(existing["id"])
            log(f"corroborated {event['algorithm_id']} via {event['source']} "
                f"(now {count})", INFO)
            return CaptureResult(activity_id=existing["id"], corroborated=True)

        agent_id = self._agent_row(event["agent"])

        # §4.3 [HARD] — the activity, its datasets and all its relations land
        # together or not at all.
        with self.store.transaction():
            activity_id = self.store.add_activity(
                algorithm_id=event["algorithm_id"],
                algorithm_name=event.get("algorithm_name"),
                provider=event.get("provider"),
                session_id=event["session_id"],
                started_at=event["started_at"],
                ended_at=event.get("ended_at"),
                parameters=event.get("parameters") or {},
                status=event.get("status", "completed"),
                execution_log=event.get("execution_log"),
                capture_channel=event.get("source"),
                dedup_key=key,
            )

            for layer in event.get("inputs") or []:
                entity_id = self._entity_for_input(layer)
                self.store.add_relation(
                    relation_type="used", source_id=activity_id, target_id=entity_id,
                    role="overlay" if layer["param"] == "OVERLAY" else "input",
                    qgis_param_key=layer["param"],
                )

            for layer in event.get("outputs") or []:
                entity_id = self._entity_for_output(layer)
                self.store.add_relation(
                    relation_type="wasGeneratedBy", source_id=entity_id,
                    target_id=activity_id, role="output",
                    qgis_param_key=layer["param"],
                )

            self.store.add_relation(
                relation_type="wasAssociatedWith",
                source_id=activity_id, target_id=agent_id,
            )

        log(f"recorded {event['algorithm_id']} "
            f"({len(event.get('inputs') or [])} in, "
            f"{len(event.get('outputs') or [])} out) via {event['source']}", INFO)
        return CaptureResult(activity_id=activity_id, recorded=True)

    def _agent_row(self, agent: dict) -> str:
        """§4.6 — one row per distinct environment, reused across activities.

        Cached in-process as well, because the environment cannot change during
        a QGIS session and a SELECT per execution is measurable overhead in the
        RQ2 numbers we are about to publish.
        """
        cache_key = repr(sorted((agent or {}).items(), key=lambda kv: kv[0]))
        cached = self._agent_cache.get(cache_key)
        if cached is not None:
            return cached

        agent_id = self.store.get_or_create_agent(
            qgis_version=(agent or {}).get("qgis_version"),
            os_info=(agent or {}).get("os_info"),
            python_version=(agent or {}).get("python_version"),
            plugin_versions=(agent or {}).get("plugin_versions"),
        )
        self._agent_cache[cache_key] = agent_id
        return agent_id

    def _entity_for_input(self, layer: dict) -> str:
        """The dataset a job read. Reuses the latest recorded version.

        Reading a file does not create a new version of it — the bytes we read
        are the bytes already on record (Appendix B.1).
        """
        if layer["path"]:
            existing = self.store.find_entity_by_path(layer["path"])
            if existing is not None:
                return existing["id"]
        return self._new_entity(layer, content_version=1)

    def _entity_for_output(self, layer: dict) -> str:
        """The dataset a job wrote. A write always makes a new version.

        ``OPEN:`` (docs/CONTRACT_schema.md decision 1) — this is the *structural*
        policy: every write bumps content_version, whether or not the bytes
        changed. The alternative is to bump only when Person B's fingerprint
        differs, which is more accurate but needs an async correction after the
        row is already written. A3 takes the structural option so the write
        path is complete and correct on its own; the decision is still due
        before contract-v1.
        """
        if layer["path"]:
            return self._new_entity(
                layer, content_version=self.store.next_content_version(layer["path"])
            )
        return self._new_entity(layer, content_version=1)

    def _new_entity(self, layer: dict, *, content_version: int) -> str:
        label = layer.get("label")
        if not label:
            path = layer.get("path")
            label = path.rsplit("/", 1)[-1] if path else f"{layer['param']} (temporary)"
        return self.store.add_entity(
            entity_type="dataset",
            label=label,
            file_path=layer.get("path"),
            content_version=content_version,
            format=layer.get("format"),
            crs=layer.get("crs"),
            layer_type=layer.get("layer_type") or "unknown",
            metadata={"feature_count": layer["feature_count"]}
            if layer.get("feature_count") is not None else None,
        )

    # -- diagnostics -------------------------------------------------------

    def summary(self) -> dict:
        """Row counts, for the plugin's info dialog and the RQ2 measurement."""
        try:
            return self.store.counts()
        except Exception as exc:  # noqa: BLE001 — §5.1
            log(f"could not read counts: {exc}", CRITICAL)
            return {}
