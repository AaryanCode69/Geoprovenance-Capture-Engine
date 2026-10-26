"""Every verdict of Definition 2 is pinned by at least one named test (C10).

    python tools/verdict_coverage.py        exit 0, or 1 naming the unpinned ones

A verdict counts as pinned when some test under tests/ ASSERTS it: an
`assert` line that names its `VERDICT_*` constant or its string value. An
import, or a mention in a docstring, is not a pin.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPARE = ROOT / "src" / "geoprovenance" / "fingerprint" / "compare.py"


def main() -> int:
    verdicts = dict(re.findall(r'^(VERDICT_[A-Z_]+) = "([a-z_]+)"', COMPARE.read_text(), re.M))
    pins: dict[str, list[str]] = {name: [] for name in verdicts}
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        test = None
        statement, depth = "", 0
        for line in path.read_text().splitlines():
            match = re.match(r"\s*def (test_\w+)", line)
            if match:
                test = match.group(1)
            # An assert may continue over bracketed lines; read it whole.
            if depth or re.match(r"\s*assert\b", line):
                statement += line
                depth += line.count("(") + line.count("[") - line.count(")") - line.count("]")
                if depth > 0:
                    continue
                line, statement, depth = statement, "", 0
            if test and "assert" in line:
                for name, value in verdicts.items():
                    if re.search(rf"\b{name}\b", line) or f'"{value}"' in line:
                        pins[name].append(f"{path.relative_to(ROOT)}::{test}")
    width = max(map(len, verdicts))
    for name, where in pins.items():
        print(f"{name:{width}}  {len(set(where)):3} test(s)  {where[0] if where else 'NONE'}")
    missing = [name for name, where in pins.items() if not where]
    if missing:
        print(f"unpinned: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
