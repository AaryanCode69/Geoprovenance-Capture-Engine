"""Review 1 demo (Week 4) — ships after sub-phase A3.

    Claim: "QGIS ran a job and we wrote it down automatically."

Run it:
    source .venv/bin/activate && python demos/review1.py

Rules this must satisfy before Week 4 — see RULES.md §7:
    §7.1  One command. One paste. Nothing for the reviewer to edit.
    §7.2  Wipes and rebuilds its own database every run (use scratch_dir()).
    §7.3  Runs with NO QGIS installed — drive the store and normalizer from
          tests/fixtures/mock_events.json, not from a live QGIS session.
          The live QGIS run is an optional SECOND act, never the only act.
    §7.4  Before/after stated in one sentence each (the Demo constructor).
    §7.5  No jargon. finish() lints the output and warns during rehearsal.
    §7.7  Numbered steps, human-formatted dates, exit 0/1, under 60 seconds.
    §7.10 At least one honest limitation.

Companion document: docs/demos/REVIEW-1.md (from docs/demos/TEMPLATE.md).

TODO(A3): implement once storage/store.py (A2) and capture/engine.py (A3) exist.
"""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from _presenter import Demo, require_python  # noqa: E402


def main() -> int:
    require_python()

    demo = Demo(
        review="1",
        claim="QGIS ran a job and we wrote it down automatically.",
        before="Nothing was recorded. Close QGIS and you had no idea what had been done.",
        after="Every job QGIS finishes is written down by itself, as it happens.",
        steps=3,
    )

    with demo.step("Setting up an empty notebook to write into"):
        raise NotImplementedError("A3 — see TODO in this file's docstring")

    return demo.finish()


if __name__ == "__main__":
    raise SystemExit(main())
