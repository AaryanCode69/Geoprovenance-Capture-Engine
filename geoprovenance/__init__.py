"""GeoProvenance — QGIS plugin entry point.

QGIS calls ``classFactory`` to instantiate the plugin. Nothing else belongs here.

Owner: Person A.  Sub-phase: A1.  See RULES.md Appendix A.
"""


def classFactory(iface):  # noqa: N802 — name required by the QGIS plugin API
    """Return the plugin instance. Called by QGIS on plugin load.

    TODO(A1): import and return GeoProvenancePlugin(iface).
    Kept lazy so a broken import in plugin.py cannot break QGIS startup.
    """
    from .plugin import GeoProvenancePlugin

    return GeoProvenancePlugin(iface)
