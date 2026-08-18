"""Symlink the plugin into the QGIS dev profile.

Owner: Person A.  Sub-phase: A1.

    make deploy      link  <repo>/geoprovenance -> <profile>/python/plugins/
    make undeploy    remove the link
    make qgis        launch QGIS on the dev profile

A symlink rather than a copy, so editing a file in the repo and hitting Plugin
Reloader in QGIS picks the change up immediately — no deploy step in the
edit/reload loop.

    RULES.md §2.4 [HARD] — never develop against your normal QGIS profile. A
    crash in capture code must not take out a working QGIS installation. This
    script refuses to touch any profile but the dev one.
"""

from __future__ import annotations

import argparse
import pathlib
import platform
import sys

PLUGIN_DIR_NAME = "geoprovenance"
DEV_PROFILE = "geoprov-dev"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / PLUGIN_DIR_NAME


def profiles_root() -> pathlib.Path:
    """Where QGIS 3 keeps its profiles on this platform."""
    home = pathlib.Path.home()
    system = platform.system()
    if system == "Linux":
        return home / ".local/share/QGIS/QGIS3/profiles"
    if system == "Darwin":
        return home / "Library/Application Support/QGIS/QGIS3/profiles"
    if system == "Windows":
        return home / "AppData/Roaming/QGIS/QGIS3/profiles"
    raise SystemExit(f"unsupported platform: {system}")


def target_dir(profile: str) -> pathlib.Path:
    return profiles_root() / profile / "python" / "plugins"


def deploy(profile: str) -> int:
    if profile != DEV_PROFILE:
        raise SystemExit(
            f"refusing to deploy into profile {profile!r}. RULES.md §2.4: "
            f"development happens in {DEV_PROFILE!r} so a crash cannot take out "
            f"your working QGIS. Pass --profile {DEV_PROFILE}, or use "
            f"--i-know-what-i-am-doing."
        )
    return _link(profile)


def _link(profile: str) -> int:
    plugins = target_dir(profile)
    plugins.mkdir(parents=True, exist_ok=True)
    link = plugins / PLUGIN_DIR_NAME

    if link.is_symlink() or link.exists():
        if link.is_symlink() and link.resolve() == SOURCE.resolve():
            print(f"already linked: {link} -> {SOURCE}")
            return 0
        raise SystemExit(
            f"{link} already exists and is not a link to this checkout.\n"
            f"Remove it yourself if that is what you want — this script will "
            f"not delete something it did not create."
        )

    try:
        link.symlink_to(SOURCE, target_is_directory=True)
    except OSError as exc:
        raise SystemExit(
            f"could not create the symlink: {exc}\n"
            f"On Windows this needs Developer Mode or an elevated shell."
        ) from exc

    print(f"linked {link} -> {SOURCE}")
    print()
    print("Next:")
    print(f"  1. qgis --profile {profile}")
    print("  2. Plugins > Manage and Install Plugins > Installed > tick GeoProvenance")
    print("  3. Install 'Plugin Reloader' too — then editing a file here and")
    print("     hitting its reload button picks the change up with no restart.")
    return 0


def undeploy(profile: str) -> int:
    link = target_dir(profile) / PLUGIN_DIR_NAME
    if not link.is_symlink():
        if link.exists():
            raise SystemExit(f"{link} exists but is not a symlink — leaving it alone.")
        print(f"nothing to remove at {link}")
        return 0
    link.unlink()
    print(f"removed {link}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("link", "unlink", "where"))
    parser.add_argument("--profile", default=DEV_PROFILE)
    parser.add_argument("--i-know-what-i-am-doing", action="store_true",
                        help="allow a profile other than the dev one (§2.4)")
    args = parser.parse_args(argv)

    if args.action == "where":
        print(f"repo plugin : {SOURCE}")
        print(f"profiles    : {profiles_root()}")
        print(f"would link  : {target_dir(args.profile) / PLUGIN_DIR_NAME}")
        return 0
    if args.action == "unlink":
        return undeploy(args.profile)
    if args.i_know_what_i_am_doing:
        return _link(args.profile)
    return deploy(args.profile)


if __name__ == "__main__":
    sys.exit(main())
