"""Event normalizer — raw QGIS objects in, the frozen event dict out.

Owner: Person A.  Sub-phase: A4.
Contract: docs/CONTRACT_event.md + schemas/event.schema.json (frozen, §3.1).

Responsibilities
    - Flatten QGIS parameter objects to JSON-serializable values.
    - Resolve output paths from ``results``.
    - Extract CRS, format, feature count / raster metadata.
    - Compute the dedup key used by the engine (§5.9).

Critical rules
    §3.3  Memory and temporary layers (memory:, TEMPORARY_OUTPUT, /vsimem/)
          get ``path: None`` but keep ``layer_type``. B must not hash them.
    §3.3  Layer-valued parameters are lifted into inputs/outputs; scalar
          parameters stay in ``parameters``.
    §5.5  Serialization NEVER raises. Unknown types fall back to repr().
          QgsProcessingFeatureSourceDefinition, QgsCoordinateReferenceSystem
          and QgsProperty are the usual offenders and are the single biggest
          source of crashes in this component (PERSON_A.md §A4).
    §5.6  ``results`` may hand back a path string, a layer id, or a
          QgsVectorLayer/QgsRasterLayer. Handle all three; unresolvable
          becomes None, never a guess.
    §5.7  CRS from the layer, falling back to context.project().crs().
          Store authid() ("EPSG:4326"); WKT only when there is no authid.
    §5.8  Format from the provider/driver name, NOT the file extension —
          a .gpkg can hold vector or raster.
    §3.2  All timestamps: datetime.now(timezone.utc).isoformat(), microsecond
          precision, no exceptions.
"""
