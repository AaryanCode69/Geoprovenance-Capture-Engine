# CLAUDE.md — GeoProvenance (Person A)

Operating instructions for Claude working in this repository.
**Hard rules live in [`RULES.md`](./RULES.md). Read it before writing code.** This file is orientation; that file is law.

---

## 1. What this project is

**GeoProvenance** — a QGIS plugin that automatically records what QGIS Processing algorithms did, stores it in SQLite mapped to the W3C PROV-O standard, fingerprints the datasets with SHA-256, draws the workflow as a graph, and scores how reproducible the workflow still is.

- Full background, literature review, schema, and experiments: [`geoprovenance_research.md`](./geoprovenance_research.md)
- Team split and phases: [`README.md`](./README.md)
- This developer's full task breakdown: [`PERSON_A.md`](./PERSON_A.md)

It is a **3-month course project ending in a research paper**, assessed at three graded reviews: **Week 4, Week 8, Week 12**.

## 2. Who the user is in this project

The user is **Person A — Capture Engine & Storage**. One of three developers.

**Person A owns the write path.** Everything that turns a QGIS Processing execution into rows in SQLite.

| Owns | Does **not** own |
|---|---|
| Plugin skeleton, `metadata.txt`, menu/toolbar/dock registration | SHA-256 computation (B) |
| Post-execution hook + `processing.run()` wrapper | PROV class model, `wasDerivedFrom` inference (B) |
| `QgsHistoryProviderRegistry` observer + polling fallback | PROV-JSON / JSON-LD export (B) |
| Event normalizer (dedup, parameter flattening, CRS, paths) | DAG rendering (C) |
| Environment / plugin-version probe | Audit scoring engine (C) |
| SQLite schema, migrations, **all** CRUD — including the `fingerprints` and `relations` tables | |
| Session → workflow grouping | |

> Person A owns the `fingerprints` and `relations` **tables and their CRUD**. B calls Person A's writer methods. **B and C never write SQL.**

**Do not write Person B's or Person C's code**, even if it looks like a small helper and even if it would make a demo nicer. If a task appears to need it, say so and stop — see `RULES.md` §1.

## 3. Current state of the repository

**Built and passing — 317 tests, `make test`, no QGIS required:**

- `storage/schema.sql` — 8 tables, 9 indices, `user_version = 1`. Draft, not yet `contract-v1`.
- `storage/migrations.py` — version get/set, forward migrations, refuses a database newer than the code.
- `storage/store.py` — **A2 complete.** `ProvenanceStore` with the full §4.5 method surface, `transaction()` with savepoint nesting, per-thread connections + write lock, WAL + foreign keys. `close()` closes **every** thread's connection, not just the caller's (fixed 19 Aug 2026 — it was leaking exactly the worker-thread connections §4.7 exists to create).
- `tests/fixtures/` — **A0.3 complete.** `mock_provenance.db` (3 workflows, 16 jobs, 23 datasets, 70 relations), `mock_events.json`, `mock_ids.json`, real Shapefile + GeoPackage in `data/`, all regenerable via `make fixtures` and byte-deterministic *on one machine*. **B and C are unblocked** — see `tests/fixtures/README.md`.
  **The two SQLite files are reproducible by their contents, not by their bytes (measured 20 Aug 2026).** Header-blanking alone was claimed to make them byte-identical anywhere; it does not, and the claim is now retired. Building `sample_areas.gpkg` from one identical SQL script under two SQLite builds compiled with identical flags: 3.51.2 vs 3.53.4 differ only in the version stamp (bytes 92–99, which `build_fixtures.py` blanks), but **3.40.1 vs 3.53.4 differ in three further bytes at offset 7368 — stale data in the free space of the schema page** — and a library built without `SQLITE_SECURE_DELETE` differs in ~1000 bytes at the same version. Rows, schema text and root pages are identical in every case; only unused bytes differ. `VACUUM` and `VACUUM INTO` reproduce the residue rather than erasing it, so there is no canonical form to write. `_logical_content` compares contents instead, and now also withholds the one fingerprint row that would otherwise leak the GeoPackage's bytes into the database's content — the SHA-256 of `sample_areas.gpkg` is stored *inside* `mock_provenance.db`. Verified end-to-end against a GeoPackage genuinely written by 3.40.1: the whole fixture set compares clean, where before it failed and named the wrong file.
  All three `capture_channel` values and one corroborated row are represented; counts and ids are unchanged.
