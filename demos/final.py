"""Final demo (Week 12) — ships after Phase 2 (integration) and Phase 3.

    Claim: "It captures live, feeds the graph and the score, and here is
            what it costs."

Run it:
    source .venv/bin/activate && python demos/final.py

What it must show, beyond Review 2:
    - The end-to-end pipeline: capture -> Person B's fingerprints and standard
      record -> Person C's family tree and reproducibility score.
    - The headline numbers, in plain words:
        "Out of 10 jobs, we noticed N."          (RQ1)
        "QGIS got N% slower."                    (RQ2 runtime)
        "The whole record for a workflow is N."  (RQ2 storage)
    - Every number regenerable from experiments/ (RULES.md §8.7).

Same rules as review1.py: RULES.md §7.1-§7.12.
Companion document: docs/demos/FINAL.md.

TODO(P3): implement.
"""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from _presenter import Demo, require_python  # noqa: E402


def main() -> int:
    require_python()
    raise NotImplementedError("P3 — see TODO in this file's docstring")


if __name__ == "__main__":
    raise SystemExit(main())
