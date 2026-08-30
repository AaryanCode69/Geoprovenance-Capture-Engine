# The workflow section — a family tree of files, and whether the work still holds

**Runs in:** under a second · **You need:** a terminal. Nothing else — not even QGIS.

---

## 1. In one sentence

A whole piece of work is drawn as a family tree of the files it touched, and every
starting file is checked to see whether it is still there and still the same — so
we can say, with a number, whether the work could be run again today.

## 2. Since last time

| Before this review | After this review |
|---|---|
| We could list the jobs QGIS ran, in order. | We can show how the *files* relate — which file came from which. |
| The record said "this job read that file". | It also says "this file came from that file", worked out on its own. |
| Nothing checked whether the record still described reality. | Every starting file is looked at again and compared with what it held. |
| No way to say whether work could be repeated. | A number out of 100, with the reason for every point lost. |
| Nothing to look at inside QGIS. | A panel in QGIS drawing the same family tree, in colour. |

Three things had to be built for this, and they were not small: working out which
file came from which; the five-part check and its report; and the arrangement of
the picture. The first belongs to the person doing the record-keeping side, the
other two to the person doing the visual side.

## 3. Why it matters

The point of keeping a record of where a file came from is to be able to trust it
later. A list of jobs does not do that. Two questions get asked about any piece of
analysis months after it was done — *where did this file actually come from?* and
*could I run this again and get the same answer?* — and until now we could answer
neither.

The second question is the harder one, and it is the one nobody else's tool
answers at all. A file can quietly change after the work was done: someone edits a
column, someone re-saves it, someone moves it. Nothing warns you. The check in
this review notices, and says which file and what changed about it.

It is deliberately careful about the difference between *"we looked and it is
fine"* and *"we could not look"*. Three of the five checks need QGIS itself
running, and on a laptop with no QGIS they say **"we cannot tell"** rather than
quietly counting as a pass. A check that scores full marks for not having run is
worse than no check at all, because it reads as reassurance.

## 4. Run it

```bash
cd <project folder>
source .venv/bin/activate && python demos/workflow.py
```

Nothing else. No QGIS, no internet, no files to download, no settings to change.
It builds its own workspace from scratch every time and deletes it first, so it
cannot pass because of anything left over from last time.

## 5. What you should see

```

════════════════════════════════════════════════════════════════
  GeoProvenance — Review of the Workflow Section Demo
  "A whole piece of work, drawn as a family tree of files, with an honest answer to whether we could still run it today."
════════════════════════════════════════════════════════════════

BEFORE this phase:  We could list the jobs QGIS ran, but not show how the files relate, and not say whether the work still holds up.
AFTER  this phase:  The files are drawn as a family tree, and every starting file is checked to see if it is still there and still the same.

[1/7] Setting out a clean workspace with real files in it.. OK
[2/7] Replaying 4 jobs through the software that watches QGIS.. OK
[3/7] Working out which file came from which.............. OK
[4/7] Drawing the family tree............................. OK
[5/7] Checking whether we could still run it today........ OK
[6/7] Changing one of the starting files behind its back.. OK
[7/7] Checking again — and noticing....................... OK
  The family tree, read top to bottom — each file sits under
  the job that made it:

    sample_points.shp
       Buffer
          points_buffered.shp
             Extract by attribute
                urban.shp
                   Dissolve
                      urban_dissolved.gpkg
                not_urban.shp
                   Centroids
                      not_urban_centroids.shp
    sample_areas.gpkg
       Dissolve
          urban_dissolved.gpkg


  The work       : Buffer to Centroids (4 steps)
  Jobs noticed   : 4 of 4
  Files tracked  : 7
  Links found    : 6 — each one 'this file came from that file'
  Started        : 8 Aug 2026, 10:05 am
  First job      : Buffer on sample_points.shp
  Score before   : 100 out of 100
  Then we edited : sample_points.shp
  Score after    : 89 out of 100 — and it named the file we touched

  Before the change:

    Could we run 'Buffer to Centroids (4 steps)' again today?

      yes  the files it started from are still there — 4 of 4 jobs
      yes  those files still hold what they held — 4 of 4 jobs
      ?  QGIS still has the tools it used — we cannot tell without QGIS
      ?  QGIS is close enough to the version it ran on — we cannot tell without QGIS
      ?  the settings still make sense to those tools — we cannot tell without QGIS

    Score: 100 out of 100 — we could almost certainly run this again and get the same answer.

  After changing one starting file — nobody told the software:

    Could we run 'Buffer to Centroids (4 steps)' again today?

      yes  the files it started from are still there — 4 of 4 jobs
      no   those files still hold what they held — 3 of 4 jobs
           sample_points.shp — The shapes in this file are unchanged, but the information attached to them was edited.
      ?  QGIS still has the tools it used — we cannot tell without QGIS
      ?  QGIS is close enough to the version it ran on — we cannot tell without QGIS
      ?  the settings still make sense to those tools — we cannot tell without QGIS

    Score: 89 out of 100 — we could almost certainly run this again and get the same answer.
    But 1 of the checks found something — read the lines marked 'no' above before trusting the number.


WHAT WE STILL CAN'T DO:
  • 3 of the 5 checks need QGIS itself running, so on this
    machine they say 'we cannot tell' rather than guessing.
    The score is worked out over the checks that did run.
  • The family tree is printed here, not drawn. The drawn one
    lives in the QGIS panel, which needs QGIS — that is the
    optional second act.
  • One edited starting file costs only its share of the
    score, so the number falls further the more of the work is
    affected. Read the named file, not just the number.
  • QGIS did not really run these four jobs: they are a
    recording, and the files were written by the demo so the
    checks had something real to read. Everything after that
    point is the shipping software.

✅ 7 of 7 checks passed.

```

