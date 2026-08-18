# Experiments — RQ1 and RQ2

Person A owns **RQ1** (capture completeness) and **RQ2** (runtime and storage overhead). The engine is the thing being measured.

**`RULES.md` §8.7 — every number reported in the paper or in a demo must be regenerable by running something in this directory.** No figure appears that cannot be traced back to a script and its raw output.

---

## Layout

```
experiments/
  rq1_completeness/   ground truth, run scripts, raw results, charts
  rq2_overhead/       timing + storage harness, raw results, charts
  data/               benchmark datasets — NOT committed (too large)
```

---

## Benchmark data — download in Week 3, not Week 9

`RULES.md` §8.9. The Sentinel-2 tile is slow to acquire and is a schedule risk.

| Workflow | Ops | Data needed | Source |
|---|---|---|---|
| A — Simple | 3 | Natural Earth `countries.shp` | naturalearthdata.com |
| B — Medium | 8 | Sentinel-2 tile, bands 4 and 8 | Copernicus Browser — **slow, get it early** |
| C — Complex | 15+ | OSM extract (roads, buildings, land use) + a DEM | Geofabrik + SRTM/Copernicus DEM |

Record the exact download URL, date, and file size for each — reproducibility of the reproducibility paper is not optional.

---

## RQ1 — Capture completeness

Protocol (`RULES.md` §8.2, §8.3; research doc §9.3 Experiment 1):

1. **Enumerate ground truth by hand, BEFORE running anything.** Counting operations after the fact contaminates the measurement.
2. Run each workflow with the plugin enabled, 3× each.
3. Across **four invocation paths**: Toolbox dialog · `processing.run()` from the Python console · Graphical Modeler · batch mode.
4. `completeness = captured / total × 100`.
5. Report **per-path**, not just an aggregate — it is the stronger result and the honest way to present paths where the hook does not fire.
6. Include the per-channel hook-vs-history split from the `activities.capture_channel` / `corroborations` columns.

Target: **>95%**. Feeds `docs/capture_coverage.md`.

---

## RQ2 — Runtime overhead

Protocol (`RULES.md` §8.4, §8.5; research doc §9.3 Experiment 2):

1. 10 runs per workflow **without** the plugin, 10 **with**. Same machine, same data.
2. The baseline has the plugin **fully disabled, not merely idle**.
3. `overhead = (t_with − t_without) / t_without × 100`. Report mean, std, 95% CI.
4. Break down by stage: hook + normalize · database write · hashing.
5. **Hashing is Person B's cost but falls inside Person A's measured window. Attribute it explicitly and separately** — reporting B's cost as A's is a measurement error that makes the headline number look worse than it is.

Target: **<5%**.

---

## RQ2 — Storage overhead

Protocol (`RULES.md` §8.6; research doc §9.3 Experiment 3):

1. Database size after each workflow.
2. `bytes_per_operation = db_size / n_operations`.
3. Repeat across **10 MB / 100 MB / 1 GB** input datasets.

The claim worth making is that **storage is independent of data volume** — the varying dataset sizes exist to demonstrate exactly that, not as an afterthought.

Target: **<100 KB per workflow**.

---

## Reporting

`RULES.md` §8.8 — results are reported as measured. **A missed target is a finding with an explanation, not a number to adjust.** A capture rate of 91% with a clear account of which invocation path failed is a better paper than an unexplained 96%.
