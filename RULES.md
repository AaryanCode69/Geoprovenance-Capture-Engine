# RULES.md — GeoProvenance, Person A

Binding rules for the Capture Engine & Storage component.

**How to use this file.** Every rule is numbered. When a decision is driven by a rule, cite it (`per §5.1`). When a rule blocks something the user asked for, say which rule and why, then propose the nearest thing the rule allows. Rules marked **[HARD]** are never broken without the user explicitly overriding them in writing; rules marked **[DEFAULT]** are the right answer unless there's a stated reason.

Source of truth for *what* to build: `PERSON_A.md`. Source of truth for *why*: `geoprovenance_research.md`. This file governs *how*.

---

## §1 — Ownership and boundaries

**§1.1 [HARD]** Person A builds the write path only: plugin skeleton, capture, normalization, environment probe, SQLite schema, migrations, CRUD, session/workflow grouping.

**§1.2 [HARD]** Do not implement, prototype, or "temporarily stub in" any of the following. They belong to Person B or Person C:

| Belongs to B | Belongs to C |
|---|---|
| SHA-256 computation and tiered fingerprint strategy | DAG layout and `QGraphicsScene` rendering |
| Entity / Activity / Agent PROV class model | Node/edge status colour-coding |
| `wasDerivedFrom` inference from path overlap | The 5-component weighted audit scorer |
| PROV-JSON / JSON-LD export | Audit report generation |

**§1.3** Person A *does* own the `fingerprints` and `relations` **tables, their DDL, their indices, and their CRUD methods**. B computes a hash and calls `store.add_fingerprint(...)`. B constructs a relation and calls `store.add_relation(...)`. **B and C never execute SQL.** If B or C needs a query Person A hasn't written, Person A writes the method.

**§1.4** When a task cannot be completed without B's or C's component, the correct action is: implement the Person A half, define the seam as a function signature with a docstring stating what B or C will supply, note the dependency plainly, and stop. Do not fill the gap with a placeholder implementation that could be mistaken for finished work.

**§1.5** Interfaces exposed to B and C are public API. Renaming a `ProvenanceStore` method, changing its argument order, or changing its return type is a **breaking change** and follows §3.4.

**§1.6** Person A is the least blocked and the most blocking of the three. Where sequencing is ambiguous, prioritise whatever unblocks B and C soonest — that is contracts, then fixtures, then `store.py`, in that order.

---

## §2 — Environment and dependencies

**§2.1 [HARD]** The development interpreter must be the same Python version bundled with the installed QGIS 3.34 LTS. Verify with `import sys; sys.version` in the QGIS Python console. Version mismatch between QGIS's Python and a system Python is the single most common source of "works on my machine" plugin bugs.

**§2.2 [HARD]** No heavyweight third-party dependencies in plugin code. Permitted: the Python standard library (`sqlite3`, `hashlib`, `json`, `uuid`, `datetime`, `platform`, `os`, `pathlib`, `threading`, `logging`) plus PyQGIS and PyQt5. Explicitly forbidden: `prov`, `rdflib`, `pydot`, `graphviz`, `networkx`, `pandas`, `numpy`, `requests`.
Rationale: research doc §6.2 and §6.5 — dependency-free installation is a stated design property of the plugin, not an accident.

**§2.3** Test-only and experiment-only dependencies are allowed and must stay out of `geoprovenance/`: `pytest`, `pytest-qgis`, `jsonschema`, and plotting libraries used solely in `experiments/`.

**§2.4 [HARD]** Never develop against the user's normal QGIS profile. Use `qgis --profile geoprov-dev`. A crash in capture code must never take out a working QGIS installation.

**§2.5** `metadata.txt` declares `qgisMinimumVersion=3.34`. Any API used that requires a newer QGIS must be feature-detected at runtime (`hasattr` / version check), not assumed.

**§2.6** Target platform assumptions are recorded, not guessed. `capture/environment.py` reports the real values; documentation never hardcodes "Ubuntu 22.04" as if it were verified.

