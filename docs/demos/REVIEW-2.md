# Review 2 — A whole piece of work, captured in the right order

**Runs in:** under a second · **You need:** a terminal. Nothing else — not even QGIS.

---

## 1. In one sentence

Four jobs were run in QGIS one after another, nobody said they belonged together, and afterwards there was one record showing them as a single piece of work, in the order they actually happened.

## 2. Since last time

| Before (Review 1) | After (now) |
|---|---|
| We could write down one job. Four jobs were four unrelated notes with nothing joining them. | The four are recognised as **one piece of work**, named after what it does, with the steps in order. |
| Nothing worked out that the file one job made was the file the next job opened. | That is exactly how the jobs are tied together — by the files they hand to each other. |
| A piece of work that split in two — one job making two files that go different ways — had no way of being described. | The split is followed, and both halves stay in the same piece of work. |
| A job that failed was a gap. | A job that failed is written down as a job that failed. A record that quietly omits the failures is not a record. |
| The computer and software it ran on was noted per job. | One note per setup, shared by every job that ran on it. |
| — | You can draw the line yourself: **"Start new workflow"** and **"Name this workflow"** are in the menu. |

## 3. Why it matters

Real map work is never one job. It is: widen the roads, pull out the urban ones, merge them, find their centres — four steps, each feeding the next, often over an afternoon, often interrupted.

The question people actually need answered is not "what did this one job do?" but "how was this final file made?" Answering that means knowing which jobs belonged together and what order they ran in. Until now that lived in somebody's head, or in a filename like `final_v3_REAL.shp`.

This step works it out without being asked. Nobody has to remember to press "start recording", and nobody has to name anything for the record to be correct.

## 4. Run it

Copy this, paste it into a terminal, press Enter:

```bash
cd Course-Project
source .venv/bin/activate && python demos/review2.py
```

## 5. What you should see

```
════════════════════════════════════════════════════════════════
  GeoProvenance — Review 2 Demo
  "A whole 4-step workflow was captured, in the right order, with nothing missing."
════════════════════════════════════════════════════════════════

BEFORE this phase:  We could write down one job at a time, but nothing tied them together — four jobs were four unrelated notes.
AFTER  this phase:  The four jobs are recognised as one piece of work, in the order they happened, on their own.

[1/6] Starting with a completely empty notebook........... OK
[2/6] Four jobs run in QGIS, one after another............ OK
[3/6] Watching in two places, but writing it down once.... OK
[4/6] The four recognised as one piece of work, in order.. OK
[5/6] A job that went wrong is written down too........... OK
[6/6] One note about the computer, not one per job........ OK

  This piece of work  : Buffer to Centroids (4 steps)
  Step 1              : Buffer, which made points_buffered.shp
  Step 2              : Extract by attribute, which made urban.shp and not_urban.shp
  Step 3              : Dissolve, which made urban_dissolved.gpkg
  Step 4              : Centroids, which made not_urban_centroids.shp
  Started             : 8 Aug 2026, 10:05 am
  The four took       : 31 seconds
  Ran on              : QGIS 3.40.0, Ubuntu 24.04
  Also on record      : 1 job that went wrong, in other work that day
  An empty notebook   : 128.0 KB
  With all this in it : 128.0 KB

  Nobody named that piece of work, drew a line around it, or
  put the steps in order. The four jobs were tied together by
  the files they passed to each other.
  Step 2 made TWO files, and steps 3 and 4 each took a
  different one. That split is why this is a piece of work and
  not just a list.
  Five jobs, and the notebook is not one byte larger — they
  fitted in the room it already had. What it keeps is a
  description of the work, never a copy of the data, so it
  stays this small however large the files are.
  You can also draw the line yourself: 'Start new workflow' in
  the menu says the next job begins something separate, even
  if it opens the same file.

WHAT WE STILL CAN'T DO:
  • We tie jobs together when they pass files to each other
    inside one sitting at QGIS. Two unrelated pieces of work
    that happen to open the same file get treated as one —
    that is what the 'Start new workflow' button is for.
  • QGIS has now run the real thing and we did record it — but
    on a newer QGIS than the one we are building for. On that
    newer one, the main way we planned to watch has been
    removed; a backup way caught everything. How the version
    we target behaves is still untested.

✅ 6 of 6 checks passed.
```

**What each line means**