- `plugin.py`, `ui/dock.py`, `lifecycle.py`, `paths.py`, `log.py`, `icon.png` — **A1**, written, not yet run in QGIS (see below).
- `capture/normalizer.py` + `capture/engine.py` — **A3 core, complete and tested.** Both import zero QGIS (they duck-type), so the whole write path is verifiable here.
  **§5.9 dedup reworked 19 Aug 2026.** The key was hashed from the *post-split* `event["parameters"]`, which the channels do not produce alike, so cross-channel dedup could never fire: every job was written twice and `corroborations` was permanently 0. It is now keyed on the **raw pre-split** parameters and matched against an activity's `[started_at, ended_at]` interval (`DEDUP_MARGIN_S`) instead of a 100 ms bucket. No schema change. Full write-up in `docs/capture_coverage.md` §4.
- `capture/hooks.py` — **A3/A5, QGIS-only, UNVERIFIED.** Pre- and post-execution hook installers + `processing.run` monkeypatch.
- `capture/history_observer.py` — **A5 complete.** `entryAdded` observer plus the `QTimer` polling fallback; the QGIS-facing halves are UNVERIFIED, the parsing and dedup are not.
- `capture/environment.py` — **A6 hardened.** Agent probe, degrades outside QGIS. Records **every installed** plugin (`available_plugins`) as of 19 Aug 2026 — see the note below.
- `storage/workflows.py` — **A6 complete.** Session → workflow grouping: shared-path connected components, `sequence_order` by `started_at`, `suggest_name`, and a reconciliation that keeps a user-given name across a merge. 26 tests.
- `plugin.py` menu — **A6**: "Start new workflow" and "Name this workflow…" registered through `_add_action`, so their teardown is registered with them. The dialogs themselves are UNVERIFIED.
- `demos/review1.py` + `docs/demos/REVIEW-1.md` — **the Review 1 gate**, passing. Drives the real `handle_post_execution` path, no QGIS needed.
- `demos/review2.py` + `docs/demos/REVIEW-2.md` — **the Review 2 gate**, passing (`make demo2`, 6/6, under a second, byte-identical run to run). Replays four recorded jobs through the real `record_event` path.
- `tools/deploy.py`, `tools/make_icon.py`, `make deploy` / `make qgis`.
- `schemas/event.schema.json` — draft; fixture events and built events both validate.
- `qgis_demo/` — **the visual demonstration, complete and verified in QGIS (24 Aug 2026).** `make qgis-demo` builds it end to end: three input datasets, four Processing steps run inside a real QGIS which captures them, the record exported to map layers, and a styled QGIS project with four layer groups plus a printable page. `make qgis-demo-open` opens it. Every layer verified to load, draw and land in the right place by `make qgis-demo-verify`. Stdlib only — hand-rolled GeoPackage and Shapefile writers, and extents derived by reading file headers, because the record stores no geometry and the schema is frozen. Walkthrough in `qgis_demo/README.md`. This is demo scaffolding, deliberately outside `geoprovenance/` (RULES.md §1.1).

**Stubs only** (docstring + rules): `demos/final.py`.

**Not started:** Phase 2, Phase 3. **Phase 1 (A1–A6) is code-complete.** Its QGIS-dependent exit criteria are now **partly met**: the plugin loads and unloads cleanly in QGIS (11/11 lifecycle tests), a 4-step workflow was captured live at 100%, and `docs/capture_coverage.md` has real measurements in it. What is still missing is the other nine invocation-path rows, which need the desktop application driven by hand — and the fact that all of it was measured on QGIS 4.2.1, not the 3.34 LTS the project targets. See below.

### QGIS ran this — on QGIS 4.2.1, not the 3.34 target (24 Aug 2026)

QGIS was installed on 24 August 2026 and the capture path has now executed inside it for the first time. **Read `docs/capture_coverage.md` before quoting anything from this section** — it holds the evidence and the caveats.

**Which QGIS, and why it matters.** The intended Flathub 3.28.9 LTS build **cannot be installed**: it depends on the end-of-life runtime `org.kde.Platform//5.15-21.08`, and one object in that runtime returns HTTP 503 past 1 MiB from every Flathub CDN edge. QGIS **4.2.1** (Python 3.13.14, Qt 6.10.3, PyQt6) was the only obtainable build. `metadata.txt` was lowered to `qgisMinimumVersion=3.28` for this exercise, with the rationale in the file. **RULES.md §2.1 is not satisfied** — the `.venv` is 3.10.12 and QGIS runs 3.13.14.

**The headline finding: the post-execution hook does not exist in QGIS 4.** `ProcessingConfig.POST_EXECUTION_SCRIPT` and `PRE_EXECUTION_SCRIPT` still exist as *settings* and still appear in the options dialog, but the entire QGIS 4.2.1 installation contains exactly one file that mentions either name — the settings definition itself. `Processing.runAlgorithm` has no hook call. Both hook scripts were written to disk correctly and neither was ever executed. **`capture/hooks.py` is not deleted**: the mechanism may still work on the 3.34 LTS this project targets, and that is precisely what could not be tested.

