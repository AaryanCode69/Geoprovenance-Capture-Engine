# CONTRACT: Provenance database schema

> **STATUS: DRAFT — NOT YET FROZEN.**
> Becomes binding when tagged `contract-v1` with Person B's and Person C's agreement.
> After that, changing anything here follows the mandatory 5-step procedure in `RULES.md` §3.4.

| | |
|---|---|
| **Author** | Person A |
| **Consumers** | Person B (writes through `ProvenanceStore`), Person C (reads) |
| **Implementation** | `geoprovenance/storage/schema.sql` |
| **Baseline** | Research doc §7.1, verbatim, plus the six decisions below |
| **Version** | `PRAGMA user_version = 1` |

---

## How B and C use this

**Person B and Person C never write SQL** (`RULES.md` §1.3). They call `ProvenanceStore` methods. If a needed query is missing, Person A adds the method — do not reach into the database directly, because the schema is versioned and the store is not.

Person A owns the `fingerprints` and `relations` tables even though Person B produces their contents. B computes a fingerprint and calls `store.add_fingerprint(...)`; B builds a relation and calls `store.add_relation(...)`.

---

## The six frozen decisions

Research doc §7.1 leaves six things open. Each one, left open, breaks B's or C's code later. Full rationale in `RULES.md` Appendix B; the short version and the resulting DDL are here.

### 1. Entity identity — one row per `(file_path, content_version)`

A file rewritten with different content gets a **new** entity row with `content_version + 1`, never an update in place.

```sql
content_version INTEGER NOT NULL DEFAULT 1,
UNIQUE (file_path, content_version)
```

*Why:* without it the graph cannot tell "the file before" from "the file after", so B's derivation chains and C's history view are both wrong. SQLite treats NULLs as distinct in `UNIQUE`, so memory layers (`file_path IS NULL`) are correctly never deduplicated against each other.

**`OPEN:` — Person A, close by end of Phase 0.** The mechanism that decides *when* to bump `content_version`. The version changes when the fingerprint changes, but B computes fingerprints asynchronously, after the row is written. Options: (a) A writes `content_version = 1` and B bumps on hash mismatch; (b) A checks file mtime + size at write time as a cheap proxy. Decide before freezing — it changes B's writer call.

### 2. Relation role vocabulary — lowercase, original key preserved

Roles are exactly `input` | `output` | `overlay` | `parameter`. The original QGIS parameter key (`OVERLAY`, `INPUT`, …) is kept in its own column.

```sql
role           TEXT,   -- lowercase only, CHECK-constrained
qgis_param_key TEXT,   -- 'OVERLAY' — the original QGIS key, unmodified
```

*Why:* §7.1's comment says `'input'|'output'|'parameter'` while §7.3's example uses `"INPUT"` and `"OVERLAY"`. Two vocabularies for one concept means C writes string-normalising code that should never have existed.

### 3. Indices — mandatory, not an optimisation

`relations(source_id)`, `relations(target_id)`, `relations(relation_type)`, `entities(file_path)`, `fingerprints(entity_id)`, `workflow_activities(workflow_id)`, plus `activities(session_id)` and `activities(started_at)`.

*Why:* C's traversal does repeated reverse lookups. Without these, Workflow C (15+ operations) is slow, and Person A's own RQ2 numbers look worse than the design deserves.

### 4. Timestamps — microsecond UTC ISO 8601, everywhere

```python
datetime.now(timezone.utc).isoformat()
```

*Why:* `fingerprints` declares `UNIQUE(entity_id, computed_at)`. B hashes input and output inside the same second; at second resolution the constraint fires and the second insert fails.

### 5. Session grouping — `activities.session_id`

A UUID minted once at plugin startup, stamped on every activity.

*Why:* §7.1 has a `workflows` table but nothing linking an activity to the QGIS session that produced it. This is what makes automatic grouping possible without asking the user to declare workflow boundaries.

### 6. Migration path — `PRAGMA user_version` + `migrations.py` from day one

*Why:* the schema **will** change in Phase 2 — that is when contract mismatches surface. With a version, B's and C's fixture databases fail loudly on mismatch instead of breaking silently.

---

## Additions beyond research doc §7.1

Marked `[+A0.1]` in `schema.sql`.

| Table | Column | Purpose |
|---|---|---|
| `entities` | `content_version` | Decision 1 |
| `entities` | `layer_type` | Set even when `file_path IS NULL`, so B knows not to hash memory layers (`RULES.md` §3.3) |
| `activities` | `session_id` | Decision 5 |
| `activities` | `capture_channel` | Which channel won: `post_hook` / `history_signal`. **This is RQ1 evidence** (`RULES.md` §8.3) |
| `activities` | `corroborations` | Times the other channel also saw it (`RULES.md` §5.9) |
| `activities` | `dedup_key` | Unique index enforces §5.9 dedup at the database level |
| `agents` | `env_fingerprint` | `UNIQUE` — makes `get_or_create_agent` correct (`RULES.md` §4.6) |
| `relations` | `qgis_param_key` | Decision 2 |
| `fingerprints` | `hash_strategy` | `file` vs `schema_sample` — B's tiered fallback (research doc §6.4) |
| `workflows` | `session_id` | Which session this grouping came from |

`CHECK` constraints on `activities.status` and `relations.relation_type` / `role` are also new. They exist so a contract violation fails at write time in Person A's code rather than surfacing as a rendering bug in Person C's.

---

## Changelog

Every post-freeze change needs a dated row here, per `RULES.md` §3.4 step 2.

| Date | Version | Change | Who must update what |
|---|---|---|---|
| — | 1 | Initial draft. Not yet frozen. | — |
