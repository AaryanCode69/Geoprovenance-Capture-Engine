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

Finding the profile directory is the hard part, and getting it wrong fails
SILENTLY — the link is created, `make deploy` prints success, and QGIS shows no
plugin because it never looks there.

    26 Aug 2026 — this is not hypothetical. The profile root was hardcoded to
    `QGIS3`, which is right for QGIS 3.x and wrong for QGIS 4.x, where profiles
    live under `QGIS4/`. On a QGIS 4.2.1 machine the link went into a tree QGIS
    never scans; the plugin was simply absent from the Plugin Manager, with no
    error anywhere. The 11 QGIS lifecycle tests did not catch it because pytest
    imports the plugin from the repo via PYTHONPATH and never goes through the
    profile directory at all.

    So: the QGIS major version is DISCOVERED, never assumed, and when nothing
    can be discovered this script says so instead of guessing (RULES.md §11.4).
    `deploy.py where` prints the whole picture in one command.
"""

from __future__ import annotations

import argparse
import pathlib
import platform
import re
import sys
from typing import NamedTuple

PLUGIN_DIR_NAME = "geoprovenance"
DEV_PROFILE = "geoprov-dev"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / PLUGIN_DIR_NAME

#: QGIS keeps its profiles under a directory named for its MAJOR version —
#: `QGIS3/profiles/<name>` on 3.x, `QGIS4/profiles/<name>` on 4.x.
_MAJOR_DIR = re.compile(r"^QGIS(\d+)$")

# A Flatpak QGIS cannot see ~/.local/share/QGIS — it is sandboxed, and keeps its
# profiles under ~/.var/app/<app-id>/. Linking into the native location would
# silently produce a QGIS with no plugin in it, so the flatpak location is
# probed alongside the native one.
FLATPAK_APP_IDS = ("org.qgis.qgis",)


class ProfileRoot(NamedTuple):
    """One `.../QGIS<N>/profiles` directory found on this machine."""

    path: pathlib.Path
    major: int
    #: QGIS has actually started against this root — it left a settings file
    #: behind. Evidence, not inference: this is what distinguishes the tree
    #: QGIS uses from one an earlier `make deploy` created by itself.
    used: bool

    @property
    def label(self) -> str:
        return f"QGIS{self.major}"


def _native_base(home: pathlib.Path) -> pathlib.Path:
    """Where a normally-installed QGIS keeps its `QGIS<N>` directories."""
    system = platform.system()
    if system == "Linux":
        return home / ".local/share/QGIS"
    if system == "Darwin":
        return home / "Library/Application Support/QGIS"
    if system == "Windows":
        return home / "AppData/Roaming/QGIS"
    raise SystemExit(f"unsupported platform: {system}")


def _bases(home: pathlib.Path) -> list[pathlib.Path]:
    """Every directory that may contain `QGIS<N>/profiles` trees.

    Flatpak first, because a flatpak QGIS cannot read the native location and a
    machine with both should still deploy somewhere QGIS can see.
    """
    bases = []
    for app_id in FLATPAK_APP_IDS:
        app_dir = home / ".var/app" / app_id
        if app_dir.is_dir():
            bases.append(app_dir / "data/QGIS")
    bases.append(_native_base(home))
    return bases


def _has_been_used(profiles: pathlib.Path, major: int) -> bool:
    """Has QGIS itself written into this profiles directory?

    QGIS drops `<profile>/QGIS/QGIS<major>.ini` on first start. Our own
    `make deploy` only ever creates `<profile>/python/plugins/`, so the presence
    of that ini is what separates "the tree QGIS uses" from "a tree we made".
    """
    try:
        children = list(profiles.iterdir())
    except OSError:
        return False
    return any((child / "QGIS" / f"QGIS{major}.ini").exists() for child in children)


def discover_profile_roots(home: pathlib.Path | None = None) -> list[ProfileRoot]:
    """Every QGIS profile root on this machine, newest major version first."""
    home = home or pathlib.Path.home()
    roots: list[ProfileRoot] = []
    seen: set[pathlib.Path] = set()

    for base in _bases(home):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            match = _MAJOR_DIR.match(child.name)
            if not match:
                continue
            profiles = child / "profiles"
            if not profiles.is_dir() or profiles in seen:
                continue
            seen.add(profiles)
            major = int(match.group(1))
            roots.append(ProfileRoot(profiles, major, _has_been_used(profiles, major)))

    # Highest major first: on a machine with both a 3.x and a 4.x tree, the 4.x
    # one is the QGIS that will actually be launched by `make qgis`.
    roots.sort(key=lambda r: r.major, reverse=True)
    return roots


def profiles_root(
    override: str | None = None,
    qgis_major: int | None = None,
    home: pathlib.Path | None = None,
) -> pathlib.Path:
    """Where to deploy, in priority order.

    1. ``override`` — an explicit ``--profiles-root``.
    2. ``qgis_major`` — an explicit ``--qgis-major``, for a machine with more
       than one QGIS where the newest is not the one you mean.
    3. The highest QGIS major version that exists on this machine.

    Never falls back to a guessed version. A profile root that does not exist is
    a question this script cannot answer, and answering it wrongly is the exact
    defect of 26 Aug 2026 — a successful-looking deploy into a tree QGIS never
    reads.
    """
    if override:
        return pathlib.Path(override).expanduser()

    roots = discover_profile_roots(home)

    if qgis_major is not None:
        for root in roots:
            if root.major == qgis_major:
                return root.path
        available = ", ".join(r.label for r in roots) or "none"
        raise SystemExit(
            f"no QGIS{qgis_major} profile directory on this machine "
            f"(found: {available}). Run 'python tools/deploy.py where'."
        )

    if not roots:
        raise SystemExit(
            "cannot find a QGIS profile directory on this machine.\n\n"
            "QGIS creates one the first time it starts, and this script will "
            "not guess which major version you have — guessing is how the "
            "plugin ends up linked into a directory QGIS never reads.\n\n"
            "Launch QGIS once:\n"
            "    make qgis\n"
            "then run 'make deploy' again. If QGIS keeps its profiles somewhere "
            "unusual, pass --profiles-root."
        )

    return roots[0].path


def target_dir(
    profile: str,
    profiles_root_override: str | None = None,
    qgis_major: int | None = None,
    home: pathlib.Path | None = None,
) -> pathlib.Path:
    root = profiles_root(profiles_root_override, qgis_major, home)
    return root / profile / "python" / "plugins"


def deploy(profile: str, profiles_root_override=None, qgis_major=None, home=None) -> int:
    if profile != DEV_PROFILE:
        raise SystemExit(
            f"refusing to deploy into profile {profile!r}. RULES.md §2.4: "
            f"development happens in {DEV_PROFILE!r} so a crash cannot take out "
            f"your working QGIS. Pass --profile {DEV_PROFILE}, or use "
            f"--i-know-what-i-am-doing."
        )
    return _link(profile, profiles_root_override, qgis_major, home)


def _link(profile: str, profiles_root_override=None, qgis_major=None, home=None) -> int:
    plugins = target_dir(profile, profiles_root_override, qgis_major, home)
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
    print(f"  1. make qgis          (launches QGIS on the {profile} profile)")
    print("  2. Plugins > Manage and Install Plugins > Settings >")
    print("     tick 'Show also Experimental Plugins'")
    print("  3. Installed > tick GeoProvenance")
    print("  4. Install 'Plugin Reloader' too — then editing a file here and")
    print("     hitting its reload button picks the change up with no restart.")
    return 0


def undeploy(profile: str, profiles_root_override=None, qgis_major=None, home=None) -> int:
    """Remove our link from EVERY profile root, not just the chosen one.

    A machine that has been through a QGIS major upgrade — or through the 26 Aug
    2026 defect — carries a stale link in the older tree. Leaving it behind
    means the next person debugging a load failure finds two links and cannot
    tell which one QGIS is reading. Only symlinks pointing at THIS checkout are
    touched; anything else is reported and left exactly where it is.
    """
    if profiles_root_override:
        roots = [pathlib.Path(profiles_root_override).expanduser()]
    else:
        roots = [
            r.path
            for r in discover_profile_roots(home)
            if qgis_major is None or r.major == qgis_major
        ]

    removed = 0
    for root in roots:
        link = root / profile / "python" / "plugins" / PLUGIN_DIR_NAME
        if link.is_symlink():
            if link.resolve() != SOURCE.resolve():
                print(f"leaving {link} alone — it points at {link.resolve()}, "
                      f"not this checkout")
                continue
            link.unlink()
            print(f"removed {link}")
            removed += 1
        elif link.exists():
            print(f"{link} exists but is not a symlink — leaving it alone.")

    if not removed:
        print("nothing to remove")
    return 0


def _where(profile: str, profiles_root_override=None, qgis_major=None, home=None) -> int:
    """Print everything needed to diagnose a plugin QGIS cannot see."""
    print(f"repo plugin : {SOURCE}")
    print()

    roots = discover_profile_roots(home)
    if not roots:
        print("profile roots: NONE FOUND — launch QGIS once (make qgis) so it "
              "creates one.")
    else:
        print("profile roots found (newest QGIS first):")
        for root in roots:
            used = "QGIS has run here" if root.used else "never used by QGIS"
            link = root.path / profile / "python" / "plugins" / PLUGIN_DIR_NAME
            if link.is_symlink():
                ours = link.resolve() == SOURCE.resolve()
                state = "LINKED to this checkout" if ours else \
                    f"linked elsewhere -> {link.resolve()}"
            elif link.exists():
                state = "exists, not a symlink"
            else:
                state = "not linked"
            print(f"  {root.label:<7} {root.path}")
            print(f"          {used}; {profile}: {state}")
    print()

    try:
        chosen = profiles_root(profiles_root_override, qgis_major, home)
    except SystemExit as exc:
        print(f"would link  : cannot decide — {exc}")
        return 0
    print(f"would link  : {chosen / profile / 'python' / 'plugins' / PLUGIN_DIR_NAME}")

    # The one cross-check that would have caught the 26 Aug defect in a second.
    for root in roots:
        if root.path == chosen and not root.used:
            print()
            print("WARNING: the chosen root has no sign QGIS has ever started "
                  "there. If another root above says 'QGIS has run here', that "
                  "is probably the one you want — pass --qgis-major.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("link", "unlink", "where"))
    parser.add_argument("--profile", default=DEV_PROFILE)
    parser.add_argument("--i-know-what-i-am-doing", action="store_true",
                        help="allow a profile other than the dev one (§2.4)")
    parser.add_argument("--profiles-root", default=None,
                        help="override the QGIS profiles directory, for an "
                             "install this script does not know how to find")
    parser.add_argument("--qgis-major", type=int, default=None,
                        help="target a specific QGIS major version (e.g. 3) on "
                             "a machine that has more than one")
    args = parser.parse_args(argv)

    if args.action == "where":
        return _where(args.profile, args.profiles_root, args.qgis_major)
    if args.action == "unlink":
        return undeploy(args.profile, args.profiles_root, args.qgis_major)
    if args.i_know_what_i_am_doing:
        return _link(args.profile, args.profiles_root, args.qgis_major)
    return deploy(args.profile, args.profiles_root, args.qgis_major)


if __name__ == "__main__":
    sys.exit(main())
