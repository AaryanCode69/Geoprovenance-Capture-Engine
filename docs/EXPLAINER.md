# GeoProvenance, end to end

**What this file is.** One read that explains the whole system: the problem it solves,
how it is put together, what each of the three developers owns, what the internal
algorithms actually do, and how far the work has got.

Written in plain words, at full technical depth. Every number, version and threshold
here is the real one, taken from the file that implements it. Where something is
untested, this document says so rather than rounding it up.

**Who it is for.** Anyone who needs the whole picture in one go — a reviewer, an
examiner, a teammate picking up a layer they did not write, or the person drafting the
Week 12 paper. No prior QGIS knowledge assumed. The exact terms are all here too, each
introduced *after* the plain explanation, so you can search for them later.

**Last checked against the code:** 31 August 2026.

---

## 1. The problem

A colleague sends you `land_use_2024.tif`. It is a map of forest, city, water and
farmland, and it looks authoritative. You want to use it, so you ask the obvious
questions:

- Which satellite image did this start from?
- Was it moved to a different coordinate system, and which one?
- Were clouds removed, and by what method?
- What was it clipped against?
- Which classification method, with which settings?
- Which version of QGIS, and which plugins?
- **Could I run this again and get the same map?**

Today the answer is: you cannot know, unless the analyst wrote it all down by hand. The
chain that produced that file might have been eight steps long — reproject, cloud mask,
clip, NDVI, classify, majority filter — and none of it survives in the file itself.

### What QGIS already gives you, and why each piece falls short

| What exists | What it does | Why it is not enough |
|---|---|---|
| **Processing History** | Logs each tool you ran | Plain text. No links between steps, no record of the data's state, nothing machine-readable |
| **Graphical Modeler** | Captures a workflow's structure | Captures the *design*, not the *execution* — no actual parameters, no record of which file version went in |
| **Python script export** | Emits the commands | Commands only. No software versions, no data state |
| **GeoLineage plugin** | Tracks lineage inside GeoPackage files | GeoPackage only. Experimental, no standard format, no reproducibility check |
| **Edit-tracking tools** | Record when geometry was edited | Geometry edits only. Blind to Processing tools entirely |

The gap is the same in every row: something records that *a thing happened*, and nothing
records *what it happened to, with what settings, on what software, and whether those
inputs are still what they were.*

### What GeoProvenance does about it

It is a QGIS plugin that watches the Processing framework and writes down every job
automatically, as you work — the tool, its settings, the files in and out, the
coordinate system, the QGIS and plugin versions. It takes a fingerprint of each file so
it can tell later whether that file has changed. It draws the result as a family tree.
And it scores how likely it is that the work could be run again today and give the same
answer.

The record is kept in a shape that matches an international standard for describing
where data came from — the W3C's PROV-O — so another tool can read it. The word for
this whole subject is **provenance**: the record of where a file came from.

---

## 2. The shape of the system

Five layers. Work flows down the table; each layer only knows about the one above it.

| Layer | What it does, in plain words | Where it lives |
|---|---|---|
| **1** | Notices that QGIS ran a job | `capture/hooks.py`, `capture/history_observer.py` |
| **2** | Writes it down, correctly and exactly once | `capture/normalizer.py`, `capture/engine.py`, `storage/` |
| **3** | Takes a fingerprint of each file touched | `fingerprint/hash.py`, `readers.py`, `compare.py` |
| **4** | Works out which file came from which | `prov.py` |
| **5** | Draws the family tree and scores it | `ui/layout.py`, `ui/panel.py`, `audit.py` |

### Two structural rules that shape everything else

**Rule one: almost nothing is allowed to import QGIS.** Only four files may —
`capture/hooks.py`, `capture/history_observer.py`, `plugin.py` and `ui/panel.py`. Every
other module works on plain Python dictionaries and asks objects what they can do rather
than what class they are. (Asking "does this object have an `authid()` method?" instead
of "is this a `QgsCoordinateReferenceSystem`?" is called *duck typing*.)

That is not tidiness. It buys two things:

- The risky logic runs under `make test` on any laptop with no GIS software installed,
  which is what let three people build in parallel from week one.
- QGIS's own API keeps moving. `QgsHistoryProviderRegistry` has already changed its
  signature between releases. Code that checks classes by name breaks on those moves;
  code that checks for methods does not.

A test enforces it: `tests/storage/test_no_qgis_imports.py`, 18 checks. It used to cover
only `storage/`, which meant a stray QGIS import in `capture/engine.py` would have first
shown up as a failed demo in a review room.

**Rule two: standard library only.** `sqlite3`, `hashlib`, `json`, `uuid`, `datetime`,
`struct`, `platform`, plus PyQGIS and PyQt. No `prov`, no `rdflib`, no `networkx`, no
`pandas`, no `numpy`. Every algorithm in section 5 is hand-written for that reason. A
QGIS plugin that needs the user to install packages is a plugin most users will not
install, and adding a dependency needs an explicit decision from the team.

