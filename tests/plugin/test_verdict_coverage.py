"""C10 — the manuscript says every verdict is pinned by a named test; keep it true."""

import pathlib
import runpy
import sys


def test_every_verdict_is_asserted_by_some_test(capsys):
    tool = pathlib.Path(__file__).resolve().parents[2] / "tools" / "verdict_coverage.py"
    namespace = runpy.run_path(str(tool))
    assert namespace["main"]() == 0, capsys.readouterr().err
