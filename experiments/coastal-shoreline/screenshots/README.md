# Cuddalore coast case study: QGIS screenshots

Screenshots of the GeoProvenance panel and map canvas in QGIS 4.2.2, taken while
running the Cuddalore shoreline-change workflow (Landsat 8, 24 Jun 2015 and
Landsat 9, 1 Aug 2026; path/row 142/052). Scene identifiers, dates and cloud
cover are in `../scene_manifest.json`. The workflow itself is `../scenario.py`.

| File | What it shows |
|---|---|
| `Fig05.1_baseline_inputs_to_MNDWI.png` | Baseline inputs (green and SWIR1 bands) through to the MNDWI rasters |
| `Fig05.2_watermask_to_transects.png` | Water mask through to the shoreline, baseline and transects |
| `Fig05.3_shoreline_to_distance_join.png` | Shoreline distances joined to the baseline points |
| `Fig05.4_distance_to_epr_classified.png` | Distances to the End Point Rate and its classes |
| `Fig05.5_reproducibility_audit_baseline_100.png` | Audit of the unmodified workflow: 100/100 |
| `Fig06.1_P1_silent_resave_convert_format_chain.png` | P1 analogue: a silent re-save made with Convert Format, shown as a new file in the chain |
| `Fig06.2_P1_vs_P4_diverging_chain.png` | A re-saved file and an attribute-edited file descending from the same parent |
| `Fig06.3_P4_reproducibility_audit_60.png` | Audit report scoring 60/100 (MODERATE); the existence check failed for 2 of 2 files |

The screenshots are illustrative live-session analogues of the controlled
perturbations. The scripted trials and their verdicts are in
`../perturbation_results.json` and `../RESULTS_SUMMARY.md`.
