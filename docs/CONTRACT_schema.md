# CONTRACT: Provenance database schema

> **STATUS: READY TO FREEZE — pending Person B and Person C sign-off.**
> Every `OPEN:` item is closed. Becomes binding when tagged `contract-v1` with
> Person B's and Person C's agreement (`RULES.md` §3.1).
> After that, changing anything here follows the mandatory 5-step procedure in `RULES.md` §3.4.

| | |
|---|---|
| **Author** | Person A |
| **Consumers** | Person B (writes through `ProvenanceStore`), Person C (reads) |
| **Implementation** | `geoprovenance/storage/schema.sql` |
| **Baseline** | Research doc §7.1, verbatim, plus the six decisions below |
| **Version** | `PRAGMA user_version = 2` |

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

#### When the version bumps

*Closed by Person A, 18 Aug 2026 (A4). Option (b).*

**The version moves when the file's size or modification time disagrees with what was recorded for that path.** Person A stats the file at write time and stores `size_bytes` and `mtime_ns` in that entity's `metadata_json`; the next execution touching the same path compares against them.

When the file cannot be stat'd — missing, permission denied, or never a real file — the two directions differ, because the evidence differs:

| The job | Cannot verify | Why |
|---|---|---|
| **wrote** the file | mint a new version | A write is itself evidence that the content changed. |
| **read** the file | reuse the entity | A read demonstrates nothing. Inventing a version would be a guess (§5.6). |

*Why not (a) — A writes `1`, B bumps on hash mismatch:* entity identity is Person A's decision (Appendix B.1) and Person B's fingerprinting is asynchronous, so by the time a hash disagrees the relations already point at the row. B would be mutating identity after the fact, which §1.2 puts outside B's half. **A fingerprint that disagrees with the previous version is an audit finding for Person C, not a correction to the record.**

*Why not "every write bumps", which is what A3 did:* re-running a workflow over unchanged bytes invented a new version of every output. That puts phantom nodes in Person C's graph and inflates Person A's own RQ2 storage numbers with a bug of Person A's making — the same failure mode §4.6 guards against for `agents` rows.

*Why size + mtime rather than a hash:* hashing is Person B's job (§1.2), it happens after this row is written, and `stat()` costs microseconds where hashing a 1 GB raster does not — this runs inside the user's processing run, and §8.4 targets under 5% overhead. It is a proxy and it can miss a rewrite that preserves both size and mtime; that is an accepted, documented limit, and B's fingerprint is the authoritative check.

> **No schema change.** The probe lives in the existing `entities.metadata_json` column, so `PRAGMA user_version` stays at 1 and no migration is needed.

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

*Why:* every timestamp in the schema is compared, ordered, or made part of a key, and second resolution is too coarse for all three inside a single processing run.

#### The fingerprints key — corrected 26 Aug 2026 (v2)

*Originally this decision read: "`fingerprints` declares `UNIQUE(entity_id, computed_at)`. B hashes input and output inside the same second; at second resolution the constraint fires and the second insert fails." **That rationale named a case the constraint cannot produce.*** An input and an output are different entities, so their rows differ on `entity_id` and never collide, at any resolution.

The case the key really governs is **the same entity measured more than once**, and there the old key was wrong in two ways:

1. **It called complementary measurements duplicates.** A byte hash and a schema hash of one file are two different measurements of that file, computed together on purpose so they can be compared against each other. Under `(entity_id, computed_at)` the second one is rejected.
2. **It made row identity depend on the clock.** Whether two such rows survived came down to whether the clock ticked between them — a platform detail. Measured: **13 rejections in 30 runs on Windows**, where `datetime.now()` advances roughly once per millisecond; effectively invisible on Linux.

```sql
hash_strategy    TEXT NOT NULL DEFAULT 'file',
...
UNIQUE (entity_id, hash_strategy, computed_at)
```

Read as **one fingerprint per dataset, per method, per instant.** Complementary measurements are permitted because they differ on `hash_strategy`; a genuine duplicate still matches on all three and is still blocked.

**`NOT NULL` is load-bearing.** SQLite counts every NULL in a `UNIQUE` as distinct — the same rule decision 1 relies on so that memory layers (`file_path IS NULL`) never deduplicate against each other. Here that rule works against us: a nullable `hash_strategy` in the key means two identical rows both land whenever it is left unset, removing the very protection the key exists to give. Every fingerprint was produced by some method, so `NOT NULL` makes no legitimate row unrepresentable.

