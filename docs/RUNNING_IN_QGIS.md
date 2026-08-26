# Running GeoProvenance in QGIS — a runbook you can follow by hand

> **Who this is for.** Anyone who wants to see the plugin working inside the desktop
> application rather than in a test suite. No prior QGIS knowledge assumed.
>
> **Why it exists.** Phase 1 (A1–A6) is code-complete and 317 tests pass without QGIS. The
> plugin has been proven to *load* inside QGIS 4.2.1 (11/11 lifecycle tests) and a 4-step
> workflow was captured at 100% — but all of that was **headless, driven by a script**.
> Nobody has opened the desktop application, ticked the plugin on, or clicked a menu item.
> `docs/capture_coverage.md` §1 has **1 of 10** invocation-path rows measured, and the other
> nine need a person clicking (`RULES.md` §5.11). This is the procedure for that.
>
> Every path and command below was checked against this machine, not recalled.

---

## What is already true on this machine

| | |
|---|---|
| QGIS | Flatpak `org.qgis.qgis` **4.2.1** — `filesystems=host`, so the symlink into the repo resolves |
| Native QGIS | **none** — `qgis` is not on `PATH`; every command goes through `flatpak run` |
| Dev profile | `~/.var/app/org.qgis.qgis/data/QGIS/QGIS4/profiles/geoprov-dev/` — QGIS 4 uses `QGIS4`, not `QGIS3` |
| Plugin link | deployed into the **QGIS4** tree since 26 Aug 2026 (see the box below) |
| `metadata.txt` | `experimental=True` ← hides the plugin in the manager by default (§2.1) |
| | `qgisMaximumVersion=4.99` ← required, or QGIS derives `3.99` and rejects the plugin |

> **Two defects were fixed on 26 Aug 2026, and both were invisible.**
>
> `make deploy` linked into `QGIS3/profiles`; QGIS 4 reads `QGIS4/profiles`. The symlink was
> real, `make deploy` printed success, and the plugin simply never appeared in the Plugin
> Manager — no error, no log line, nothing. Behind it sat a second one: with no
> `qgisMaximumVersion`, QGIS derives a ceiling of `3.99` from the minimum and marks the
> plugin *incompatible* on 4.x.
>
> If the plugin ever fails to appear again, **`make where` is the first command
> to run** — it prints every profile root on the machine, which one QGIS has
> actually started in, and where the link currently points. Full account in
> `docs/capture_coverage.md` §4, 26 Aug.

`make deploy` is already done. What remains is launching and clicking.

---

## Part 1 — Sanity check outside QGIS first (30 seconds)

```bash
cd /home/aaryanu/Documents/Course-Project
make test          # everything that needs no QGIS
make demo2         # the Review 2 gate
```

If these are green, every non-QGIS thing is fine, and anything that goes wrong below is
QGIS-side. That is worth knowing before you start debugging a GUI.

---

## Part 2 — Launch QGIS with the plugin

```bash
make deploy        # idempotent; prints "already linked: ..."
make qgis          # flatpak run org.qgis.qgis --profile geoprov-dev
```

`make qgis` uses the **`geoprov-dev` profile**, never your normal one — `RULES.md` §2.4, so
a crash in capture code cannot take out a working QGIS. `tools/deploy.py` refuses to link
into any other profile.

**First launch is a fresh profile**: welcome screen, default toolbars, no saved layout.
That is correct, not a failure.

### 2.1 Turn the plugin on

**Plugins → Manage and Install Plugins…**

1. Open the **Settings** tab *first* and tick **"Show also Experimental Plugins"**.
   `metadata.txt` carries `experimental=True`, so without this the plugin **will not appear
   in the list at all**, even though it is correctly installed. This is the single most
   likely place to get stuck.
2. Go to **Installed**. **GeoProvenance** is listed.
3. Tick its checkbox.
4. While you are here, install **Plugin Reloader** from the *All* tab. Because the plugin is
   a symlink to this repo, editing a file and hitting Reloader picks the change up with no
   restart — there is no deploy step in the edit/reload loop.

### 2.2 What becomes visible the moment you tick it

