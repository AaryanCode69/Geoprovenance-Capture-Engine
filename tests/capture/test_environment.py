"""Environment probe — the record of what this machine was running (A6).

No QGIS. The probe reaches QGIS through ``from qgis import utils``, so a
stand-in module in ``sys.modules`` is enough to exercise every branch — which
matters, because this is the one part of the agent record that cannot be
verified against a real build on this machine (§11.4).

What is being defended: §4.6 (one agent row per distinct environment) is only
as good as this dict. A probe that raises would take the user's run down with
it (§5.1); a probe that returns nothing loses the environment record entirely.
"""

from __future__ import annotations

import sys
import types

import pytest

from geoprovenance.capture import environment


def _install_fake_qgis(monkeypatch, *, available=None, active=None, versions=None,
                       explode_on=()):
    """Put a stand-in ``qgis.utils`` where the probe will import it."""
    utils = types.ModuleType("qgis.utils")
    if available is not None:
        utils.available_plugins = available
    if active is not None:
        utils.active_plugins = active

    def plugin_metadata(name, key):
        if name in explode_on:
            raise RuntimeError(f"{name} has a broken metadata.txt")
        return (versions or {}).get(name)

    utils.pluginMetadata = plugin_metadata

    qgis = types.ModuleType("qgis")
    qgis.utils = utils
    monkeypatch.setitem(sys.modules, "qgis", qgis)
    monkeypatch.setitem(sys.modules, "qgis.utils", utils)
    return utils


def test_every_installed_plugin_is_recorded_not_only_the_loaded_ones(monkeypatch):
    """The closed contract decision (docs/CONTRACT_event.md, 18 Aug 2026), and
    the A6 change: a plugin that was merely present can still have changed the
    result, so it belongs in the environment record."""
    _install_fake_qgis(
        monkeypatch,
        available=["GeoProvenance", "QuickMapServices", "pluginreloader"],
        active=["GeoProvenance"],
        versions={"GeoProvenance": "0.1.0", "QuickMapServices": "0.19.29",
                  "pluginreloader": "0.9.3"},
    )
    assert environment.plugin_versions() == {
        "GeoProvenance": "0.1.0",
        "QuickMapServices": "0.19.29",
        "pluginreloader": "0.9.3",
    }


def test_an_older_build_falls_back_to_the_loaded_set(monkeypatch):
    """A narrower answer beats no answer — the loaded set is a strict subset."""
    _install_fake_qgis(monkeypatch, active=["GeoProvenance"],
                       versions={"GeoProvenance": "0.1.0"})
    assert environment.plugin_versions() == {"GeoProvenance": "0.1.0"}


def test_one_broken_plugin_does_not_cost_us_the_others(monkeypatch):
    """§5.1 — a third-party plugin's bad metadata is not our failure to have."""
    _install_fake_qgis(
        monkeypatch,
        available=["GeoProvenance", "brokenplugin"],
        versions={"GeoProvenance": "0.1.0"},
        explode_on=("brokenplugin",),
    )
    assert environment.plugin_versions() == {"GeoProvenance": "0.1.0"}


def test_a_plugin_qgis_cannot_read_is_left_out_rather_than_guessed(monkeypatch):
    """§5.6 — QGIS returns the literal '__error__' when it cannot read the
    version. Recording that string as a version would poison the fingerprint."""
    _install_fake_qgis(
        monkeypatch,
        available=["GeoProvenance", "mystery"],
        versions={"GeoProvenance": "0.1.0", "mystery": "__error__"},
    )
    assert environment.plugin_versions() == {"GeoProvenance": "0.1.0"}


def test_no_qgis_at_all_is_an_empty_answer_not_a_crash(monkeypatch):
    """This is the machine the demos and the whole storage suite run on."""
    monkeypatch.setitem(sys.modules, "qgis", None)
    assert environment.plugin_versions() == {}


def test_the_probe_reports_measured_values_only():
    """§2.6 — nothing here is hardcoded. Off QGIS the version is 'unknown',
    said out loud, rather than a plausible-looking number."""
    probe = environment.probe()
    assert set(probe) == {"qgis_version", "os_info", "python_version",
                          "plugin_versions"}
    assert probe["qgis_version"] == environment.UNKNOWN
    assert probe["python_version"] == ".".join(
        str(part) for part in sys.version_info[:3]
    )
    assert probe["os_info"] != environment.UNKNOWN
