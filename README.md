# GeoProvenance

**Automatic provenance capture and reproducibility auditing for QGIS Processing workflows.**

[![Tests](https://github.com/AaryanCode69/Geoprovenance-Capture-Engine/actions/workflows/tests.yml/badge.svg)](https://github.com/AaryanCode69/Geoprovenance-Capture-Engine/actions/workflows/tests.yml)
[![License: GPL v2+](https://img.shields.io/badge/License-GPL%20v2%2B-blue.svg)](./LICENSE)
[![QGIS](https://img.shields.io/badge/QGIS-3.28%E2%80%934.x-589632.svg)](https://qgis.org)
![Version](https://img.shields.io/badge/version-0.1.0-informational.svg)
<!-- DOI badge: replace once Zenodo has minted the DOI (see docs/RELEASING.md)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
-->

GeoProvenance is a QGIS plugin that keeps a record of where every output file came from. It runs in the background:
- **Records each job.** Whenever a QGIS Processing algorithm runs, the plugin notes which algorithm it was, its parameters, the files it read and wrote, timings, and the software environment.
- **Stores the record.** Everything goes into a local SQLite database whose shape follows the W3C PROV-O standard.
- **Fingerprints files.** Each dataset gets a SHA-256 fingerprint, plus structural fingerprints that tell a harmless re-save apart from a real change to the data.
- **Shows the workflow.** A dock panel draws it as a family tree of files and jobs.
- **Scores reproducibility.** It reports how reproducible the workflow still is (0–100) and names any input that has gone missing or changed.

It needs no third-party Python packages, only the standard library and PyQGIS.

---

## Features

- **Multi-channel automatic capture.** Four independent channels: a `processing.run()` wrapper, a Processing Toolbox wrapper, the QGIS history registry (with a polling fallback), and the Processing post-execution hook. A job seen by more than one channel is merged into a single record and marked as corroborated.
- **Standards-based record.** Files, jobs and environments are stored as PROV entities, activities and agents. `used` / `wasGeneratedBy` / `wasDerivedFrom` relations are inferred automatically. The record exports to PROV-JSON.
- **Change classification beyond checksums.** Shapefiles and GeoPackages get `structure`, `geometry` (count and extent), `geometry_content` (the coordinates themselves) and `attributes` fingerprints alongside the byte hash, so a vertex moved inside the extent is a geometry change, not a re-save. Two versions of a file can then be classified as `unchanged`, `resaved`, `attributes_changed`, `geometry_changed`, `schema_changed`, `changed` or `unknown`. Files larger than 500 MB fall back to a schema-and-sample fingerprint.
- **Workflow grouping.** Jobs in a QGIS session are grouped into workflows by the files they share, and put in order by start time. The plugin menu has items to start a new workflow and to name the current one; those two dialogs have not yet been tested by hand.
- **Reproducibility audit.** A weighted 5-component score:

  | Check | Weight |
  |---|---|
  | input data exists | 30 |
  | input data unchanged | 25 |
  | algorithms available | 20 |
  | environment similar | 15 |
  | parameters valid | 10 |

  A check that cannot be run is reported as *not run*, never as passed.
- **Never breaks QGIS.** All capture code that runs inside QGIS is wrapped so a failure is logged and the user's job carries on.

## Status and tested environment

GeoProvenance is **experimental** (version 0.1.0, `experimental=True` in `metadata.txt`). Read the points below before relying on it.

- **Verified on QGIS 4.2.1** (Python 3.13, Qt 6.10, PyQt6, Linux). On that version the plugin loads and unloads cleanly (11/11 in-QGIS lifecycle tests), and a 4-step workflow driven by `processing.run()` was captured completely (4/4).
- **QGIS 3.x LTS is not yet verified.** The code supports PyQt5 and PyQt6 through runtime feature detection, but no 3.x release has been tested.
- **Capture coverage is only partly measured.** One of ten invocation paths (scripted `processing.run()`) has been measured live; the Toolbox, Graphical Modeler and batch paths have not. See [`docs/capture_coverage.md`](./docs/capture_coverage.md).
- **The post-execution hook does not fire on QGIS 4.** The setting exists but QGIS 4 never calls it. On QGIS 4, capture goes through the `processing.run()` and Toolbox wrappers instead.
- **Only some job durations can be trusted.** Durations are reliable only for rows captured by the `run_wrapper` and `toolbox` channels; check the `capture_channel` column.

## Requirements

| | |
|---|---|
| QGIS | 3.28 or newer (tested on 4.2.1) |
| Python | the interpreter bundled with QGIS |
| Runtime dependencies | none beyond the Python standard library and PyQGIS |
| Development / tests | Python 3.10+, `pytest`, `jsonschema` (`pytest-qgis` for the in-QGIS tests) |

## Installation

The plugin is the folder `src/geoprovenance/`.

**Manual install.** Copy (or symlink) `src/geoprovenance` into your QGIS profile's plugin folder:

| OS | Plugin folder |
|---|---|
| Linux | `~/.local/share/QGIS/QGIS4/profiles/default/python/plugins/` |
| Windows | `%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins\` |
| macOS | `~/Library/Application Support/QGIS/QGIS4/profiles/default/python/plugins/` |

On QGIS 3.x, use `QGIS3` instead of `QGIS4` in the path. Then restart QGIS and open **Plugins → Manage and Install Plugins → Installed**. Tick **GeoProvenance**. You may first need to enable *Show also experimental plugins* in the Settings tab.

**From a clone (developers).** `make deploy` symlinks `src/geoprovenance` into a separate `geoprov-dev` QGIS profile, and `make qgis` launches QGIS on that profile. `make where` shows which profile folder is used.

## Quick start

1. Enable the plugin. A **GeoProvenance** menu and dock panel appear.
2. Run any Processing algorithm. Scripted calls to `processing.run(...)` (for example from the Python console) are the path that has been measured live. Toolbox runs are captured by a separate wrapper that is unit-tested but has not yet been measured in a live session (see [`docs/capture_coverage.md`](./docs/capture_coverage.md)).
3. Open the GeoProvenance dock. Pick the workflow to see its family tree of files, then open the audit tab to see its reproducibility score.

The record is stored in `<QGIS profile>/geoprovenance/provenance.db`. You can change that location with the QSettings key `GeoProvenance/database_path`. A full walkthrough, including what each menu item does, is in [`docs/RUNNING_IN_QGIS.md`](./docs/RUNNING_IN_QGIS.md).

## Running the tests and demos

None of these need QGIS installed:

```bash
make venv            # create .venv with the development dependencies
make test            # the full test suite that runs without QGIS (537 tests)
make demo1           # one job captured automatically
make demo2           # a 4-step workflow captured in order, nothing missing
make demo-workflow   # family tree + reproducibility score; edits a file and shows the score drop
```

The tests that need a running QGIS are run separately, inside QGIS, with `make test-qgis`. `make help` lists every command. A full visual demonstration inside QGIS (a styled project built from a real captured run) is described in [`qgis_demo/README.md`](./qgis_demo/README.md).

## Repository layout

```
src/geoprovenance/     the QGIS plugin
  capture/             capture channels, event normaliser, environment probe
  storage/             SQLite schema, migrations, ProvenanceStore API, workflow grouping
  fingerprint/         SHA-256 + structural fingerprints and change classification
  prov.py              PROV graph, derivation inference, PROV-JSON export
  audit.py             reproducibility score and reports
  ui/                  dock, graph layout (no Qt) and graph panel
tests/                 pytest suite and shared fixtures (real .shp / .gpkg files)
demos/                 one-command demos that run without QGIS
qgis_demo/             end-to-end visual demonstration inside QGIS
schemas/               JSON Schema for captured events
experiments/           evaluation harness (capture completeness, runtime overhead)
tools/                 deploy and icon scripts
docs/                  architecture, data contracts, coverage measurements
```

## Documentation

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md): how the parts fit together
- [`docs/DFD.md`](./docs/DFD.md): how information moves through the system
- [`docs/USE_CASES.md`](./docs/USE_CASES.md): what a user can do with it
- [`docs/EXPLAINER.md`](./docs/EXPLAINER.md): the whole system end to end, in plain language
- [`docs/CONTRACT_schema.md`](./docs/CONTRACT_schema.md) and [`docs/CONTRACT_event.md`](./docs/CONTRACT_event.md): the database shape and the captured-event format
- [`docs/capture_coverage.md`](./docs/capture_coverage.md): measured capture coverage, per invocation path and QGIS version
- [`docs/RUNNING_IN_QGIS.md`](./docs/RUNNING_IN_QGIS.md): running the plugin by hand
- [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md): developer setup and project organisation
- [`CHANGELOG.md`](./CHANGELOG.md): release notes

## How to cite

If you use GeoProvenance in your research, please cite it using the metadata in [`CITATION.cff`](./CITATION.cff). GitHub shows this as "Cite this repository". A DOI will be added on the first archived release.

## License

GeoProvenance — Copyright (C) 2026 Aaryan Upadhyay, Saniya Goyal, Dibyendu De.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 2 of the License, or (at your option) any later version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See [`LICENSE`](./LICENSE) for the full text.

## Support and contributing

- Report bugs and ask questions through [GitHub Issues](https://github.com/AaryanCode69/Geoprovenance-Capture-Engine/issues).
- Contact: aaryanupadhyay68@gmail.com
- See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for how to run the tests and submit changes.
