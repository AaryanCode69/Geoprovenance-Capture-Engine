"""Logging that works inside QGIS and outside it.

Owner: Person A.  Sub-phase: A1.

Capture code must be able to log from inside a Processing hook without caring
whether it is running under QGIS, under pytest, or inside a demo script:

    §5.1 [HARD] — every code path inside a hook is wrapped in a broad
    try/except that LOGS and returns normally. A capture failure must be
    invisible to the person using QGIS.

"Logs" has to mean something in all three environments, or the except block
quietly swallows the one message that would have explained the failure.
"""

from __future__ import annotations

import logging

LOG_TAG = "GeoProvenance"

_fallback = logging.getLogger("geoprovenance")

INFO = "info"
WARNING = "warning"
CRITICAL = "critical"

_STDLIB_LEVELS = {
    INFO: logging.INFO,
    WARNING: logging.WARNING,
    CRITICAL: logging.ERROR,
}


def log(message: str, level: str = INFO) -> None:
    """Write to the QGIS message log, or to stdlib logging outside QGIS."""
    if level not in _STDLIB_LEVELS:
        raise ValueError(f"level must be one of {sorted(_STDLIB_LEVELS)}, got {level!r}")
    try:
        from qgis.core import Qgis, QgsMessageLog
    except ImportError:
        _fallback.log(_STDLIB_LEVELS[level], "%s", message)
        return

    qgis_level = {
        INFO: Qgis.Info,
        WARNING: Qgis.Warning,
        CRITICAL: Qgis.Critical,
    }[level]
    QgsMessageLog.logMessage(message, LOG_TAG, qgis_level)


def log_exception(context: str, exc: BaseException) -> None:
    """Report a swallowed exception (§5.1) with enough detail to debug it.

    Used by the broad try/except blocks in capture code. The traceback goes to
    the log so the failure is diagnosable, while the user's processing run
    continues undisturbed.
    """
    import traceback

    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log(f"{context}: {type(exc).__name__}: {exc}\n{detail}", CRITICAL)
