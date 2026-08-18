"""Environment probe — the PROV Agent record for this machine and software set.

Owner: Person A.  Sub-phase: A6.

Responsibilities
    - QGIS version (Qgis.QGIS_VERSION)
    - OS (platform.platform())
    - Python version
    - Installed plugin names and versions (qgis.utils.plugins / pluginMetadata())

Critical rules
    §4.6  Feeds ProvenanceStore.get_or_create_agent(), which deduplicates on the
          FULL environment fingerprint. One agent row per distinct environment,
          reused across activities. Writing one agent row per execution inflates
          the RQ2 storage numbers with our own bug.
    §2.6  Report real measured values. Never hardcode "Ubuntu 22.04" as though
          it had been verified.

This module may import QGIS. storage/ may not (§4.1).
"""
