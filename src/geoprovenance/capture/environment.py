"""Environment probe — the PROV Agent record for this machine and software set.

Owner: Person A.  Sub-phase: A3 (working), hardened in A6.

Degrades outside QGIS rather than failing, for the same reason the normalizer
imports no QGIS: it keeps the capture path runnable — and therefore testable
and demonstrable — on a machine with no QGIS installed.

    §4.6  Feeds ProvenanceStore.get_or_create_agent(), which de-duplicates on
          the FULL environment fingerprint. One agent row per distinct
          environment, reused across activities. A fresh agent row per
          execution would inflate our own RQ2 storage numbers with a bug of
          our own making (§8.6).
    §2.6  Report real measured values. Never hardcode "Ubuntu 22.04" as though
          it had been verified.
"""

from __future__ import annotations

import platform
import sys

UNKNOWN = "unknown"


def qgis_version() -> str:
    try:
        from qgis.core import Qgis
    except ImportError:
        return UNKNOWN
    try:
        return str(Qgis.QGIS_VERSION).split("-")[0].strip()
    except Exception:  # noqa: BLE001 — §5.1, a probe must never break capture
        return UNKNOWN


def os_info() -> str:
    try:
        return platform.platform()
    except Exception:  # noqa: BLE001
        return UNKNOWN


def python_version() -> str:
    return ".".join(str(part) for part in sys.version_info[:3])


def plugin_versions() -> dict[str, str]:
    """Installed plugin names and versions.

    The contract decision is CLOSED (docs/CONTRACT_event.md, 18 Aug 2026):
    **every installed plugin**, not only those that took part in the run. A
    plugin that was merely present can still have changed the result — it may
    have registered a Processing provider or shadowed an algorithm id — so it
    belongs in §4.6's environment fingerprint.

    Widened to ``available_plugins`` in A6 (19 Aug 2026), from
    ``active_plugins`` — the *loaded* set — which A4 shipped and flagged as
    not matching the decision. Done once and deliberately, because it changes
    every environment fingerprint from here on: agent rows written before and
    after this change describe the same machine but will not be the same row
    (§4.6). Recorded in docs/capture_coverage.md §4 so an RQ2 agent-row count
    is not compared naively across the boundary.

    UNVERIFIED (§11.4): no QGIS on this machine, so the attribute names are
    from the API docs and have never been read from a running build. Both the
    fallback and the per-plugin try/except exist for that reason — an
    environment probe that raises would take the user's run down with it
    (§5.1), and a probe that returns nothing loses the whole agent record.
    """
    try:
        from qgis import utils as qgis_utils
    except ImportError:
        return {}

    installed = getattr(qgis_utils, "available_plugins", None)
    if not installed:
        # Older build, or the attribute is not what the docs say. The loaded
        # set is a strict subset and a narrower answer beats no answer.
        installed = getattr(qgis_utils, "active_plugins", None)

    versions: dict[str, str] = {}
    try:
        for name in list(installed or []):
            try:
                metadata = qgis_utils.pluginMetadata(name, "version")
            except Exception:  # noqa: BLE001 — one bad plugin must not stop the probe
                continue
            if metadata and metadata != "__error__":
                versions[name] = str(metadata)
    except Exception:  # noqa: BLE001
        return versions
    return versions


def probe() -> dict:
    """The ``agent`` block of the event dict (docs/CONTRACT_event.md)."""
    return {
        "qgis_version": qgis_version(),
        "os_info": os_info(),
        "python_version": python_version(),
        "plugin_versions": plugin_versions(),
    }
