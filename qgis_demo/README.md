# The visual demo — seeing what was recorded

This folder turns the record GeoProvenance keeps into a QGIS project you can open,
click around, and understand without reading any code.

Everything here is **demo scaffolding, not plugin code.** It lives outside
`geoprovenance/` on purpose: `RULES.md` §1.1 lists exactly what the plugin package
is, and drawing maps is not on that list.

---

## Build it

```bash
make qgis-demo
```

That runs five steps in order. Three of them need no QGIS at all:

| Step | What it does | Needs QGIS? |
|---|---|---|
| `qgis-demo-inputs` | Writes the three starting datasets | no |
| `qgis-demo-run` | Runs the four steps in a real QGIS, which captures them | **yes** |
| `qgis-demo-layers` | Turns the record into map layers | no |
| `qgis-demo-project` | Styles them into a QGIS project and a printable page | **yes** |
| `qgis-demo-verify` | Reopens the project and checks every layer | **yes** |

Then:

```bash
make qgis-demo-open
```

**On a machine with no QGIS**, swap the one step that needs it:

```bash
make qgis-demo-inputs qgis-demo-record qgis-demo-layers
```

`qgis-demo-record` puts the same four steps through the same capture code with no QGIS
anywhere. It writes the record but not the output files, so the map will show three
files instead of seven and list the other four as "not on this computer any more" —
which is the truth, and is exactly what that part of the map is for.

---

## What the demo shows

The workflow answers one question: **which schools are within about 500 m of a main
road, inside the city boundary?**

1. Draw a band about 500 m wide either side of every road.
2. Cut those bands back to the city boundary.
3. Keep only the schools that fall inside those bands.
4. Merge the overlapping bands into one road corridor.

Fourteen schools go in; five come out.

Nobody wrote any of that down. QGIS ran the four steps and the record below was made
while the work was happening.

---

## Walking someone through the project

Open `project/GeoProvenance.qgz`. Four groups, in order, top to bottom.

**1 — What we started with.** Six roads, one city boundary, fourteen schools. Ordinary
data, the kind anybody would begin with.

**2 — What QGIS produced.** The four results, one per step, in the order they were made.
Turn them on one at a time and the workflow tells itself: bands appear around the roads,
get trimmed to the boundary, the schools thin out from fourteen to five, and the bands
merge into a single corridor.

**3 — What we noticed, automatically.** This is the part that is new.

- **Jobs QGIS ran** — one dot per step, labelled `Step 1: Buffer` and so on, sitting on
  the middle of what that step produced. **The colour is which of our three ways of
  watching actually noticed it.** Click one and the table says what it read, what it
  created, when it started, how long it took, and how many times we saw it confirmed.
- **Files we are keeping track of** — a green rectangle around each file, drawn where
  that file actually is on Earth. Green means it is still on this computer. Click one for
  its name, its type, its size, and which version of it this is.
- **One piece of work** — the dashed blue box around everything the four steps touched.
  Nobody told us those four jobs belonged together; they were grouped automatically.

**4 — Where the record has gaps.** Two tables with no map presence, because being honest
about what is missing matters more than a tidy map:

- **Files we know about but cannot draw** — and, in plain words, why not. Empty after a
  full QGIS run; four rows after an offline one.
- **The computer and software it ran on** — which QGIS, which Python, which operating
  system. This is what makes "can this still be reproduced?" answerable later.

There is also a printable page (**Project → Layouts**) with the map, a legend and the
counts, exported to `project/overview.png` — for a slide, or for a room where the
projector will not talk to your laptop.

---

## How it is put together

```
scenario.py       the workflow, defined once — the roads, the schools, the four steps
make_inputs.py    writes the three starting datasets
run_in_qgis.py    runs the four steps inside QGIS, which captures them   (needs QGIS)
replay.py         records the same four steps with no QGIS               (no QGIS)
export_layers.py  the record -> map layers                               (no QGIS)
build_project.py  map layers -> a styled QGIS project                    (needs QGIS)
verify_project.py reopens the project and checks it                      (needs QGIS)

geopkg.py         a GeoPackage writer, standard library only
shapefile.py      a Shapefile writer, standard library only
footprints.py     works out where a file sits on Earth, standard library only
```

Two deliberate choices are worth knowing about.

**Nothing here adds a dependency.** No GDAL, no fiona, no geopandas. `RULES.md` §2.2
keeps them out, and the demo has to rebuild on a machine with no GIS stack. The
GeoPackage and Shapefile writers are hand-rolled against the OGC and ESRI specifications,
the same way `tests/fixtures/_minifiles.py` already does it. That file is *not* imported
or edited here — it is part of the frozen fixture set Person B and Person C consume.

**The part that can be wrong imports no QGIS.** `export_layers.py` decides what goes
where, and it runs anywhere, which means it can be checked anywhere. `build_project.py`
only decorates, and it uses QGIS's own API to write the project file so that a styling
mistake fails on this machine rather than looking wrong in a review room. That split
mirrors how `capture/` is already arranged.

---

## Where the coordinates come from

**The record stores no geometry.** It knows a file's path, its format and its coordinate
system — there is no extent column, no bounding box, no centroid, and adding one would be
a breaking change to a schema Person B and Person C already build against
(`RULES.md` §3.4).

So every rectangle on the map is worked out at export time, by opening the file the
record points at: a Shapefile's bounding box lives in bytes 36–67 of its header, a
GeoPackage's in its `gpkg_contents` table. Both are readable with the standard library.

If the file is gone, there is no rectangle, and it goes in the "cannot draw" table with
the reason. A blank space on a map is never the only evidence that something is missing.

---

## What this demo does *not* show

Stated plainly, because a reviewer who finds an unmentioned gap trusts the mentioned
results less (`RULES.md` §7.10):

- **No fingerprints.** The map says a file is still on this computer. It does not say
  whether the contents have changed since. That check is Person B's.
- **No "this file came from that file".** Files and jobs are drawn; the lines between
  them are not. Working out which file was derived from which is Person B's, and drawing
  the family tree is Person C's (`RULES.md` §1.2).
- **No score.** Nothing here says how reproducible the workflow still is. That is
  Person C's audit engine.
- **A GeoTIFF gets no rectangle.** Reading a raster's georeferencing without GDAL means
  parsing TIFF tags and the GeoKey directory — a lot of code, and the alternative is the
  dependency §2.2 exists to refuse. Rasters are listed as "we would need extra software
  to place this one". The demo workflow is all vector, so it does not come up here.
- **The job dots are nudged apart.** Each step's output covers nearly the same ground as
  the last, so the four dots would land on top of each other. They are fanned by a fixed
  step to stay readable, which moves each one slightly off the exact centre of what it
  produced.
- **This ran on QGIS 4.2.1, not the QGIS 3.34 the project targets.** See
  `docs/capture_coverage.md` for why, and for what that does and does not let you claim.
