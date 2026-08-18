"""Shared pytest configuration.

Two suites, kept strictly separate (RULES.md §6.1):

    tests/storage/   pure sqlite3 + pytest, NO QGIS import at all, runs anywhere.
    tests/capture/   runs under pytest-qgis.

Run them separately, via the Makefile:

    make test-storage    # works on any machine, no QGIS needed
    make test-capture    # needs QGIS + pytest-qgis

Do NOT run `pytest tests/storage` directly (RULES.md §6.1.1). pytest-qgis
registers a pytest11 entrypoint that imports qgis.core at plugin-load time,
before any conftest runs, so a bare invocation crashes on a machine without
QGIS -- and on a machine WITH QGIS it silently masks §4.1 violations.
`make test-storage` passes `-p no:pytest_qgis`.

Gate counts (RULES.md §6.2): 15+ storage tests by end of A2, 5+ capture tests by
Review 1, 25+ total by Phase 1 exit.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"

# Import geoprovenance from the working tree without installing it.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