- **"This piece of work: Buffer to Centroids (4 steps)"** — nobody typed that name. It was written from what the four jobs actually are, so it stays honest. If you would rather call it "Urban centres", the menu lets you, and your name is kept from then on.
- **"Step 1 … Step 4"** — the order the jobs really ran in, not the order they happened to be noticed in. That distinction matters: the two places we watch do not always report in the same order.
- **"Step 2 … made urban.shp and not_urban.shp"** — this is the split. One job made two files; step 3 took one of them and step 4 took the other. A record that could only describe a straight line would have to drop one of those two halves.
- **"Also on record: 1 job that went wrong"** — a failed job is kept, marked as failed. If failures were dropped, an honest question like "did anyone try this and give up?" would have no answer, and the count of what we noticed would flatter itself.
- **"An empty notebook / With all this in it"** — both 128 KB. Five jobs fitted in the room the blank notebook already had. What is kept is a description of the work, never a copy of the data, which is why this holds however large the map files are.

**Step 3 is worth pausing on.** We watch for work in two places at once, in case one misses something. In the run above, one of the four jobs was reported by both. The record still shows four jobs — the second sighting is recognised as the same job and counted, not written down again. How often each watcher catches something the other misses is one of the numbers this project sets out to measure, and this is where that count comes from.

## 6. Live version — now available

QGIS was installed on 24 August 2026. One command runs four real jobs, records them as
they happen, and builds a map of the result:

```bash
make qgis-demo
make qgis-demo-open
```

The map has four groups, top to bottom, and they tell the story in order: what we started
with, what QGIS produced, **what we noticed automatically**, and where the record still
has gaps. In the third group each job is a dot coloured by *how* we came to notice it, and
each file is a rectangle drawn where that file actually sits on Earth. Click anything for
its details. `qgis_demo/README.md` is the walkthrough.

The menu actions described in section 2 now load in a real QGIS and their teardown is
tested there — eleven checks covering load, unload, reload and leaving no trace behind,
none of which had ever been executed before that date. Clicking them by hand is still
outstanding, and this document does not pretend otherwise.

## 7. What this still can't do

- **QGIS has now called us — on a newer QGIS than we are building for, where the main way we planned to watch turned out to be gone.** It is still listed in QGIS's own settings; nothing behind it runs any more. A second way of watching caught all four jobs, so the record was complete, but "we watch QGIS the way we designed to" is false on that version and we are not going to write it as though it were true. How the version we actually target behaves is untested, because it could not be installed.
- **Jobs are tied together by the files they share, within one sitting at QGIS.** Two genuinely unrelated pieces of work that both happen to open `roads.shp` are treated as one. "Start new workflow" exists precisely for that, but it needs a person to press it — we do not guess.
- **A job that touches no files at all stands alone.** Sometimes that is right and sometimes it is not; on the evidence available there is nothing to link it to, and inventing a link would be a guess dressed up as a record.
- **We still do not know which ways of running a job we catch.** Toolbox, script, batch list, visual model builder. One of the four — from a script — is now measured, and we caught all of it. The other three need a person in front of QGIS, and measuring them is one of the project's actual results.
- **No fingerprints, and nothing drawn on screen yet.** Checking a file is still the same file is Person B's part; the picture of how the files relate is Person C's. Both build on what this step now records.

## 8. Questions you might be asked

**Q. How do you know the four jobs belong together? Couldn't that be a coincidence?**
A. Two things have to hold: they happened in the same sitting at QGIS, and they pass files to each other — the file one job made is the file the next one opened. A coincidence would need both. It can still be wrong, and section 7 says exactly how; that is why there is a button to correct it.

**Q. What happens if I run a fifth job an hour later?**
A. If it opens a file from this piece of work, it joins it and the order is worked out again from scratch. That recalculation is the point: whether two jobs belong together can only be known once both exist. If you would rather it started something new, press "Start new workflow" first.

**Q. Why keep a job that failed?**
A. Two reasons. It is part of what actually happened, and a record that silently drops failures is a record that flatters itself. And separately, one of this project's results is "out of the jobs QGIS ran, how many did we notice?" — dropping the failures would make that number look better than it is.

**Q. You wrote down one note about the computer for five jobs. What if I upgrade QGIS halfway through?**
A. Then it is a different setup, and it gets its own note; jobs after the upgrade point at that one. The note is shared only while nothing about the setup has changed — which is why the demo above has two of them, one per recorded machine.

**Q. Did any of this need me to open a database or type a command?**
A. No. The four jobs, the order, the split, the name, and the note about the computer were all worked out from watching. The only command in this document is the one in section 4.

---

*Governed by `RULES.md` §7. Demo script: `demos/review2.py`.*
