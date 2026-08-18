"""Plugin lifecycle: load, unload, menu, toolbar, dock registration.

Owner: Person A.  Sub-phase: A1.

Responsibilities
    - Register the menu action, toolbar button, and the empty dock widget
      placeholder that Person C will later fill (agree the dock class name
      with C before A1 is done — RULES.md Appendix A, row A1).
    - Mint the session UUID at startup (RULES.md §3.2 decision 5).
    - Install the post-execution hook, saving and later restoring the user's
      previous ProcessingConfig POST_EXECUTION_SCRIPT value (RULES.md §5.3).

Critical rules
    §5.3  Never clobber the user's existing POST_EXECUTION_SCRIPT setting.
    §5.4  unload() must disconnect every signal, stop every QTimer, un-patch
          every monkeypatch, close the DB connection, and restore §5.3's value.
          load -> unload -> load must leave no residue and log no errors.
"""


class GeoProvenancePlugin:
    """TODO(A1): implement initGui() / unload() per RULES.md §5.3, §5.4."""

    def __init__(self, iface):
        self.iface = iface

    def initGui(self):  # noqa: N802 — QGIS plugin API
        raise NotImplementedError("A1")

    def unload(self):
        raise NotImplementedError("A1")
