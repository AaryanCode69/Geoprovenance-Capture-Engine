# Changelog

All notable changes to GeoProvenance are recorded here. Versions follow
[Semantic Versioning](https://semver.org/); while the major version is 0 the
database shape and event format may still change between minor versions.

## [1.0.0] — 2026-10-26

The release the Array manuscript describes. Built and measured locally on
24 Oct 2026; tagged and published on GitHub 26 Oct 2026.

### Added
- **GeoTIFF fingerprinting, standard library only.** A TIFF reader (classic and
  BigTIFF, both byte orders, strips and tiles, uncompressed or Deflate, predictor
  1 or 2, planar 1 or 2, integer and IEEE float samples) gives rasters a
  `structure` digest (size, bands, sample type, CRS GeoKeys, geotransform, nodata)
  and a `pixel_content` digest of the decoded samples, independent of tiling and
  compression. New verdict `pixels_changed`; a raster is `resaved` only when its
  pixels were read and held.
- **A fifth capture channel, `batch`.** Batch-dialog runs reached none of the
  other four channels on QGIS 4.2.3 or 3.34.6 (measured in E7).
- **Processing-model steps are recorded as jobs of their own** (QGIS 3.38+), from
  `QgsProcessingContext.modelResult()`. Before, a model run was one job under the
  model's name with no files.
- **Schema v3.** `agents` gains `gdal_version`, `proj_version`, `geos_version`
  and `capabilities_json`; `activities` gains `parameter_definitions_json`; new
  table `registry_snapshots` (the Processing registry, zlib-compressed JSON,
  written on the first job of each session). `MIGRATIONS[3]` migrates v2 records.
- **`wasAttributedTo`** for every output, exported in PROV-JSON.
- **Runtime probe of the post-execution hook**, recorded in `capabilities_json`
  as `active`, `inactive` or `not_installed`.
- **Audit:** the environment check compares QGIS, GDAL, PROJ, GEOS and Python at
  major.minor and names each one that differs; algorithm availability and
  parameter validity are evaluated offline from the registry snapshot and the
  definitions captured with each job.
- `tools/verdict_coverage.py`: every verdict is asserted by a named test.
- `evaluation/`: the scripts, frozen hypotheses and raw results behind every
  table and figure of the manuscript, and `evaluation/run_all.sh`.

### Changed
- **Content digests are order-insensitive multisets (AdHash over SHAKE-256,
  2048 bits).** Shapefile coordinates and `.dbf` rows were order-sensitive, and
  the GeoPackage payloads were sorted, which held a table in memory and stopped
  at 100,000 rows, so no vector file over that had a coordinate or attribute
  digest. They now stream in constant memory with no row limit. Tags
  `geometry_content/3`, `attributes/4`; older values compare as unavailable.
- Canonicalisation fixes found by the E1 development run: GeoPackage geometry
  column type spellings, dBASE number formatting, raster nodata spelling and
  pixel-is-point georeferencing (`structure/2`, `structure/raster/2`).
- Cross-channel de-duplication matches on overlapping intervals, keys on the
  resolved file path (the Toolbox names a loaded output by its project layer id)
  and on flattened parameter values (it passes output definitions, not paths).
  On QGIS 4.2.3 every Toolbox job was written twice before this.
- `qgisMinimumVersion` is 3.34 again; 3.34.6 and 4.2.3 both run the QGIS-hosted
  suite.

### Fixed
- **QGIS 3.34 crash.** Any Python slot on `QgsHistoryProviderRegistry.entryAdded`
  segfaults QGIS 3.34.6 when the Toolbox writes its history entry. Below QGIS 4
  the history channel now polls instead of connecting the signal.
- A QGIS 4 history entry with no parameters (a model without inputs) recorded
  its envelope as the parameters and was written twice.
- Large rasters (over 500 MB) crashed the schema-sample fallback.

### Known limitations
- Two features swapping geometries, or attributes, with nothing else changed is
  not detected (the content digests are order-insensitive by design).
- On QGIS 3.34, model steps are not recorded (no `modelResult()` API there); the
  model job is.
- Model steps carry the model's interval, not a duration of their own, and batch
  and history-channel rows carry none.

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
  (feature count and extent), geometry-content (the coordinates themselves) and
  attributes fingerprints, and two fingerprint sets can be compared to classify
  a change (`unchanged`, `resaved`, `attributes_changed`, `geometry_changed`,
  `schema_changed`, `changed`, `unknown`). A point or vertex moved inside the
  extent is a geometry change, not a re-save; `resaved` is only reported when the
  attribute values and the coordinates were both checked and held.
- **PROV.** Derivations (`wasDerivedFrom`) are inferred, and the record exports to PROV-JSON.
- **Audit.** A 5-component weighted reproducibility score. A check that cannot be run
  is reported as not run, never counted as passed.
- **Interface.** A dock panel with a workflow picker, a provenance graph and an audit tab.
  The plugin menu has items to start a new workflow and to name the current one.
- **Demos and tests.** 537 tests that run without QGIS, one-command demos
  (`make demo1`, `make demo2`, `make demo-workflow`) and an end-to-end visual demo
  inside QGIS (`qgis_demo/`). GitHub Actions runs the tests and demos on Python
  3.10 and 3.13.

### Known limitations
- Verified on QGIS 4.2.1 only. QGIS 3.x LTS is supported in code but untested.
- The Processing post-execution hook is never called by QGIS 4. Capture there
  relies on the `processing.run()` and Toolbox wrappers.
- Capture coverage has been measured for 1 of 10 invocation paths
  (`docs/capture_coverage.md`).
- The "Start new workflow" and "Name this workflow…" dialogs have not been tested by hand.
- Job durations are reliable only from the `run_wrapper` and `toolbox` channels.
- The evaluation harness in `experiments/` holds no results yet.
- A big-endian GeoPackage geometry, or one that is not a standard GeoPackage blob,
  gets no coordinate fingerprint, so a change to it is reported as `changed` rather
  than classified.
- Two GeoPackage features swapping geometries, with nothing else changed, is not
  detected.

[0.1.0]: https://github.com/AaryanCode69/Geoprovenance-Capture-Engine/releases/tag/v0.1.0
