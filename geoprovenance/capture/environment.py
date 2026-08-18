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

    TODO(A6): PERSON_A.md §A6 wants every installed plugin enumerated. The
    OPEN item in docs/CONTRACT_event.md — every plugin, or only those that
    took part in the run — must close before contract-v1. Every-plugin is
    implemented here because it matches §4.6's environment fingerprint: a
    plugin that was merely *present* can still have changed the result.
    """
    try:
        from qgis import utils as qgis_utils
    except ImportError:
        return {}

    versions: dict[str, str] = {}
    try:
        for name in list(getattr(qgis_utils, "active_plugins", []) or []):
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
