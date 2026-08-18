# Demo Template — copy this to `REVIEW-1.md`, `REVIEW-2.md`, `FINAL.md`

> **Audience:** someone who has never used QGIS and has never used git.
> **Governed by:** `RULES.md` §7. Before publishing, check every rule §7.1–§7.12.
> **Delete this box and all `<!-- guidance -->` comments before the review.**

---

# Review N — <the one-line claim, in plain words>

**Date:** <date> · **Runs in:** about 1 minute · **You need:** a terminal. Nothing else.

---

## 1. In one sentence

<!-- What does this review prove? One sentence, no jargon. Not "the capture engine
     persists normalized events" — instead: "QGIS ran a job, and we wrote down what
     it did, without anyone telling it to." -->

## 2. Since last time

<!-- The heart of the demo. Plain-English bullets of what changed since the previous
     review. For Review 1, "since the project started". Compare capabilities, not code.
     Good:  "Before, the record was written by hand for the demo. Now the software
             writes it itself, the moment QGIS finishes a job."
     Bad:   "Implemented ProvenanceCaptureEngine singleton with dual-channel dedup." -->

| Before this review | After this review |
|---|---|
| <what was not possible> | <what is possible now> |
| | |

## 3. Why it matters

<!-- Two or three sentences on the real-world problem. Anchor it in something a
     non-specialist recognises: a colleague hands you a map file and you have no idea
     which files it came from, what settings were used, or whether the source data has
     changed since. That's the problem. This is the step that fixes part of it. -->

## 4. Run it

Copy this, paste it into a terminal, press Enter:

```bash
cd <project folder>
source .venv/bin/activate && python demos/reviewN.py
```

<!-- ONE block. Includes activation. Nothing to edit, no paths to fill in.
     If it needs a second paste, it is not finished (RULES.md §7.1). -->

## 5. What you should see

<!-- Paste the real output verbatim, so the reviewer can compare line by line.
     Format is fixed by RULES.md §7.7. -->

```
════════════════════════════════════════════════
  GeoProvenance — Review N Demo
  "<the claim>"
════════════════════════════════════════════════

BEFORE this phase:  <one plain sentence>
AFTER  this phase:  <one plain sentence>

[1/3] <plain description of the step>...      OK
[2/3] <plain description of the step>...      OK
[3/3] <plain description of the step>...      OK

  Someone ran : Buffer
  On the file : roads.shp
  Produced    : buffered_roads.shp
  At          : 18 Aug 2026, 2:31 pm
  Settings    : distance = 500 m

WHAT WE STILL CAN'T DO:
  <one honest limitation>

✅ 3 of 3 checks passed.
```

**What each line means:**

<!-- Walk through the output in plain words. One short line per interesting bit.
     e.g. "'Someone ran: Buffer' — Buffer is a QGIS tool that draws a zone around
     things on a map. We didn't tell our software that Buffer had been used; it
     noticed by itself." -->

## 6. Live version *(optional — see `RULES.md` §7.12)*

<!-- Only if attempting the live QGIS act. Numbered, one action per line, written
     for someone who has never opened QGIS. Name the exact menu items.
     If this fails on the day: say so plainly, run section 4, carry on. -->

1. Open QGIS.
2. …
3. …

**Expected:** <what appears on screen, in plain words>

## 7. What this still can't do

<!-- REQUIRED, not optional (RULES.md §7.10). At least one honest limitation.
     These are research results, not weaknesses — they become the paper's
     limitations section. -->

- <limitation, plainly stated, with one clause on why>

## 8. Questions you might be asked

<!-- Three or four likely reviewer questions with short, honest answers. -->

**Q. <question>**
A. <answer in two sentences, no jargon>

---

<!-- ── PRE-REVIEW CHECKLIST — verify all of these, then delete this block ──

  [ ] §7.1  One command. One paste. Nothing to edit.
  [ ] §7.2  Script wipes and rebuilds its own database — runs twice in a row identically.
  [ ] §7.3  Ran with no QGIS installed / not running.
  [ ] §7.4  "Before and after" is stated explicitly, in one sentence each.
  [ ] §7.5  Zero banned words. Re-read the output loud — would a non-GIS friend follow it?
  [ ] §7.6  Reviewer needs no git, no SQL, no QGIS clicks.
  [ ] §7.7  Dates human-formatted. Steps numbered. Exit code correct. Under 60 seconds.
  [ ] §7.10 At least one honest limitation stated.
  [ ] §7.11 Rehearsed from a fresh copy of the project, in a clean folder, a day early.
  [ ] §7.9  Output pasted in section 5 matches what the script prints TODAY.

──────────────────────────────────────────────────────────────────────── -->
