# Capture coverage — what fires the hook, and what doesn't

> **This table is RQ1's evidence and the paper's limitations section.**
> Start filling it in **Week 4**, not Week 9 (`RULES.md` §5.11, §8.2).
> Every row is measured on this machine, not inferred from documentation (`RULES.md` §11.4).

| | |
|---|---|
| **Owner** | Person A |
| **QGIS version tested** | `UNVERIFIED:` fill in from `Qgis.QGIS_VERSION` |
| **Python version** | `UNVERIFIED:` fill in from the QGIS Python console |
| **OS** | `UNVERIFIED:` fill in from `platform.platform()` |
| **Last updated** | — |

---

## 1. Invocation paths — does the post-execution hook fire?

The central empirical question of A3. The hook is run by `Processing.runAlgorithm`; the Toolbox dialog, batch mode, and the Graphical Modeler may take **different code paths**, and this is not reliably documented.

| Invocation path | Hook fires? | History signal fires? | Captured? | Notes |
|---|---|---|---|---|
| Processing Toolbox dialog | `UNVERIFIED:` | `UNVERIFIED:` | | |
| `processing.run()` from the Python console | `UNVERIFIED:` | `UNVERIFIED:` | | |
| Graphical Modeler (whole model) | `UNVERIFIED:` | `UNVERIFIED:` | | Does it fire once, or once per step? |
| Graphical Modeler (per step) | `UNVERIFIED:` | `UNVERIFIED:` | | |
| Batch mode | `UNVERIFIED:` | `UNVERIFIED:` | | |
| Toolbox, algorithm fails mid-run | `UNVERIFIED:` | `UNVERIFIED:` | | Must record `status='failed'` (§4.10) |
| Toolbox, user cancels | `UNVERIFIED:` | `UNVERIFIED:` | | Must record `status='cancelled'` |
| GDAL/OGR algorithm via Processing | `UNVERIFIED:` | `UNVERIFIED:` | | |
| GRASS algorithm via Processing | `UNVERIFIED:` | `UNVERIFIED:` | | |
| SAGA algorithm via Processing | `UNVERIFIED:` | `UNVERIFIED:` | | |

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

| Channel | Executions caught first | Corroborations | Caught *only* by this channel |
|---|---|---|---|
| Post-execution hook | `UNVERIFIED:` | `UNVERIFIED:` | `UNVERIFIED:` |
| `processing.run` wrapper | `UNVERIFIED:` | `UNVERIFIED:` | `UNVERIFIED:` |
| History registry signal | `UNVERIFIED:` | `UNVERIFIED:` | `UNVERIFIED:` |

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
| — | | | |