---

## 3. The record — eight tables

Everything is kept in one SQLite file, at
`<your QGIS profile>/geoprovenance/provenance.db`. The layout is in
`geoprovenance/storage/schema.sql`: 8 tables, 9 indices, currently at version 2.

| Table | What a row is |
|---|---|
| `entities` | A file we are keeping track of |
| `activities` | A job QGIS ran |
| `agents` | A computer-and-software setup a job ran on |
| `fingerprints` | One measurement of what a file held at one instant |
| `relations` | A link: this job read that file; this job made that file; this file came from that one |
| `workflows` | A named group of jobs that belong together |
| `workflow_activities` | Which jobs are in which group, and in what order |
| `audit_results` | A score, and what it was based on |

The three standard terms are worth knowing because they appear throughout the code and
in the PROV-O standard: a file is an **entity**, a job is an **activity**, a
computer-and-software setup is an **agent**.

### Three identity rules that carry real weight

**A file's identity is its path *plus a version number*.** The unique key on `entities`
is `(file_path, content_version)`. When a file is rewritten with different content, it
gets a **new row** with the version raised by one — never an update to the old row. That
is the whole reason the record can hold "the boundary file before the edit" and "the
boundary file after" as two different things, which is what makes both the family tree
and the change detection possible.

Files with no path on disk — memory layers, temporary outputs, `/vsimem/` — store `NULL`
there. SQLite treats every `NULL` in a unique key as distinct, so two memory layers are
correctly never merged into one row.

**A fingerprint is unique on `(entity_id, hash_strategy, computed_at)`** — one
fingerprint per file, per method, per instant. This replaced an earlier key, and the
reason for the change is instructive.

The old key's stated rationale turned out to be wrong and has been retracted in
`docs/CONTRACT_schema.md`. The real defect was two-fold. First, whether a row counted as
a duplicate depended on how finely the computer's clock ticks — Windows advances
`datetime.now()` roughly once per millisecond, Linux far faster — which produced **13
rejected rows in 30 runs on Windows**. Second, and worse: the system takes several
different measurements of the same file at the same moment (see §5.4), and without
`hash_strategy` in the key, the second and third measurements were thrown away as
duplicates of the first.

**Link rows have no foreign key, on purpose — so which table an id lives in *is* its
type.** `relations.source_id` can point at a file or at a job, so it cannot be
constrained to one table. The consequence bit once already: in the shared test fixture,
one id was used for both the `native:centroids` job and the file it produced. Because
identity is by table membership, the same id came back in both the "files" list and the
"jobs" list, and the drawing code produced a node with an arrow pointing at itself. It
was caught by a layout test asserting that a file sits one row below the job that made
it, and the output was renamed to `w3/centroided`.

---

## 4. Noticing that a job ran — four channels

This is layer 1, and it is where the project's most significant empirical finding lives.

### The finding: on QGIS 4, the documented mechanism does not exist

The design in the research report (§5.2) rests on QGIS's *post-execution hook* — a
script QGIS is supposed to run after every Processing algorithm finishes. On **QGIS
4.2.1, it never fires, on any path, because QGIS 4 no longer runs it at all.**

The settings are still there. `ProcessingConfig.POST_EXECUTION_SCRIPT` and
`PRE_EXECUTION_SCRIPT` still exist, still appear in the Processing options dialog, and
`hasattr` finds them. But the entire QGIS 4.2.1 installation contains exactly **one**
file that mentions either name, and that file is the settings definition itself. Nothing
reads them back. `Processing.runAlgorithm` has no hook call in it. Both hook scripts
were written to disk correctly, and neither was ever executed.

**Capture was 4 out of 4 — 100% — anyway.** That is the result worth reporting. The
design installs four channels rather than trusting one, and the `processing.run` wrapper
caught every job the dead hook missed. A single-channel plugin built on the documented
mechanism would have captured nothing on this QGIS.

Two limits on that finding, both important. It was measured on QGIS 4.2.1, and **the
project targets QGIS 3.34 LTS**. Whether the hook works on 3.x is untested and, from
this evidence, unknowable — which is exactly why `capture/hooks.py` has not been
deleted. And only 1 of 10 invocation paths has been measured this way; the rest need the
desktop application driven by hand.

### The four channels

| Channel | How it notices | What it sees |
|---|---|---|
| `post_hook` | A script QGIS runs after each algorithm | **Nothing on QGIS 4** — the mechanism is gone. Untested on 3.34 |
| `run_wrapper` | Replaces `processing.run` with a wrapper that calls the original | Everything: the algorithm object, the settings, the results, and a real start and end time. Does **not** see the Toolbox, which does not call `processing.run` |
| `history_signal` | Listens to QGIS's own history registry, plus a 5-second polling timer as a fallback | That a job happened, and its settings. Often no files, because a history entry does not always name them |
| `toolbox` | Wraps both execution branches of the Processing Toolbox dialog | Files and a real duration for Toolbox runs. Added 26 Aug 2026 |

