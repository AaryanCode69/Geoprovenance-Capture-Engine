"""Storage layer — the SQLite schema, migrations, and the CRUD API.

Owner: Person A.  Sub-phase: A2.

    ┌──────────────────────────────────────────────────────────────┐
    │  RULES.md §4.1 [HARD]                                        │
    │                                                              │
    │  NOTHING under storage/ may import QGIS or PyQt5.            │
    │      import qgis            ✗                                │
    │      from qgis...           ✗                                │
    │      from PyQt5...          ✗                                │
    │                                                              │
    │  This is what lets Person B and Person C use the store       │
    │  immediately, lets tests/storage/ run on any machine with    │
    │  plain pytest, and lets the review demos run with no QGIS    │
    │  installed (§7.3).                                           │
    │                                                              │
    │  Enforced by tests/storage/test_no_qgis_imports.py.          │
    └──────────────────────────────────────────────────────────────┘

Person B and Person C call this API. They never write SQL (§1.3).
"""
