"""Logging fallback — RULES.md §5.1.

Capture code logs from inside a broad try/except and must not care whether it
is running under QGIS, pytest, or a demo script. If "log" silently does nothing
outside QGIS, the except block swallows the one message that would have
explained the failure.
"""

from __future__ import annotations

import logging

import pytest

from geoprovenance import log as log_module


def test_logging_outside_qgis_reaches_stdlib(caplog):
    with caplog.at_level(logging.INFO, logger="geoprovenance"):
        log_module.log("capture engine started")
    assert "capture engine started" in caplog.text


def test_each_level_maps_to_a_stdlib_level(caplog):
    with caplog.at_level(logging.DEBUG, logger="geoprovenance"):
        log_module.log("routine", log_module.INFO)
        log_module.log("odd", log_module.WARNING)
        log_module.log("bad", log_module.CRITICAL)

    levels = [record.levelno for record in caplog.records]
    assert levels == [logging.INFO, logging.WARNING, logging.ERROR]


def test_an_unknown_level_is_rejected():
    with pytest.raises(ValueError, match="level must be one of"):
        log_module.log("hello", "catastrophic")


def test_a_swallowed_exception_is_logged_with_its_traceback(caplog):
    """§5.1 — the exception never reaches the user, so the log is the only
    record of it. A message without a traceback is not debuggable three weeks
    later."""
    try:
        raise ValueError("parameter was a QgsProperty")
    except ValueError as exc:
        with caplog.at_level(logging.ERROR, logger="geoprovenance"):
            log_module.log_exception("normalising parameters", exc)

    assert "normalising parameters" in caplog.text
    assert "ValueError: parameter was a QgsProperty" in caplog.text
    assert "Traceback" in caplog.text
    assert "test_log.py" in caplog.text  # the frame, not just the message