**What each line means:**

- **Steps 1 and 2** — the demo lays out a handful of real, small files, then
  replays four recorded jobs through the same code that watches QGIS. The jobs are
  a recording; everything that happens to them afterwards is the real software.
- **Step 3** — nobody told it which file came from which. It worked out six such
  links by looking at what each job read and what each job wrote.
- **Step 4** — the family tree. Read it top to bottom: each file sits underneath
  the job that made it. Notice that `sample_areas.gpkg` appears on its own at the
  bottom — it is a second starting file, and `Dissolve` read both it and
  `urban.shp`, so it shows up under both branches.
- **Step 5** — everything checks out: 100.
- **Step 6** — the demo then edits one of the starting files behind the software's
  back. This is the part that matters. Nobody records the change, nobody is told.
- **Step 7** — the check runs again and notices. The score falls to 89, and it
  names `sample_points.shp` and says what changed about it: the shapes are the
  same, the information attached to them was edited.

**The one to pause on is the very last line of the report.** The score is still
89, which sounds fine, because one changed file is only worth its share of the
total. So the report refuses to let the number stand on its own and says: *one of
the checks found something — read the lines marked "no" before trusting the
number.* A score that quietly reassures you is the failure this whole layer exists
to prevent.

## 6. Live version — the panel in QGIS

The family tree above is printed. The same arrangement is drawn, in colour, in a
panel inside QGIS: files as rectangles, jobs as circles, and each file coloured by
what the check found — green for unchanged, amber for changed, red for gone.

```bash
make deploy && make qgis
```

Then turn GeoProvenance on in the plugin list, open its panel from the toolbar,
pick a piece of work, and press **"Check it still holds"**.

Inside QGIS all five checks run, not two — QGIS is there to be asked whether it
still has the tools and whether the settings still make sense.

This is the optional second act. If it does not work on the day, the scripted run
above has already shown everything that matters.

## 7. What this still can't do

- **Three of the five checks need QGIS.** Without it, they report "we cannot tell"
  and the score is worked out over the two that did run. Honest, but partial.
- **One changed file costs only its share of the score.** A high number with a
  finding under it is possible, which is why the report says so out loud. The
  number is a summary, not a verdict.
- **QGIS did not really run the four jobs in the scripted demo.** They are a
  recording, and the files were written by the demo so the checks had something
  real to read. The live act above is where QGIS really runs.
- **The panel has been built but not yet driven by hand in QGIS by anyone other
  than its author.** Treat the live act as unproven until it has been.
- **We only notice work done with QGIS's built-in tools.** Editing a shape by hand
  on the map is invisible to us, on purpose.

## 8. Questions you might be asked

**"How does it know which file came from which? Did someone type it in?"**
No. Each job records what it read and what it wrote. If a job read A and wrote B,
then B came from A. Where a job read two files and wrote one, the result is
recorded as coming from *both* — which matters, because changing either one would
change the answer.

**"The score went from 100 to 89. Is 89 good?"**
On its own, the number says "probably fine". But it found something specific, and
the report says which file and what changed about it. Read the finding, not the
number. We chose the bands ourselves — above 85 we call it high — and that choice
is ours, not a standard.

**"What if a file is just re-saved and not actually edited?"**
That is handled deliberately, and it is a harder problem than it sounds. Re-saving
a file in a different version of the software changes it byte for byte while the
data inside is identical. Reporting that as a change would cry wolf. So several
different things about each file are recorded — its shapes, its columns, the
information attached — and they are read together. A re-save counts as unchanged.

**"Why do three checks say 'we cannot tell'?"**
They need to ask QGIS whether a tool is still installed and whether its settings
are still accepted, and this demo runs without QGIS on purpose so it works on any
machine. We could have counted them as passes. We did not, because a check that
awards itself full marks for not running is worse than no check.

**"Could someone else's tool do this?"**
The nearest existing thing records which file came from which, inside one file
format, and stops there. None of them check whether the record still describes
reality, and none of them put a number on it.

---

*Governed by `RULES.md` §7. Demo script: `demos/workflow.py`. Not one of the three
graded gates — see the note at the top of that file.*
