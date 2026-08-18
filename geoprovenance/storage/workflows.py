"""Session -> workflow grouping.

Owner: Person A.  Sub-phase: A6.  RULES.md §4.1 — no QGIS imports.

What this does (§5.12)
    Activities sharing a ``session_id`` AND connected by shared dataset paths
    become one ``workflows`` row, with ``sequence_order`` set by ``started_at``.
    Plus a manual override: the "Start new workflow" / "Name this workflow"
    action in the plugin menu.

What this does NOT do
    Person B independently infers ``wasDerivedFrom`` from input/output path
    overlap. That is DATA-FLOW based; this is TEMPORAL/SESSION based. Both are
    needed and they are different jobs — do not reimplement B's inference here
    (RULES.md §1.2, §5.12).

TODO(A6): implement.
"""
