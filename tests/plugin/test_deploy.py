"""Finding the QGIS profile directory.

No QGIS. This is the one piece of tooling whose failure mode is SILENT: get the
profile root wrong and `make deploy` prints success, creates a real symlink, and
QGIS shows no plugin at all because it never looks there.

    26 Aug 2026 — that is exactly what happened. The root was hardcoded to
    `QGIS3`; QGIS 4.2.1 keeps its profiles under `QGIS4`. The plugin was absent
    from the Plugin Manager with no error anywhere, and the 11 QGIS lifecycle
    tests did not catch it because pytest imports the plugin straight from the
    repo via PYTHONPATH and never touches the profile directory.

Every test here builds a fake home directory in tmp_path and asks the real
discovery code what it would do with it, so the machine running the suite does
not have to have QGIS installed at all (RULES.md §6.1).
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import deploy  # noqa: E402


FLATPAK = ".var/app/org.qgis.qgis/data/QGIS"
NATIVE = ".local/share/QGIS"


def _make_root(home: pathlib.Path, base: str, major: int, *, profile="geoprov-dev",
               used: bool = False) -> pathlib.Path:
    """Create `<home>/<base>/QGIS<major>/profiles/<profile>/`.

    ``used`` writes the settings file QGIS itself leaves behind on first start,
    which is how the tool tells a tree QGIS uses from one we made ourselves.
    """
    profiles = home / base / f"QGIS{major}" / "profiles"
    (profiles / profile).mkdir(parents=True, exist_ok=True)
    if used:
        settings = profiles / profile / "QGIS"
        settings.mkdir(parents=True, exist_ok=True)
        (settings / f"QGIS{major}.ini").write_text("[General]\n")
    return profiles


# ===========================================================================
# discovery
# ===========================================================================

def test_a_profile_root_is_never_assumed_to_be_qgis3(tmp_path, monkeypatch):
    """The regression test for 26 Aug 2026.

    A machine whose ONLY QGIS is version 4 must resolve to the QGIS4 tree. The
    old code returned a QGIS3 path here — a directory that does not exist and
    that QGIS would never read.
    """
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 4, used=True)

    chosen = deploy.profiles_root(home=tmp_path)

    assert "QGIS4" in str(chosen)
    assert "QGIS3" not in str(chosen)


def test_the_newest_qgis_wins_when_several_are_present(tmp_path, monkeypatch):
    """Both trees exist on the development machine: QGIS3 from an older deploy,
    QGIS4 from the QGIS that actually runs. `make qgis` launches the newest, so
    that is where the plugin has to go."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 3)
    _make_root(tmp_path, FLATPAK, 4, used=True)

    assert "QGIS4" in str(deploy.profiles_root(home=tmp_path))


def test_an_older_qgis_alone_still_resolves(tmp_path, monkeypatch):
    """The fix must not break the 3.x machines this project actually targets."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 3, used=True)

    assert "QGIS3" in str(deploy.profiles_root(home=tmp_path))


def test_discovery_reports_which_root_qgis_has_actually_used(tmp_path, monkeypatch):
    """`used` is evidence, not inference — it is the only thing that separates
    the tree QGIS writes to from one an earlier deploy created by itself."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 3)            # ours, never launched
    _make_root(tmp_path, FLATPAK, 4, used=True)  # QGIS's

    roots = {r.major: r for r in deploy.discover_profile_roots(home=tmp_path)}

    assert roots[4].used is True
    assert roots[3].used is False


def test_the_native_location_is_found_too(tmp_path, monkeypatch):
    """Not every QGIS is a flatpak."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, NATIVE, 4, used=True)

    assert str(deploy.profiles_root(home=tmp_path)).startswith(
        str(tmp_path / NATIVE)
    )


def test_roots_come_back_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    for major in (3, 4, 2):
        _make_root(tmp_path, FLATPAK, major)

    majors = [r.major for r in deploy.discover_profile_roots(home=tmp_path)]

    assert majors == [4, 3, 2]


def test_a_directory_that_is_not_a_qgis_version_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    (tmp_path / FLATPAK / "QGISbackup" / "profiles").mkdir(parents=True)
    _make_root(tmp_path, FLATPAK, 4, used=True)

    majors = [r.major for r in deploy.discover_profile_roots(home=tmp_path)]

    assert majors == [4]


# ===========================================================================
# refusing to guess
# ===========================================================================

def test_no_qgis_anywhere_says_so_instead_of_guessing(tmp_path, monkeypatch):
    """Guessing a version is the defect. A wrong guess fails silently; a message
    fails loudly (RULES.md §11.4)."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")

    with pytest.raises(SystemExit) as raised:
        deploy.profiles_root(home=tmp_path)

    message = str(raised.value)
    assert "launch qgis once" in message.lower()
    assert "make qgis" in message