---

## §3 — Contracts (the frozen interfaces)

**§3.1 [HARD]** Two contracts are authored by Person A and consumed by B and C:

| Contract | Files | Consumers |
|---|---|---|
| SQLite schema | `docs/CONTRACT_schema.md`, `storage/schema.sql` | B (writes through store), C (reads) |
| Event dict | `docs/CONTRACT_event.md`, `schemas/event.schema.json` | B (PROV mapper) |

Both are tagged `contract-v1` once agreed by all three people.

**§3.2 [HARD]** These six schema decisions are frozen before `contract-v1` and are recorded in `docs/CONTRACT_schema.md` with their rationale (full text in Appendix B):

1. **Entity identity** — one entity row per `(file_path, content version)`. A file rewritten with different content gets a **new** entity UUID.
2. **Relation role vocabulary** — lowercase `input` / `output` / `overlay` / `parameter`. The original QGIS parameter key (e.g. `OVERLAY`) is preserved in its own column.
3. **Indices** — mandatory on `relations(source_id)`, `relations(target_id)`, `relations(relation_type)`, `entities(file_path)`, `fingerprints(entity_id)`, `workflow_activities(workflow_id)`.
4. **Timestamps** — microsecond-precision UTC ISO 8601 everywhere: `datetime.now(timezone.utc).isoformat()`. Necessary but not sufficient for `fingerprints`, which since schema v2 declares `UNIQUE(entity_id, hash_strategy, computed_at)` — see Appendix B.4.
5. **Session grouping** — `activities.session_id TEXT`, a UUID minted once at plugin startup.
6. **Versioning** — `PRAGMA user_version` plus a working `migrations.py`. Currently **2**; see the `docs/CONTRACT_schema.md` changelog for what each bump changed.

**§3.3** The event dict shape is exactly as specified in `PERSON_A.md` §A0.2. Three rules that must be stated explicitly in `docs/CONTRACT_event.md`, because B will hit all three:
- Memory and temporary layers (`memory:`, `TEMPORARY_OUTPUT`, `/vsimem/`) have `path: None` but keep `layer_type`. **B must not attempt to hash them.**
- Parameter values that are themselves layers are lifted into `inputs`/`outputs`. Scalar parameters stay in `parameters`.
- `parameters` is always JSON-serializable. The normalizer flattens `QgsProcessingFeatureSourceDefinition`, `QgsCoordinateReferenceSystem`, `QgsProperty` and friends to strings before they reach it.

**§3.4 [HARD] — Contract change procedure.** After `contract-v1` is tagged, changing the schema or the event dict requires **all** of the following, in one change:
1. Bump `PRAGMA user_version` and add the forward migration in `storage/migrations.py`.
2. Update `docs/CONTRACT_schema.md` / `docs/CONTRACT_event.md`, including a dated changelog entry saying what changed and why.
3. Re-run `python tests/fixtures/build_fixtures.py` so the shared fixtures match.
4. Verify Person A's own tests still pass.
5. **Tell B and C, explicitly, what broke and what they must change.** Silent contract drift is the failure mode that costs the most time in Phase 2.

Never edit `storage/schema.sql` without steps 1–5. Never hand-edit `tests/fixtures/mock_provenance.db`.

**§3.5** Contract documents state decisions and rationale, not aspirations. If a decision is still open, mark it `OPEN:` with a named owner and a date it must close by.

---

## §4 — Storage layer

**§4.1 [HARD]** `storage/` imports **zero QGIS**. `import qgis`, `from qgis...`, and PyQt5 imports are forbidden anywhere under `storage/`. This is what lets B and C use the store immediately, lets the storage test suite run on any machine with plain `pytest`, and lets the review demos run without QGIS (§7.3).
A CI-style guard test asserts this by importing every module in `storage/` in a subprocess with `qgis` blocked from `sys.modules`.

**§4.2 [HARD]** Every connection sets `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL`. WAL is required because Person C's audit reads while the capture engine writes.

