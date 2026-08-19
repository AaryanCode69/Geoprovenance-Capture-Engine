# CONTRACT: The capture event dict

> **STATUS: READY TO FREEZE — pending Person B and Person C sign-off.**
> Every `OPEN:` item is closed. Becomes binding when tagged `contract-v1`, which
> needs all three people's agreement (`RULES.md` §3.1). After that, §3.4 applies.

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
  # Every layer entry carries the SAME key set whatever its type. Vector
  # fields are null on a raster and raster fields are null on a vector, so
  # Person B tests for null, never for presence.
  "inputs":  [{"param": "INPUT",  "path": "/data/roads.shp",  "format": "Shapefile",
               "crs": "EPSG:4326", "layer_type": "vector", "feature_count": 1204,
               "band_count": None, "pixel_size": None, "width": None, "height": None}],
  "outputs": [{"param": "OUTPUT", "path": "/out/buffered.shp", "format": "Shapefile",
               "crs": "EPSG:4326", "layer_type": "vector", "feature_count": 1204,
               "band_count": None, "pixel_size": None, "width": None, "height": None}],
  # ...and the same entry for a raster:
  # {"param": "INPUT", "path": "/data/dem.tif", "format": "GeoTIFF",
  #  "crs": "EPSG:32643", "layer_type": "raster", "feature_count": None,
  #  "band_count": 3, "pixel_size": [30.0, 30.0], "width": 1200, "height": 800}
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
| `format` | From the provider/driver name, **not** the file extension — a `.gpkg` can hold vector or raster (`RULES.md` §5.8). Canonicalised to a stable name where the driver is recognised (`ESRI Shapefile` → `Shapefile`, `GPKG` → `GeoPackage`, `GTiff` → `GeoTIFF`). An unrecognised driver is reported **verbatim**, never mapped to a guess. The generic provider names `ogr` and `gdal` are deliberately not translated — they identify a container, not a format. |
| `feature_count` | Vectors only, `None` for rasters. |
| `band_count`, `pixel_size`, `width`, `height` | Rasters only, `None` for vectors. `pixel_size` is `[x, y]` ground units per pixel in the layer's CRS, or `None` when either axis is unavailable or non-finite. |
| `ended_at` | May be `None` for a cancelled run that never completed. |
| `parameters` | A source restricted to a layer's selected features records its path with a `\|selectedFeaturesOnly=yes` suffix. **This is a parameter value, never a path** — the corresponding `inputs` entry holds the clean path. Two runs differing only by this flag are genuinely different runs and are not deduplicated against each other. |

---

## Closed decisions

Both `OPEN:` items are resolved. Recorded here with their rationale so the reasoning survives.

### Raster layer entries — four fields, always present

*Closed by Person A, 18 Aug 2026 (A4).* Raster entries carry `band_count`, `pixel_size`, `width` and `height`, mirroring `feature_count` for vectors.

The keys are present on **every** layer entry regardless of type rather than appearing only on rasters. A uniform key set costs four nulls per vector entry and saves Person B from branching on key presence — and a `KeyError` in the PROV mapper is a worse outcome than four nulls in a JSON blob.

*Why not a nested `raster: {...}` sub-object:* it reads better but makes `merge_results` and Person B's mapper both walk two shapes instead of one, for no gain that a reader of the record ever sees.

### `agent.plugin_versions` — every installed plugin

*Closed by Person A, 18 Aug 2026 (A4). Person B to confirm.* The map lists **every installed plugin**, not only those that took part in the run.

*Why:* it matches `RULES.md` §4.6's environment fingerprint, which is what `get_or_create_agent` deduplicates on. A plugin that was merely *present* can still have changed the result — it may have registered a Processing provider, patched a setting, or shadowed an algorithm id — so it belongs in the fingerprint of the environment. "Only participating plugins" also cannot be determined reliably from inside a post-execution hook.

> **`UNVERIFIED:` — the code does not implement this yet.** `capture/environment.py` currently enumerates `qgis.utils.active_plugins`, which is the **loaded** set, not the installed set. The switch to `available_plugins` is scheduled for A6, where `environment.py` is hardened, and it needs a running QGIS to verify (`RULES.md` §11.4).

---

## Changelog

| Date | Version | Change | Who must update what |
|---|---|---|---|
| 2026-08-19 | 1 (draft) | **The event dict itself is unchanged.** What changed is how §5.9's dedup key is computed from it: it was hashing `event["parameters"]` — the POST-SPLIT scalar dict — so the hook (which passes `parameter_definitions` and lifts layer params into `inputs`/`outputs`) and the history channel (which passes none and keeps them as scalars) produced different keys for one execution. Cross-channel dedup could therefore never fire. The key is now computed over the RAW pre-split parameter dict, and duplicates are matched against an activity's `[started_at, ended_at]` interval instead of a shared 100 ms bucket. `ProvenanceCaptureEngine.record_event` gained an optional keyword-only `raw_parameters`. | **Person B:** nothing to change — the event shape, its schema and every field are as before, and `record_event(event)` still works unchanged (§1.5). Worth knowing only because `activities.corroborations` was previously always 0 and now reflects reality. |
| 2026-08-18 | 1 (draft) | **Both `OPEN:` items closed; status is now READY TO FREEZE.** Layer entries gain four raster fields — `band_count`, `pixel_size`, `width`, `height` — present on every entry and null where they do not apply. `format` is now canonicalised from the driver name. A source restricted to selected features records a `\|selectedFeaturesOnly=yes` suffix in `parameters`. | **Person B:** four new keys on every `inputs`/`outputs` entry — additive, so an existing mapper keeps working, but rasters now carry real metadata worth mapping. If you assert on `format` strings, `ESRI Shapefile` is now `Shapefile` and `GPKG` is now `GeoPackage`. Re-pull `tests/fixtures/mock_events.json`. Please confirm the `plugin_versions` decision above. |
| 2026-08-18 | 1 (draft) | `source` gains `run_wrapper`. A3 installs the `processing.run` monkeypatch alongside the post-execution hook, so there are three channels, not two. Free to change now — the contract is not yet tagged `contract-v1`. | Person B: if you switch on `source`, add the third case. |
| — | 1 | Initial draft. Not yet frozen. | — |
