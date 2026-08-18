"""Guard test for RULES.md §4.1 [HARD]: storage/ must import zero QGIS.

This is the rule that lets Person B and Person C use ProvenanceStore
immediately, lets this suite run on any machine with plain pytest, and lets the
review demos run with no QGIS installed (RULES.md §7.3).

The check runs in a subprocess with ``qgis`` and ``PyQt5`` blocked, so an
accidental import fails loudly here rather than three weeks later when someone
tries to run the Review 1 demo on a laptop without QGIS.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
STORAGE_DIR = REPO_ROOT / "geoprovenance" / "storage"

BANNED = ("qgis", "PyQt5", "PyQt6", "qgis.core", "qgis.gui", "qgis.utils")

# Setting a sys.modules entry to None makes `import <name>` raise ImportError,
# regardless of whether the package is actually installed. Version-proof, and
# simpler than a custom meta_path finder.
_PROBE = """\
import sys
for _name in {banned!r}:
    sys.modules[_name] = None
import importlib
importlib.import_module({module!r})
print("OK")
"""


def _storage_modules() -> list[str]:
    modules = ["geoprovenance.storage"]
    modules += [
        f"geoprovenance.storage.{p.stem}"
        for p in sorted(STORAGE_DIR.glob("*.py"))
        if p.stem != "__init__"
    ]
    return modules


@pytest.mark.parametrize("module", _storage_modules())
def test_storage_module_imports_without_qgis(module: str) -> None:
    """Every module under storage/ imports cleanly with QGIS unavailable."""
    code = _PROBE.format(banned=BANNED, module=module)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"RULES.md §4.1 violation — {module} cannot be imported without QGIS.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_storage_source_contains_no_qgis_import() -> None:
    """Belt and braces: no textual qgis/PyQt import anywhere under storage/."""
    offenders = []
    for path in sorted(STORAGE_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            if any(tok in stripped for tok in ("qgis", "PyQt5", "PyQt6")):
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, "RULES.md §4.1 violation:\n" + "\n".join(offenders)


def test_schema_sql_exists_and_sets_user_version() -> None:
    """schema.sql is present and declares PRAGMA user_version (Appendix B.6)."""
    schema = STORAGE_DIR / "schema.sql"
    assert schema.is_file(), "geoprovenance/storage/schema.sql is missing"
    text = schema.read_text()
    assert "PRAGMA user_version" in text, "schema.sql must set PRAGMA user_version"
