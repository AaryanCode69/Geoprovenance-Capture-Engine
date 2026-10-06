"""Capture layer — turns QGIS Processing executions into normalized event dicts.

Owner: Person A.  Sub-phases: A3-A6.

THE PRIME DIRECTIVE (RULES.md §5.1)
    Every code path that runs inside a Processing hook, a signal handler, or the
    processing.run() wrapper is wrapped in a broad ``try/except Exception`` that
    logs to the QGIS message log and returns normally.

    A capture failure must be invisible to the person using QGIS. This outranks
    capture correctness: losing one record is acceptable, aborting or corrupting
    a user's real analysis is not.
"""