The `toolbox` channel exists because measurement showed it was needed. On 26 Aug 2026 a
Toolbox run (Buffer, then Convex hull) was captured 2 out of 2 — but entirely by
`history_signal`, which meant **0 files recorded and 0 usable durations**. The record
said two jobs happened and nothing about the data. Wrapping the Toolbox fixed it.

The pre-execution hook is not a fifth channel. It records nothing; it only leaves a
start time behind for the post hook to pick up, because a post-execution hook fires
*after* the run and would otherwise make every job look instantaneous.

### Which durations you may trust

**Check `capture_channel` before quoting any duration.**

- `run_wrapper` and `toolbox` — trustworthy. Both bracket the call, so start and end are
  real.
- `history_signal` — **not** trustworthy. It timestamps after the run, so
  `started_at == ended_at` on every row it writes. Measured 26 Aug 2026.
- `post_hook` — no rows exist on the only QGIS measured so far, so there is nothing to
  report.

### Never break the user's QGIS

Every piece of capture code that runs inside QGIS is wrapped in a broad
`try/except` that logs and returns. This outranks correctness of capture: it is better
to miss a record than to crash somebody's session. A signal handler that throws inside
Qt's event loop is worse than a lost row.

---

## 5. The algorithms

Eight of them. Each section gives the question it answers, how it works, what it costs,
and where it stops working.

### 5.1 Recognising one job seen twice — cross-channel dedup

**The question.** Four channels are watching. When two of them see the same run, the
record must hold **one** job, with a note that a second channel confirmed it — not two
jobs. Getting this wrong does not just duplicate rows; it doubles the denominator of the
capture-completeness measurement (RQ1) and makes the per-channel breakdown meaningless.

**How it works.** Two observations are the same run when both of these hold:

1. **Same algorithm, same settings.** A digest is taken over the settings and joined to
   the algorithm id: `native:buffer|3f2a9c...`. This is `dedup_group` in
   `capture/normalizer.py`.
2. **Overlapping in time.** The new observation's start time must fall inside the
   already-recorded job's own `[started_at, ended_at]` window, widened by
   `DEDUP_MARGIN_S = 2.0` seconds at each end. This is `_find_duplicate` in
   `capture/engine.py`.

First channel to report wins and inserts. The second increments a `corroborations`
counter and inserts nothing.

**Two subtleties that were defects first.**

The digest is taken over the **raw settings dictionary, before the plugin splits it
up** — because that is the only form all four channels genuinely hold alike. The hook
and the wrapper hold a `QgsProcessingAlgorithm` object, so they know which settings name
layers and lift those out into separate input and output lists. The history channel has
no algorithm object and cannot, so it keeps them as plain values. For `native:buffer`
that gave:

```
hook     {"DISTANCE": 500}
history  {"INPUT": "/data/roads.shp", "DISTANCE": 500, "OUTPUT": "/data/buf.shp"}
```

Different digests, for every algorithm that takes a layer — which is nearly all of them.
Matching could never fire, every job was written twice, and `corroborations` sat
permanently at 0.

**Memory addresses are stripped out of the digest.** When a setting holds a type the
serialiser does not recognise, it falls back to Python's `repr()`, which embeds the
object's address: `<QgsProperty object at 0x7f3c...>`. Two channels observing the same
run get the same address, but a re-run moves it — so the digest was unstable and the
first-channel-wins rule degenerated into writing the job twice. `_MEMORY_ADDRESS` in
`normalizer.py` masks the address before hashing.

**Why time is an interval and not a bucket.** The original design rounded timestamps
down onto a fixed 100-millisecond grid and matched on the bucket. That could not work:
two observations 2 ms apart get different buckets whenever a grid line falls between
them, and the hook/history pair is separated by *the entire runtime of the algorithm*
regardless. The bucket value still exists in the `dedup_key` column so the database's
unique index remains a last-resort backstop, and so that fixing this needed no schema
change.

**Where it stops.** A genuine re-run of the same algorithm over the same data, later in
the session and outside the interval, is correctly **not** a duplicate. Collapsing those
would understate the completeness figure, and a named test
(`test_a_genuinely_separate_run_is_not_swallowed_as_a_duplicate`) exists to catch it. If
a timestamp cannot be parsed at all, the code records the job rather than discarding it:
a possible duplicate beats a lost execution.

**One more guard.** Two threads can pass the duplicate check at the same moment. The
unique database index on `dedup_key` catches the second insert, and the code recovers
the corroboration rather than letting the observation be swallowed.

### 5.2 Deciding when a file becomes a new version

