"""Review 2 demo (Week 8) — ships after sub-phase A6.

    Claim: "A whole 4-step workflow was captured, in the right order,
            with nothing missing."

Run it:
    source .venv/bin/activate && python demos/review2.py

What it must show, beyond Review 1:
    - Four jobs in a row, correctly ordered (session grouping, A6).
    - The same job seen by both watching channels counted once, not twice —
      say it as "we double-check ourselves and never write it down twice"
      (RULES.md §5.9, §7.5).
    - A job that failed, still recorded (RULES.md §4.10).
    - Which computer and software setup it ran on (A6).

Same rules as review1.py: RULES.md §7.1-§7.12.
Companion document: docs/demos/REVIEW-2.md.

TODO(A6): implement.
"""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from _presenter import Demo, require_python  # noqa: E402


def main() -> int:
    require_python()
    raise NotImplementedError("A6 — see TODO in this file's docstring")


if __name__ == "__main__":
    raise SystemExit(main())