**Capture was 4/4 = 100% anyway, entirely via the `run_wrapper` channel.** A5's decision to install three channels rather than trust one is what carried it. A single-channel design built on research doc §5.2 would have captured nothing on this QGIS.

| Was unverified | Now |
|---|---|
| Plugin loads/unloads cleanly in QGIS | **Verified.** All 11 `-m qgis` tests in `tests/capture/test_plugin_lifecycle.py` pass inside QGIS 4.2.1 — load, unload, reload, no residue, Person C's `set_content` seam. The A1 exit criterion, met. |
| `ProcessingConfig.POST_EXECUTION_SCRIPT` constant + persistence | **Verified, and the answer is bad.** The constants exist and hold the guessed strings; the feature behind them is gone (above). |
| What variables QGIS puts in the hook namespace | **Still open, and unanswerable on QGIS 4** — the hook never fires, so there is nothing to log. |
| Which invocation paths fire the hook (§5.11 — RQ1 evidence) | **1 of 10 rows measured** (`processing.run()` from a script). The other nine need the desktop application driven by hand. |
| Fixture `.shp` / `.gpkg` open in QGIS | **Verified** against QGIS 4.2.1 *and* GDAL 3.13.3. See `tests/fixtures/README.md`. |
| `qgis.utils.available_plugins` exists and is what A6 assumes | **Verified** — the attribute exists. It reported 0 in a headless run, which is correct; a desktop count is still needed. |
| The A6 menu dialogs ("Start new workflow", "Name this workflow…") | **Still open.** The plugin is deployed (`make deploy`); nobody has clicked them. |
| — new — `QgsHistoryProviderRegistry` | Lives in `qgis.gui`, **not** `qgis.core`, on QGIS 4. `history_observer.py` already reaches it correctly via `QgsGui.historyProviderRegistry()`; do not "tidy" that import. Installed and tore down cleanly, but never fired on a script-driven run. |
| — new — **PyQt6 would have stopped the plugin loading** | `Qt.RightDockWidgetArea` and `Qt.AlignTop` do not exist on Qt 6 (enums are scoped). `ui/dock.py` now uses `_qt_enum()` and `plugin.py` falls back to `QtGui` for `QAction` — feature detection per §2.5, working on both PyQt5 and PyQt6. |

**Do not run `pytest tests` inside QGIS.** Seven tests fail there, none of them a defect: they assert the *no-QGIS* degradation path on purpose (e.g. `test_the_default_needs_qgis_and_says_so_clearly` expects `QgisUnavailableError`). Use `make test` outside QGIS and `make test-qgis` inside. Running `test_regenerating_the_icon_produces_identical_bytes` inside QGIS also **rewrites `geoprovenance/icon.png`** — zlib differs between Python 3.10 and 3.13 — so check `git status` afterwards.

The design compensates rather than hopes: `normalizer.py` and `engine.py` import no QGIS and duck-type instead, so the risky logic is tested and only the thin QGIS adapter is unproven. A guard test now enforces that for `capture/normalizer.py`, `capture/engine.py`, `capture/history_observer.py`, `lifecycle.py` and `log.py` as well as `storage/` — it previously covered `storage/` only, so a stray QGIS import in `engine.py` would have surfaced as a failed demo in a review room.

**One caution carried forward from the A6 review (19 Aug 2026).** All three pre-existing §5.9 tests passed against the broken dedup, because each was built on the one shape where the defect is invisible, and the Review 2 demo asserted the claim too. When `docs/capture_coverage.md` §1 and §2 are filled in from a running QGIS, remember that a green suite was not evidence here.

**Known limitation from A3, addressed in A5:** the post-execution hook fires *after* a run, so unless QGIS leaves a start time in the namespace every job looks instantaneous. A5's pre-execution hook fixes it — but on QGIS 4 neither hook runs at all (above), so this stays unresolved rather than fixed. **Do not report `post_hook` durations in RQ2**; on the only QGIS measured so far there are no `post_hook` rows to report.

**Environment fingerprint changed in A6 (19 Aug 2026).** `environment.plugin_versions()` moved from `qgis.utils.active_plugins` (loaded) to `available_plugins` (installed), closing the `docs/CONTRACT_event.md` decision of 18 Aug. Agent rows written before and after describe the same machine but are not the same row — do not compare an RQ2 agent-row count naively across that date.

Never describe unwritten code as existing; update this section when that changes.

