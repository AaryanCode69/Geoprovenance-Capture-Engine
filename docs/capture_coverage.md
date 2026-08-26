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
| Processing Toolbox dialog | **no** (mechanism absent) | **yes** — first live firing | **yes**, 2/2 | Measured 26 Aug 2026 (Buffer, then Convex hull). **`run_wrapper` did not fire** — the Toolbox does not call `processing.run()` — so before the `toolbox` channel landed this path was carried entirely by `history_signal`, which meant **0 entities and 0 durations**: the record said two jobs happened and nothing about the data. See §4, 26 Aug. |
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
cannot stand in for them (`RULES.md` §5.11).

The plugin is deployed and ready — but only since **26 Aug 2026**. Until that date
`make deploy` linked into `QGIS3/profiles` while QGIS 4 reads `QGIS4/profiles`, so the
plugin had never once appeared in the Plugin Manager, and a second defect
(no `qgisMaximumVersion`) would have had QGIS reject it as incompatible even from the right
directory. Both are in §4 under 26 Aug. **Nothing below this line was blocked by capture
code; it was blocked by the plugin never loading.** `make deploy`, then `make qgis`, and
what remains is the clicking — the click-by-click procedure, and what to paste back for each
row, is `docs/RUNNING_IN_QGIS.md` §3.

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
| Processing Toolbox dialog | `toolbox` | `capture/hooks.py` (26 Aug 2026) | both Toolbox execution branches — the threaded `QgsProcessingAlgRunnerTask` and the synchronous `execute()`. Holds the algorithm, so unlike `history_signal` it lifts files and records a real duration |

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

### 26 Aug 2026 — the Toolbox, before the `toolbox` channel existed

Two executions driven from the Processing Toolbox by hand, all three channels installed.
Generated by `store.channel_statistics()` against the live profile database, not retyped:

    {'history_signal': {'first': 2, 'corroborations': 0}}

> **Retracted the same day.** Those two rows are **one** Convex hull, recorded twice: the
> timezone defect in §4 (26 Aug) put the two channels' clocks 5:30 apart, so §5.9 could not
> recognise the second sighting. Read this block as evidence that the Toolbox path is seen,
> **not** as a completeness figure. It is re-measured after the fix, below.

| Channel | Caught first | Corroborations | Notes |
|---|---|---|---|
| Post-execution hook | **0** | **0** | mechanism absent on QGIS 4 |
| `processing.run` wrapper | **0** | **0** | **the Toolbox does not call `processing.run`** |
| History registry signal | **2** | **0** | fired for the first time; carried the path alone |