Microsecond precision remains mandatory — it is necessary, it was simply never sufficient on its own.

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
| `activities` | `capture_channel` | Which channel won: `post_hook` / `run_wrapper` / `history_signal` / `toolbox`. **This is RQ1 evidence** (`RULES.md` §8.3) |
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
| 2026-08-26 | **2** (draft) | **`fingerprints` UNIQUE gains `hash_strategy`, which also becomes `NOT NULL DEFAULT 'file'`.** `(entity_id, computed_at)` → `(entity_id, hash_strategy, computed_at)`. Decision 4's fingerprint rationale is corrected above — it named a collision the old key could not produce (input and output are different entities and never collide) and missed the one it did. The new key permits several complementary measurements of one file at one instant, which is what Person B's layered fingerprinting needs, while still blocking genuine duplicates. It also removes 13-in-30 spurious rejections measured on Windows, where row identity had been depending on clock granularity. **`NOT NULL` is part of the fix, not tidying:** SQLite counts every NULL in a `UNIQUE` as distinct, so a nullable column in the key silently disables the duplicate check for any row that leaves it unset — which was the default call path. No new column; `hash_strategy` already existed, and existing NULLs backfill to `'file'`, which is what they were. `user_version` 1 → 2; the forward migration rebuilds the table, because SQLite has no `ALTER TABLE … DROP CONSTRAINT`. | **Person A:** the migration runs on open; row data is preserved (verified against the committed v1 fixture — 22 rows, `integrity_check` ok, `foreign_key_check` clean). **One change inside `store.py`:** `add_fingerprint`'s `hash_strategy` default moves from `None` to `'file'`, because an explicit `None` bypasses a column default and would now hit `NOT NULL`. Keyword-only, nothing calls it positionally. `test_two_fingerprints_in_the_same_second_both_land` is replaced by three tests — its body used one entity for what its docstring called "an input and an output", which under the new key is a genuine duplicate. **Person B:** pass `hash_strategy` whenever you write more than one measurement for a file. **Person C:** re-pull the fixtures. A file may now carry several fingerprint rows at one instant, one per method — `get_latest_fingerprint()` returns the newest of *any* method, so filter on `hash_strategy` if your audit specifically means the byte hash. |
| 2026-08-26 | **2** (draft) | **No additional DDL change or migration.** `activities.capture_channel` is plain `TEXT` with no `CHECK`, so the fourth channel value `toolbox` (see `docs/CONTRACT_event.md`, same date) needed only the column comment extended. The concurrent fingerprint change above is what moved `user_version` to 2. Because SQLite stores the `CREATE TABLE` text verbatim in `sqlite_master`, editing the comment still changes the committed fixture, so it was rebuilt with `make fixtures`. | **Person B and Person C: re-pull `tests/fixtures/mock_provenance.db`.** All row values and `mock_ids.json` remain unchanged by the channel-comment update, so every pinned id in your tests still resolves. The fixture also includes the v2 fingerprint constraint described above. `mock_events.json` is untouched. |
| 2026-08-19 | 1 (draft) | **No DDL change.** `schema.sql`'s comment on `activities.capture_channel` listed only `post_hook` and `history_signal`; the code has emitted three values since A3 and both `docs/CONTRACT_event.md` and `schemas/event.schema.json` list `run_wrapper`. Comment corrected, status wording aligned with this document. Separately, the committed fixtures were regenerated: SQLite stamps its own library version into every file it writes, so `sample_areas.gpkg` — and therefore the SHA-256 of it recorded in `mock_provenance.db` — differed on every machine with a different SQLite build. `build_fixtures.py` now blanks that header field. | **Person B and Person C: re-pull `tests/fixtures/mock_provenance.db` and `tests/fixtures/data/sample_areas.gpkg`.** The only row that changed is the `fingerprints` hash for `sample_areas.gpkg`; entity, activity, agent, relation and workflow ids are all unchanged, so pinned ids in your tests still resolve. `mock_events.json` and `mock_ids.json` are byte-identical. |
| 2026-08-18 | 1 (draft) | **Decision 1's `OPEN:` item closed; status is now READY TO FREEZE.** `content_version` bumps when a size + mtime probe disagrees with what was recorded, not on every write. The probe is stored in the existing `entities.metadata_json`, so **no DDL change and no migration** — `user_version` stays 1. | **Person B:** do not bump `content_version` yourself. Attach your fingerprint to whichever version Person A minted; a hash that disagrees with the previous version is an audit finding for Person C, not a correction. **Person C:** re-running a workflow over unchanged files no longer produces a fresh node per output. |
| — | 1 | Initial draft. Not yet frozen. | — |
