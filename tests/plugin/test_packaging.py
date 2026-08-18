"""metadata.txt, the icon, and the names Person C builds against.

No QGIS. These are checks on the plugin as a *package* — the things QGIS reads
before any of our code runs, plus the public names that are contracts with
Person C (RULES.md §1.5).

The plugin modules themselves cannot be imported here (they import qgis.PyQt),
so the name contracts are checked by parsing the source rather than by
importing it. That catches a rename, which is the failure that matters.
"""

from __future__ import annotations

import ast
import configparser
import pathlib
import struct
import subprocess
import sys
import zlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "geoprovenance"
METADATA = PLUGIN / "metadata.txt"
ICON = PLUGIN / "icon.png"


def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _module_constant(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"module constant {name!r} not found")


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name!r} not found")


def _methods(cls: ast.ClassDef) -> set[str]:
    return {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


# ===========================================================================
# metadata.txt — the first thing QGIS reads
# ===========================================================================

def test_metadata_parses():
    parser = configparser.ConfigParser()
    parser.read(METADATA)
    assert parser.has_section("general")


def test_minimum_qgis_version_is_the_lts():
    """RULES.md §2.5 — 3.34 LTS. Anything newer must be feature-detected at
    runtime, not assumed."""
    parser = configparser.ConfigParser()
    parser.read(METADATA)
    assert parser["general"]["qgisMinimumVersion"] == "3.34"


def test_metadata_has_the_fields_qgis_requires():
    parser = configparser.ConfigParser()
    parser.read(METADATA)
    general = parser["general"]
    for field in ("name", "description", "version", "author", "email", "about"):
        assert general.get(field), f"metadata.txt is missing {field}"


def test_the_referenced_icon_exists():
    """A metadata file pointing at a missing icon is how a plugin ships with a
    blank toolbar button."""
    parser = configparser.ConfigParser()
    parser.read(METADATA)
    assert (PLUGIN / parser["general"]["icon"]).is_file()


# ===========================================================================
# the icon
# ===========================================================================

def test_icon_is_a_valid_32px_rgba_png():
    data = ICON.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, depth, colour_type = struct.unpack(">2I2B", data[16:26])
    assert (width, height, depth, colour_type) == (32, 32, 8, 6)  # 6 = RGBA


def test_every_icon_chunk_has_a_valid_crc():
    data = ICON.read_bytes()
    offset, tags = 8, []
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        tag = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
        assert crc == zlib.crc32(tag + payload) & 0xFFFFFFFF, f"bad CRC in {tag!r}"
        tags.append(tag)
        offset += 12 + length
    assert tags == [b"IHDR", b"IDAT", b"IEND"]


def test_regenerating_the_icon_produces_identical_bytes():
    """The icon is generated, not hand-drawn (tools/make_icon.py). If it were
    not deterministic, every run of `make icon` would churn the diff."""
    before = ICON.read_bytes()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "make_icon.py")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert ICON.read_bytes() == before


# ===========================================================================
# names Person C builds against (RULES.md §1.5)
# ===========================================================================

def test_class_factory_is_present_and_lazy():
    """QGIS calls classFactory to load the plugin. The import inside it is
    deliberate: a broken import in plugin.py must not break QGIS startup."""
    tree = _parse(PLUGIN / "__init__.py")
    factory = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "classFactory"
    )
    assert [a.arg for a in factory.args.args] == ["iface"]
    imports_inside = [n for n in ast.walk(factory) if isinstance(n, ast.ImportFrom)]
    assert imports_inside, "the plugin import should be inside classFactory, not top-level"


def test_the_plugin_class_has_the_qgis_lifecycle_methods():
    cls = _class(_parse(PLUGIN / "plugin.py"), "GeoProvenancePlugin")
    assert {"initGui", "unload"} <= _methods(cls)


