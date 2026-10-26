"""Registry snapshot — which Processing algorithms this QGIS offers (C9).

Owner: Person A.  Added 24 Oct 2026 for schema v3 (CLAIMS_TO_IMPLEMENT.md C9).

    Imports no QGIS at module level: `build_snapshot` duck-types the algorithm
    objects, so it is tested with fakes, and `record_snapshot` reaches for the
    live registry lazily and does nothing outside QGIS.

Why a snapshot is stored at all
    Two of the audit's five checks — is the algorithm still there, does it still
    accept these parameters — need a Processing registry. Outside QGIS there is
    none, so before v3 those checks could never be evaluated from the database
    alone. A snapshot written whenever the plugin is active lets an audit run
    later, anywhere, answer them for the last installation that opened the
    database. It cannot answer them for an installation that never did, and
    the audit does not pretend to.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..log import INFO, log, log_exception
from . import environment
from .engine import agent_kwargs


def build_snapshot(algorithms: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """{algorithm id: {"provider": id, "parameters": [names]}} for each algorithm."""
    snapshot: dict[str, dict[str, Any]] = {}
    for algorithm in algorithms:
        try:
            algorithm_id = str(algorithm.id())
            provider = algorithm.provider()
            snapshot[algorithm_id] = {
                "provider": str(provider.id()) if provider is not None else None,
                "parameters": sorted(
                    str(definition.name())
                    for definition in algorithm.parameterDefinitions()
                ),
            }
        except Exception as exc:  # noqa: BLE001 — one odd algorithm must not cost the rest
            log_exception("could not read one algorithm for the registry snapshot", exc)
    return snapshot


def record_snapshot(store, algorithms: Iterable[Any] | None = None) -> str | None:
    """Write a snapshot of the live registry. Never raises; None if not possible."""
    try:
        if algorithms is None:
            try:
                from qgis.core import QgsApplication
            except ImportError:
                return None
            algorithms = QgsApplication.processingRegistry().algorithms()
        snapshot = build_snapshot(algorithms)
        if not snapshot:
            return None
        agent_id = store.get_or_create_agent(**agent_kwargs(environment.probe()))
        snapshot_id = store.add_registry_snapshot(agent_id=agent_id, algorithms=snapshot)
        log(f"registry snapshot recorded ({len(snapshot)} algorithms)", INFO)
        return snapshot_id
    except Exception as exc:  # noqa: BLE001 — §5.1
        log_exception("registry snapshot", exc)
        return None
