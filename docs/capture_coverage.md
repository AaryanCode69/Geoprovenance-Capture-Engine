# Capture coverage — what fires the hook, and what doesn't

> **This table is RQ1's evidence and the paper's limitations section.**
> Start filling it in **Week 4**, not Week 9 (`RULES.md` §5.11, §8.2).
> Every row is measured on this machine, not inferred from documentation (`RULES.md` §11.4).

| | |
|---|---|
| **Owner** | Person A |
| **QGIS version tested** | **4.2.1-Belém do Pará** (Flathub `org.qgis.qgis//stable`) |
| **Python version** | **3.13.14** (QGIS's own; the development `.venv` is 3.10.12 — see the §2.1 note below) |
| **Qt version** | **6.10.3** — PyQt6, not PyQt5 |
| **OS** | **Linux-6.18.42-1-cachyos-lts-x86_64-with-glibc2.42** |
| **Measured by** | `make qgis-demo-run` → `qgis_demo/findings.txt` (RULES.md §8.7 — every number here traces back to that) |
| **Last updated** | 24 Aug 2026 |

> ### Read this before quoting any number below
>
> **These are QGIS 4 measurements. The project targets QGIS 3.34 LTS, and nothing here has
> been verified against 3.x at all.** The intended 3.28.9 Flathub build could not be
> installed: it depends on the end-of-life runtime `org.kde.Platform//5.15-21.08`, and one
> object in that runtime returns HTTP 503 past 1 MiB from every Flathub CDN edge. QGIS 4.2.1
> was the only obtainable build. `geoprovenance/metadata.txt` was lowered to
> `qgisMinimumVersion=3.28` for the same exercise and carries the same caveat.
>
> The single most important consequence is in §1: **the post-execution hook mechanism does
> not exist in QGIS 4** (see §4, 24 Aug). Whether it works on 3.34 is untested and, from this
> evidence, unknowable. Do not present a 3.34 claim on the strength of this table.
>
> **RULES.md §2.1 is not satisfied.** The development interpreter (3.10.12) is not the one
> QGIS runs (3.13.14). Recorded, not papered over (§2.6, §11.4).

---

## 1. Invocation paths — does the post-execution hook fire?

The central empirical question of A3. The hook is run by `Processing.runAlgorithm`; the Toolbox dialog, batch mode, and the Graphical Modeler may take **different code paths**, and this is not reliably documented.

> **Headline, 24 Aug 2026: on QGIS 4.2.1 the post-execution hook never fires, on any path,
> because QGIS 4 no longer runs it at all.** `POST_EXECUTION_SCRIPT` and
> `PRE_EXECUTION_SCRIPT` still exist as *settings* — they appear in Processing options and
> `hasattr` finds them — but the entire QGIS 4.2.1 installation contains exactly one file
> that mentions either name, and that file is the settings definition itself. Nothing reads
> them back. `Processing.runAlgorithm` has no hook call in it. See §4, 24 Aug, for the
> evidence.
>
> **The capture rate was 4/4 = 100% anyway, and that is the finding worth reporting.** A5's
> decision to install three channels rather than trust one is what carried it: the
> `processing.run` wrapper caught every job the dead hook missed. A single-channel design
> built on the research doc's §5.2 assumption would have captured nothing on this QGIS.

| Invocation path | Hook fires? | History signal fires? | Captured? | Notes |
|---|---|---|---|---|
| `processing.run()` from a script | **no** — the mechanism is gone | **no** | **yes**, 4/4, all via `run_wrapper` | Measured. The history registry attached without error but received nothing: `processing.run()` from a script does not write a Processing history entry, and the polling timer needs an event loop this run did not have. |
| Processing Toolbox dialog | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | Needs the desktop application with the plugin ticked. The hook column is already answered by the mechanism being absent; only the history column is open. |
| Graphical Modeler (whole model) | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | Still open: does the model report once, or once per step? |
| Graphical Modeler (per step) | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | |
| Batch mode | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | |
| Algorithm fails mid-run | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | Must record `status='failed'` (§4.10) |
| User cancels | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | Must record `status='cancelled'` |
| GDAL/OGR algorithm via Processing | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | |
| GRASS algorithm via Processing | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | |
| SAGA algorithm via Processing | **no** (mechanism absent) | `UNVERIFIED:` | `UNVERIFIED:` | |

**What is still open, and why.** Only the first row is measured. The rest need the desktop
application driven by hand, with the plugin loaded from the `geoprov-dev` profile — the
Toolbox dialog, the Modeler and batch mode are separate code paths inside QGIS and a script
cannot stand in for them (`RULES.md` §5.11). The plugin is deployed and ready
(`make deploy`, then `make qgis`); what remains is the clicking.

**How to fill a row**

1. `make deploy && qgis --profile geoprov-dev`, enable GeoProvenance.
2. Open **View → Panels → Log Messages → GeoProvenance**.
3. Run the operation.
4. Read the log. The first hook firing of each session logs its whole namespace:
   `post-execution hook namespace: [...]` — **copy that list into §4 below.** It answers,
   from the running QGIS rather than from documentation, what the hook actually receives.
5. **Plugins → GeoProvenance → Provenance database…** shows the running count, or query
   the database directly.
6. Record what actually happened, including partial captures.

**Three channels are installed**, so a row can be caught by any of them:

| Channel | `capture_channel` value | Installed by | Catches |
|---|---|---|---|
| Processing post-execution hook | `post_hook` | `capture/hooks.py` | whatever QGIS routes through `Processing.runAlgorithm` |
| `processing.run` monkeypatch | `run_wrapper` | `capture/hooks.py` | scripted calls, whether or not the hook fires |
| History registry signal + polling | `history_signal` | `capture/history_observer.py` (A5) | anything QGIS writes to its Processing history, including runs the hook missed |

A job seen by more than one is stored once, with `corroborations` incremented — that
column *is* the per-channel evidence, so read it rather than counting log lines.

> **The history channel records less per job, by design.** It has no
> `QgsProcessingAlgorithm` in hand, so there is no parameter type map and no way to tell
> a layer-valued parameter from a scalar one (§3.3). Everything stays in `parameters`
> and **nothing is lifted into `inputs`/`outputs`** — a job caught *only* by this channel
> has no files attached to it. It answers "did this run happen?", not "what did it
> touch". A job the hook also caught is unaffected: the hook wins the §5.9 race and its
> richer record is the one that is stored.

---

## 2. Per-channel split

The number that makes RQ1 interesting rather than a single aggregate (`RULES.md` §5.9, §8.3).

Generate this table with `ProvenanceStore.channel_statistics()` — do not count log lines,
and do not retype the numbers (§8.7: every reported number traces back to something
runnable in this repository).

Measured 24 Aug 2026, QGIS 4.2.1, four `processing.run()` executions with all three channels
installed. Generated by `store.channel_statistics()`, not retyped:

    {'run_wrapper': {'first': 4, 'corroborations': 0}}

| Channel | Executions caught first | Corroborations | Caught *only* by this channel |
|---|---|---|---|
| Post-execution hook | **0** | **0** | **0** — the mechanism does not exist on QGIS 4 |
| `processing.run` wrapper | **4** | **0** | **4** (all of them) |
| History registry signal | **0** | **0** | **0** — installed cleanly, received nothing on this path |

Two things this does *not* say. It is one invocation path out of ten, so it is not an RQ1
result yet — it is the first row of one. And a corroboration count of zero here is not the
§5.9 defect returning: with only one channel able to see a script-driven run there is
nothing to corroborate *with*. The dedup path is exercised separately and does fire — see
`make qgis-demo-record`, where a deliberate second sighting raises the count to 1 without
creating a second job.

Target claim: *"the hook caught N%, the history channel caught the remaining M%."*

> **`channel_statistics()` does not tell you which channel did the corroborating** — the
> schema counts confirmations per activity, not per confirming channel. The "caught
> *only* by this channel" column therefore has to come from the experiment design (run
> a workflow with one channel disabled), not from the database. Noted here so the gap is
> not discovered in Week 11.