## 4. Target repository layout

```
geoprovenance/              # the QGIS plugin package
  __init__.py               # classFactory()
  plugin.py                 # load/unload, menu, toolbar, dock
  metadata.txt              # qgisMinimumVersion=3.34
  icon.png                  # generated by tools/make_icon.py
  lifecycle.py              # CleanupStack — the §5.4 teardown mechanism (no QGIS)
  paths.py                  # database location, the one §4.8 config value
  log.py                    # QGIS message log, with a stdlib fallback
  ui/
    dock.py                 # GeoProvenanceDockWidget — the shell Person C fills
  capture/
    engine.py               # ProvenanceCaptureEngine singleton
    hooks.py                # post-execution hook installer + processing.run wrapper
    history_observer.py     # entryAdded signal + QTimer polling fallback
    normalizer.py           # dedup, parameter flattening, CRS, path resolution
    environment.py          # QGIS/OS/Python/plugin versions
  storage/
    schema.sql              # §7.1 DDL + indices
    migrations.py           # PRAGMA user_version
    store.py                # ProvenanceStore — the API B and C call
    workflows.py            # session → workflow grouping

docs/
  CONTRACT_schema.md        # frozen, tagged contract-v1
  CONTRACT_event.md         # frozen, tagged contract-v1
  capture_coverage.md       # empirical: what fires the hook, what doesn't
  demos/
    TEMPLATE.md             # the plain-English demo template
    REVIEW-1.md  REVIEW-2.md  FINAL.md

demos/
  _presenter.py             # shared plain-English output helpers
  review1.py  review2.py  final.py

schemas/event.schema.json   # JSON Schema for the event dict

tools/
  deploy.py                 # symlink into the geoprov-dev QGIS profile
  make_icon.py              # regenerates icon.png

tests/
  fixtures/
    build_fixtures.py       # regenerates everything below
    mock_provenance.db      # shared with B and C
    mock_events.json        # shared with B
    mock_ids.json           # readable name -> UUID
    data/                   # small real .shp / .gpkg files
  storage/                  # MUST run with zero QGIS imports
  plugin/                   # MUST run with zero QGIS imports
  capture/                  # runs under pytest-qgis

qgis_demo/                  # the visual demonstration — NOT plugin code (§1.1)
  scenario.py               # the workflow, defined once; read by all three drivers
  make_inputs.py            # writes the three starting datasets      (no QGIS)
  run_in_qgis.py            # runs the four steps inside QGIS         (needs QGIS)
  replay.py                 # records the same four steps offline     (no QGIS)
  export_layers.py          # the record -> map layers                (no QGIS)
  build_project.py          # map layers -> a styled .qgz + a page    (needs QGIS)
  verify_project.py         # reopens the project and checks it       (needs QGIS)
  geopkg.py  shapefile.py   # dependency-free format writers
  footprints.py             # where a file sits on Earth, from its header
  data/                     # inputs committed; data/derived/ is generated
  project/                  # generated: GeoProvenance.qgz, overview.png

experiments/                # RQ1 / RQ2 scripts, raw results, charts
```

## 5. Environment

| | |
|---|---|
| Python | **Must match the interpreter bundled with QGIS 3.34 LTS** (check in the QGIS Python console: `import sys; sys.version`). 3.10 or 3.11. Not 3.12+. |
| QGIS | 3.34 LTS or newer, with a **separate dev profile**: `qgis --profile geoprov-dev` |
| Deps | `pytest`, `pytest-qgis`, `jsonschema` — nothing else |

**No heavyweight third-party libraries.** No `prov`, `rdflib`, `pydot`, `networkx`, `pandas`, `numpy` in plugin code. Standard library only (`sqlite3`, `hashlib`, `json`, `uuid`, `datetime`, `platform`) plus PyQGIS/PyQt5. Adding a dependency requires an explicit decision from the user — see `RULES.md` §2.

Common commands:

```bash
make help            # list every command
make venv            # create .venv, install dev deps, print the Python version to check
make test-storage    # storage suite — no QGIS needed, runs anywhere
make test-capture    # capture suite — needs QGIS + pytest-qgis
make schema-check    # apply schema.sql to a throwaway DB and report tables/indices
make fixtures        # regenerate the fixtures B and C consume
make demo1           # run the Review 1 demo
```

**Do not run `pytest tests/storage` directly.** `pytest-qgis` auto-loads and imports `qgis` before any conftest runs, so a bare invocation crashes on a machine without QGIS and hides §4.1 violations on a machine with it. `make test-storage` passes `-p no:pytest_qgis`. See `RULES.md` §6.1.1.

## 6. The three frozen contracts