**The question.** A job wrote `roads_buffered.shp`. Is that the file already on record,
or a new version of it?

**How it works** (`_entity_for_path` in `capture/engine.py`). Compare the file's size
and modification time on disk now against what was recorded. If they match, reuse the
existing row. If they differ, mint a new row with the version raised by one.

**When the file cannot be inspected, the two directions differ, because the evidence
differs.** A job that *wrote* the file has demonstrated a change, so an uninspectable
write still bumps the version. A job that merely *read* it has demonstrated nothing, so
an uninspectable read reuses the existing row rather than inventing a version.

**Two rejected alternatives, and why.** "Bump on every write" was the original
behaviour: re-running a workflow over unchanged bytes then invented a new version of
every output, which puts phantom nodes in the family tree and inflates the project's own
storage-overhead measurement with a bug of its own making. "Let the fingerprint decide"
does not work either, because fingerprinting happens after the link rows already point
at the file's row — a fingerprint that disagrees with the previous version is a finding
for the audit to report, not a correction to make.

### 5.3 Grouping jobs into workflows

**The question.** You ran nine jobs this afternoon. Which of them are one piece of work?

**How it works** (`storage/workflows.py`). Two jobs belong together if they touched the
same file — and that relationship carries: job A shares a file with job B, job B shares
a different file with job C, so A, B and C are one workflow. The technique is
**union-find with path compression**: every job starts as its own group, each shared
path merges two groups, and a lookup flattens the chain it walked so the next lookup is
shorter.

Jobs are ordered inside the group by `started_at`, which becomes `sequence_order`.

**The link is deliberately undirected.** The grouper asks only "are these two related?",
never "which one wrote the file and which one read it". That direction question is a
different job — it belongs to Person B and its answer is a "this file came from that
file" row (§5.6). Reaching for direction here is the exact shape a boundary violation
would take, and the module says so.

**Grouping is recomputed, never appended to.** Whether two jobs belong together can only
be known once both exist: job 4 may write the file job 1 read, joining two groups that
looked separate a moment ago. So the whole session is regrouped after each capture, and
the previous answer is replaced.

**A name a person chose survives that.** When a computed group overlaps existing groups,
the oldest is kept and the rest are deleted, so a user-given name is the one that
survives a merge. To tell a user's name from a generated one, `_was_auto_named`
**recomputes the suggestion for the membership the group had last time and compares**.
That is exact where a "does this look auto-generated?" heuristic is not — a user who
names their work "Flood risk" would have it silently overwritten by any rule based on
the shape of the string. It is inferred rather than stored because adding a
`named_by_user` column would be a breaking change to two other people's code for a flag
only one module reads.

**What it costs.** Grouping runs once per captured job over the whole session, so a
session of *n* jobs accumulates work proportional to *n²*. Small in practice and served
by an index (`idx_activities_session`), and it is measured rather than assumed — it
falls inside the timed window and is attributed to the grouping stage there.

**Where it stops.** A job that touched no files is its own group. That is the normal case
for the history channel, which records that a run happened but attaches no files — such
a job is genuinely unconnected on the available evidence, and inventing a link would be
a guess.

### 5.4 Fingerprinting a file — one primary measurement, three complementary ones

**The question.** What did this file hold at the moment the job ran, in a form small
enough to store and exact enough to compare later?

**The primary measurement**, chosen by file size (`fingerprint/hash.py`):

- **At or under 500 MB** (`LARGE_FILE_THRESHOLD_BYTES = 500 * 1024 * 1024`): a SHA-256
  hash over every byte, read in 1 MB chunks so a large file never lands in memory whole.
  SHA-256 is a method for turning any amount of data into a fixed 64-character code that
  changes completely if a single byte changes. Strategy name: `file`.
- **Over 500 MB**: hashing the *shape* of the data instead of its bytes — file size,
  feature count, field names in order, and for rasters the band count, width, height and
  pixel size. Strategy name: `schema_sample`. Approximate by construction: it can miss
  an edit that leaves all of those unchanged. That trade-off is recorded in the
  `hash_strategy` column so the audit can report the weaker guarantee rather than imply
  the stronger one.

Two details in the shape hash that are not decoration. **The recipe's name travels
inside the hashed payload** (`"algorithm": "geoprovenance/schema_sample/2"`), so when the
recipe changes, every old value stops comparing equal to every new one — a version
sitting *beside* the hash could be ignored by code comparing two hex strings, and a
changed recipe would then read as a changed file. And **the raster fields are described
too**: rasters are the files that actually exceed the threshold, and with only the
vector fields the digest collapses to a hash of the file size, making any two same-sized
rasters identical.

**The three complementary measurements**, taken alongside the primary one whenever the
file can be read:

