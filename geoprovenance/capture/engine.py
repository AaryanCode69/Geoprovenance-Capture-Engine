"""ProvenanceCaptureEngine — the singleton both capture channels report into.

Owner: Person A.  Sub-phase: A3 (POC), hardened through A6.

Responsibilities
    - ``instance()`` singleton accessor, used by the post-execution hook script.
    - ``record_algorithm_execution(algorithm, parameters, context, results,
      feedback)`` — the hook entry point.
    - ``process_history_entry(entry)`` — the history-channel entry point.
    - Hand raw input to the normalizer, then persist through ProvenanceStore in
      a single transaction (RULES.md §4.3).

Critical rules
    §5.1  Wrap everything. Never raise into QGIS.
    §5.9  Dedup key is (algorithm_id, hash of normalized parameters,
          started_at rounded to 100ms). First channel wins; the second
          increments a corroboration counter and does NOT insert.
          Keep that counter — it is an RQ1 result (RULES.md §8.3).
    §4.10 Failed and cancelled runs are persisted with their status, never
          dropped. C's audit needs them and RQ1 completeness counts them.

Phase 2 note
    Person B's fingerprinter is called from here at two moments: inputs before
    execution, outputs after (research doc §5.3). Run hashing on a background
    thread or after the transaction commits so it never adds latency to the
    user's run. Its cost is attributed to B, not to A (RULES.md §8.5).
"""
