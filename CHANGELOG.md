# Changelog

All notable changes to GeoProvenance are recorded here. Versions follow
[Semantic Versioning](https://semver.org/); while the major version is 0 the
database shape and event format may still change between minor versions.

## [Unreleased]

### Fixed
- **A vertex moved inside a dataset's extent was classified `resaved`.** The only
  shape signal was feature count + bounding box, so moving one point or vertex
  without changing either moved the byte hash alone. A fourth complementary
  fingerprint, `geometry_content`, now digests the coordinates themselves: every
  `.shp` record (record numbers excluded, file order kept), and every GeoPackage
  geometry with its blob header removed (rows sorted, so renumbering is still a
  re-save). Pinned for both formats in `tests/fingerprint/test_compare.py`.
- `test_deploy_knows_where_qgis_keeps_profiles` read the real home directory and
  failed on any machine where QGIS had never started; it now uses a fake home.

### Changed
- `resaved` now requires both the attribute and the coordinate signals to have held;
  `attributes_changed` requires the coordinate signal to have held. Fingerprint sets
  written by 0.1.0 have no coordinate signal, so a re-save or attribute edit compared
  against them now reads `changed`. Re-fingerprinting the inputs removes this.
- A captured file now leaves five fingerprint rows instead of four. No schema change.

### Added
- GitHub Actions CI running the QGIS-free suite and the workflow demo on Python
  3.10 and 3.13.

### Known limitations
- A big-endian GeoPackage geometry, or one that is not a standard GeoPackage blob,
  gets no coordinate signal (the comparison then says `changed`, not `resaved`).
- Two GeoPackage features swapping geometries with nothing else changed is not seen.

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
