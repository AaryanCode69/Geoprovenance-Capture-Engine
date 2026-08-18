"""Channel 2 (redundant): QgsHistoryProviderRegistry observer + polling fallback.

Owner: Person A.  Sub-phase: A5.

Responsibilities
    - Connect ``QgsGui.historyProviderRegistry().entryAdded`` (QGIS 3.24+).
    - QTimer + ``queryEntries()`` polling fallback since the last seen entry id.

Critical rules
    §5.10 The entryAdded signal signature HAS CHANGED across QGIS releases and
          is a known crash risk (research doc §12, risk 7). Verify the exact
          signature against the locally installed build before relying on it.
          Implement the polling fallback regardless.
    §5.4  unload() must disconnect the signal and stop the QTimer.
    §5.9  Events arriving here that the hook already caught are corroborations,
          not inserts.

Why two channels at all
    The per-channel split ("the hook caught 98%, the history channel caught the
    other 2%") is a publishable RQ1 result, not just belt-and-braces.
"""