def test_an_explicit_major_can_override_the_newest(tmp_path, monkeypatch):
    """For a machine carrying a 3.x LTS alongside a 4.x, where the newest is not
    the one you mean."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 3, used=True)
    _make_root(tmp_path, FLATPAK, 4, used=True)

    assert "QGIS3" in str(deploy.profiles_root(qgis_major=3, home=tmp_path))


def test_asking_for_a_qgis_that_is_not_installed_lists_what_is(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 4, used=True)

    with pytest.raises(SystemExit) as raised:
        deploy.profiles_root(qgis_major=3, home=tmp_path)

    assert "QGIS4" in str(raised.value)


def test_an_explicit_profiles_root_beats_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 4, used=True)
    elsewhere = tmp_path / "somewhere-else"

    assert deploy.profiles_root(str(elsewhere), home=tmp_path) == elsewhere


# ===========================================================================
# linking and unlinking
# ===========================================================================

def test_deploy_refuses_any_profile_but_the_dev_one(tmp_path, monkeypatch):
    """RULES.md §2.4 [HARD] — a crash in capture code must not be able to take
    out a working QGIS."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")

    with pytest.raises(SystemExit) as raised:
        deploy.deploy("default", home=tmp_path)

    assert "§2.4" in str(raised.value)


def test_linking_lands_in_the_newest_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 3)
    _make_root(tmp_path, FLATPAK, 4, used=True)

    deploy.deploy(deploy.DEV_PROFILE, home=tmp_path)

    link = (tmp_path / FLATPAK / "QGIS4" / "profiles" / deploy.DEV_PROFILE
            / "python" / "plugins" / "geoprovenance")
    assert link.is_symlink()
    assert link.resolve() == deploy.SOURCE.resolve()


def test_unlink_sweeps_every_tree_including_the_stale_one(tmp_path, monkeypatch):
    """A machine that has been through a QGIS major upgrade — or through the
    26 Aug defect — carries a link in the older tree too. Leaving it means the
    next person finds two and cannot tell which QGIS reads which."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    old = _make_root(tmp_path, FLATPAK, 3)
    _make_root(tmp_path, FLATPAK, 4, used=True)

    stale = old / deploy.DEV_PROFILE / "python" / "plugins"
    stale.mkdir(parents=True)
    (stale / "geoprovenance").symlink_to(deploy.SOURCE, target_is_directory=True)
    deploy.deploy(deploy.DEV_PROFILE, home=tmp_path)

    deploy.undeploy(deploy.DEV_PROFILE, home=tmp_path)

    assert not (stale / "geoprovenance").is_symlink()
    assert not (tmp_path / FLATPAK / "QGIS4" / "profiles" / deploy.DEV_PROFILE
                / "python" / "plugins" / "geoprovenance").is_symlink()


def test_unlink_leaves_a_link_it_did_not_create(tmp_path, monkeypatch):
    """The script deletes only what it made. Somebody else's plugin of the same
    name is theirs."""
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    root = _make_root(tmp_path, FLATPAK, 4, used=True)
    plugins = root / deploy.DEV_PROFILE / "python" / "plugins"
    plugins.mkdir(parents=True)
    other = tmp_path / "someone-elses-checkout"
    other.mkdir()
    (plugins / "geoprovenance").symlink_to(other, target_is_directory=True)

    deploy.undeploy(deploy.DEV_PROFILE, home=tmp_path)

    assert (plugins / "geoprovenance").is_symlink()


def test_linking_twice_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.platform, "system", lambda: "Linux")
    _make_root(tmp_path, FLATPAK, 4, used=True)

    assert deploy.deploy(deploy.DEV_PROFILE, home=tmp_path) == 0
    assert deploy.deploy(deploy.DEV_PROFILE, home=tmp_path) == 0
