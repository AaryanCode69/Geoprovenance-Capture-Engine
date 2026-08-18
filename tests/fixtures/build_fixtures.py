"""Regenerate the shared test fixtures that Person B and Person C both consume.

Owner: Person A.  Sub-phase: A0.3.

    Run:  python tests/fixtures/build_fixtures.py

    RULES.md §10.3 — the generated .db and .json ARE committed, because B and C
    consume them directly. They are regenerated only by this script, NEVER
    hand-edited.

    RULES.md §3.4 step 3 — after any schema or event-dict change, re-run this so
    B's and C's tests stay green, then tell them what changed.

Produces
    mock_provenance.db    the §7.3 Buffer -> Clip workflow, hand-built, PLUS
                          one 8-step chain AND one branch (two outputs from one
                          job) so Person C's layout code meets a non-linear
                          graph early rather than in week 10. (RULES.md §6.6)
    mock_events.json      the same workflows as a list of event dicts, for B.
                          Every entry must validate against
                          schemas/event.schema.json.
    data/                 a few-KB Shapefile and GeoPackage, so B's fingerprinter
                          and C's "does this file still exist?" check have
                          something real on disk.

Phase 0 exit criterion (PERSON_A.md §A0.3)
    B and C can each run `pytest` against these fixtures with ZERO QGIS running
    and zero Person A code beyond storage/store.py.

TODO(A0.3): implement. Blocked on storage/store.py (A2) being importable.
"""

from __future__ import annotations

import pathlib

HERE = pathlib.Path(__file__).resolve().parent
MOCK_DB = HERE / "mock_provenance.db"
MOCK_EVENTS = HERE / "mock_events.json"
DATA_DIR = HERE / "data"


def main() -> int:
    raise NotImplementedError("A0.3 — see TODO in this file's docstring")


if __name__ == "__main__":
    raise SystemExit(main())