| Where | What appears |
|---|---|
| **Toolbar** | one new button with the GeoProvenance icon |
| **Plugins menu** | a **GeoProvenance** submenu with **four** items |
| **Panels** | a dock named **GeoProvenance**, docked right, **starting hidden** |
| **Log Messages** | a new **GeoProvenance** tab |

The dock starts hidden on purpose — `plugin.py` calls `self.dock.hide()` so the plugin does
not steal screen space on first load. It is opt-in.

The four menu items (`geoprovenance/plugin.py:_build_actions`):

- **Show GeoProvenance panel** — toggles the dock
- **Start new workflow** — draws a boundary the file paths cannot see (A6)
- **Name this workflow…** — two dialogs: which piece of work, then what to call it
- **Provenance database…** — where the record lives, and the running counts

### 2.3 Open the log before doing anything else

**View → Panels → Log Messages**, then the **GeoProvenance** tab.

A healthy load reads, in order:

```
GeoProvenance loading. Session <uuid>
database ready at /home/.../geoprov-dev/geoprovenance/provenance.db (schema version 1)
```

followed by lines from the three capture channels installing.

If instead you see **"GeoProvenance loaded in a degraded state"**, the reason is in the
lines above it. `initGui` is wrapped so it can never raise into QGIS (`RULES.md` §5.1),
which means a failure here looks like a quiet log line, not a crash dialog — so read the
log rather than waiting for a popup.

> **Expect the hook channel to install and then never fire.** On QGIS 4 the Processing
> post-execution hook mechanism does not exist: the setting is still registered and still
> shows in the options dialog, but nothing reads it back. Measured 24 Aug 2026 —
> `docs/capture_coverage.md` §4. This is a documented finding, **not a fault to debug.**
> The `processing.run` wrapper and the history channel are what capture on this QGIS, and
> on the one path measured so far they caught 4/4.

### 2.4 The panel itself

Click the toolbar button, or **Plugins → GeoProvenance → Show GeoProvenance panel**.

The dock opens on the right and says:

> **GeoProvenance**
> No workflow to show yet.
> *Run a Processing algorithm and its record will appear here.*

**It will keep saying that.** The dock is Person A's shell; the family-tree view and the
audit panel that fill it are Person C's Phase-3 work, through the `set_content` seam in
`geoprovenance/ui/dock.py`. **An empty panel here is the design, not a bug.** The evidence
that capture is working lives in the log, the **Provenance database…** dialog, and the
database file — not in this panel.

---

## Part 3 — Make it capture something, and see the proof

### 3.1 Load a layer

**Layer → Add Layer → Add Vector Layer…**, and pick one of the datasets already committed
to this repo:

```
/home/aaryanu/Documents/Course-Project/qgis_demo/data/roads.shp
/home/aaryanu/Documents/Course-Project/qgis_demo/data/schools.shp
/home/aaryanu/Documents/Course-Project/qgis_demo/data/city_boundary.gpkg
/home/aaryanu/Documents/Course-Project/tests/fixtures/data/sample_points.shp
```

These are written by this repo's own hand-rolled writers, and all of them were verified to
open in QGIS 4.2.1 and GDAL 3.13.3 on 24 Aug 2026.

### 3.2 Run a Buffer from the Toolbox dialog — the row that matters most

**Processing → Toolbox → Vector geometry → Buffer.** Input `roads`, distance `500`, **Run**.

Then check three places, in this order:

1. **Log Messages → GeoProvenance.** A capture line for the run. Two lines here are
   RQ1 evidence and should be copied into `capture_coverage.md` §4:
   - `Toolbox capture: first execution seen via the … branch` — which of the Toolbox's two
     execution paths this algorithm took (threaded, or synchronous for `FlagNoThreading` ones).
   - the line `_on_entry_added` logs on the history channel's first firing, giving the
     **arity and argument types it actually received**.
