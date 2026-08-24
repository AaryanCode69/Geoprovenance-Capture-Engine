"""Review 2 demo (Week 8) — ships after sub-phase A6.

    Claim: "A whole 4-step workflow was captured, in the right order,
            with nothing missing."

Run it:
    source .venv/bin/activate && python demos/review2.py

What this actually exercises
    The REAL write path. The recorded jobs in tests/fixtures/mock_events.json
    are handed to ProvenanceCaptureEngine.record_event — the same method the
    QGIS hook reaches after it has tidied up what QGIS handed it. Everything
    downstream of that point is the shipping code: the same de-duplication,
    the same file-version rule, the same grouping.

    Review 1 stood in for QGIS calling us. This one stands in for QGIS
    *running*, and replays four jobs that were recorded earlier — which is
    RULES.md §7.3: the demo must run in a review room, offline, on a laptop
    with no QGIS installed.

Why these four jobs
    They are the awkward ones on purpose. The four arrive on BOTH of the
    places we watch, one of them branches (a single job making two files that
    then go different ways), and one reads a second file as well as the file
    the previous job made. A chain of four buffers would prove much less.

Rules: RULES.md §7.1-§7.12. Companion document: docs/demos/REVIEW-2.md.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

from _presenter import Demo, human_size, human_time, require_python, scratch_dir  # noqa: E402

from geoprovenance.capture.engine import ProvenanceCaptureEngine  # noqa: E402
from geoprovenance.storage.store import ProvenanceStore  # noqa: E402

RECORDING = REPO_ROOT / "tests" / "fixtures" / "mock_events.json"

#: The recorded run this demo replays: one piece of work, four jobs, a branch.
#: The same recording holds a fifth job an hour later — the same tool run a
#: second time — which belongs to a different story than this gate's, so the
#: four are taken deliberately rather than "everything in the file".
WORK_SESSION = "832807f6-eaac-5701-8b79-6158b321b445"
JOBS_IN_THIS_PIECE_OF_WORK = 4

#: A job that went wrong, from a different recorded run that day. §4.10 — a
#: failure is part of the record, not something to quietly drop.
OTHER_WORK = "d453321e-4a24-5baa-921d-67d7b01dbd73"
FAILED_JOB = "gdal:warpreproject"


def load(session_id, *, limit=None, status=None):
    """Jobs from the recording, oldest first."""
    events = json.loads(RECORDING.read_text())
    chosen = [
        event for event in events
        if event["session_id"] == session_id
        and (status is None or event["status"] == status)
    ]
    chosen.sort(key=lambda event: event["started_at"])
    return chosen[:limit] if limit else chosen


def files_made(store, activity_id):
    """The files one job created, by their plain names."""
    made = [
        relation for relation in store.get_relations_for(activity_id)
        if relation["relation_type"] == "wasGeneratedBy"
    ]
    names = []
    for relation in made:
        file = store.get_entity(relation["source_id"])
        if file is not None:
            names.append(file["label"])
    return names


def and_list(names):
    """['a', 'b'] -> 'a and b' — plain English, not a Python list (§7.5)."""
    if not names:
        return "nothing on disk"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def second_sighting_of(job):
    """The same job as the OTHER place we watch would report it.

    That place does not get told which settings name files, so everything stays
    a plain setting and nothing is listed as a file read or made. It also only
    notices a job after it has finished, so its time is the job's end, not its
    start. Both differences are real, and both are what the matching has to
    cope with — see RULES.md §5.9 and docs/capture_coverage.md §4.
    """
    settings = dict(job.get("parameters") or {})
    for entry in (job.get("inputs") or []) + (job.get("outputs") or []):
        settings[entry["param"]] = entry.get("path")

    seen_again = dict(job)
    seen_again["source"] = "history_signal"
    seen_again["parameters"] = settings
    seen_again["inputs"] = []
    seen_again["outputs"] = []
    seen_again["started_at"] = job.get("ended_at") or job["started_at"]
    seen_again["ended_at"] = seen_again["started_at"]
    return seen_again


def _seconds(started_at, ended_at):
    """How long the whole piece of work took, start of the first job to end of
    the last."""
    start = _dt.datetime.fromisoformat(started_at)
    end = _dt.datetime.fromisoformat(ended_at)
    return (end - start).total_seconds()


def main() -> int:
    require_python()

    demo = Demo(
        review="2",
        claim="A whole 4-step workflow was captured, in the right order, "
              "with nothing missing.",
        before="We could write down one job at a time, but nothing tied them "
               "together — four jobs were four unrelated notes.",
        after="The four jobs are recognised as one piece of work, in the "
              "order they happened, on their own.",
        steps=6,
    )

    workspace = scratch_dir()
    notebook = workspace / "record.db"
    jobs = load(WORK_SESSION, limit=JOBS_IN_THIS_PIECE_OF_WORK)
    store = None
    piece_of_work = None

    with demo.step("Starting with a completely empty notebook"):
        store = ProvenanceStore(notebook)
        assert store.counts()["activities"] == 0, "the notebook should start empty"
        engine = ProvenanceCaptureEngine.start(store, session_id=WORK_SESSION)
        assert len(jobs) == JOBS_IN_THIS_PIECE_OF_WORK, (
            f"expected {JOBS_IN_THIS_PIECE_OF_WORK} recorded jobs, found {len(jobs)}"
        )

    with demo.step("Four jobs run in QGIS, one after another"):
        for job in jobs:
            assert engine.record_event(dict(job)).recorded, job["algorithm_id"]
        assert store.counts()["activities"] == 4, store.counts()

    with demo.step("Watching in two places, but writing it down once"):
        # The second place we watch reports a job the first place already told
        # us about. It is the SAME run of the SAME tool, so it is counted as a
        # second sighting and not written down again (A5).
        #
        # Built the way the second place ACTUALLY reports it, not by copying
        # what the first place said. The two watch from different vantage
        # points: the first is told which settings are files and which are
        # plain values, the second is not, and the second only notices a job
        # once it has finished. Copying the first one's note hid that, and hid
        # a real defect behind a passing demo (RULES.md §7.9).
        result = engine.record_event(second_sighting_of(jobs[0]))
        assert result.corroborated and not result.recorded, "should be a second sighting"
        assert store.counts()["activities"] == 4, "still four jobs, not five"

    with demo.step("The four recognised as one piece of work, in order"):
        pieces = store.find_workflows_by_session(WORK_SESSION)
        assert len(pieces) == 1, f"expected one piece of work, got {len(pieces)}"
        piece_of_work = store.get_workflow_graph(pieces[0]["id"])

        steps = piece_of_work["activities"]
        assert len(steps) == 4, f"expected four steps, got {len(steps)}"
        assert [s["started_at"] for s in steps] == sorted(
            s["started_at"] for s in steps
        ), "the steps must be in the order they actually happened"
        assert [s["algorithm_name"] for s in steps] == [
            job["algorithm_name"] for job in jobs
        ], "and they must be the same four jobs"

    with demo.step("A job that went wrong is written down too"):
        failure = load(OTHER_WORK, status="failed")[0]
        assert failure["algorithm_id"] == FAILED_JOB, failure["algorithm_id"]
        assert engine.record_event(dict(failure)).recorded
        failures = [
            a for a in store.list_activities_for_session(failure["session_id"])
            if a["status"] == "failed"
        ]
        assert len(failures) == 1, "the failed job should be on record"
        assert store.counts()["activities"] == 5

    with demo.step("One note about the computer, not one per job"):
        # Five jobs, two different computers, TWO notes about them — not five.
        # A fresh note per job would make our own size measurements look bad
        # for a reason of our own making.
        assert store.counts()["agents"] == 2, store.counts()

    if piece_of_work is None:
        # A step failed, so there is nothing to read back. Print the tail
        # anyway rather than crashing over it — a demo reports, it does not
        # blow up in the room (§7.12).
        demo.limitation("This run did not get far enough to show a result. "
                        "The failure is printed above.")
        return demo.finish()

    order = {
        f"Step {index + 1}": (
            f"{step['algorithm_name']}, which made "
            f"{and_list(files_made(store, step['id']))}"
        )
        for index, step in enumerate(piece_of_work["activities"])
    }
    first, last = piece_of_work["activities"][0], piece_of_work["activities"][-1]
    setup = piece_of_work["agents"][0]
    failed = sum(
        activity["status"] == "failed"
        for activity in store.list_activities_for_session(OTHER_WORK)
    )

    # Closed before it is measured. Until then part of the record is still in
    # a side file, and the size printed below would be a flattering lie.
    store.close()
    store = None

    # A blank notebook, for comparison. Quoting one total on its own invites
    # the wrong conclusion — most of it is the empty notebook, and the honest
    # number is what the work ADDED to it (§8.6).
    blank = workspace / "blank.db"
    ProvenanceStore(blank).close()

    demo.readback({
        "This piece of work": piece_of_work["workflow"]["name"],
        **order,
        "Started": human_time(first["started_at"]),
        "The four took": f"{_seconds(first['started_at'], last['ended_at']):.0f} seconds",
        "Ran on": f"QGIS {setup['qgis_version']}, {setup['os_info']}",
        "Also on record": f"{failed} job that went wrong, in other work that day",
        "An empty notebook": human_size(blank.stat().st_size),
        "With all this in it": human_size(notebook.stat().st_size),
    })

    demo.note("Nobody named that piece of work, drew a line around it, or put "
              "the steps in order. The four jobs were tied together by the "
              "files they passed to each other.")
    demo.note("Step 2 made TWO files, and steps 3 and 4 each took a different "
              "one. That split is why this is a piece of work and not just a "
              "list.")
    demo.note("Five jobs, and the notebook is not one byte larger — they "
              "fitted in the room it already had. What it keeps is a "
              "description of the work, never a copy of the data, so it "
              "stays this small however large the files are.")
    demo.note("You can also draw the line yourself: 'Start new workflow' in "
              "the menu says the next job begins something separate, even if "
              "it opens the same file.")

    demo.limitation(
        "We tie jobs together when they pass files to each other inside one "
        "sitting at QGIS. Two unrelated pieces of work that happen to open "
        "the same file get treated as one — that is what the 'Start new "
        "workflow' button is for."
    )
    demo.limitation(
        "QGIS has now run the real thing and we did record it — but on a newer "
        "QGIS than the one we are building for. On that newer one, the main way "
        "we planned to watch has been removed; a backup way caught everything. "
        "How the version we target behaves is still untested."
    )

    if store is not None:
        store.close()
    ProvenanceCaptureEngine.stop()
    return demo.finish()


if __name__ == "__main__":
    raise SystemExit(main())