| Name | What it covers | Survives | Moves when |
|---|---|---|---|
| `structure` | Field names, field types, CRS | A re-save | A column is added, renamed, retyped or reordered |
| `geometry` | Feature count and bounding box | A re-save | Features are added, removed or moved |
| `attributes` | The attribute values themselves | A re-save | One value in one row is edited |

They are read straight off the raw bytes with `struct` and `sqlite3` — no QGIS, no GDAL
(`fingerprint/readers.py`). A Shapefile's `.shp` header carries the bounding box at
bytes 36–67, the `.shx` carries the record count, the `.dbf` header carries the field
names and types, and the `.prj` carries the coordinate system. A GeoPackage is a SQLite
file, so `gpkg_contents` and `PRAGMA table_info` answer the same questions.

They are read from the path rather than from an open layer because the comparison
happens long after capture, against whatever is on disk now, with nothing open in QGIS.

They are stored as **separate rows rather than one combined digest**, because a combined
digest moves whenever anything moves — which is the one-bit answer again.

### 5.5 Deciding what changed — six verdicts, not one bit

**The question.** Comparing two byte hashes gives one bit: same or different. That bit is
wrong in **both** directions often enough to matter, and both errors are counted by the
change-detection accuracy measurement (RQ3).

**Wrong as a false alarm.** A GeoPackage re-saved by a different SQLite build has
different bytes and identical data — SQLite stamps its own version into every file it
writes. Measured in this repository on `tests/fixtures/data/sample_areas.gpkg`, built
from one identical script: **bytes 92–99 move between SQLite 3.51.2 and 3.53.4**, three
further bytes at **offset 7368** move between 3.40.1 and 3.53.4, and roughly a thousand
bytes move on a library built without `SQLITE_SECURE_DELETE` — while rows, schema text
and root pages stayed identical every time. Calling that an edit is a false alarm.

**Wrong as a miss.** A Shapefile is four files, and the record points at the `.shp`.
Editing a name in the `.dbf` leaves the `.shp` byte-identical, so the fingerprint does
not move and the audit reports the file untouched. It was not.

**How it works** (`compare_fingerprint_sets` in `fingerprint/compare.py`). Take the
measurements from both moments, keep only the strategies present on **both** sides, and
split them into moved and held. Then, most-structural first:

| Verdict | When |
|---|---|
| `schema_changed` | The field list, types or CRS moved |
| `geometry_changed` | The feature count or extent moved |
| `attributes_changed` | Attribute values moved **and** geometry was checked and held |
| `resaved` | The bytes moved **and** the attribute values were checked and held |
| `unchanged` | Nothing that could be compared moved |
| `changed` | Something moved and there was not enough measured to say what |
| `unknown` | Nothing could be compared at all |

**The rule the whole module turns on: a signal missing on one side is reported as
`unavailable` and takes no part in the verdict. It is never counted as agreement.** A
GeoTIFF has no readable description here, so a GeoTIFF whose bytes moved comes back as
`changed` — today's answer, stated as today's answer, rather than a confident `resaved`
inferred from three signals that were never taken.

The same discipline shows up in two conditions above. `resaved` requires the
**attribute** signal to have held, not merely `structure` and `geometry` — a row can be
edited without disturbing the column list or the extent, and concluding `resaved` from
those two would hide a real edit. And `attributes_changed` is only claimed when the
geometry was actually checked; without it, the honest answer is `changed`.

Both measured failure cases are pinned as named tests in
`tests/fingerprint/test_compare.py`, so neither can silently come back.

### 5.6 Working out which file came from which

**The question.** The record holds "this job read that file" and "this job made that
file". Which files came from which?

**How it works** (`infer_derivations` in `prov.py`). **Every output of a job is derived
from every input of that job** — the full cross-product, not just the first input.

The research report's worked example (§7.3) lists only the primary chain:
`final_roads.shp` derived from `buffered_roads.shp`, but *not* from the
`city_boundary.shp` it was clipped against. That understates the flow. A clip's result
depends on the boundary just as much as on the layer being clipped, and an audit that
missed it would report an input as irrelevant to a file it in fact shaped.

This was not academic. The shared test fixture had transcribed §7.3 literally, including
its omission, so the fixture asserted that editing the boundary could not affect the
clip result. That is the exact claim the audit's "input unchanged" check exists to make,
so the shared artefact was training every consumer on a falsehood. It was held pinned
for one day while the other two developers were notified, then fixed: 70 link rows
became 71, no ids changed, no schema change and no migration.

Files with no path on disk take part. They cannot be fingerprinted, but they are real
nodes in the flow, and dropping them would break the chain either side of them.

The inference is idempotent — safe to re-run after every capture.

**On the missing classes.** The project brief asks Person B for "Entity / Activity /
Agent classes". There are none, deliberately: the storage layer already hands back
exactly those three row shapes as plain dictionaries, and `get_workflow_graph()` hands
back all of them together. Wrapping each in a dataclass that restates the column names
would add a second place for the schema to be written down and a translation layer to
keep in step with it, for no behaviour. The model is the graph and its lookups.

