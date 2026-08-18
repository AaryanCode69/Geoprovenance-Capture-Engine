# CONTRACT: The capture event dict

> **STATUS: DRAFT — NOT YET FROZEN.**
> Becomes binding when tagged `contract-v1`. After that, `RULES.md` §3.4 applies.

| | |
|---|---|
| **Author** | Person A (`geoprovenance/capture/normalizer.py` emits it) |
| **Consumer** | Person B (the PROV mapper consumes it) |
| **Machine-readable** | `schemas/event.schema.json` |
| **Baseline** | `PERSON_A.md` §A0.2 |

---

## The shape

```python
{
  "event_id": "uuid4",
  "session_id": "uuid4",
  "source": "post_hook" | "run_wrapper" | "history_signal",  # dedup + RQ1 channels
  "algorithm_id": "native:buffer",
  "algorithm_name": "Buffer",
  "provider": "qgis",
  "started_at": "2026-08-08T10:14:22.481903+00:00",
  "ended_at":   "2026-08-08T10:14:23.004117+00:00",
  "status": "completed" | "failed" | "cancelled",
  "parameters": {"DISTANCE": 500, "SEGMENTS": 5, "DISSOLVE": False},
  "inputs":  [{"param": "INPUT",  "path": "/data/roads.shp",  "format": "Shapefile",
               "crs": "EPSG:4326", "layer_type": "vector", "feature_count": 1204}],
  "outputs": [{"param": "OUTPUT", "path": "/out/buffered.shp", "format": "Shapefile",
               "crs": "EPSG:4326", "layer_type": "vector", "feature_count": 1204}],
  "agent": {"qgis_version": "3.34.8", "os_info": "Ubuntu 22.04",
            "python_version": "3.10.12", "plugin_versions": {"GeoProvenance": "0.1.0"}},
  "execution_log": None
}
```

---

## Three rules Person B will definitely hit

Stated explicitly because every one of them has bitten someone (`RULES.md` §3.3).

### 1. Memory and temporary layers have no path

`memory:`, `TEMPORARY_OUTPUT`, and `/vsimem/` layers get `"path": None` but keep `"layer_type"`.

> **Person B: do not attempt to fingerprint these.** There is no file on disk. Skip them, and record the skip — an unfingerprinted intermediate is a legitimate audit finding for Person C, not an error.

### 2. Layer-valued parameters are lifted out

If a parameter's value is itself a layer, it appears in `inputs` or `outputs` with its `param` key, **not** in `parameters`. Only scalar values (numbers, strings, booleans, enums) stay in `parameters`.

So `native:clip`'s `OVERLAY` appears as an entry in `inputs` with `"param": "OVERLAY"`, not as `parameters["OVERLAY"]`.

### 3. `parameters` is always JSON-serializable

QGIS hands the normalizer `QgsProcessingFeatureSourceDefinition`, `QgsCoordinateReferenceSystem`, `QgsProperty`, and friends. The normalizer flattens all of them to strings before they reach this dict, falling back to `repr()` for anything unrecognised (`RULES.md` §5.5).

> This is the single biggest source of crashes in this component (`PERSON_A.md` §A4). Person B can rely on `json.dumps(event)` never raising.

---

## Field notes

| Field | Note |
|---|---|
| `source` | Which channel produced the event: `post_hook` (the Processing post-execution hook), `run_wrapper` (the `processing.run` monkeypatch), `history_signal` (`QgsHistoryProviderRegistry.entryAdded`). Kept for dedup (`RULES.md` §5.9) **and** because the per-channel split is an RQ1 result (`RULES.md` §8.3). |
| `started_at` / `ended_at` | Microsecond-precision UTC ISO 8601, always (`RULES.md` §3.2 decision 4). |
| `status` | `failed` and `cancelled` events **are emitted**, never dropped — C's audit needs them and RQ1 completeness counts them (`RULES.md` §4.10). |
| `crs` | `authid()` (`"EPSG:4326"`). WKT only when the CRS has no authid (`RULES.md` §5.7). |
| `format` | From the provider/driver name, **not** the file extension — a `.gpkg` can hold vector or raster (`RULES.md` §5.8). |
| `feature_count` | Vectors only. `None` for rasters; raster metadata goes in the layer entry as band/size fields. |
| `ended_at` | May be `None` for a cancelled run that never completed. |

---

## `OPEN:` items — close before freezing

**`OPEN:` — Person A, end of Phase 0.** Raster layer entries need their own field set (band count, pixel size, dimensions). The shape above only specifies `feature_count` for vectors. Define the raster equivalent before B writes the mapper.

**`OPEN:` — Person A + Person B, end of Phase 0.** Whether `agent.plugin_versions` includes every installed plugin or only those that participated in the run. Every-plugin is simpler and matches `RULES.md` §4.6's environment fingerprint; confirm B agrees.

---

## Changelog

| Date | Version | Change | Who must update what |
|---|---|---|---|
| 2026-08-18 | 1 (draft) | `source` gains `run_wrapper`. A3 installs the `processing.run` monkeypatch alongside the post-execution hook, so there are three channels, not two. Free to change now — the contract is not yet tagged `contract-v1`. | Person B: if you switch on `source`, add the third case. |
| — | 1 | Initial draft. Not yet frozen. | — |
