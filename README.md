# GeoProvenance

Automated Spatial Workflow Lineage Tracking and Reproducibility Framework for QGIS.

A QGIS plugin that automatically captures Processing Framework operations, maps them to the W3C PROV-O standard, fingerprints input/output datasets (SHA-256), visualizes provenance as an interactive DAG, and produces a quantitative reproducibility audit score.

Full research background, literature review, and architecture rationale: [`geoprovenance_research.md`](./geoprovenance_research.md).

---

## Environment

| Requirement | Version |
|---|---|
| **Python** | **3.10+** (developed against Python 3.10 or 3.11 — matches QGIS 3.34 LTS's bundled interpreter; do not use 3.12+ until QGIS LTS ships it) |
| **QGIS** | 3.34 LTS or newer |
| **Plugin API** | PyQGIS + PyQt5 |
| **Storage** | SQLite (`sqlite3`, stdlib) |
| **Hashing** | `hashlib` (SHA-256, stdlib) |
| **Testing** | `pytest` + `pytest-qgis` |
| **Version control** | Git |

Everyone must develop and test against the **same Python version installed with your QGIS 3.34 LTS instance** (check via the QGIS Python console: `import sys; sys.version`). Mismatched interpreter versions between QGIS's bundled Python and a separately installed system Python is the most common source of "works for me" plugin bugs — always run tests through `pytest-qgis`, not a bare system `python3`.

No external heavyweight dependencies (no `prov`, `rdflib`, `pydot`) — the project uses a custom lightweight PROV model and PyQt5-native visualization to keep the plugin dependency-free (see research doc §6.2, §6.5).

Setup:
```bash
python3 --version        # confirm 3.10+
git clone <repo-url>
cd geoprovenance
python3 -m venv .venv
source .venv/bin/activate
pip install pytest pytest-qgis
```

---

## Team Structure — 3 People, Independent Components

The project is split into three components with a **frozen shared contract** defined up front, so all three people build and test in parallel without waiting on each other's code. The contract is:

- The SQLite schema in research doc §7.1 (`entities`, `activities`, `agents`, `fingerprints`, `relations`, `workflows`, `audit_results`)
- The event/PROV-JSON shape shown in research doc §7.3 (worked Buffer→Clip example)

A shared **mock dataset** (a hand-built SQLite file + JSON matching §7.3) is generated once in Phase 0 and used by everyone as test fixtures — nobody needs the real capture engine running to develop or test their own component.

### Person A — Capture Engine & Storage

Owns everything left of "PROV Mapper" in the architecture diagram (research doc §5.1).

- QGIS plugin skeleton (Plugin Builder scaffold)
- Post-execution hook (`processing.run()` wrapper)
- `QgsHistoryProviderRegistry.entryAdded` signal listener (redundant capture channel)
- Event normalizer (dedup, parameter parsing, CRS extraction)
- SQLite schema implementation + CRUD layer

Reference: research doc §5.2, §5.3, §7.1.

### Person B — Provenance Modeling, Fingerprinting & Export

Owns everything from "PROV Mapper" through "Data Fingerprinter" in the architecture diagram.

- Custom lightweight PROV model — Entity / Activity / Agent classes
- Relation inference (`wasDerivedFrom` from input/output path overlap)
- SHA-256 tiered fingerprinting (file-level hash; schema+sample-hash fallback for large vectors)
- PROV-JSON / JSON-LD exporter

Fully testable standalone: fingerprinting only needs a file path; PROV mapping only needs the mock event data from Phase 0.

Reference: research doc §4.3 (Layers 2–3), §6.2, §6.4, §7.2.

### Person C — Visualization & Reproducibility Audit

Owns the two output modules: DAG Viewer and Reproducibility Audit.

- DAG viewer: PyQt5 `QGraphicsScene` dock widget, hierarchical top-to-bottom layout, node/edge rendering with status color-coding (verified/changed/missing)
- Reproducibility audit engine: 5-component weighted scorer (input exists 30%, input unchanged 25%, algorithm available 20%, environment similar 15%, parameters valid 10%)
- Audit report generator (text + visual)

Fully testable standalone against the mock SQLite DB from Phase 0 — never needs a live QGIS capture session.

Reference: research doc §4.3 (Layers 4–5), §7.1 (`audit_results`).

---

## Phases

### Phase 0 — Contracts (joint, short)

The only phase requiring lockstep coordination. All three agree on and freeze:
- The §7.1 SQLite schema
- The event-dict shape Person A's capture engine will emit
- The §7.3-style PROV-JSON shape

Build the shared mock dataset from these contracts.

### Phase 1 — Independent Build (parallel, bulk of the project)

Each person builds and unit-tests their component in isolation against the Phase 0 contracts and mock data. No cross-waiting.

### Phase 2 — Integration

Wire the real pipeline together: Person A's capture engine → Person B's PROV mapper + fingerprinter → shared SQLite DB → Person C's DAG viewer + audit engine now read from the live DB instead of the mock. Budget real time here — this is where contract mismatches surface, even though the interface was fixed in Phase 0.

### Phase 3 — Experiments, Paper & Polish

Split by research question (research doc §9), matching each person's component:

| Owner | Research question | What's measured |
|---|---|---|
| Person A | RQ1 — capture completeness; RQ2 — runtime/storage overhead | Their engine is the thing being measured |
| Person B | RQ3 — change-detection accuracy via fingerprinting | Plus PROV-JSON schema validation |
| Person C | RQ4 — reconstruction accuracy via DAG traversal | Plus the GeoProvenance vs. GeoLineage vs. History Manager comparison table |

Each person drafts the methodology subsection for their own layer; Introduction, Related Work, and Results are synthesized jointly at the end.

### Stretch Goal — Workflow Replay

Not assigned by default (research doc §4.3 Layer 6, "stretch goal"). Whoever finishes their track first can pick it up — it extends both Person A's capture side (re-invoking `processing.run()`) and Person B's PROV side (reading back stored relations).

---

## Feature Priority (for scope decisions during Phase 1)

| Feature | Priority | Owner |
|---|---|---|
| Automatic `processing.run()` capture | MUST HAVE | A |
| W3C PROV-O mapping | MUST HAVE | B |
| SQLite storage | MUST HAVE | A |
| SHA-256 fingerprinting | MUST HAVE | B |
| Reproducibility audit + scoring | MUST HAVE | C |
| PROV-JSON/JSON-LD export | MUST HAVE | B |
| DAG visualization | SHOULD HAVE | C |
| Multi-step workflow chaining | SHOULD HAVE | A/B |
| Plugin version tracking | SHOULD HAVE | A |
| Workflow replay | STRETCH GOAL | unassigned |

Explicitly out of scope for this project: manual geometry edit tracking, non-Processing plugin GUI tracking, RDF/SPARQL queries, web-based (D3.js) visualization, cross-plugin unification, real-time collaboration, cloud/remote data provenance (full rationale in research doc §13.13).