### 5.7 Arranging the family tree

**The question.** Given a set of files and jobs, where does each one go on the page?

**How it works** (`_rank_nodes` in `ui/layout.py`). Each node gets a row number, computed
as the **longest path from any starting file**. Everything begins at 0; then repeatedly:
a job's row is one more than the highest row of any file it reads, and a file's row is
one more than the row of the job that made it. Repeat until nothing moves, bounded at
`len(activities) + 1` passes.

The longest path, not the shortest, is what guarantees a file always sits below **every**
job that could have produced it. A single pass in recorded order would be correct for
anything the capture engine writes — a job cannot read a file a later job made — but
quietly wrong for a record assembled any other way, and the bound costs nothing at these
sizes: fifteen operations is the largest workflow the experiments use. The bound also
means a record containing a cycle terminates instead of spinning.

Columns are assigned in **first-appearance order** within a row, never from a set, so the
same record always draws the same picture. That matters because a demo has to be
byte-identical run to run.

The arrangement is deliberately **not** force-directed — no spring simulation. The
research report flags it as a risk in as many words, and a hand-rolled spring solver is
the kind of thing that eats a week and then jitters.

Splitting the arrangement from the drawing is what puts the branching case under
`make test` and what lets the demo print the same tree the panel draws. `ui/layout.py`
imports no Qt and no QGIS; `ui/panel.py` is the thin half that needs Qt.

### 5.8 Scoring reproducibility

**The question.** Could this work be run again today and give the same answer?

**How it works** (`audit.py`). Five checks per job, with the weights fixed by the
research report (§4.3 Layer 5):

| Check | Weight | What it asks |
|---|---|---|
| Input data exists | 30% | Is the file still where the record says? |
| Input data unchanged | 25% | Do its contents still match? |
| Algorithms available | 20% | Does this QGIS still have the tool? |
| Environment similar | 15% | Same major.minor QGIS version? |
| Parameters valid | 10% | Does the tool still accept these settings? |

Each check returns yes, no, or **cannot say**. Each component's score is the percentage
of jobs where it said yes, over the jobs where it could answer at all. The overall score
is the weighted mean over the components that ran.

**A check that could not run stores nothing, never 100.** Outside QGIS there is no
Processing registry, so "algorithm available" and "parameters valid" are unanswerable —
and scoring an unanswered check as a pass would report perfect reproducibility for every
workflow audited outside QGIS. The report says which checks did not run. This is the
same "not measured is not the same as fine" rule that §5.5 turns on.

**Two judgements the research report leaves open, made here and marked as judgements.**
The bands: HIGH at 85 or above, MODERATE at 60 or above, LOW below. The report prints
"87/100 (HIGH)" and never says what HIGH means. And **`resaved` counts as unchanged** — a
GeoPackage rewritten by a different SQLite build has different bytes and identical data,
and calling that an edit is exactly the false alarm §5.5 exists to remove.

Two smaller decisions worth knowing. A file that is *gone* is not also scored as
*changed*: awarding the contents check against a file nobody can read would let a deleted
input cost 30 points instead of the 55 it actually costs. And each file is examined
once, with the result reused for the panel's colours, so a ten-step chain reads each
file once rather than ten times — the audit runs in the foreground when you click.

### Where the fingerprinting and derivation passes run

Both happen in `capture/engine.py`, **after the database transaction has committed,
never inside it.** Fingerprinting a large raster takes seconds, and holding the write
transaction open for it would block every other writer for the duration.

The whole capture — the job row, its files, and all its link rows — lands together or
not at all. The agent row is inside that boundary too; it used to commit just before,
which left an orphan row behind whenever the main write then failed.

`ProvenanceCaptureEngine(..., enrich=False)` turns both passes off. That is how their
cost gets measured separately for the runtime-overhead result: run it both ways and
report the difference. A captured job with enrichment on leaves **four** link rows, not
three.

### How the database is opened

One connection per thread, plus one process-wide write lock. SQLite is put in
write-ahead logging mode, which lets many readers proceed while one writer works — but
it permits exactly **one** writer, so without the lock two capture channels on two
threads would produce `database is locked`. Nested transactions are supported through
savepoints, because the capture engine composes operations that each want a transaction
of their own. `close()` closes **every** thread's connection, not just the caller's — it
was leaking exactly the worker-thread connections the per-thread design exists to
create.

---

## 6. Who owns what

The project is split three ways, with the shared interfaces frozen up front so all three
people could build in parallel without waiting on each other.

