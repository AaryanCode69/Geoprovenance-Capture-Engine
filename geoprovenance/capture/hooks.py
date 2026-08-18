"""Channel 1 (primary): the Processing post-execution hook + processing.run wrapper.

Owner: Person A.  Sub-phase: A3.

Responsibilities
    - Write the hook script and set ProcessingConfig's POST_EXECUTION_SCRIPT
      programmatically on plugin load; restore the user's previous value on
      unload (RULES.md §5.3).
    - Fallback channel if the hook proves unreliable: wrap
      ``processing.tools.general.run`` by monkeypatching it.

Critical rules
    §5.2  The wrapper preserves the original signature and return value
          EXACTLY, and never swallows exceptions raised by the algorithm
          itself. QGIS exceptions propagate untouched; only exceptions from
          capture code are caught.
    §5.3  Save and restore the user's POST_EXECUTION_SCRIPT.
    §5.11 Which invocation paths actually fire this hook is an EMPIRICAL
          question answered in Week 4, not assumed from documentation. The
          Toolbox dialog, batch mode, and the Graphical Modeler may take
          different code paths. Record findings in docs/capture_coverage.md as
          you discover them — that table is the RQ1 evidence.
"""
