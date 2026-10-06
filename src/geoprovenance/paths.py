"""Where the provenance database lives.

Owner: Person A.  Sub-phase: A1.

This resolution lives HERE and not in ``storage/`` because the default comes
from ``QgsApplication.qgisSettingsDirPath()`` and RULES.md §4.1 forbids QGIS
imports under ``storage/``. ``ProvenanceStore`` takes an explicit path for
exactly this reason.

    §4.8 [HARD] — the database location defaults to the plugin profile
    directory and is overridable per project, and the override must be ONE
    configuration value. Phase 2 points Person C's viewer and audit engine at
    the live database by changing exactly one thing; if that turns into three
    things, integration week gets longer.

The one value is the QSettings key below. Empty or unset means "use the
default". Nothing else may influence the path.
"""

from __future__ import annotations

import pathlib

#: The single override (§4.8). Empty string = use the profile default.
SETTINGS_KEY = "GeoProvenance/database_path"

#: Subdirectory of the QGIS profile, and the database filename inside it.
PROFILE_SUBDIR = "geoprovenance"
DB_FILENAME = "provenance.db"


class QgisUnavailableError(RuntimeError):
    """The default path was requested outside a QGIS process."""


def qgis_profile_dir() -> pathlib.Path:
    """The active QGIS profile directory. Requires a running QGIS."""
    try:
        from qgis.core import QgsApplication
    except ImportError as exc:  # pragma: no cover — needs a non-QGIS process
        raise QgisUnavailableError(
            "The default database location comes from QGIS "
            "(QgsApplication.qgisSettingsDirPath()) and QGIS is not importable "
            "here. Pass an explicit path instead — that is what the demos and "
            "the storage test suite do."
        ) from exc
    return pathlib.Path(QgsApplication.qgisSettingsDirPath())


def default_db_path() -> pathlib.Path:
    """``<qgis profile>/geoprovenance/provenance.db``. Requires QGIS."""
    return qgis_profile_dir() / PROFILE_SUBDIR / DB_FILENAME


def resolve_db_path(override=None, settings=None) -> pathlib.Path:
    """The database path to use, in priority order (§4.8).

    1. ``override`` — an explicit path, for tests, demos and experiments.
    2. The single QSettings key, if it holds a non-empty value.
    3. The QGIS profile default.

    ``settings`` is anything with a ``value(key, default)`` method — a real
    ``QSettings`` in the plugin, a stand-in in tests. Passing it in rather than
    constructing one keeps this function testable with no QGIS present, which
    matters because this is the value Phase 2 hinges on.
    """
    if override:
        return pathlib.Path(override).expanduser()

    if settings is not None:
        configured = settings.value(SETTINGS_KEY, "")
        if configured:
            return pathlib.Path(str(configured)).expanduser()

    return default_db_path()