> **Authorship note, applying to Persons B and C below.** Seven modules owned by B or C
> were written by **Person A**, under an explicit written override of `RULES.md` §1.2
> requested by the user on 30 August 2026, so the workflow section could be demonstrated.
> Five of them carry that override in their own header: `prov.py`, `audit.py`,
> `ui/layout.py`, `ui/panel.py`, and the two enrichment passes inside
> `capture/engine.py`. The three `fingerprint/` modules carry an owner line naming
> Person B. **The override has not been extended** — §1.2 still governs, and new B or C
> work needs the same explicit request. Nothing written under it touched Person A's
> frozen surface: no schema change, no migration, no change to a `store.py` signature.

### Person A — capture engine and storage

Owns the write path: everything that turns a QGIS Processing run into rows in SQLite.

- The plugin itself — `plugin.py`, `metadata.txt`, menu, toolbar, dock registration,
  `lifecycle.py` (the teardown mechanism), `paths.py`, `log.py`
- All four capture channels — `capture/hooks.py`, `capture/history_observer.py`
- The event normalizer — `capture/normalizer.py`: flattening settings, resolving paths,
  extracting the coordinate system, the dedup key
- The capture engine — `capture/engine.py`
- The environment probe — `capture/environment.py`
- **All** of `storage/`: the schema, migrations, and every piece of SQL in the project,
  including the `fingerprints` and `relations` tables that B writes into
- Session-to-workflow grouping — `storage/workflows.py`
- Two of the three frozen contracts: the schema and the event shape

**B and C never write SQL.** They call Person A's writer methods.

Research questions: **RQ1** (capture completeness — how many of the jobs did we notice?)
and **RQ2** (runtime and storage overhead — how much slower did QGIS get, and how many
bytes per workflow?).

### Person B — provenance modelling, fingerprinting and export

Owns the middle: turning raw rows into a standards-shaped record.

- `fingerprint/hash.py` — the size-tiered fingerprint and the three complementary
  measurements
- `fingerprint/readers.py` — reading a dataset's shape off disk with `struct` and
  `sqlite3`
- `fingerprint/compare.py` — two sets of measurements to a verdict
- `prov.py` — the graph, the "this file came from that file" inference, and both exports

The export emits real PROV-JSON, with top-level `entity` / `activity` / `used` sections
and **lowercase** roles. The research report's §7.3 example uses `"OVERLAY"` in upper
case, which the database's own check constraint would refuse.

Research question: **RQ3** (change-detection accuracy), plus validating the exported
format.

### Person C — visualisation and reproducibility audit

Owns the two outputs.

- `ui/layout.py` — where every node sits, and the same tree as plain text. No Qt, no QGIS
- `ui/panel.py` — the drawing: workflow picker, the tree as a `QGraphicsScene` (files as
  rectangles, jobs as circles, dashed lines for derivation), and the audit tab
- `audit.py` — the five-component score and the reports

Research question: **RQ4** (reconstruction accuracy), plus the comparison table against
GeoLineage and the QGIS History Manager.

**One trap recorded for whoever works on the panel next.** Do not use `dock._qt_enum`
there. It hardcodes `Qt` as the enum's owner, but `RenderHint` belongs to `QPainter` and
`DragMode` to `QGraphicsView`, and asking `Qt` for either raises on both PyQt5 and
PyQt6. `panel._member(owner, enum, name)` takes the owner. The version that got this
wrong **imported cleanly and threw only when the panel was constructed**, so an
import-only check passed it straight through — which is why `tests/capture/test_panel.py`
builds the widget rather than importing it.

### Why the split works

The shared interfaces — the schema, the event shape, the export shape — were frozen
before anyone built. A shared mock database and event file were generated once from
them (3 workflows, 16 jobs, 23 files, 71 link rows) and everyone tests against those. No
one has ever needed a live QGIS capture session to develop their own layer.

---

## 7. Where the work stands

**523 tests pass** under `make test`, on a machine with no QGIS and no GIS stack
installed. Verified 31 August 2026.

| Suite | Tests | Covers |
|---|---|---|
| `tests/storage/` | 151 | Schema, store, migrations, fixtures, the no-QGIS guard |
| `tests/capture/` | 179 | Normalizer, engine, history observer, toolbox channel, timing |
| `tests/fingerprint/` | 86 | Hashing, readers, comparison |
| `tests/plugin/` | 68 | Lifecycle, packaging, paths, deploy, project boundaries |
| `tests/prov/` | 11 | Graph, derivation inference, both exports |
| `tests/audit/` | 16 | The five checks and the score |
| `tests/ui/` | 12 | Arrangement, including the branching case |

**Phase 1 is code-complete.** Its QGIS-dependent exit criteria are **partly** met: the
plugin loads and unloads cleanly in QGIS (11 of 11 lifecycle tests, run inside QGIS
4.2.1), a 4-step workflow was captured live at 100%, and the coverage document has real
measurements in it.

**What is not done, stated plainly:**