def test_the_dock_contract_with_person_c_is_unchanged():
    """A1 exit criterion: the dock's names are agreed with Person C.

    RULES.md §1.5 — renaming any of these is a breaking change to Person C's
    work and follows §3.4. objectName in particular is what QGIS persists dock
    geometry against; changing it silently resets every user's panel layout.
    """
    tree = _parse(PLUGIN / "ui" / "dock.py")
    assert _module_constant(tree, "DOCK_OBJECT_NAME") == "GeoProvenanceDock"
    assert _module_constant(tree, "DOCK_TITLE") == "GeoProvenance"

    cls = _class(tree, "GeoProvenanceDockWidget")
    assert {"set_content", "clear_content", "content"} <= _methods(cls)


#: Each QGIS registration and the call that must undo it (RULES.md §5.4).
UI_PAIRS = [
    ("addPluginToMenu", "removePluginMenu"),
    ("addToolBarIcon", "removeToolBarIcon"),
    ("addDockWidget", "removeDockWidget"),
]


def test_every_ui_registration_has_a_matching_removal():
    """§5.4, structurally: the plugin must not add UI it never takes away.

    Counts each registration call and its paired removal across the whole
    class, including inside the lambdas handed to CleanupStack.defer. Two menu
    entries after a Plugin Reloader cycle is the classic symptom, and it is
    caught here rather than by noticing it in QGIS three weeks later.
    """
    cls = _class(_parse(PLUGIN / "plugin.py"), "GeoProvenancePlugin")

    counts: dict[str, int] = {}
    for node in ast.walk(cls):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            counts[node.func.attr] = counts.get(node.func.attr, 0) + 1

    assert any(counts.get(add) for add, _ in UI_PAIRS), \
        "no UI registration found at all — did the file move?"

    unbalanced = [
        f"{add} x{counts.get(add, 0)} but {remove} x{counts.get(remove, 0)}"
        for add, remove in UI_PAIRS
        if counts.get(add, 0) != counts.get(remove, 0)
    ]
    assert not unbalanced, "RULES.md §5.4 violation: " + "; ".join(unbalanced)


def test_the_a6_menu_actions_exist_and_go_through_the_cleanup_helper():
    """PERSON_A.md §A6 requires a manual override in the plugin menu.

    Checked at source level because the handlers open QGIS dialogs and this
    suite runs with no QGIS (§6.1). What is worth checking here anyway: both
    actions are registered through _add_action, which is what registers their
    own teardown — an action added directly would leave a menu entry behind
    after a Plugin Reloader cycle (§5.4).
    """
    cls = _class(_parse(PLUGIN / "plugin.py"), "GeoProvenancePlugin")
    methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    assert {"_start_new_workflow", "_name_workflow"} <= methods

    build = next(node for node in cls.body
                 if isinstance(node, ast.FunctionDef) and node.name == "_build_actions")
    handlers = {
        node.attr
        for call in ast.walk(build)
        if isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "_add_action"
        for node in call.args
        if isinstance(node, ast.Attribute)
    }
    assert {"_start_new_workflow", "_name_workflow"} <= handlers, (
        "the A6 actions must be registered through _add_action so their "
        "removal is registered with them (RULES.md §5.4)"
    )


def test_every_signal_connection_has_a_matching_disconnect():
    """§5.4 — a signal left connected after unload fires into a dead object."""
    cls = _class(_parse(PLUGIN / "plugin.py"), "GeoProvenancePlugin")

    connects = disconnects = 0
    for node in ast.walk(cls):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            connects += node.func.attr == "connect"
            disconnects += node.func.attr == "disconnect"

    assert connects > 0, "no signal connections found — did the file move?"
    assert connects == disconnects, (
        f"{connects} .connect() calls but {disconnects} .disconnect() calls "
        f"(RULES.md §5.4)"
    )


# ===========================================================================
# the deploy helper
# ===========================================================================

def test_deploy_refuses_a_profile_other_than_the_dev_one():
    """RULES.md §2.4 [HARD] — a crash in capture code must never take out the
    user's working QGIS installation."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import deploy

    with pytest.raises(SystemExit, match="refusing to deploy"):
        deploy.deploy("default")


def test_deploy_knows_where_qgis_keeps_profiles():
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import deploy

    target = deploy.target_dir(deploy.DEV_PROFILE)
    assert target.name == "plugins"
    assert "geoprov-dev" in str(target)
