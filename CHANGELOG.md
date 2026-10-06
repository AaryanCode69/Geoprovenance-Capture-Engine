# Changelog

All notable changes to GeoProvenance are recorded here. Versions follow
[Semantic Versioning](https://semver.org/); while the major version is 0 the
database shape and event format may still change between minor versions.

## [0.1.0] — 2026-10-06

First public release.

### Added
- **Capture.** Four capture channels: a `processing.run()` wrapper, a Processing
  Toolbox wrapper, a `QgsHistoryProviderRegistry` observer with a polling fallback,
  and pre/post-execution hook installers. Events from different channels are merged
  into one record, and a merged record is marked as corroborated. An environment probe
  records the QGIS, OS and Python versions and the installed plugins. A new session
  starts whenever a project is opened or cleared.
- **Storage.** A SQLite record mapped to W3C PROV-O: 8 tables, 9 indices, schema
  version 2, with forward migrations. `ProvenanceStore` is the only write API.
  Jobs are grouped into workflows by the files they share.
- **Fingerprinting.** Streamed SHA-256 for files under 500 MB and a schema-and-sample
  fingerprint above that. Shapefiles and GeoPackages also get structure, geometry
  and attributes fingerprints, and two fingerprint sets can be compared to classify
  a change (`unchanged`, `resaved`, `attributes_changed`, `geometry_changed`,
  `schema_changed`, `changed`, `unknown`).
- **PROV.** Derivations (`wasDerivedFrom`) are inferred, and the record exports to PROV-JSON.
- **Audit.** A 5-component weighted reproducibility score. A check that cannot be run
  is reported as not run, never counted as passed.
- **Interface.** A dock panel with a workflow picker, a provenance graph and an audit tab.
  The plugin menu has items to start a new workflow and to name the current one.
- **Demos and tests.** 523 tests that run without QGIS, one-command demos
  (`make demo1`, `make demo2`, `make demo-workflow`) and an end-to-end visual demo
  inside QGIS (`qgis_demo/`).

### Known limitations
- Verified on QGIS 4.2.1 only. QGIS 3.x LTS is supported in code but untested.
- The Processing post-execution hook is never called by QGIS 4. Capture there
  relies on the `processing.run()` and Toolbox wrappers.
- Capture coverage has been measured for 1 of 10 invocation paths
  (`docs/capture_coverage.md`).
- The "Start new workflow" and "Name this workflow…" dialogs have not been tested by hand.
- Job durations are reliable only from the `run_wrapper` and `toolbox` channels.
- The evaluation harness in `experiments/` holds no results yet.

[0.1.0]: https://github.com/AaryanCode69/Geoprovenance-Capture-Engine/releases/tag/v0.1.0
