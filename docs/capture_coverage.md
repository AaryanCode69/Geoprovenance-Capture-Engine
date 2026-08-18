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

**Two channels are installed** (`capture/hooks.py`), so a row can be caught by either:

| Channel | `capture_channel` value | Catches |
|---|---|---|
| Processing post-execution hook | `post_hook` | whatever QGIS routes through `Processing.runAlgorithm` |
| `processing.run` monkeypatch | `run_wrapper` | scripted calls, whether or not the hook fires |
| History registry signal (A5) | `history_signal` | not yet installed |

A job seen by both is stored once, with `corroborations` incremented — that column *is*
the per-channel evidence, so read it rather than counting log lines.

---

## 2. Per-channel split

The number that makes RQ1 interesting rather than a single aggregate (`RULES.md` §5.9, §8.3).

| Channel | Executions caught first | Corroborations | Caught *only* by this channel |
|---|---|---|---|
| Post-execution hook | — | — | — |
| History registry signal | — | — | — |

Target claim: *"the hook caught N%, the history channel caught the remaining M%."*

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
| — | **Start time in the hook** | The post-execution hook fires *after* the run, so unless QGIS leaves a start time in the namespace every job looks instantaneous. | A5 adds a pre-execution hook that stamps `geoprovenance_started_at`. Until then durations from the `post_hook` channel are not meaningful — **do not report them in RQ2.** |
| — | `QgsHistoryProviderRegistry.entryAdded` | Signature has changed across releases; known crash risk (research doc §12 risk 7) | Verify signature against the local build; `QTimer` + `queryEntries()` polling fallback (`RULES.md` §5.10) |
| 2026-08-18 | `pytest-qgis` 4.1.1 | Registers a `pytest11` entrypoint that runs `from qgis.core import ...` at plugin-load time, before any conftest. `pytest tests/storage` crashes at startup on a machine without QGIS, even though that suite imports no QGIS — which would have silently voided the §4.1 guarantee. | `make test-storage` passes `-p no:pytest_qgis` (`RULES.md` §6.1.1). Verified: 6/6 storage tests pass with QGIS absent. |
| — | | | |