- **The QGIS version is wrong for the target.** Everything was measured on QGIS 4.2.1,
  Python 3.13.14, Qt 6.10.3, PyQt6 — not the QGIS 3.34 LTS the project targets. The
  intended Flathub 3.28.9 LTS build **cannot be installed**: it depends on the
  end-of-life runtime `org.kde.Platform//5.15-21.08`, and one object in that runtime
  returns HTTP 503 past 1 MiB from every Flathub CDN edge. QGIS 4.2.1 was the only
  obtainable build.
- **The development interpreter does not match QGIS's.** The `.venv` is Python 3.10.12;
  QGIS runs 3.13.14. `RULES.md` §2.1 is not satisfied. Recorded, not papered over.
- **1 of 10 invocation paths measured.** Only `processing.run()` from a script has been
  measured this way. The Toolbox has been measured separately (2 of 2, 26 Aug). The
  Modeler, batch mode, failure, cancellation, and the GDAL/GRASS/SAGA providers all need
  the desktop application driven by hand.
- **The menu dialogs have not been clicked.** "Start new workflow" and "Name this
  workflow…" are written and untested by a human. `make deploy` was broken until 26 Aug
  2026 — it linked into `QGIS3/profiles` while QGIS 4 reads `QGIS4/profiles`, so the
  plugin had never once appeared in the Plugin Manager.
- **Phase 2 and Phase 3 have not started.** The RQ1 and RQ2 numbers do not exist yet.
- **The contracts are not tagged.** `schema.sql` still says "change it freely until
  then"; no `contract-v1` tag exists.

**One caution worth carrying into the experiments.** When the cross-channel dedup was
found broken in August, **all three existing tests for it passed**, because each was
built on the one shape where the defect is invisible — and the Review 2 demo asserted
the same claim. A green suite was not evidence there, and will not be for the
measurements still to come.

### A note on running tests

Run `make test` **outside** QGIS and `make test-qgis` **inside** it. Do not run
`pytest tests` inside QGIS: seven tests fail there and none of them is a defect — they
assert the no-QGIS degradation path on purpose. Running the icon test inside QGIS also
rewrites `geoprovenance/icon.png`, because zlib differs between Python 3.10 and 3.13.

And do not run `pytest tests/storage` directly: `pytest-qgis` loads automatically and
imports `qgis` before any configuration file runs, so a bare invocation crashes on a
machine without QGIS and hides the no-QGIS-import violations on a machine with it. The
`make` targets pass `-p no:pytest_qgis`.

---

## 8. Running it

| Command | What happens |
|---|---|
| `make test` | 523 tests, no QGIS needed, a few seconds |
| `make demo1` | The Week 4 gate: QGIS ran a job and we wrote it down automatically |
| `make demo2` | The Week 8 gate: a whole 4-step workflow captured in the right order, 6 of 6, under a second |
| `make demo-workflow` | Capture, then the family tree, then a score of 100. Then one starting file is edited behind the software's back and the score falls to 89, **naming the file** |
| `make qgis-demo` | The visual demonstration: three input datasets, four Processing steps run inside a real QGIS, the record exported to map layers, and a styled QGIS project with four layer groups and a printable page |
| `make qgis-demo-open` | Opens that project |
| `make fixtures` | Regenerates the shared mock database the other two developers test against |
| `make schema-check` | Applies the schema to a throwaway database and reports the tables and indices |
| `make deploy && make qgis` | Links the plugin into the `geoprov-dev` QGIS profile and launches it |

Every demo runs **without QGIS**, on any machine, offline, in a review room — the QGIS
side is replayed from recorded events. A live QGIS run is a separate optional second
act, never the only act. Each demo deletes and rebuilds its own database every run, so
it cannot pass because of leftover state, and each is byte-identical run to run.

To run the plugin inside QGIS by hand — launching it, ticking it on, what you should see,
and how to fill in the remaining coverage rows — follow
[`RUNNING_IN_QGIS.md`](./RUNNING_IN_QGIS.md).

---

## Where to go next

| You want | Read |
|---|---|
| The same system as three pictures | [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`DFD.md`](./DFD.md) · [`USE_CASES.md`](./USE_CASES.md) |
| The research background and literature review | [`../geoprovenance_research.md`](../geoprovenance_research.md) |
| Setup, the team split, the phases | [`DEVELOPMENT.md`](./DEVELOPMENT.md) |
| The rules the code is written under | [`../RULES.md`](../RULES.md) |
| The exact shape of the record | [`CONTRACT_schema.md`](./CONTRACT_schema.md) |
| The exact shape of a captured event | [`CONTRACT_event.md`](./CONTRACT_event.md) |
| What has actually been measured, and what has not | [`capture_coverage.md`](./capture_coverage.md) |
| Running the plugin in QGIS by hand | [`RUNNING_IN_QGIS.md`](./RUNNING_IN_QGIS.md) |
| The shared test data, for Persons B and C | [`../tests/fixtures/README.md`](../tests/fixtures/README.md) |