2. **Plugins → GeoProvenance → Provenance database…** — a deliberately plain-English dialog:

   ```
   Where the record is kept:
   /home/.../geoprov-dev/geoprovenance/provenance.db

   Project: not saved yet
   Watching for jobs: yes

   In this project:
       Jobs written down so far: 1
       Files being tracked: 2

   Everything on this computer:
       Jobs: 7    Files: 9
   ```

   **The counts are scoped to the current project** (since 26 Aug 2026). `File → New`, or
   opening another project, starts a fresh record — the machine total keeps everything, so
   nothing is lost, it just stops being shown.

   Those counts moving 0 → 1 is the whole claim of the project, visible in one dialog with
   no SQL and no code. **"Files being tracked" must not stay at 0.** It did until 26 Aug 2026,
   because the Toolbox was captured only by the history channel, which records that a job
   happened but attaches no files. If you see 0 there after a Toolbox run, the `toolbox`
   channel did not install — check the log.
3. **The database file**, from an ordinary terminal. The Flatpak has host filesystem access,
   so this is a real file at a real path:

   ```bash
   sqlite3 ~/.var/app/org.qgis.qgis/data/QGIS/QGIS4/profiles/geoprov-dev/geoprovenance/provenance.db \
     "SELECT algorithm_id, capture_channel, status, corroborations,
             (ended_at > started_at) AS has_duration FROM activities;"
   ```

   After a Toolbox run expect `capture_channel = 'toolbox'`, `corroborations = 1` (the history
   channel confirming the same job rather than duplicating it) and `has_duration = 1`.

### 3.3 Name the work

Run a **second** algorithm that consumes the buffer output — **Clip**, say — so two jobs
share a file and A6's auto-grouping links them without being told to.

Then **Plugins → GeoProvenance → Name this workflow…**:

- **First dialog** — a dropdown of this session's work, labelled like
  `Untitled workflow  (2 jobs)`. The step count is how you confirm grouping worked, without
  reading any SQL. If it says `(1 job)` twice instead, the two runs were not linked, and
  that is itself a finding worth recording.
- **Second dialog** — type a name. A blank name is dropped rather than stored.

**Start new workflow** pops a confirmation that jobs from here on are recorded separately
even if they reuse the same files, and that everything already written down is untouched.

### 3.4 Fill in the nine open RQ1 rows

Same recipe once per path — run it, read the log, read the counts dialog:

| Row in `capture_coverage.md` §1 | How to drive it |
|---|---|
| Processing Toolbox dialog | §3.2 above |
| Graphical Modeler (whole model) | build a 2-step model, run it — **does it report once, or once per step?** |
| Graphical Modeler (per step) | the same run; inspect the rows written |
| Batch mode | right-click an algorithm → *Execute as Batch Process*, give it 3 rows |
| Algorithm fails mid-run | Buffer with a nonsense distance, or an unwritable output path → must store `status='failed'` (§4.10) |
| User cancels | a slow Buffer on a large layer, then Cancel → must store `status='cancelled'` |
| GDAL/OGR via Processing | `gdal:buffervectors` |
| GRASS via Processing | `grass7:v.buffer` |
| SAGA via Processing | likely not installed on this build — "not installed" is a legitimate recorded result |

Read **`corroborations` from the database**, not the number of log lines: a job seen by more
than one channel is stored once with that column incremented, so it *is* the per-channel
evidence (`capture_coverage.md` §2).

### 3.5 What to send back after each run

To get a row written into `capture_coverage.md` with evidence behind it, paste:

1. the **GeoProvenance log lines** for that run (whole block, including anything that looks
   like noise — the namespace and arity lines are exactly what is missing);
2. the three numbers from **Provenance database…**;
3. the output of the `sqlite3` query in §3.2.

---

## Part 4 — The visual demo

Separate from the live plugin, and the more presentable artefact of the two:

```bash
make qgis-demo        # inputs -> run in QGIS -> layers -> styled project -> verify
make qgis-demo-open   # opens qgis_demo/project/GeoProvenance.qgz
```

Nothing in `qgis_demo/project/` or `qgis_demo/data/derived/` exists yet, so the first run
builds it all. The project opens with **four layer groups**:

1. **What we started with** — 6 roads, 1 city boundary, 14 schools
2. **What QGIS produced** — the four results in order; toggling them one at a time tells the
   story by itself
3. **What we noticed, automatically** — one labelled dot per job, **coloured by which of the
   three channels caught it**; a green rectangle per tracked file, drawn where that file
   actually sits on Earth; a dashed blue box around the auto-grouped workflow