**§4.3 [HARD]** One algorithm execution is **one atomic transaction**, via `with store.transaction():`. A half-written execution — an `activities` row with no `relations` — silently corrupts C's graph traversal and is worse than capturing nothing.

**§4.4** `ProvenanceStore(db_path)` creates the database on first use, applies `schema.sql`, and sets `user_version`. It is safe to call on an existing database.

**§4.5** Minimum method surface, since B and C build against it: `add_entity`, `add_activity`, `add_agent`, `add_fingerprint`, `add_relation`, `get_or_create_agent`, `find_entity_by_path`, `get_activity`, `get_relations_for`, `list_workflows`, `get_workflow_graph`.

**§4.6 [HARD]** `get_or_create_agent` deduplicates on the full environment fingerprint (QGIS version + OS + Python version + plugin versions). Writing one agent row per execution inflates the RQ2 storage numbers with data that is Person A's own bug.

**§4.7** Thread safety must be decided, implemented, and documented — QGIS may run algorithms off the main thread. Either `check_same_thread=False` with a lock, or a connection per thread. Whichever is chosen, the reason goes in a module docstring. Not deciding is not an option.

**§4.8 [DEFAULT]** Database location defaults to the plugin profile directory (`QgsApplication.qgisSettingsDirPath()`), overridable per project. The override must be **one configuration value**, because Phase 2 requires pointing C's viewer and audit engine at the live database by changing exactly one thing.

**§4.9** All identifiers are UUID4 strings generated in Python, never SQLite `rowid` or autoincrement. Records must survive being exported, merged, and re-imported.

**§4.10** Failed and cancelled executions are stored with `status='failed'` / `status='cancelled'`. They are never dropped — C's audit needs them and RQ1 completeness counts them.

---

## §5 — Capture layer

**§5.1 [HARD] — The prime directive: never break the user's processing run.**
Every code path that executes inside a Processing hook, a signal handler, or the `processing.run()` wrapper is wrapped in a broad `try/except Exception` that logs to the QGIS message log and returns normally. A capture failure must be invisible to the person using QGIS.
This outranks capture correctness. Losing one record is acceptable; corrupting or aborting a user's real analysis is not.

**§5.2 [HARD]** The `processing.run` wrapper preserves the original signature and return value exactly, and **never swallows exceptions raised by the algorithm itself**. Exceptions from QGIS propagate untouched; only exceptions from capture code are caught.

**§5.3 [HARD]** Installing the post-execution hook means writing `ProcessingConfig`'s `POST_EXECUTION_SCRIPT` programmatically on plugin load. The user's previous value is read first, stored, and **restored on unload**. Clobbering a user's existing hook setting is a defect.

**§5.4 [HARD]** `plugin.unload()` disconnects every signal, stops every `QTimer`, un-patches every monkeypatch, closes the database connection, and restores §5.3's setting. Load → unload → load must leave no residue and produce no log errors.

**§5.5** Parameter serialization never raises. Unknown types fall back to `repr()`. Per `PERSON_A.md` §A4, awkward QGIS types are the single biggest source of crashes in this component.

**§5.6** Output path resolution handles all three shapes `results` can return: a filesystem path string, a layer id, or a `QgsVectorLayer`/`QgsRasterLayer` object. Anything unresolvable becomes `None`, not a guess.

**§5.7** CRS comes from the layer where available, falling back to `context.project().crs()`. Stored as `authid()` (`EPSG:4326`); WKT only when there is no authid.

**§5.8** Format detection uses the provider/driver name, **not** the file extension — a `.gpkg` can hold vector or raster.

**§5.9 [HARD] — Deduplication.** The same execution arrives on both the hook channel and the history channel. The dedup key is `(algorithm_id, hash of normalized parameters, started_at rounded to 100 ms)`. **First channel wins; the second increments a corroboration counter and does not insert.**
Keep that counter and report it. "The hook caught 98%, the history channel caught the remaining 2%" is a genuine RQ1 result, not bookkeeping.

