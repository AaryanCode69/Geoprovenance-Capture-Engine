# Person A — Capture Engine & Storage

Task breakdown, requirements, and deliverables for the GeoProvenance component owned by Person A.

Scope reference: `README.md` § "Person A", research doc §5.1 (architecture, everything left of *PROV Mapper*), §5.2 (interception), §5.3 (sequence), §7.1 (schema), §9 (RQ1, RQ2).

---

## 0. What you own (and what you don't)

**You own — the write path.** Everything that turns a QGIS Processing execution into rows in the SQLite database.

| Module | File (proposed) | Responsibility |
|---|---|---|
| Plugin skeleton | `geoprovenance/__init__.py`, `plugin.py`, `metadata.txt` | Loads in QGIS, registers menu/toolbar, starts & stops the engine |
| Hook manager | `capture/hooks.py` | Installs the Processing post-execution hook / `processing.run()` wrapper |
| History observer | `capture/history_observer.py` | `QgsHistoryProviderRegistry.entryAdded` redundant channel + polling fallback |
| Capture engine | `capture/engine.py` | `ProvenanceCaptureEngine` singleton; receives raw events from both channels |
| Event normalizer | `capture/normalizer.py` | Dedup, parameter parsing, type inference, CRS extraction, path resolution |
| Environment probe | `capture/environment.py` | QGIS version, OS, Python version, installed plugin versions (agent record) |
| Schema + migrations | `storage/schema.sql`, `storage/migrations.py` | §7.1 DDL, `PRAGMA user_version` versioning |
| CRUD layer | `storage/store.py` | `ProvenanceStore` — the API **B and C both call** |
| Session/workflow grouping | `storage/workflows.py` | Group activities into `workflows` + `workflow_activities` with `sequence_order` |

**You do not own:** SHA-256 computation, PROV class model, `wasDerivedFrom` inference, PROV-JSON export (all B); DAG rendering, audit scoring (both C). You *do* own the `fingerprints` and `relations` **tables and their CRUD** — B calls your writer, B does not write SQL.

**Feature priority you own:** automatic `processing.run()` capture (MUST), SQLite storage (MUST), plugin version tracking (SHOULD), multi-step chaining — session/order half (SHOULD, shared with B).

---

## Phase 0 — Contracts (joint, ~week 2, short but blocking)

You are the *author* of two of the three frozen contracts, because both come out of your component. B and C cannot start Phase 1 until you publish them.

### A0.1 Freeze the SQLite schema
Take §7.1 verbatim as the baseline, then resolve these open points **before** freezing — each one changes B's or C's code if you change it later:

1. **Entity identity / versioning.** §7.1 has no uniqueness rule on `entities.file_path`. If `roads.shp` is overwritten by a second run, is it the same entity or a new one? Decide: *one entity row per (file_path, content version)*, i.e. a re-written file with a different fingerprint gets a new entity UUID. This is what makes `wasDerivedFrom` chains (B) and DAG history (C) correct. Document it.
2. **`relations.role` vocabulary.** The schema comment says `'input' | 'output' | 'parameter'`; the §7.3 example uses `"INPUT"` and `"OVERLAY"`. Pick one — recommend lowercase `input`/`output`/`overlay`/`parameter` and store the original QGIS parameter key (e.g. `OVERLAY`) in a separate column or in the relation's role string. Freeze it.
3. **Missing indices.** Add `CREATE INDEX` on `relations(source_id)`, `relations(target_id)`, `relations(relation_type)`, `entities(file_path)`, `fingerprints(entity_id)`, `workflow_activities(workflow_id)`. C's DAG traversal does repeated reverse lookups; without these it will be slow on Workflow C (15+ ops) and your RQ2 storage/runtime numbers will look worse than they are.
4. **`fingerprints` UNIQUE(entity_id, computed_at).** Second-resolution ISO timestamps can collide when B hashes input and output in the same tick. Mandate microsecond-precision ISO 8601 everywhere (`datetime.now(timezone.utc).isoformat()`).
5. **Session grouping.** §7.1 has `workflows` but nothing links an activity to the QGIS session that produced it. Add `activities.session_id TEXT` (a UUID minted at plugin startup) — this is what lets you auto-group a run into a workflow without user input.
6. **`PRAGMA user_version = 1`** plus a `migrations.py` that can bump it. You will change the schema in Phase 2; a migration path stops B and C's fixture DBs from silently breaking.

**Output:** `docs/CONTRACT_schema.md` + `storage/schema.sql`, tagged `contract-v1` in git.

### A0.2 Freeze the event dict
The shape your normalizer emits and B's PROV mapper consumes. Proposed:

```python
{
  "event_id": "uuid4",
  "session_id": "uuid4",
  "source": "post_hook" | "history_signal",   # for dedup + RQ1 channel analysis
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

Non-obvious rules to state explicitly, because B will hit all of them:
- Memory / temporary layers (`memory:`, `TEMPORARY_OUTPUT`, `/vsimem/`) — `path` is `None`, `layer_type` still set. B must not try to hash them.
- Parameter values that are themselves layers are lifted into `inputs`; scalar parameters stay in `parameters`.
- `parameters` must be JSON-serializable — QGIS hands you `QgsProcessingFeatureSourceDefinition`, `QgsCoordinateReferenceSystem`, `QgsProperty` objects. Your normalizer flattens them to strings. This is the single biggest source of crashes in this component.

**Output:** `docs/CONTRACT_event.md` + a `jsonschema` file, tagged `contract-v1`.

### A0.3 Build the shared mock dataset
You generate it (you own the schema), everyone consumes it.

- `tests/fixtures/mock_provenance.db` — the §7.3 Buffer→Clip workflow, hand-built, plus one longer 8-step chain and one branch (two outputs from one activity) so C's layout code meets a non-linear graph early.
- `tests/fixtures/mock_events.json` — the same workflow as a list of event dicts, for B.
- `tests/fixtures/build_fixtures.py` — the generator, so the fixtures are reproducible and regenerable after a schema bump.
- Small real data files under `tests/fixtures/data/` (a few-KB shapefile + GeoPackage) so B's fingerprinter and C's "input exists" check have something on disk.

**Phase 0 exit criterion:** B and C can each run `pytest` against your fixtures with zero QGIS running and zero code from you beyond `storage/store.py`.

---

## Phase 1 — Independent build (weeks 3–8, your bulk of work)

Six sub-phases. A1–A3 are Review 1 (week 4); A4–A6 land by Review 2 (week 8).

### A1 — Plugin skeleton *(week 3)*
**Requirements**
- Plugin Builder 3 scaffold, `metadata.txt` with `qgisMinimumVersion=3.34`.
- Separate QGIS dev profile (`qgis --profile geoprov-dev`) so a crash never takes out your normal QGIS.
- Symlink or `pb_tool deploy` into `~/.local/share/QGIS/QGIS3/profiles/geoprov-dev/python/plugins/`.
- Menu action + toolbar button + an empty dock widget placeholder (C will fill the dock later — agree on the dock's class name now).
- Plugin reload workflow (Plugin Reloader) documented in the repo README.

**Done when:** plugin loads and unloads cleanly, no errors in the QGIS log, `unload()` disconnects everything.

### A2 — Storage layer *(week 3)*
**Requirements**
- `ProvenanceStore(db_path)` — creates the DB on first use, applies `schema.sql`, sets `user_version`.
- `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL` (WAL matters: C's audit reads while your engine writes).
- Methods: `add_entity`, `add_activity`, `add_agent`, `add_fingerprint`, `add_relation`, `get_or_create_agent`, `find_entity_by_path`, `get_activity`, `get_relations_for`, `list_workflows`, `get_workflow_graph`.
- A `with store.transaction():` context manager — one algorithm execution is one atomic transaction. A half-written activity (activity row but no relations) will silently corrupt C's DAG.
- Thread-safety note: QGIS may run algorithms off the main thread. Either `check_same_thread=False` + a lock, or a per-thread connection. Decide and document.
- DB location: plugin profile dir by default (`QgsApplication.qgisSettingsDirPath()`), overridable per-project.

**Done when:** 15+ unit tests pass with **no QGIS import at all** (pure `sqlite3` + `pytest`) — this is what makes your storage layer independently testable and lets B and C use it immediately.

### A3 — Capture POC: one algorithm end-to-end *(week 4 — Review 1)*
**Requirements**
- `ProvenanceCaptureEngine.instance()` singleton with `record_algorithm_execution(algorithm, parameters, context, results, feedback)`.
- Post-execution hook installed: write the hook script, and set `ProcessingConfig` `POST_EXECUTION_SCRIPT` programmatically on plugin load (restore the user's previous value on unload — don't clobber their setting).
- **Verify empirically which invocation paths actually fire the hook.** The hook is run by `Processing.runAlgorithm`; the Toolbox dialog, batch mode, and the Modeler may take different code paths. Write a one-page findings table — this table *is* your RQ1 evidence, so start it in week 4, not week 9.
- Fallback channel if the hook proves unreliable: wrap `processing.run` by monkeypatching `processing.tools.general.run`, preserving the original signature and return value, never swallowing exceptions.
- Capture a single `native:buffer` → one `agents` row, one `activities` row, two `entities` rows, `used` + `wasGeneratedBy` relations → print to the QGIS message log.

**Review 1 demo (week 4):** run Buffer in the Toolbox → record appears in SQLite and in the message log. 5+ unit tests green.

### A4 — Event normalizer, hardened *(week 5)*
**Requirements**
- Parameter serialization for every awkward QGIS type (see A0.2). Fall back to `repr()` rather than raising — **the capture layer must never break the user's actual processing run.** Wrap the whole hook body in a broad `try/except` that logs and returns.
- Output path resolution: `results` gives you `{'OUTPUT': '/path'}` or a layer id or a `QgsVectorLayer`; resolve all three to a filesystem path or `None`.
- CRS extraction: from the layer where available; from `context.project().crs()` as fallback; store as `authid()` (e.g. `EPSG:4326`), WKT only if no authid.
- Format detection from the provider/driver name, not the file extension (a `.gpkg` can hold vector or raster).
- Feature count for vectors (cheap: `layer.featureCount()`), band/size metadata for rasters.

### A5 — Dual-channel capture and deduplication *(week 6)*
**Requirements**
- Connect `QgsGui.historyProviderRegistry().entryAdded` (QGIS 3.24+; verify the exact signal signature against your local build — it has changed across releases).
- Polling fallback per risk #7: `QTimer` + `queryEntries()` since the last seen entry id, in case the signal is unstable.
- **Dedup rule** — the same execution will arrive on both channels. Key on `(algorithm_id, normalized_parameters_hash, started_at rounded to 100ms)`; first channel wins, second is recorded as a *corroboration* (increment a counter, don't insert). Keep that counter — "the hook caught 98%, the history channel caught the other 2%" is a genuinely publishable RQ1 result.
- Failed and cancelled runs must be recorded with `status='failed'`, not dropped. C's audit needs them and RQ1 completeness counts them.

### A6 — Session grouping and plugin version tracking *(weeks 6–7)*
**Requirements**
- Workflow auto-grouping: activities sharing a `session_id` and connected by shared dataset paths become one `workflows` row with `sequence_order` set by `started_at`. (B independently infers `wasDerivedFrom` from path overlap — your grouping is temporal/session-based, B's is data-flow-based. Both are needed; don't duplicate B's job.)
- Manual override: a "Start new workflow" / "Name this workflow" action in the plugin menu.
- `plugin_versions_json`: enumerate installed plugins and versions via `qgis.utils.plugins` / `pluginMetadata()`. Also record QGIS version, OS (`platform.platform()`), Python version. One `agents` row per distinct environment fingerprint, reused across activities (`get_or_create_agent`) — otherwise you write a duplicate agent row per execution and inflate your RQ2 storage numbers.

**Phase 1 exit criteria**
- ✅ 4-step workflow run in QGIS → all 4 activities, all entities, all relations, correct `sequence_order`.
- ✅ Zero user-visible impact when the plugin errors internally.
- ✅ 25+ tests; storage tests run without QGIS, capture tests run under `pytest-qgis`.
- ✅ `docs/capture_coverage.md` — the empirical table of what fires the hook and what doesn't.

---

## Phase 2 — Integration (weeks 7–8)

**Your job here:** be the upstream. Everything else waits on your writes being correct.

- Call B's fingerprinter from the engine at the right two moments (input before execution, output after) — per the §5.3 sequence. Run hashing on a background thread or after the transaction commits so it never adds latency to the user's run.
- Hand B the event dicts; accept B's PROV objects and persist them through your store.
- Point C's viewer and audit engine at the live DB path instead of the mock fixture (one config value — make sure it *is* one config value).
- Concurrency check: C reading (audit + DAG) while you write. WAL mode plus short transactions.
- Fix the contract mismatches that surface here, via a `migrations.py` bump — and regenerate the fixtures so B's and C's tests stay green.

**Done when:** a fresh QGIS session, an empty DB, a 4-step workflow → DAG renders and the audit produces a score, with no manual DB fiddling.

---

## Phase 3 — Experiments and paper (weeks 9–12)

You own **RQ1 (capture completeness)** and **RQ2 (runtime + storage overhead)** — your engine is the thing being measured.

### RQ1 — Capture completeness (research doc §9.3 Exp. 1)
- Ground truth: manually enumerate every operation in Workflows A (3 ops), B (8 ops), C (15+ ops) *before* running them.
- Execute each workflow 3× with the plugin enabled; `completeness = captured / total × 100`.
- Run each workflow through **four invocation paths**: Toolbox dialog, `processing.run()` from the Python console, Graphical Modeler, batch mode. Report per-path completeness — this is a stronger result than a single aggregate number, and it's the honest way to present the paths where the hook doesn't fire.
- Report the per-channel breakdown (hook vs. history signal) from your A5 counter.
- Target: >95%.

### RQ2 — Runtime overhead (§9.3 Exp. 2)
- 10 runs per workflow without the plugin, 10 with. Same machine, same data, plugin fully disabled (not just idle) for the baseline.
- `overhead = (t_with − t_without) / t_without × 100`; report mean, std, 95% CI.
- Break the overhead down by stage: hook + normalize, DB write, hashing (B's, but it's inside your measured window — attribute it explicitly or you'll be reporting B's cost as yours).
- Target: <5%.

### RQ2 — Storage overhead (§9.3 Exp. 3)
- DB size after each workflow; `bytes_per_operation = db_size / n_operations`.
- Vary dataset size (10 MB / 100 MB / 1 GB) to show storage is independent of data volume — that's the actual claim worth making.
- Target: <100 KB per workflow.

### Writing
- Methodology subsection for the capture + storage layer (architecture, interception strategy, dedup, the honest limitations table from §5.2).
- Charts for RQ1/RQ2.
- Contribute to the joint Intro / Related Work / Results.

---

## Requirements checklist (things to have before you start)

| | Requirement |
|---|---|
| ☐ | QGIS 3.34 LTS installed; note its bundled Python version (`import sys; sys.version` in the QGIS console) |
| ☐ | A separate QGIS dev profile |
| ☐ | `pytest`, `pytest-qgis`, `jsonschema` in a venv built on that same Python |
| ☐ | Plugin Builder 3 + Plugin Reloader installed in QGIS |
| ☐ | DB Browser for SQLite (or `sqlite3` CLI) for inspecting output |
| ☐ | Benchmark data downloaded early: Natural Earth (Workflow A), a Sentinel-2 tile (B), OSM extract + DEM (C) — the Sentinel-2 download is slow, get it in week 3, not week 9 |
| ☐ | Git repo with the `contract-v1` tag agreed by all three |

**Skills to ramp on:** PyQGIS Processing internals (`processing.run`, `QgsProcessingAlgorithm`, `QgsProcessingContext`), `ProcessingConfig` settings, PyQt5 signals/slots, `sqlite3` transactions and WAL, `pytest-qgis` fixtures.

**Blocking dependencies on others:** none after Phase 0. You are the least blocked of the three — and the most blocking, so ship the contract and fixtures fast.

---

## Final output — what Person A delivers

**Code**
1. `geoprovenance/` QGIS plugin skeleton that loads in QGIS 3.34 LTS (`metadata.txt`, `plugin.py`, menu/toolbar/dock registration, clean `unload()`).
2. `capture/` — capture engine, post-execution hook installer + `processing.run()` wrapper, history-registry observer with polling fallback, dedup logic, event normalizer, environment/plugin-version probe.
3. `storage/` — §7.1 schema with indices and `user_version` migrations, and `ProvenanceStore`, the CRUD API that B and C both build against.
4. Session→workflow auto-grouping with manual naming.

**Contracts and fixtures (Phase 0, used by B and C)**
5. `docs/CONTRACT_schema.md` + `storage/schema.sql`, tagged `contract-v1`.
6. `docs/CONTRACT_event.md` + JSON Schema for the event dict.
7. `tests/fixtures/` — mock SQLite DB, mock event JSON, sample data files, and the regenerating script.

**Tests**
8. 25+ tests: storage suite runs with no QGIS; capture suite runs under `pytest-qgis`.

**Documentation**
9. `docs/capture_coverage.md` — empirical table of what is and isn't captured, per invocation path (doubles as the paper's limitations section).
10. Installation + developer setup section of the README.

**Research**
11. RQ1 results: capture completeness across 3 workflows × 4 invocation paths × 3 repeats, with per-channel breakdown.
12. RQ2 results: runtime overhead (mean/std/95% CI) and storage overhead (bytes/operation across 3 dataset sizes), with stage-level attribution.
13. Methodology subsection for the capture + storage layer, plus RQ1/RQ2 charts, for the joint paper.

**Demo obligations**
- Review 1 (wk 4): run one algorithm → record in SQLite + message log.
- Review 2 (wk 8): 4-step workflow → all steps captured with correct ordering, feeding B and C.
- Final (wk 12): live capture during the end-to-end demo + your experimental results.
