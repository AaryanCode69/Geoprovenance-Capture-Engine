"""The workflow section, end to end — capture, family tree, and a score.

    Claim: "A whole piece of work, drawn as a family tree of files, with an
            honest answer to whether we could still run it today."

Run it:
    source .venv/bin/activate && python demos/workflow.py

Which gate is this?
    None of the three. RULES.md §7 defines exactly three (Review 1, Review 2,
    Final), and this is not one of them: the Final gate's claim ends "...and
    here is what it costs", and the RQ1/RQ2 numbers do not exist yet, so filling
    demos/final.py with this would make it claim something untrue. This is the
    act for the workflow-section review, and `final.py` can call into it once
    the cost numbers land.

What this actually exercises
    The real write path and the real read path, with no QGIS anywhere:

      - the four recorded jobs go through ProvenanceCaptureEngine.record_event,
        the same method the QGIS hook reaches (as demos/review2.py does);
      - "this file came from that file" is worked out by geoprovenance.prov,
        from the record, not from the recording;
      - the family tree printed below is the SAME arrangement the panel draws
        in QGIS — geoprovenance.ui.layout decides it, and only the drawing
        needs Qt;
      - the score is the real five-part check, and it says out loud which parts
        it could not run here.

    What is stood in for: QGIS running. The four jobs are a recording, and their
    files are written by tests/fixtures/_minifiles.py rather than produced by
    QGIS — the recording says a file was made at a path, so the demo puts a real
    file there for the checks to read. Everything downstream of that is shipping
    code.

Rules: RULES.md §7.1-§7.12. Companion document: docs/demos/WORKFLOW.md.
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "fixtures"))

import _minifiles  # noqa: E402

from _presenter import Demo, human_time, require_python, scratch_dir  # noqa: E402

from geoprovenance import audit, prov  # noqa: E402
from geoprovenance.capture.engine import ProvenanceCaptureEngine  # noqa: E402
from geoprovenance.storage.store import ProvenanceStore  # noqa: E402
from geoprovenance.ui import layout as L  # noqa: E402

RECORDING = REPO_ROOT / "tests" / "fixtures" / "mock_events.json"

#: The recorded run this replays: one piece of work, four jobs, and a branch —
#: one job making two files that then go different ways. The same recording
#: holds a fifth job an hour later that overwrites an earlier file; it belongs
#: to a different story and is left out deliberately, as demos/review2.py does.
WORK_SESSION = "832807f6-eaac-5701-8b79-6158b321b445"
JOBS = 4

#: The starting file the demo edits behind the software's back, to show that
#: the check notices. Named here so the readback and the check agree.
THE_FILE_WE_EDIT = "data/sample_points.shp"

FIELDS = [("NAME", "C", 12), ("KIND", "C", 8)]


def recorded_jobs():
    """The four jobs, oldest first, exactly as they were written down."""
    events = [e for e in json.loads(RECORDING.read_text())
              if e["session_id"] == WORK_SESSION]
    events.sort(key=lambda event: event["started_at"])
    return events[:JOBS]


def every_file_named(jobs):
    """Every path the four jobs mention, whether read or written."""
    paths = []
    for job in jobs:
        for layer in list(job["inputs"]) + list(job["outputs"]):
            if layer["path"] and layer["path"] not in paths:
                paths.append(layer["path"])
    return paths


def put_a_real_file_at(workspace, relative, kinds=("urban", "rural", "urban")):
    """Write a small, real dataset where the recording says one should be.

    Standing in for QGIS having produced it. The checks further down read these
    files for real, so they have to be real files.
    """
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    points = [(1.0 + i, 2.0 + i) for i in range(len(kinds))]
    if path.suffix == ".gpkg":
        # The two writers take different column names; each takes its own.
        _minifiles.write_point_geopackage(
            path, "areas",
            points,
            [{"name": f"p{i}", "category": kind} for i, kind in enumerate(kinds)],
        )
    else:
        _minifiles.write_point_shapefile(
            path, points,
            [{"NAME": f"p{i}", "KIND": kind} for i, kind in enumerate(kinds)],
            FIELDS,
        )
    return path


def pointing_into(workspace, job):
    """The same job, with its file paths pointing at the workspace."""
    job = dict(job)
    for side in ("inputs", "outputs"):
        job[side] = [
            dict(layer, path=str(workspace / layer["path"]) if layer["path"] else None)
            for layer in job[side]
        ]
    return job


def main() -> int:
    require_python()

    demo = Demo(
        review="of the Workflow Section",
        claim="A whole piece of work, drawn as a family tree of files, with an "
              "honest answer to whether we could still run it today.",
        before="We could list the jobs QGIS ran, but not show how the files "
               "relate, and not say whether the work still holds up.",
        after="The files are drawn as a family tree, and every starting file is "
              "checked to see if it is still there and still the same.",
        steps=7,
    )

    workspace = scratch_dir()
    jobs = recorded_jobs()
    store = ProvenanceStore(workspace / "record.db")
    engine = ProvenanceCaptureEngine(store, session_id=WORK_SESSION)
    tree = score_before = score_after = None
    written = 0

    with demo.step("Setting out a clean workspace with real files in it"):
        for relative in every_file_named(jobs):
            put_a_real_file_at(workspace, relative)
        assert (workspace / THE_FILE_WE_EDIT).exists()
        assert store.counts()["activities"] == 0, "the notebook should start empty"

    with demo.step(f"Replaying {JOBS} jobs through the software that watches QGIS"):
        for job in jobs:
            assert engine.record_event(pointing_into(workspace, job)).recorded
        assert store.counts()["activities"] == JOBS, store.counts()

    with demo.step("Working out which file came from which"):
        piece = store.find_workflows_by_session(WORK_SESSION)[0]
        graph = prov.ProvGraph.load(store, piece["id"])
        written = sum(1 for _ in prov.infer_derivations(graph))
        # Already written during capture, so a second pass finds nothing new.
        assert prov.write_derivations(store, piece["id"]) == 0
        assert written > 0, "no links between files were found"

    with demo.step("Drawing the family tree"):
        tree = L.as_text(L.build_layout(graph), graph)
        assert tree.splitlines()[0] == "sample_points.shp"

    with demo.step("Checking whether we could still run it today"):
        score_before = audit.audit_workflow(store, piece["id"])
        audit.persist(store, score_before)
        assert score_before.overall == 100.0, score_before.components

    with demo.step("Changing one of the starting files behind its back"):
        put_a_real_file_at(workspace, THE_FILE_WE_EDIT,
                           kinds=("urban", "URBAN", "urban"))

    with demo.step("Checking again — and noticing"):
        score_after = audit.audit_workflow(store, piece["id"])
        audit.persist(store, score_after)
        assert score_after.overall < score_before.overall, "the change went unnoticed"
        assert "sample_points.shp" in " ".join(
            score_after.reasons("input_unchanged")
        )

    if tree is None or score_after is None:
        demo.limitation("A step above failed, so there is nothing to read back.")
        store.close()
        return demo.finish()

    demo.note("The family tree, read top to bottom — each file sits under the "
              "job that made it:")
    demo.block(tree)

    first = jobs[0]
    demo.readback({
        "The work": piece["name"],
        "Jobs noticed": f"{store.counts()['activities']} of {JOBS}",
        "Files tracked": str(len(graph.entities)),
        "Links found": f"{written} — each one 'this file came from that file'",
        "Started": human_time(first["started_at"]),
        "First job": f"{first['algorithm_name']} on "
                     f"{pathlib.Path(first['inputs'][0]['path']).name}",
        "Score before": f"{score_before.overall:.0f} out of 100",
        "Then we edited": pathlib.Path(THE_FILE_WE_EDIT).name,
        "Score after": f"{score_after.overall:.0f} out of 100 — and it named "
                       f"the file we touched",
    })

    demo.note("Before the change:")
    demo.block(audit.plain_report(score_before))
    demo.note("After changing one starting file — nobody told the software:")
    demo.block(audit.plain_report(score_after))

    unchecked = [name for name, value in score_after.components.items()
                 if value is None]
    demo.limitation(
        f"{len(unchecked)} of the 5 checks need QGIS itself running, so on this "
        "machine they say 'we cannot tell' rather than guessing. "
        "The score is worked out over the checks that did run."
    )
    demo.limitation(
        "The family tree is printed here, not drawn. The drawn one lives in the "
        "QGIS panel, which needs QGIS — that is the optional second act."
    )
    demo.limitation(
        "One edited starting file costs only its share of the score, so the "
        "number falls further the more of the work is affected. Read the named "
        "file, not just the number."
    )
    demo.limitation(
        "QGIS did not really run these four jobs: they are a recording, and the "
        "files were written by the demo so the checks had something real to "
        "read. Everything after that point is the shipping software."
    )

    store.close()
    return demo.finish()


if __name__ == "__main__":
    raise SystemExit(main())
