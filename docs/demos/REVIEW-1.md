# Review 1 — QGIS ran a job, and we wrote it down automatically

**Runs in:** about 2 seconds · **You need:** a terminal. Nothing else — not even QGIS.

---

## 1. In one sentence

QGIS finished a piece of work, nobody told our software anything, and afterwards there was a complete written record of what was done, to which file, with which settings.

## 2. Since the project started

| Before | After |
|---|---|
| Nothing was kept. Close QGIS and there was no record of what had been done to a map file. | Every job QGIS finishes is written down by itself, as it happens. |
| You had to remember, or write notes by hand, and notes go stale. | The record is made by watching, so it cannot disagree with what actually happened. |
| — | We watch in two places at once, and check we never write the same job down twice. |

## 3. Why it matters

Somebody hands you a map file. Which file did it come from? What was done to it, in what order, with what settings? Was the original data the same then as it is now?

Today there is no way to answer that, so people answer it from memory — and a year later, nobody remembers. This step removes the remembering. The record writes itself while the work is being done.

That matters most when someone tries to *repeat* the work: a report that cannot be redone is a report nobody can check.

## 4. Run it

Copy this, paste it into a terminal, press Enter:

```bash
cd Course-Project
source .venv/bin/activate && python demos/review1.py
```

## 5. What you should see

```
════════════════════════════════════════════════════════════════
  GeoProvenance — Review 1 Demo
  "QGIS ran a job and we wrote it down automatically."
════════════════════════════════════════════════════════════════

BEFORE this phase:  Nothing was kept. Close QGIS and there was no record of what had been done.
AFTER  this phase:  Every job QGIS finishes is written down by itself, as it happens.

[1/5] Starting with a completely empty notebook........... OK
[2/5] Nobody tells us anything — QGIS just finishes a 'Buffer' job.. OK
[3/5] Watching in two places at once, but never writing it down twice.. OK
[4/5] Checking every piece of the record landed........... OK
[5/5] Reading it back in plain English.................... OK

  Someone ran   : Buffer
  On the file   : roads.shp
  Which held    : 1,204 shapes
  Producing     : buffered_roads.shp
  At            : 18 Aug 2026, 2:31 pm
  Took          : 0.5 seconds
  Settings used : distance = 500 m, corner detail = 5, merged = no
  On            : Linux-7.1.8-…, Python 3.10.14

  Nobody typed any of that in. It was noticed and written down
  on its own.
  We also spotted the same job a second time, from a second
  place we watch — and correctly kept one record, not two.
  The whole record so far takes 4.0 KB.

WHAT WE STILL CAN'T DO:
  • We only notice work done with QGIS's built-in tools.
    Editing a shape by hand on the map is invisible to us, on
    purpose.
  • This ran without QGIS open. The next step is watching it
    happen inside a real QGIS window — that has not been
    proved yet.

✅ 5 of 5 checks passed.
```

The line beginning `On :` will show *your* computer, not the one above. That is the point — it is measured, not typed in.

**What each line means**

- **"Buffer"** is one of QGIS's built-in tools. It draws a zone of a given width around things on a map — around roads, say, to find everything within 500 metres of one.
- **"Someone ran: Buffer"** — we were not told this. Our software noticed by itself, after the job was already finished.
- **"On the file / Producing"** — which file went in and which came out. This is the link that lets you trace any result back to where it came from.
- **"Settings used"** — the exact choices. Re-doing the work later needs these, and they are the first thing people forget.
- **"1,204 shapes"** — how much was in the file. If it says 1,204 today and 900 next month, the file changed underneath you.
- **"On"** — which computer and which software versions. The same job on different versions can give different answers.
- **"4.0 KB"** — the whole record. Keeping this costs essentially nothing.

**Step 3 is worth pausing on.** We watch for work in two places at once, in case one of them misses something. That means the same job often gets spotted twice. The record still shows it once — we recognise it as the same job and note the second sighting rather than duplicating it. How often each watcher catches something the other misses is one of the numbers this project sets out to measure.

## 6. Live version — now available

QGIS was installed on 24 August 2026, and it has now run this for real. One command:

```bash
make qgis-demo
```

QGIS runs four jobs over real data, our code records them while they happen, and the
record is turned into a map you can open:

```bash
make qgis-demo-open
```

If you would rather click than type, the plugin itself is installed and ready:

1. `make deploy`
2. `make qgis`
3. **Plugins → Manage and Install Plugins → Installed →** tick **GeoProvenance**
4. **View → Panels → Log Messages →** the **GeoProvenance** tab, so you can watch it work
5. Run any tool from the Processing Toolbox
6. **Plugins → GeoProvenance → Provenance database…** shows the count going up

One honest caveat before you do: the QGIS that could be installed here is a **newer
version than this project targets**, and on that newer version the main way we planned to
watch for work no longer exists. A backup way caught everything — see section 7.

## 7. What this still can't do

- **It has now run inside QGIS — but not the QGIS we are building for.** The version obtainable on this machine is newer than the one this project targets, and the two are far enough apart to matter. On the newer one, **the main way we planned to watch for work has been taken out of QGIS entirely.** The setting is still there in the options dialog; nothing behind it does anything any more. We only found that out by looking, which is the point of looking. A second way of watching caught all four jobs, so nothing was missed — but the claim "we watch QGIS the way we designed to" is, on that version, false, and we say so.
- **We only see work done with QGIS's built-in tools.** Editing a shape by hand on the map is invisible to us. That is a deliberate boundary, not an oversight — a different QGIS add-on already covers hand edits, and trying to cover everything is how a three-month project becomes a two-year one.
- **We still do not know which ways of running a job we catch.** QGIS can run the same tool from a toolbox, from a script, from a batch list, or from a visual model builder. One of those four — from a script — has now been measured, and we caught all of it. The other three need somebody sitting in front of QGIS clicking, and until that happens they are open. Measuring this is one of the project's actual results, not a detail to sort out quietly.
- **No fingerprints yet.** We record *which* file was used, but not yet a check that the file is still the same file. That is Person B's part, coming next.
- **Nothing is drawn on screen.** The record exists but there is no picture of it yet. That is Person C's part.

## 8. Questions you might be asked

**Q. If QGIS is not running, what exactly did this demo prove?**
A. It proved the record-keeping half: given a finished job, we correctly work out what was read, what was made, and what settings were used, and we store it so it can be read back. Splitting it this way was deliberate — it means most of the system can be tested on any laptop, including in this room. The other half, QGIS handing us the job, has since been tested too; section 6 has the command and section 7 has the catch.

**Q. You said a way of watching had been removed from QGIS. Isn't that fatal?**
A. It would have been, if we had only built one. We built three, because we did not know which would work — and that turned out to be the right call rather than a lucky one. On the newer QGIS the primary way is gone and a backup caught every job. That result is worth more to the write-up than a clean run would have been: it is evidence that watching one place is not safe.

**Q. Does this slow QGIS down?**
A. Measuring that is one of the project's four research questions, with a target of under 5%. Writing the record took a few thousandths of a second here, but a proper measurement with real data comes later.

**Q. What if your record-keeping crashes in the middle of someone's work?**
A. It cannot affect them. Every piece of the watching code is wrapped so that a failure on our side is written to a log and otherwise ignored — the user's job finishes normally. We would rather lose one record than break somebody's actual work. There is a test for exactly this.

**Q. Why "two places at once"? Isn't one enough?**
A. We do not yet know whether the main one catches everything, and finding out is part of the research. Watching twice means that if one misses a job, the other still records it — and comparing the two tells us how good each one is.

---

*Governed by `RULES.md` §7. Demo script: `demos/review1.py`.*