**§5.10** The `QgsHistoryProviderRegistry.entryAdded` signal signature has changed across QGIS releases and is a known crash risk (research doc §12, risk 7). Verify the signature against the locally installed build before relying on it, and implement the `QTimer` + `queryEntries()` polling fallback.

**§5.11** Which invocation paths actually fire the hook is an **empirical question, answered by experiment, in Week 4** — not assumed from documentation. The findings table in `docs/capture_coverage.md` is started in Week 4 because it is the RQ1 evidence and doubles as the paper's limitations section.

**§5.12** Session→workflow grouping is temporal and session-based (shared `session_id` + shared dataset paths + `sequence_order` by `started_at`). Person B independently infers `wasDerivedFrom` from data flow. **These are different jobs — do not reimplement B's inference.**

---

## §6 — Testing

**§6.1 [HARD]** Suites are split by *what they need to run*, not by what they test. Anything that can be verified without QGIS must be, because that is the suite that actually gets run:
- `tests/storage/` — pure `sqlite3` + `pytest`, **no QGIS import at all**. The store, the migrations, the shared fixtures.
- `tests/plugin/` — **no QGIS import at all**. The plugin layer's testable-anywhere parts: teardown bookkeeping, path resolution, logging fallback, packaging metadata, and the name contracts with Person C.
- `tests/capture/` — runs under `pytest-qgis`. Only what genuinely needs a QGIS process.

