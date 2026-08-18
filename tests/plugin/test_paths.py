"""Database location resolution — RULES.md §4.8.

No QGIS. The override branches are exactly the ones Phase 2 depends on, so
they must be testable without a QGIS process.
"""

from __future__ import annotations

import pathlib

import pytest

from geoprovenance import paths


class RecordingSettings:
    """A stand-in for QSettings that remembers which keys were read.

    Existence is the point of test_only_one_setting_is_consulted below.
    """

    def __init__(self, values: dict[str, str] | None = None):
        self._values = values or {}
        self.reads: list[str] = []

    def value(self, key, default=None):
        self.reads.append(key)
        return self._values.get(key, default)


def test_an_explicit_override_wins():
    assert paths.resolve_db_path("/tmp/explicit.db") == pathlib.Path("/tmp/explicit.db")


def test_the_override_beats_the_setting():
    settings = RecordingSettings({paths.SETTINGS_KEY: "/from/settings.db"})
    assert paths.resolve_db_path("/explicit.db", settings) == pathlib.Path("/explicit.db")


def test_the_setting_is_used_when_there_is_no_override():
    settings = RecordingSettings({paths.SETTINGS_KEY: "/project/prov.db"})
    assert paths.resolve_db_path(settings=settings) == pathlib.Path("/project/prov.db")


def test_a_tilde_in_the_setting_is_expanded():
    settings = RecordingSettings({paths.SETTINGS_KEY: "~/prov.db"})
    resolved = paths.resolve_db_path(settings=settings)
    assert "~" not in str(resolved)
    assert resolved.is_absolute()


def test_only_one_setting_is_consulted():
    """§4.8 [HARD] — the per-project override must be ONE configuration value.

    Phase 2 points Person C's viewer and audit engine at the live database by
    changing exactly one thing. If a second key ever creeps in, integration
    week gets longer and this test is where it should be noticed.
    """
    settings = RecordingSettings({paths.SETTINGS_KEY: "/project/prov.db"})
    paths.resolve_db_path(settings=settings)
    assert set(settings.reads) == {paths.SETTINGS_KEY}


def test_an_empty_setting_falls_through_to_the_default():
    """Empty means "use the profile default", not "use a path called ''"."""
    settings = RecordingSettings({paths.SETTINGS_KEY: ""})
    with pytest.raises(paths.QgisUnavailableError):
        paths.resolve_db_path(settings=settings)


def test_the_default_needs_qgis_and_says_so_clearly():
    """The default comes from QgsApplication.qgisSettingsDirPath(), which is
    why this lives outside storage/ (§4.1). Outside QGIS it must fail with an
    explanation, not an opaque ImportError."""
    with pytest.raises(paths.QgisUnavailableError, match="explicit path"):
        paths.default_db_path()


def test_the_filename_is_stable():
    """B and C reference this location in their setup notes."""
    assert paths.DB_FILENAME == "provenance.db"
    assert paths.PROFILE_SUBDIR == "geoprovenance"