4. **Where the record has gaps** — files we know about but cannot draw, and the machine and
   software it ran on

There is also a printable page under **Project → Layouts**, exported to
`qgis_demo/project/overview.png`.

Because QGIS is available here, every step runs for real, so group 4's "cannot draw" table
should be **empty**. Four rows there means the offline `make qgis-demo-record` path ran
instead of `qgis-demo-run`. Full walkthrough in `qgis_demo/README.md`.

---

## Part 5 — Running the QGIS test suite (optional, and it has a trap)

`make test-qgis` invokes `.venv/bin/python`, which **cannot import QGIS on a Flatpak-only
machine** — it will fail. The 11 lifecycle tests were run on 24 Aug 2026 inside the
sandbox's own interpreter; `pytest` and `pytest-qgis` are not in the Flatpak image, so they
were installed with `python3 -m ensurepip --user` then `pip install --user pytest
pytest-qgis` inside the sandbox (`capture_coverage.md` §4, 24 Aug).

Two warnings that have already cost time once:

- **Never run bare `pytest tests` inside QGIS.** Seven tests fail there and none is a
  defect — they assert the *no-QGIS degradation* path on purpose. Use `make test` outside
  QGIS and the marker-filtered `-m qgis` run inside it.
- Running the icon test inside QGIS **rewrites `geoprovenance/icon.png`**, because zlib
  differs between Python 3.10 and 3.13. Check `git status` afterwards.

---

## Part 6 — When you are done

```bash
make undeploy      # removes the symlink; the captured database stays where it is
```

Or simply untick the plugin. Teardown is structural — every setup step registers its own
undo on a `CleanupStack` that unwinds last-in-first-out (`RULES.md` §5.4) — and a clean
unload logs:

```
GeoProvenance unloaded cleanly
```

Anything else names the step that failed.

---

## Troubleshooting, in the order things actually go wrong

| Symptom | Cause | What to do |
|---|---|---|
| Plugin missing from the Installed list | `experimental=True` in `metadata.txt` | Plugin Manager → **Settings** → tick *Show also Experimental Plugins* |
| Still missing with experimental shown | the link is in a profile root QGIS does not read | **`make where`** — it names every root and which one QGIS uses. Then `make undeploy && make deploy` |
| Listed under an **Invalid** tab, greyed out | `qgisMaximumVersion` missing or too low | QGIS derives `min[0] + ".99"`. `metadata.txt` must declare the ceiling explicitly |
| No **GeoProvenance** tab in Log Messages | the plugin never loaded at all | Check the **Python** tab of Log Messages for an import traceback |
| "loaded in a degraded state" | the store or a channel failed | The reason is the log line just above it; `initGui` cannot raise (§5.1) |
| Counts stay at 0 after a run | that invocation path is not captured | **This is a result, not a bug.** Record it in `capture_coverage.md` §1 |
| The panel is empty | Person C's Phase-3 content does not exist yet | By design — see §2.4 |
| The hook never fires | QGIS 4 removed the mechanism | Known and documented; `run_wrapper` is what carries capture here |
| `make test-qgis` fails | it uses the venv Python, which has no QGIS | Run pytest inside the Flatpak interpreter — see Part 5 |
| Menu items appear twice after a reload | an unload step failed | The failing step is named in the log at CRITICAL |

---

## Where things live

| | |
|---|---|
| The record (desktop) | `~/.var/app/org.qgis.qgis/data/QGIS/QGIS4/profiles/geoprov-dev/geoprovenance/provenance.db` |
| The record (headless script) | `~/.var/app/org.qgis.qgis/data/profiles/default/geoprovenance/provenance.db` — **a different file**; `--profile` is parsed by the QGIS application, not by `QgsApplication` |
| Override it | one QSettings key, `GeoProvenance/database_path` (`RULES.md` §4.8 — exactly one config value) |
| Plugin link | `~/.var/app/org.qgis.qgis/data/QGIS/QGIS4/profiles/geoprov-dev/python/plugins/geoprovenance` |
| Which root is right | `make where` — never assume |
| Generated hook scripts | `<profile>/geoprovenance/hooks/` — written on QGIS 4, never executed by it |
| Findings go here | `docs/capture_coverage.md` |