Person A **authors** two of the three contracts. Person B and Person C cannot start until they are published, and their code breaks if they change silently.

1. **SQLite schema** — `docs/CONTRACT_schema.md` + `storage/schema.sql`
2. **Event dict** — `docs/CONTRACT_event.md` + `schemas/event.schema.json`
3. **PROV-JSON shape** — authored by B, from research doc §7.3

Once tagged `contract-v1`, a change to 1 or 2 is a **breaking change to two other people's work**. The change procedure is mandatory and is in `RULES.md` §3.

## 7. Demo obligation — the thing that must never be skipped

There are **three demo gates**, matching the graded reviews:

| Gate | Week | Ships after | The one-line claim |
|---|---|---|---|
| **Review 1** | 4 | A3 | "QGIS ran a job and we wrote it down automatically." |
| **Review 2** | 8 | A6 | "A whole 4-step workflow was captured, in the right order, with nothing missing." |
| **Final** | 12 | Phase 2 + 3 | "It captures live, feeds the graph and the score, and here is how much it costs." |

Every demo must be understandable to **a reviewer who does not know git and does not know QGIS.**

That means, non-negotiably:

- **One command.** `python demos/reviewN.py`. Not a sequence, not a notebook, not "first activate the venv then...". The doc gives one copy-pasteable block.
- **It runs without QGIS.** The scripted demo simulates the QGIS side using recorded events, so it works on any machine, offline, in a review room. A *live* QGIS run is a separate optional second act, never the only act.
- **Before vs. After.** Every demo opens by stating what was not possible before this phase and what is possible now.
- **No jargon.** Use the glossary in §8. The words *entity, activity, agent, DAG, hash, commit, schema, PROV-O, transaction, WAL* do not appear in demo output or demo docs without an immediate plain-English replacement.
- **No git, no SQL, no QGIS clicks required from the reviewer.**
- **Self-resetting.** The script deletes and rebuilds its own database every run, so it cannot pass because of leftover state.

Full demo specification, output format, and the banned-words list: **`RULES.md` §7**. Template: `docs/demos/TEMPLATE.md`.

## 8. Plain-English glossary — use these words in anything a reviewer reads

| Internal term | Say this instead |
|---|---|
| entity | a file we're keeping track of |
| activity | a job QGIS ran |
| agent | the computer and software setup it ran on |
| relation / `used` / `wasGeneratedBy` | "this job read that file" / "this job created that file" |
| `wasDerivedFrom` | "this file came from that file" |
| DAG | a family tree of files |
| SHA-256 hash / fingerprint | a fingerprint — a short code that changes if the file changes even slightly |
| provenance | the record of where a file came from |
| schema | the shape of the record we keep |
| commit / branch / tag | (don't mention — reviewers don't need git) |
| transaction / WAL | (don't mention — say "saved all at once, or not at all") |
| capture completeness | "out of 10 jobs, how many did we notice?" |
| runtime overhead | "how much slower QGIS got" |

## 9. How to work in this repo

1. **Check `RULES.md` before writing code.** It is numbered; cite the rule number when a decision is driven by it.
2. **Storage before capture.** `storage/store.py` must be complete and tested with zero QGIS imports before capture code is written — that is what unblocks B and C (`RULES.md` §4.1).
3. **Tests are not optional.** Phase 1 exit needs 25+ tests. Write the test with the code, not after (`RULES.md` §6).
4. **Never break the user's QGIS run.** Any code that executes inside a Processing hook is wrapped in a broad `try/except` that logs and returns. This outranks correctness of capture (`RULES.md` §5.1).
5. **If a change affects the demo's claim, update the demo in the same change.** A demo script that no longer matches the code is a failed gate (`RULES.md` §7.9).
6. **Stay in scope.** The out-of-scope list in `RULES.md` §9 is not a suggestion; the 12-week timeline is the reason it exists.
7. **Don't claim something works without running it.** Run the test, paste the output. If something is untested, say it is untested.

## 10. Where the research questions land

Person A owns **RQ1** and **RQ2** — the engine is the thing being measured.

- **RQ1 — capture completeness.** 3 workflows × 4 invocation paths (Toolbox, Python console, Modeler, batch) × 3 repeats. Report per-path, plus the hook-vs-history-channel split. Target >95%.
- **RQ2 — runtime overhead.** 10 runs with, 10 without. Mean, std, 95% CI, broken down by stage. Target <5%.
- **RQ2 — storage overhead.** Bytes per operation across 10 MB / 100 MB / 1 GB datasets. Target <100 KB per workflow.

Evidence collection starts in Week 4, not Week 9 (`RULES.md` §8).
