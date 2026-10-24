# Evaluation — every number in the manuscript's §5

One command re-runs every measurement and regenerates every table, number and
figure (about 20 minutes on the machine in `ENVIRONMENT.md`):

```sh
evaluation/run_all.sh            # measure, then report
evaluation/run_all.sh report     # only regenerate tables and figures from the results here
```

`report.py` writes `docs/Journal/array/generated/*.tex` (a `numbers.tex` of
macros plus the table bodies) and the data figures. The manuscript `\input`s
them, so no number in it is typed by hand.

Hypotheses (expected verdicts) were written to `expected.json` files and
committed **before** each run; they are not edited afterwards. Where a result
differs from its hypothesis the paper reports the difference.

| Manuscript | What | Script | Raw results |
|---|---|---|---|
| Tables 6–7, Fig. 5 (E1) | perturbation suite, confusion matrix | `perturb_suite/run_suite.py` (gp-q42) | `perturb_suite/results/trials.csv`, `final_run.log`; development run: `dev_run_trials.csv` |
| Table 8 (E2) | baselines: SHA-256, sidecar SHA-256, Kart, geodiff | `baselines/run_baselines.py` (gp-q42) | `baselines/results/baselines.csv`, `versions.json` |
| Table 9 (E7) | capture completeness per invocation path, both QGIS | `completeness/run_paths.py` (gp-q42, gp-q334) | `completeness/results/qgis_<version>.json` |
| Table 10 (E3) | per-job overhead by stage, database growth | `overhead/run_overhead.py` (gp-q42, gp-q334) | `overhead/results/overhead_<version>.json` |
| Fig. 6 (E3) | fingerprint time and memory against size | `overhead/fingerprint_bench.py generate`, then `measure` | `overhead/results/fingerprint_bench.json` |
| Fig. 7, Table 11 (E4) | case study 1, Cuddalore shoreline change, P1–P5 | `case_cuddalore/download.py`, `run_in_qgis.py baseline`, `run_in_qgis.py perturb` | `case_cuddalore/results/*.json`, `data/scenes.json`, `provenance.db` |
| Table 12, Fig. 8 (E5) | case study 2, watershed delineation, H1–H4 | `case_hydro/run_in_qgis.py` (gp-q42 with gp-grass on `PATH`) | `case_hydro/results/hydro.json`, `provenance.db` |
| Table 13 (E6) | audit scenarios, offline and on QGIS 3.34 | `audit/scenarios.py offline` (`.venv`), `audit/scenarios.py q334` (gp-q334) | `audit/results/scenarios.json` |
| Fig. 4 | the panel, live, offscreen | `figures/panel_shot.py` (gp-q42) | `figures/results/panel.json` |
| §4, §5.1 (E8) | machine, test counts | `hardware.py`, pytest with `--junitxml` | `ENVIRONMENT.json`, `tests_noqgis.xml`, `tests_q42.xml`, `tests_q334.xml` |

Large regenerable files (downloaded scenes, intermediate rasters, the synthetic
benchmark datasets, per-run work directories) are gitignored; their sources and
checksums are recorded so the scripts rebuild them.

The GUI paths of E7 (Toolbox, batch, Modeler) are driven **programmatically**
through the dialogs QGIS itself opens, on an offscreen display, not by a person
clicking. The manuscript says so.