When a rule can only be observed inside QGIS (§5.4's clean unload, say), extract the *mechanism* into a module that imports no QGIS and test that; leave only the observation for `tests/capture/`.

**§6.1.1** `pytest-qgis` registers a `pytest11` entrypoint that runs `from qgis.core import ...` at **plugin load time**, before any `conftest.py` executes. On a machine without QGIS this crashes pytest during startup, so a bare `pytest tests/storage` fails even though the storage suite itself imports zero QGIS — which would silently destroy the §4.1 guarantee. The storage suite is therefore always run as:

```bash
make test-storage        # → pytest tests/storage -q -p no:pytest_qgis
```

Never remove `-p no:pytest_qgis` from that command, and never verify §4.1 on a machine that happens to have QGIS installed — that is the configuration in which the violation is invisible.

**§6.2** Gate counts, from `PERSON_A.md`: **15+** storage tests by end of A2; **5+** capture tests by Review 1; **25+** total by Phase 1 exit.

**§6.3 [HARD]** Never report a test as passing without having run it and seen the output. If a suite was not run, say so.

**§6.4** Tests are written alongside the code, in the same change. A feature is not done when it works once by hand.

**§6.5** Required test coverage for the awkward cases, because these are where this component actually fails:
- Memory / temporary / `/vsimem/` layers produce `path: None` without raising.
- Un-serializable QGIS parameter types fall back to `repr()`.
- A raised exception inside the hook body does not propagate (§5.1).
- Dedup: the same execution on both channels produces one row and one corroboration.
- Failed and cancelled runs are persisted.
- A rolled-back transaction leaves no partial activity.
- `storage/` imports cleanly with `qgis` unavailable (§4.1).

**§6.6** Fixtures are generated by `tests/fixtures/build_fixtures.py` and are regenerable from scratch. The fixture set includes the §7.3 Buffer→Clip workflow, one 8-step chain, **and one branch** (two outputs from one activity) so C's layout code meets a non-linear graph early.

---

## §7 — Demos

Three demo gates, matching the graded reviews. Everything in this section exists to serve one requirement: **a reviewer who does not know git and does not know QGIS must understand what changed.**

### The gates

| Gate | Week | After | The single claim it proves |
|---|---|---|---|
| Review 1 | 4 | A3 | "QGIS ran a job and we wrote it down automatically." |
| Review 2 | 8 | A6 | "A whole 4-step workflow was captured, in the right order, with nothing missing." |
| Final | 12 | Phase 2 + 3 | "It captures live, feeds the graph and the score, and here is what it costs." |

Each gate ships exactly two artefacts: `docs/demos/REVIEW-N.md` (what to say) and `demos/reviewN.py` (what to run).

### Rules

**§7.1 [HARD] — One command.** The demo is `python demos/reviewN.py` and nothing else. No multi-step setup, no notebook, no "first activate the environment, then...". The document provides one copy-pasteable block that includes any activation step. If it takes more than one paste, it is not finished.

**§7.2 [HARD] — Self-resetting.** The script deletes and rebuilds its own database at the start of every run, into a scratch directory. A demo must never pass because of leftover state from yesterday, and must be re-runnable back-to-back with identical output.

**§7.3 [HARD] — Runs without QGIS.** The scripted demo drives the storage and normalization layers using recorded events from `tests/fixtures/`, so it runs offline, on any machine, in a review room, with no QGIS installed and no data downloaded.
A **live QGIS run is a separate, optional second act** — never the only act. If the live act fails on stage, the scripted act has already proved the claim.

**§7.4 [HARD] — Before and after.** Every demo opens by stating, in one sentence each, what was **not** possible before this phase and what **is** possible now. This is the entire point of the demo; a demo that only shows the current state does not show what changed.

**§7.5 [HARD] — Plain language only.** The banned words below never appear in demo output or demo documents unless immediately replaced:

| Never write | Write instead |
|---|---|
| entity | a file we're keeping track of |
| activity | a job QGIS ran |
| agent | the computer and software setup |
| `used` / `wasGeneratedBy` | "this job read that file" / "this job created that file" |
| `wasDerivedFrom` | "this file came from that file" |
| DAG / graph | a family tree of files |
| hash / SHA-256 / fingerprint | a fingerprint — a short code that changes if the file changes even slightly |
| provenance | the record of where a file came from |
| schema / DDL | the shape of the record we keep |
| commit / branch / tag / repo | — do not mention git at all |
| transaction / WAL / rollback | "saved all at once, or not at all" |
| PROV-O / W3C PROV | "an international standard for recording where data came from" |
| capture completeness | "out of 10 jobs, how many did we notice?" |
| runtime overhead | "how much slower QGIS got" |
| normalizer / serialization | "tidying the messy details into a clean record" |

**§7.6 [HARD] — Nothing required of the reviewer.** No git commands, no SQL, no QGIS clicks, no file paths to edit, no config to change. The reviewer watches. If they want to drive, they type the one command from §7.1.

**§7.7 — Output format.** Every demo script prints, in this order:

```
════════════════════════════════════════════════
  GeoProvenance — Review N Demo
  "<the one-line claim from the gate table>"
════════════════════════════════════════════════

BEFORE this phase:  <one plain sentence>
AFTER  this phase:  <one plain sentence>

[1/N] <what it's doing, in plain words>...   OK
[2/N] <...>                                  OK
[3/N] <...>                                  OK

  <the readback — real captured data, in plain English>
  Someone ran : Buffer
  On the file : roads.shp
  Produced    : buffered_roads.shp
  At          : 18 Aug 2026, 2:31 pm
  Settings    : distance = 500 m

WHAT WE STILL CAN'T DO:
  <one honest limitation>

✅ N of N checks passed.
```

Constraints: steps are numbered `[k/N]` and print `OK` or `FAIL`; dates are human-formatted (`18 Aug 2026, 2:31 pm`), never raw ISO; the script exits `0` on all-pass and `1` on any failure; total runtime under 60 seconds; the scripted portion of the presentation under 5 minutes.

**§7.8 — Demo document structure.** `docs/demos/REVIEW-N.md` follows `docs/demos/TEMPLATE.md`, with these sections in order:
1. **In one sentence** — what this review proves.
2. **Since last time** — plain-English list of what changed. (For Review 1: "since the project started".)
3. **Why it matters** — the real-world problem this step solves, in two or three sentences, no jargon.
4. **Run it** — the single copy-paste block.
5. **What you should see** — the expected output, pasted verbatim, so the reviewer can compare.
6. **Live version (optional)** — the QGIS click-by-click steps, if attempting the live act. Numbered, one action per line, written for someone who has never opened QGIS.
7. **What this still can't do** — honest limitations. Required, not optional (§7.10).
8. **Questions you might be asked** — three or four likely reviewer questions with short answers.

**§7.9 [HARD] — Demos stay true.** If a change alters what a demo claims, the demo script and document are updated **in the same change**. A demo that no longer matches the code is a failed gate, whatever the tests say.

**§7.10 [HARD] — Honest limitations.** Every demo states at least one thing the system still cannot do. This is not modesty: for RQ1 the limitations table *is* a research result, and a reviewer who finds an unmentioned gap trusts the mentioned results less.

**§7.11 — Rehearsal.** Before each gate, run the demo end to end on a **fresh copy of the project in a clean directory**, at least one day before the review. "It worked in my working folder" is the most common way a demo fails in the room.

**§7.12 — If the live act fails on stage.** Say plainly what didn't work, run the scripted demo, continue. Do not debug in front of the reviewers. The scripted demo exists precisely for this.

---

## §8 — Research and experiments

**§8.1** Person A owns **RQ1** (capture completeness) and **RQ2** (runtime and storage overhead).

**§8.2 [HARD]** Ground truth for RQ1 is enumerated **before** the workflows are run, by hand, and written down. Counting operations after the fact contaminates the measurement.

**§8.3** RQ1 protocol: Workflows A (3 ops), B (8 ops), C (15+ ops) × four invocation paths (Toolbox dialog, `processing.run()` from the Python console, Graphical Modeler, batch mode) × 3 repeats. Report **per-path** completeness, not just an aggregate — it is the stronger result and the honest way to present paths where the hook does not fire. Include the per-channel hook-vs-history split from §5.9. Target >95%.

**§8.4** RQ2 runtime protocol: 10 runs without the plugin, 10 with. Same machine, same data. The baseline has the plugin **fully disabled, not merely idle**. Report mean, standard deviation, 95% CI. Break the overhead down by stage — hook + normalize, database write, hashing. Target <5%.

**§8.5 [HARD]** Hashing is Person B's cost but falls inside Person A's measured window. It is attributed explicitly and separately. Reporting B's cost as Person A's overhead is a measurement error, and it makes the headline number look worse than it is.

**§8.6** RQ2 storage protocol: database size after each workflow, `bytes_per_operation = db_size / n_operations`, across 10 MB / 100 MB / 1 GB datasets. The claim worth making is that **storage is independent of data volume** — the varying dataset sizes exist to demonstrate exactly that. Target <100 KB per workflow.

**§8.7** Every reported number traces back to a script in `experiments/` and its raw output. No number appears in the paper or a demo that cannot be regenerated by running something in this repository.

**§8.8** Results are reported as measured. A target missed is a finding with an explanation, not a number to adjust.

**§8.9** Benchmark data is downloaded in **Week 3**, not Week 9 — the Sentinel-2 tile for Workflow B is slow to acquire and is a schedule risk.

---

## §9 — Scope guard

**§9.1 [HARD]** Out of scope for this project, per research doc §13.13. Do not build these, and do not accept a task that quietly requires them:

- Manual geometry edit tracking (GeoLineage's job)
- Non-Processing plugin GUI operation tracking
- Direct PyQGIS API calls that bypass `processing.run()`
- External tool execution outside the QGIS process
- Layer styling change tracking
- RDF / SPARQL / triple stores
- Web-based (D3.js, Cytoscape) visualization
- Cross-plugin provenance unification
- Real-time collaboration
- Cloud or remote data provenance

**§9.2** Workflow replay is a **stretch goal**, unassigned. It is not started until Person A's own track is complete through Phase 3.

**§9.3** Priorities when time runs short, in this order: **MUST** — automatic `processing.run()` capture, SQLite storage. **SHOULD** — plugin version tracking, multi-step chaining (session/order half). **STRETCH** — replay. A MUST-have at 80% beats a SHOULD-have at 100%.

**§9.4** The out-of-scope list is a research asset, not an admission. Each excluded item has a documented reason in the research doc, and those reasons become the paper's limitations section.

**§9.5** Do not add features that were not asked for. A 12-week timeline with three graded reviews and a paper has no slack for polish that no rubric rewards.

---

## §10 — Repository and version control

**§10.1** The project is versioned in git from Phase 0 onward. `contract-v1` is a git tag agreed by all three people.

**§10.2** Commits are atomic and describe *what changed and why*, not *what file was touched*. One logical change per commit.

**§10.3** Generated artefacts that are shared contracts — `tests/fixtures/mock_provenance.db`, `tests/fixtures/mock_events.json` — **are committed**, because B and C consume them directly. They are regenerated only via `build_fixtures.py` (§3.4), never hand-edited.

**§10.4** Not committed: the runtime provenance database, QGIS profile directories, `.venv/`, benchmark datasets (too large — `experiments/` documents how to fetch them), `__pycache__`.

**§10.5** Commit or push only when the user asks. Never force-push. Never rewrite shared history — B and C build against this repository.

**§10.6** Git is invisible at demo time (§7.6). Version control discipline serves the developers; it never appears in a reviewer's path.

---

## §11 — Documentation

**§11.1** These documents are deliverables in their own right and are kept current, not written at the end:

| Document | Purpose | Due |
|---|---|---|
| `docs/CONTRACT_schema.md` | Frozen schema + rationale for the six §3.2 decisions | Phase 0 |
| `docs/CONTRACT_event.md` | Frozen event dict + the three §3.3 gotchas | Phase 0 |
| `docs/capture_coverage.md` | Empirical table: what fires the hook per invocation path | Started Week 4, final Week 12 |
| `docs/demos/REVIEW-N.md` | Plain-English demo walkthroughs | Weeks 4, 8, 12 |
| README installation + dev setup | How B, C, and a marker install and run this | Week 3 |

**§11.2** `docs/capture_coverage.md` records what does **not** work as carefully as what does. It is simultaneously the RQ1 evidence and the paper's limitations section.

**§11.3** Code comments explain *why*, not *what*. The QGIS-specific workarounds — signal signature drift, hook invocation paths, parameter type quirks — are the ones that need a comment, because nobody will rediscover the reason six weeks later.

**§11.4** Never document behaviour that has not been verified on the actual machine. If something is expected but untested, mark it `UNVERIFIED:` with what would confirm it.

---

## Appendix A — Definition of done, by sub-phase

Demos are required only at the three gates (§7). The other rows still have to be *finishable*, and the checks below are what "finished" means.

| | Sub-phase | Done when | Gate |
|---|---|---|---|
| **A0.1** | Freeze schema | Six §3.2 decisions written up with rationale; `schema.sql` applies cleanly; `user_version=1` | |
| **A0.2** | Freeze event dict | `CONTRACT_event.md` + `event.schema.json`; every fixture event validates against it | |
| **A0.3** | Shared fixtures | B and C can each run `pytest` against the fixtures with **zero QGIS running and zero Person A code beyond `store.py`** | |
| **A1** | Plugin skeleton | Loads and unloads cleanly in the dev profile, no QGIS log errors, `unload()` leaves no residue (§5.4); dock class name agreed with C | |
| **A2** | Storage layer | 15+ tests pass with no QGIS import (§4.1, §6.1); WAL + foreign keys on; transaction context manager works | |
| **A3** | Capture POC | One `native:buffer` in the Toolbox → 1 agent, 1 activity, 2 entities, `used` + `wasGeneratedBy` rows; 5+ capture tests | **★ Review 1** |
| **A4** | Normalizer hardened | Every §6.5 awkward case has a passing test; hook body cannot raise (§5.1) | |
| **A5** | Dual channel + dedup | Both channels connected; dedup key implemented; corroboration counter recorded; failed/cancelled persisted | |
| **A6** | Sessions + versions | 4-step workflow → correct `sequence_order`; manual "name this workflow" action; one agent row per distinct environment (§4.6) | **★ Review 2** |
| **P2** | Integration | Fresh QGIS, empty database, 4-step workflow → C's graph renders and the score appears, with no manual database fiddling | |
| **P3** | Experiments | RQ1 and RQ2 numbers regenerable from `experiments/`; methodology subsection drafted; charts produced | **★ Final** |

**Phase 1 exit criteria** (all four): 4-step workflow fully captured with correct ordering · zero user-visible impact when capture fails internally · 25+ tests · `docs/capture_coverage.md` populated with real measurements.

---

## Appendix B — The six frozen schema decisions, with rationale

Copy this reasoning into `docs/CONTRACT_schema.md`. Each decision exists because leaving it open breaks B's or C's code later.

**B.1 — Entity identity.** Research doc §7.1 puts no uniqueness rule on `entities.file_path`. If `roads.shp` is overwritten by a second run, is that the same file or a new one? **Decision: one entity row per `(file_path, content version)`** — a rewritten file with a different fingerprint gets a new entity UUID. Without this, B's derivation chains and C's history view are both wrong, because the graph cannot distinguish "the file before" from "the file after".

**B.2 — Relation role vocabulary.** The schema comment says `'input' | 'output' | 'parameter'`; the §7.3 worked example uses `"INPUT"` and `"OVERLAY"`. These disagree. **Decision: lowercase `input` / `output` / `overlay` / `parameter`**, with the original QGIS parameter key preserved in its own column. Two vocabularies for the same concept means C writes string-normalising code that should never have been needed.

**B.3 — Indices.** C's graph traversal does repeated reverse lookups on `relations`. Without indices on `source_id`, `target_id`, `relation_type`, `entities(file_path)`, `fingerprints(entity_id)`, and `workflow_activities(workflow_id)`, Workflow C (15+ operations) is slow — and Person A's own RQ2 numbers look worse than the design deserves.

**B.4 — Timestamp precision.** **Decision: microsecond-precision UTC ISO 8601 everywhere**, `datetime.now(timezone.utc).isoformat()`.

*Corrected 30 Aug 2026 — the original rationale here was wrong and is retracted.* It read: "`fingerprints` declares `UNIQUE(entity_id, computed_at)`. B hashes input and output within the same second, so second-resolution timestamps collide and the second insert fails." **That names a collision the constraint cannot produce** — an input and an output are different entities, so their rows differ on `entity_id` and never collide at any resolution.

The real problem was the opposite one. The key ignored *which measurement a row was*, so several complementary measurements of one file — a byte hash and the descriptions of its shape that make it interpretable — were rejected as duplicates of each other. Whether they landed depended on whether the clock happened to tick between two writes, which is a platform detail: 13 of 30 same-file writes were rejected on Windows, where `datetime.now()` advances roughly once per millisecond.

Schema v2 therefore declares `UNIQUE(entity_id, hash_strategy, computed_at)` — **one fingerprint per dataset, per method, per instant** — with `hash_strategy NOT NULL DEFAULT 'file'`, because SQLite counts every NULL in a `UNIQUE` as distinct and a nullable column in the key silently disables the duplicate check. Microsecond precision is still mandatory; it is just not sufficient on its own. Full rationale and the changelog entry are in `docs/CONTRACT_schema.md`.

**B.5 — Session grouping.** §7.1 has a `workflows` table but nothing linking an activity to the QGIS session that produced it. **Decision: add `activities.session_id TEXT`**, a UUID minted at plugin startup. This is what makes automatic workflow grouping possible without asking the user to declare workflow boundaries.

**B.6 — Migration path.** The schema *will* change in Phase 2 — that is when contract mismatches surface, and expecting otherwise is the mistake. **Decision: `PRAGMA user_version` plus a working `migrations.py` from day one**, so B's and C's fixture databases fail loudly with a version mismatch instead of breaking silently.
