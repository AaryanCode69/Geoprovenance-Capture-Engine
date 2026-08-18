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

**Built and passing — 193 tests, `make test`, no QGIS required:**

- `storage/schema.sql` — 8 tables, 9 indices, `user_version = 1`. Draft, not yet `contract-v1`.
- `storage/migrations.py` — version get/set, forward migrations, refuses a database newer than the code.
- `storage/store.py` — **A2 complete.** `ProvenanceStore` with the full §4.5 method surface, `transaction()` with savepoint nesting, per-thread connections + write lock, WAL + foreign keys.
- `tests/fixtures/` — **A0.3 complete.** `mock_provenance.db` (3 workflows, 16 jobs, 23 datasets, 70 relations), `mock_events.json`, `mock_ids.json`, real Shapefile + GeoPackage in `data/`, all regenerable and byte-deterministic via `make fixtures`. **B and C are unblocked** — see `tests/fixtures/README.md`.
- `plugin.py`, `ui/dock.py`, `lifecycle.py`, `paths.py`, `log.py`, `icon.png` — **A1**, written, not yet run in QGIS (see below).
- `capture/normalizer.py` + `capture/engine.py` — **A3 core, complete and tested.** Both import zero QGIS (they duck-type), so the whole write path is verifiable here. 70 tests.
- `capture/hooks.py` — **A3, QGIS-only, UNVERIFIED.** Post-execution hook installer + `processing.run` monkeypatch.
- `capture/environment.py` — agent probe, degrades outside QGIS.
- `demos/review1.py` + `docs/demos/REVIEW-1.md` — **the Review 1 gate**, passing. Drives the real `handle_post_execution` path, no QGIS needed.
- `tools/deploy.py`, `tools/make_icon.py`, `make deploy` / `make qgis`.
- `schemas/event.schema.json` — draft; fixture events and built events both validate.

**Stubs only** (docstring + rules): `capture/history_observer.py` (A5), `storage/workflows.py` (A6), `demos/review2.py`, `demos/final.py`.

**Not started:** A4 (normalizer hardening), A5, A6, Phase 2, Phase 3.

### What is UNVERIFIED and why

Nothing that requires a QGIS process has ever been executed — QGIS is not installed on this machine, so `pytest-qgis` cannot even import. Specifically:

| Unverified | Where | First check |
|---|---|---|
| Plugin loads/unloads cleanly in QGIS | `tests/capture/test_plugin_lifecycle.py` | `make test-qgis` |
| `ProcessingConfig.POST_EXECUTION_SCRIPT` constant + persistence | `capture/hooks.py` | the log says whether the hook installed |
| What variables QGIS puts in the hook namespace | `capture/hooks.py` | `handle_post_execution` logs the names it received — paste into `docs/capture_coverage.md` §4 |
| Which invocation paths fire the hook (§5.11 — this is RQ1 evidence) | — | the coverage table |
| Fixture `.shp` / `.gpkg` open in QGIS | `tests/fixtures/data/` | drag onto the canvas |

The design compensates rather than hopes: `normalizer.py` and `engine.py` import no QGIS and duck-type instead, so the risky logic is tested and only the thin QGIS adapter is unproven.

**Known limitation carried into A5:** the post-execution hook fires *after* a run, so unless QGIS leaves a start time in the namespace every job looks instantaneous. A5's pre-execution hook fixes it. Until then, **do not report `post_hook` durations in RQ2** — noted in `docs/capture_coverage.md` §4.

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