**Read this together with the two rows it produced, not as a success.** 2/2 is a completeness
figure; the record behind it had `entities = 0` and no durations. Completeness alone overstates
what was captured, which is worth saying plainly in the paper: **an RQ1 number should be
reported next to what the row actually contains.** The `toolbox` channel (§4, 26 Aug) is the
response; this table gets a third block once it has been re-measured with that channel live,
where the expected shape is `toolbox` caught first and `history_signal` corroborating.
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
| 2026-08-26 | **QGIS 4 moved the profile directory: `QGIS3/` → `QGIS4/`** | `tools/deploy.py` hardcoded `<flatpak data>/QGIS/**QGIS3**/profiles` (and `~/.local/share/QGIS/QGIS3/profiles` natively). QGIS 4.2.1 keeps profiles under **`QGIS4/profiles`** — confirmed on this machine: `QGIS4/profiles/geoprov-dev/QGIS/QGIS4.ini` was created the moment `make qgis` ran, while our symlink sat in the `QGIS3` tree QGIS never scans. **Failure mode: totally silent.** `make deploy` printed success, the symlink was real, and the Plugin Manager simply had no GeoProvenance row — no error, no Invalid tab, nothing in any log. The 11 QGIS lifecycle tests did not catch it because `pytest` puts the repo on `PYTHONPATH` and imports `geoprovenance` directly, never going through a profile directory. **Every "the plugin is deployed" claim before this date was false.** | `deploy.py` now **discovers** the major version: it scans for every `QGIS<N>/profiles` across the flatpak and native bases, prefers the highest `N`, and — when none exists — **refuses to guess**, telling you to launch QGIS once. `unlink` sweeps every root so a stale link from an older tree cannot linger. `deploy.py where` prints every root, whether QGIS has actually run there (evidence: a `QGIS<N>.ini`), the link state of each, and which would be chosen. Regression tests: `tests/plugin/test_deploy.py`, 16 of them, no QGIS needed. |
| 2026-08-26 | **An absent `qgisMaximumVersion` is not "no ceiling"** | QGIS derives one by taking the **first character** of the minimum and appending `".99"` — `pyplugin_installer/installer_data.py:834`, the code path for locally installed plugins: `qgisMaximumVersion = qgisMinimumVersion[0] + ".99"`. That is string indexing, not a version parse. With `qgisMinimumVersion=3.28` the implied ceiling was **3.99**, so QGIS 4.2.1 flagged the plugin `incompatible` — *"Plugin designed for QGIS 3.28 - 3.99"* — and would have filed it under the Plugin Manager's **Invalid** tab rather than Installed. This was a second, independent blocker sitting behind the first: fixing the profile path alone would have moved the plugin from *absent* to *greyed out*. | `metadata.txt` now declares `qgisMaximumVersion=4.99` explicitly, with the derivation rule quoted in the file so nobody deletes the line as redundant. Verified with QGIS's own `version_compare.isCompatible` inside the 4.2.1 install: `3.28 - 4.99` accepts 3.28.9, 3.34.0 and 4.2.1; the derived `3.28 - 3.99` accepts 3.28.9 and **rejects 4.2.1**. `tests/plugin/test_packaging.py` now asserts the key is present *and* that the QGIS version this document records as tested falls inside the declared window, using QGIS's own padding semantics — that assertion fails on the pre-fix metadata. |
| 2026-08-26 | **A headless PyQGIS script and the desktop application use different profiles** | `QgsApplication.qgisSettingsDirPath()` returns `<flatpak data>/**profiles/default**/` in a headless script but `<flatpak data>/QGIS/QGIS4/profiles/**geoprov-dev**/` in the desktop app started with `--profile geoprov-dev`. `--profile` is parsed by the QGIS *application*, not by `QgsApplication`, so a script cannot opt into a named profile merely by constructing one (setting `sys.argv` does nothing). **Consequence: the database written by the 24 Aug headless measurements and the one written by desktop clicking are two different files.** | Nothing to fix — `geoprovenance/paths.py` already asks QGIS at runtime instead of constructing a path, so each lands correctly for wherever it is running. Recorded so nobody hunts for a missing row in the wrong database. When comparing an RQ1 or RQ2 figure, check which profile produced it. |
| 2026-08-26 | **The Toolbox is a third execution path, distinct from both `processing.run` and the hook** | A Buffer and a Convex hull run from the Processing Toolbox were captured **only** by `history_signal`. `Processing.runAlgorithm` is not what the Toolbox calls: `processing/gui/algorithm_widget.py:runAlgorithm()` branches on the algorithm's `FlagNoThreading` between **`QgsProcessingAlgRunnerTask(alg, parameters, context, feedback)`** (line 427, threaded — what `native:buffer` takes) and **`execute(alg, …)`** from `AlgorithmExecutor` (line 452, synchronous). Neither goes anywhere near the `processing.run` monkeypatch. The consequence was not "one channel instead of two" but a materially poorer record: the history channel holds no `QgsProcessingAlgorithm`, so no parameter type map, so nothing lifted into `inputs`/`outputs` (§3.3), and no start time. Measured state of the database after two Toolbox runs: `activities=2`, **`entities=0`**, `relations=2` (both `wasAssociatedWith`), `started_at == ended_at` on both rows. | A fourth channel, `capture_channel='toolbox'`, in `capture/hooks.py` — `install_toolbox_wrapper()`. It patches **both** branches, and patches them **in the `algorithm_widget` namespace** rather than at their source: `AlgorithmExecutor.execute` is also called by `Processing.runAlgorithm`, which is what `processing.run` already goes through, so patching there would double-count every scripted run. It brackets the call, so the duration is real. Tests: `tests/capture/test_toolbox_channel.py`, 20 of them, no QGIS. |
| 2026-08-26 | **QGIS 4 wraps the parameters in a history entry — and that silently killed §5.9 dedup** | The `parameters` key of a Processing history entry does **not** hold the algorithm's parameters. It holds an envelope: `{"area_units": "m2", "distance_units": "meters", "ellipsoid": "EPSG:7030", "inputs": {"INPUT": "…/roads.shp", "DISTANCE": 10.0, …}}` — read straight out of the `parameters_json` written by the 26 Aug Toolbox runs. Two consequences. The stored record kept `area_units` and friends as though a person had passed them. Worse, the §5.9 digest is computed over the **raw** parameter dict precisely so all channels agree (the 19 Aug fix) — but every other channel holds the **flat** dict, so the digests could never match and cross-channel dedup could not fire on QGIS 4 at all. This is the 19 Aug defect returning through a different door. | `parse_history_entry` unwraps the envelope when it finds one, and returns the dict unchanged when it does not — feature detection, so a QGIS 3 entry believed to store the flat dict is unaffected (§2.5). Regression tests are built from the way the channels **actually** differ, not a convenient shape: `test_the_envelope_is_what_used_to_break_the_digest` and `test_one_toolbox_run_seen_twice_is_one_row_with_a_corroboration` both **fail** when the unwrap is removed — checked, because the 19 Aug lesson is that a green suite was not evidence. |
| 2026-08-26 | **`qgis.utils.available_plugins` from the desktop** — closes the 24 Aug "a desktop count is still needed" note | The headless run reported 0, correctly. A desktop run reports **5**, with versions, exactly as A6 assumes: `{"MetaSearch": "0.3.6", "db_manager": "0.1.20", "geoprovenance": "0.1.0", "grassprovider": "2.12.99", "processing": "2.12.99"}` — the real `plugin_versions` block from a captured job, as asked for on 19 Aug. | None needed. An RQ2 agent-row claim can now rest on a measured desktop count. |
| 2026-08-26 | **The RQ2 duration caution is wider than `post_hook`** | `CLAUDE.md` said "do not report `post_hook` durations". On QGIS 4 the history channel supplies no start time either, so every Toolbox row it wrote had `started_at == ended_at`. Between the two, **no measured path produced a usable duration** until the `toolbox` channel landed. | The `toolbox` channel stamps before the run and records the real end, so durations exist on the Toolbox path from 26 Aug. `post_hook` and `history_signal` durations remain unreportable; check `capture_channel` before using a duration in RQ2. |
| 2026-08-26 | **Auto-grouping splits a chained in-memory workflow** — a limitation, not fixed | Buffer → Convex hull were chained in the GUI, and produced **two** workflows rather than one. §5.12 groups by shared dataset paths, and the chain here was `OUTPUT: "TEMPORARY_OUTPUT"` feeding `INPUT: "memory://MultiPolygon?…uid={…}"` — two strings that are not the same path, and neither is a path at all. Working entirely in temporary layers is the *normal* way to use the Toolbox, so this is not an edge case. | **Not fixed** — recorded as a measured limitation for the paper. The grouper is deliberately conservative: §5.12 declines to invent a link it cannot evidence, and a wrong grouping is worse than an absent one. The manual override (**Plugins → GeoProvenance → Start new workflow / Name this workflow…**) is the intended answer meanwhile. |
| 2026-08-26 | **QGIS history timestamps are naive LOCAL time — and treating them as UTC broke §5.9 for a third time** | `entry_timestamp` did `moment.replace(tzinfo=utc)` on a naive `QDateTime`, which *relabels* 21:40 in Kolkata as 21:40 UTC instead of *converting* it to 16:10 UTC. Everything Person A writes comes from `utc_now_iso()` and is genuinely UTC, so the two channels' clocks disagreed by the whole local offset. Measured on this machine (UTC+05:30): one Convex hull produced two rows written **0.04 s apart** — `toolbox` at `16:10:25.228` and `history_signal` at `21:40:25.205` — whose `started_at` values are exactly `5:30:00` apart. §5.9 matches inside a 2 s window, so it could not fire: **every Toolbox job seen by both channels was recorded twice and `corroborations` sat at 0**, which is precisely the number the RQ1 per-channel split is made of (§8.3). **Consequence for the data: every `history_signal` row written before this date has a `started_at` that is wrong by the local UTC offset**, and the 26 Aug §2 measurement of `{'history_signal': {'first': 2}}` is two sightings of the same job, not two jobs. | `entry_timestamp` now uses `moment.astimezone()`, which reads a naive datetime as local and attaches the local zone, then converts to UTC. The same rule is applied to a naive ISO **string**, which used to pass straight through carrying the identical skew. A value that already states an offset keeps its instant. **The test suite is why this survived**: `test_a_naive_datetime_is_assumed_utc_rather_than_dropped` asserted the broken behaviour and passed, because CI and the dev machine both ran at UTC+0 where the bug is invisible. Its replacement pins `TZ=Asia/Kolkata` with `time.tzset()` and asserts an exact string, so it fails on the old code on **any** machine. Third occurrence of "a green suite was not evidence" — see 19 Aug. |
| 2026-08-26 | **The plugin had no idea QGIS has projects** | Reported symptom: a brand new project, one Convex hull run, and **"Jobs written down so far: 4"** — including work from a project that had been closed. Two causes, and only one is a bug. `_show_database_info` reported `ProvenanceStore.counts()`, which is `SELECT count(*)` over the whole database *on purpose* (it exists for the RQ2 storage measurement, §8.6). And no `QgsProject` signal was connected anywhere, so the `session_id` minted at plugin load ran forever: workflow grouping accumulated across unrelated projects, and §5.12's connected-components ran over a session that was really several projects deep. The other two of those four rows were the duplicate pair from the timezone bug above. | `plugin.py` connects `QgsProject.cleared` and `readProject`, and a project change calls the **existing** `engine.begin_new_workflow()`. Because `session_id` is already the grouping key (Appendix B.5), grouping stops spanning projects with **no schema change and no second mechanism**. Skipped when the outgoing session recorded nothing, so QGIS's clear-then-read on File → Open draws one boundary rather than two. The dialog now reports this project first and the machine total second — nothing is deleted, the past just stops being shown. Project awareness lives only in `plugin.py`; `capture/` and `storage/` stay project-agnostic and `engine.py` still imports no QGIS. Tests: `tests/plugin/test_project_boundaries.py`, 15, no QGIS — including two that drive `initGui()` itself, because the first eleven all passed with the wiring deleted. |
| — | | | |
