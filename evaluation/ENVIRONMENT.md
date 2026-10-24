# Evaluation environment

Every live measurement in the manuscript's §5 ran on one machine, in the
environments below. `ENVIRONMENT.json` (written by `hardware.py`) and the
`versions` block inside each result file are the machine-read record; this page
is how to rebuild it.

## Machine

| | |
|---|---|
| CPU | 13th Gen Intel Core i7-13700HX, 24 threads |
| RAM | 15 GiB |
| OS | CachyOS Linux, kernel 7.2.11 |
| Display | none used: QGIS runs on Qt's `offscreen` platform (`evaluation/qgis.sh` unsets `DISPLAY` and `WAYLAND_DISPLAY`) |

## Environments (micromamba 2.9.0, conda-forge, user-level, no sudo)

| Environment | Purpose | Key packages |
|---|---|---|
| `gp-q42` | QGIS 4.2 measurements, report and figures | qgis 4.2.3, Qt 6.11.2, Python 3.14.9, GDAL 3.13.3, PROJ 9.9.0, GEOS 3.14.1, SQLite 3.54.1, matplotlib 3.11.2, numpy 2.5.4, pytest 9.1.1, pytest-qgis 5.0.2 (pip), pygeodiff 2.3.2 (pip) |
| `gp-q334` | QGIS 3.34 LTR measurements | qgis 3.34.6, Qt 5.15.8 / PyQt 5.15.9, Python 3.12.15, GDAL 3.8.5, PROJ 9.4.0, GEOS 3.12.1, SQLite 3.53.4, pytest-qgis 5.0.2 (pip), draco 1.5.7 (pinned: the solver's newer draco lacks `libdraco.so.9`, which this QGIS build links) |
| `gp-grass` | GRASS GIS 8.5.0 for case study 2, put on `PATH` for the QGIS 4.2 run | grass 8.5.0 (a separate environment: it does not co-solve with qgis 4.2.3) |

```sh
micromamba create -p ~/micromamba/envs/gp-q42  -c conda-forge qgis=4.2.3 pytest jsonschema matplotlib
micromamba create -p ~/micromamba/envs/gp-q334 -c conda-forge qgis=3.34.6 draco=1.5.7 pytest jsonschema matplotlib
micromamba create -p ~/micromamba/envs/gp-grass -c conda-forge grass=8.5.0
micromamba run -p ~/micromamba/envs/gp-q42  pip install pytest-qgis==5.0.2 pygeodiff==2.3.2
micromamba run -p ~/micromamba/envs/gp-q334 pip install pytest-qgis==5.0.2
```

conda-forge had no 3.34.15 build that solved on this machine; 3.34.6 is the
3.34 LTR release measured.

## Other tools

| Tool | Version | Where |
|---|---|---|
| Kart (baseline B3) | 0.17.1 | release binary, `~/.local/opt/Kart-0.17.1-linux-x86_64/kart/kart` (override with `KART=`) |
| geodiff (baseline B4) | 2.3.2 | `pygeodiff` in `gp-q42` |
| mermaid-cli (diagrams) | 12.0.0 | `npx`, rendering through the system Chromium (`docs/Journal/array/figures/puppeteer.json`) |
| Tectonic (manuscript) | 0.17.0 | standalone binary |
| Development `.venv` | Python 3.10.21 | unit tests and the offline audits (no QGIS) |

## Data sources

| Data | Source | Access |
|---|---|---|
| Landsat Collection 2 Level-2, path/row 142/052 | Microsoft Planetary Computer STAC, `landsat-c2-l2` | anonymous SAS token; product ids and SHA-256 in `case_cuddalore/data/scenes.json` |
| Copernicus DEM GLO-30, tile N11 E079 | Planetary Computer STAC, `cop-dem-glo-30` | signed through the Planetary Computer `sign` endpoint (the collection token returns 403) |

## Running QGIS headless

`evaluation/qgis.sh <env> <script>` runs a script with an environment's own
Python through `micromamba run`, so the activation scripts set `PROJ_DATA` and
`GDAL_DATA` (calling the environment's Python directly loses them and every CRS
lookup fails). Scripts call `os._exit` after flushing their output, because QGIS
aborts during interpreter teardown.

Headless runs write Processing history entries into the default QGIS profile of
the user running them (`~/.local/share/QGIS/QGIS3` or `QGIS4`), exactly as a
desktop session would.