---

## 3. Known-uncapturable operations

Out of scope by design (research doc §5.2, §13.13; `RULES.md` §9.1). Listing them is a research asset, not an admission — each has a documented reason that becomes a limitations paragraph.

| Operation | Why not | Disposition |
|---|---|---|
| Manual geometry edits | No processing event is fired | Out of scope — GeoLineage's territory |
| Plugin GUI operations (e.g. SCP dialogs) | Plugins don't always call `processing.run()` | Out of scope |
| Direct PyQGIS API calls bypassing `processing.run()` | No standardised interception point | Documented limitation |
| External tool execution (standalone GDAL CLI) | Happens outside the QGIS process | Out of scope |
| Layer styling changes | Different API surface entirely | Out of scope |

---

## 4. QGIS API quirks encountered

Log these as they are found — this is the "things nobody will rediscover in six weeks" list (`RULES.md` §11.3).

| Date | API / behaviour | What happened | Workaround |
|---|---|---|---|
| — | **`ProcessingConfig.POST_EXECUTION_SCRIPT`** | `UNVERIFIED:` the constant name and whether `setSettingValue` persists it are informed guesses (`capture/hooks.py`). | Check on first load; the log says whether the hook installed. |
| — | **Hook script namespace** | `UNVERIFIED:` research doc §5.2 shows `alg` / `parameters` / `context` / `results`. Not confirmed against a running QGIS. | `handle_post_execution` takes the whole namespace and logs the names it received, so the first run answers this. **Paste the logged list here.** |
| — | **Start time in the hook** | The post-execution hook fires *after* the run, so unless QGIS leaves a start time in the namespace every job looks instantaneous. | **A5 addressed this**: a pre-execution hook now stamps the start time, and `handle_post_execution` consumes it. `UNVERIFIED:` — whether `PRE_EXECUTION_SCRIPT` exists and fires on the same paths as the post hook is the first thing to check. **Until a row below confirms it, still do not report `post_hook` durations in RQ2.** |
| — | **`ProcessingConfig.PRE_EXECUTION_SCRIPT`** | `UNVERIFIED:` same informed guess as the post-execution constant. | Same mitigation: `getattr(ProcessingConfig, name, name)` falls back to the literal string, and the log says whether the hook installed. |
| — | **Pre/post hook correlation** | The two hooks are separate script executions with separate namespaces, so the start time is handed over through module state in `hooks.py`. If the pre hook fires and the post hook does not, that start time is orphaned. | One slot, consumed on read, discarded if older than `MAX_PENDING_START_AGE_S` or in the future — so a leak costs one lost duration rather than inventing a long one for the *next* job. `UNVERIFIED:` whether batch mode interleaves pre/post across concurrent runs; if it does, durations from batch mode are not trustworthy and must be excluded from RQ2. |
| — | `QgsHistoryProviderRegistry.entryAdded` | Signature has changed across releases; known crash risk (research doc §12 risk 7) | **A5**: `_on_entry_added` takes `*args` and identifies each argument by shape, never by position, and logs the arity and types it actually received on first fire — **paste that log line here.** The `QTimer` + `queryEntries()` polling fallback is installed regardless, so a signature change degrades this channel to "late", not "dead" (`RULES.md` §5.10). |
| — | **Processing history entry keys** | `UNVERIFIED:` which keys a history entry uses for the algorithm id and parameters. `parse_history_entry` tries `algorithm_id` / `algorithmId` / `alg_id` / `algorithm`. | Falls back to reading the algorithm id out of the recorded `python_command`. Record the real key names here on first fire. |
| 2026-08-18 | `pytest-qgis` 4.1.1 | Registers a `pytest11` entrypoint that runs `from qgis.core import ...` at plugin-load time, before any conftest. `pytest tests/storage` crashes at startup on a machine without QGIS, even though that suite imports no QGIS — which would have silently voided the §4.1 guarantee. | `make test-storage` passes `-p no:pytest_qgis` (`RULES.md` §6.1.1). Verified: 6/6 storage tests pass with QGIS absent. |
| 2026-08-19 | **`qgis.utils.available_plugins` vs `active_plugins`** | A6 widened the environment note from the *loaded* plugin set to the *installed* one, closing the `docs/CONTRACT_event.md` decision of 18 Aug. `UNVERIFIED:` the attribute name comes from the API docs and has never been read from a running build. **Consequence to remember: every environment fingerprint changed on this date.** Agent rows written before and after describe the same machine but are not the same row — an RQ2 agent-row count must not be compared naively across it. | Falls back to `active_plugins` when `available_plugins` is absent or empty: a narrower answer beats no answer, and the per-plugin `try/except` means one bad `metadata.txt` costs that plugin, not the whole note. Paste the real `plugin_versions` block from the first captured job here. |
| 2026-08-19 | **§5.9 cross-channel dedup never fired** | The key was hashed from `event["parameters"]` — the dict AFTER layer-valued parameters have been lifted into `inputs`/`outputs` (§3.3). The hook and the `processing.run` wrapper hold a `QgsProcessingAlgorithm` and pass `parameter_definitions`, so that lifting happens; the history channel has no algorithm, passes none, and keeps those parameters as scalars. For `native:buffer` the hook hashed `{"DISTANCE": 500}` and the history channel hashed `{"INPUT": …, "DISTANCE": 500, "OUTPUT": …}`. Different digests, for **every algorithm with a layer parameter** — i.e. all of them. Compounding it, the 100 ms floor-bucket gave two observations 2 ms apart different keys whenever a grid line fell between them, and the hook stamps *before* the run while the history entry is written *after* it. Net effect: one execution written as two rows, `corroborations` permanently 0, and the per-channel split in §2 above unmeasurable. | The key is now computed over the **raw, pre-split** parameter dict, which is the one form all three channels genuinely hold, and duplicates are matched against the recorded activity's own `[started_at, ended_at]` interval widened by `DEDUP_MARGIN_S` (2 s) rather than by bucket equality — so the tolerance does not have to be widened for slow algorithms. `activities.dedup_key` keeps its `algorithm\|digest\|bucket` shape, so the UNIQUE index stays a backstop and **no schema change was needed**. **Residual limitation, for the paper:** outputs cannot be part of the digest, because the history channel records what was *requested* (often literally `TEMPORARY_OUTPUT`) while the hook records what was *written*. Two runs of one algorithm over identical inputs and settings, differing only in destination and less than 2 s apart, would be recorded as one. Regression tests: `tests/capture/test_engine.py::test_the_hook_and_the_history_channel_agree_on_one_execution` and the five beside it. |
| 2026-08-19 | **Tests can agree with each other and still be wrong** | The three pre-existing §5.9 tests all passed against the broken code. Each drove the hook side *without* `parameter_definitions`, so both channels split identically, and each chose timestamps inside one bucket. `demos/review2.py` replayed the *same event dict* with only `source` changed, so the demo asserted the claim too. The defect was only visible where production differs from all three. | Test the channels the way they actually differ, not the way that is convenient to construct. The demo now builds the second sighting through `second_sighting_of()`, which reproduces the real divergence (no type map, no lifted files, a post-run timestamp). Worth remembering when §1 below is filled in from a running QGIS: a green suite was not evidence here. |
| 2026-08-24 | **`ProcessingConfig.POST_EXECUTION_SCRIPT` / `PRE_EXECUTION_SCRIPT`** — closes two `UNVERIFIED:` rows above | Both constants **exist** on QGIS 4.2.1 and both hold the literal strings `'POST_EXECUTION_SCRIPT'` / `'PRE_EXECUTION_SCRIPT'`, so `capture/hooks.py`'s informed guess was right and `setSettingValue` accepts them. **But the setting is vestigial.** `grep -rl POST_EXECUTION_SCRIPT /app` over the entire QGIS 4.2.1 install returns exactly one file — `processing/core/ProcessingConfig.py`, the definition. `Processing.runAlgorithm` contains no hook invocation; `AlgorithmExecutor.py` mentions neither name; no library under `/app/lib` contains the string. QGIS 4 registers the setting, shows it in the options dialog, and never runs what you put in it. Both hook scripts were written to disk correctly and neither was ever executed. | None available — this is not a bug to work around, it is a removed feature. The `processing.run` wrapper and the history channel are what capture on QGIS 4, and they were enough (§1: 4/4). **`hooks.py` is not deleted**: the mechanism may still exist on the 3.34 LTS the project targets, which is exactly the thing that could not be tested here. |
| 2026-08-24 | **Hook script namespace** — the `UNVERIFIED:` row above stays open | Cannot be answered on QGIS 4. `handle_post_execution` logs the names it receives on first firing, but it never fires, so there is nothing to paste. The question is only answerable on a QGIS that still runs the hook. | Unchanged: the handler takes the whole namespace and reads by name with `.get()`, so it cannot break on an unexpected shape. |
| 2026-08-24 | **`QgsHistoryProviderRegistry` — where it lives** | `from qgis.core import QgsHistoryProviderRegistry` **fails** on QGIS 4.2.1; the class is in `qgis.gui`. `capture/history_observer.py` already reaches it the right way, through `QgsGui.historyProviderRegistry()`, so nothing needed changing — but anyone who "tidies" that import to `qgis.core` will break the channel. Confirmed present on the instance: `entryAdded`, `queryEntries`, `addEntry`. The observer and its polling timer both installed and both tore down cleanly. | None needed. Recorded so the working import is not refactored away. |
| 2026-08-24 | **`entryAdded` arity** — the `UNVERIFIED:` row above stays open | The signal exists but never fired on this path, so its real argument shape is still unmeasured. `_on_entry_added`'s `*args` shape-detection was therefore never exercised against the live signal. | Unchanged, and still the right design — it degrades rather than crashes if the signature has moved (`RULES.md` §5.10). |
| 2026-08-24 | **Processing history entry keys** — still open | Same reason: no history entry was produced by a script-driven run. Answerable only from the desktop application. | Unchanged. |
| 2026-08-24 | **`qgis.utils.available_plugins`** — closes the 19 Aug `UNVERIFIED:` row | The attribute **exists** on QGIS 4.2.1, so A6's assumption holds and the `active_plugins` fallback is not needed. It reported **0 installed** in this run, which is correct and not a failure: the run was headless, outside the desktop application, with no plugin directory loaded. A count from the desktop application is still needed before an RQ2 agent-row claim rests on it. | None needed. |
| 2026-08-24 | **PyQt6: `Qt.RightDockWidgetArea` does not exist** | QGIS 4 is Qt 6, where enum members are scoped under their type. `Qt.RightDockWidgetArea` and `Qt.AlignTop` — both used by `ui/dock.py` — raise `AttributeError`, so **the plugin would not have loaded at all**. Measured directly: `hasattr(Qt, 'RightDockWidgetArea')` is `False`, `hasattr(Qt.DockWidgetArea, 'RightDockWidgetArea')` is `True`. `QAction` turned out to be re-exported from **both** `QtWidgets` and `QtGui` by QGIS's `qgis.PyQt` shim, so that import was safe either way — but it is the other well-known Qt 5→6 move and is now handled explicitly. | `ui/dock.py` gained `_qt_enum()`, which reads the scoped spelling first and falls back to the flat one; `plugin.py` imports `QAction` from `QtWidgets` and falls back to `QtGui`. Both are feature detection, not a version test, exactly as `RULES.md` §2.5 requires, and both work on PyQt5 and PyQt6. |
| 2026-08-24 | **A1 exit criterion, verified at last** | `tests/capture/test_plugin_lifecycle.py` — 11 tests, marked `qgis`, never once executed before today — **all pass inside QGIS 4.2.1**. That covers `classFactory`, `initGui` opening the database, the dock registering under the agreed object name, the dock starting hidden, Person C's `set_content` seam, `unload` draining every deferred cleanup, load→unload→load leaving no residue, `unload` being safe twice, and `initGui` not raising when the database cannot be opened (§5.4). | Run with `pytest tests -q -m qgis` inside QGIS's own interpreter. `pytest` and `pytest-qgis` are not in the Flatpak image; `python3 -m ensurepip --user` then `pip install --user pytest pytest-qgis` inside the sandbox installs them to `/var/data/python`. |
| 2026-08-24 | **The full suite must not be run inside QGIS** | Running `pytest tests` (no marker filter) inside QGIS fails 7 tests. None is a defect. They assert the *degraded, no-QGIS* behaviour on purpose — `test_the_default_needs_qgis_and_says_so_clearly` expects `QgisUnavailableError`, `test_logging_outside_qgis_reaches_stdlib` expects the stdlib fallback rather than `QgsMessageLog`, `test_the_probe_reports_measured_values_only` expects unknowns — and all of them pass, correctly, when QGIS is absent. The icon-byte test differs on zlib version between Python 3.10 and 3.13. | Use the two Makefile targets, which is what they are for: `make test` (everything except `-m qgis`, run outside QGIS) and `make test-qgis` (only `-m qgis`, run inside). A bare `pytest tests` inside QGIS is not a supported mode. Worth marking these `requires_no_qgis` if it keeps catching people. |
| 2026-08-24 | **Fixture datasets open in QGIS** — closes the `tests/fixtures/README.md` caveat | `tests/fixtures/data/sample_points.shp` opens: valid, 8 features, `EPSG:4326`. `sample_areas.gpkg` opens: valid, 4 features, `EPSG:4326`. Both had been written by hand against the specifications and never opened by QGIS or GDAL until today. The three `qgis_demo/` datasets, written the same way, also open — including a polyline shapefile, which QGIS reads as MultiLineString as expected. | None needed. The hand-rolled writers in `tests/fixtures/_minifiles.py` and `qgis_demo/` produce files QGIS accepts. |
| — | | | |
