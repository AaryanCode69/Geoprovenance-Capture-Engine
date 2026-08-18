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

**How to fill a row:** run the operation in the dev profile, then check the message log and the database. Record what actually happened, including partial captures.

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
| — | `QgsHistoryProviderRegistry.entryAdded` | Signature has changed across releases; known crash risk (research doc §12 risk 7) | Verify signature against the local build; `QTimer` + `queryEntries()` polling fallback (`RULES.md` §5.10) |
| 2026-08-18 | `pytest-qgis` 4.1.1 | Registers a `pytest11` entrypoint that runs `from qgis.core import ...` at plugin-load time, before any conftest. `pytest tests/storage` crashes at startup on a machine without QGIS, even though that suite imports no QGIS — which would have silently voided the §4.1 guarantee. | `make test-storage` passes `-p no:pytest_qgis` (`RULES.md` §6.1.1). Verified: 6/6 storage tests pass with QGIS absent. |
| — | | | |
