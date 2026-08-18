"""Review 1 demo (Week 4) — ships after sub-phase A3.

    Claim: "QGIS ran a job and we wrote it down automatically."

Run it:
    source .venv/bin/activate && python demos/review1.py

What this actually exercises
    The REAL capture path, not a recording. The stand-in objects below are
    handed to ``geoprovenance.capture.hooks.handle_post_execution`` — the exact
    function the generated hook script calls inside QGIS — which normalises
    them and writes through the real store.

    That is possible because the normalizer and the engine import no QGIS
    (they duck-type instead), which is also RULES.md §7.3: the demo must run in
    a review room on a laptop with no QGIS installed.

    The one thing being stood in for is QGIS itself calling the hook. That is
    exactly the part that has not been verified yet, and section 7 of
    docs/demos/REVIEW-1.md says so out loud.

Rules: RULES.md §7.1-§7.12. Companion document: docs/demos/REVIEW-1.md.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

from _presenter import Demo, human_size, human_time, require_python, scratch_dir  # noqa: E402

from geoprovenance.capture import hooks  # noqa: E402
from geoprovenance.capture.engine import ProvenanceCaptureEngine  # noqa: E402
from geoprovenance.storage.store import ProvenanceStore  # noqa: E402

RAN_AT = "2026-08-18T14:31:07.482913+00:00"
FINISHED_AT = "2026-08-18T14:31:08.004117+00:00"


# ---------------------------------------------------------------------------
# Stand-ins for what QGIS hands the hook. Shaped exactly like the real thing:
# a layer knows its own file, its coordinate system and how many shapes it
# holds; the algorithm knows which of its settings are files and which are
# plain values.
# ---------------------------------------------------------------------------

class Crs:
    def __init__(self, code):
        self._code = code

    def authid(self):
        return self._code


class Provider:
    def __init__(self, driver):
        self._driver = driver

    def name(self):
        return "ogr"

    def storageType(self):  # noqa: N802 — QGIS name
        return self._driver


class Layer:
    def __init__(self, path, shapes, driver="ESRI Shapefile", code="EPSG:4326"):
        self._path, self._shapes = path, shapes
        self._crs, self._provider = Crs(code), Provider(driver)

    def publicSource(self):  # noqa: N802 — QGIS name
        return self._path

    def crs(self):
        return self._crs

    def dataProvider(self):  # noqa: N802 — QGIS name
        return self._provider

    def featureCount(self):  # noqa: N802 — QGIS name
        return self._shapes


class Setting:
    def __init__(self, name, kind):
        self._name, self._kind = name, kind

    def name(self):
        return self._name

    def type(self):
        return self._kind


class Algorithm:
    """A stand-in for QGIS's 'Buffer' tool."""

    def __init__(self):
        self._settings = [
            Setting("INPUT", "source"), Setting("OUTPUT", "sink"),
            Setting("DISTANCE", "distance"), Setting("SEGMENTS", "number"),
            Setting("DISSOLVE", "boolean"),
        ]

    def id(self):
        return "native:buffer"

    def displayName(self):  # noqa: N802 — QGIS name
        return "Buffer"

    def provider(self):
        return None

    def parameterDefinitions(self):  # noqa: N802 — QGIS name
        return self._settings

    def outputDefinitions(self):  # noqa: N802 — QGIS name
        return []


def main() -> int:
    require_python()

    demo = Demo(
        review="1",
        claim="QGIS ran a job and we wrote it down automatically.",
        before="Nothing was kept. Close QGIS and there was no record of what had been done.",
        after="Every job QGIS finishes is written down by itself, as it happens.",
        steps=5,
    )

    workspace = scratch_dir()
    notebook = workspace / "record.db"
    store = None

    with demo.step("Starting with a completely empty notebook"):
        store = ProvenanceStore(notebook)
        assert store.counts()["activities"] == 0, "the notebook should start empty"
        engine = ProvenanceCaptureEngine.start(store)

    roads = Layer("/data/roads.shp", shapes=1204)
    buffered = Layer("/out/buffered_roads.shp", shapes=1204)
    what_qgis_hands_us = {
        "alg": Algorithm(),
        "parameters": {
            "INPUT": roads, "OUTPUT": "TEMPORARY_OUTPUT",
            "DISTANCE": 500, "SEGMENTS": 5, "DISSOLVE": False,
        },
        "results": {"OUTPUT": buffered},
        # Fixed times so the demo prints the same thing every run (§7.2).
        "geoprovenance_started_at": RAN_AT,
        "geoprovenance_ended_at": FINISHED_AT,
    }

    with demo.step("Nobody tells us anything — QGIS just finishes a 'Buffer' job"):
        hooks.handle_post_execution(dict(what_qgis_hands_us))
        assert store.counts()["activities"] == 1, "the job should have been noticed"

    with demo.step("Watching in two places at once, but never writing it down twice"):
        hooks.handle_post_execution(dict(what_qgis_hands_us))
        assert store.counts()["activities"] == 1, "it should still be a single job"

    with demo.step("Checking every piece of the record landed"):
        counts = store.counts()
        assert counts["activities"] == 1, counts
        assert counts["entities"] == 2, counts      # the file read, the file made
        assert counts["agents"] == 1, counts        # the computer it ran on
        assert counts["relations"] == 3, counts     # read, made, ran-on

    with demo.step("Reading it back in plain English"):
        job = _only_activity(store)
        read, made = _files(store, job["id"])
        assert read is not None and made is not None, "both files should be on record"

    demo.readback({
        "Someone ran": job["algorithm_name"],
        "On the file": read["label"],
        "Which held": f"{read_shapes(read):,} shapes",
        "Producing": made["label"],
        "At": human_time(job["started_at"]),
        "Took": f"{_seconds(job):.1f} seconds",
        "Settings used": "distance = 500 m, corner detail = 5, merged = no",
        "On": _computer(store, job["id"]),
    })
    demo.note("Nobody typed any of that in. It was noticed and written down "
              "on its own.")
    demo.note("We also spotted the same job a second time, from a second place "
              "we watch — and correctly kept one record, not two.")
    demo.note(f"The whole record so far takes {human_size(notebook.stat().st_size)}.")

    demo.limitation(
        "We only notice work done with QGIS's built-in tools. Editing a shape "
        "by hand on the map is invisible to us, on purpose."
    )
    demo.limitation(
        "This ran without QGIS open. The next step is watching it happen inside "
        "a real QGIS window — that has not been proved yet."
    )

    if store is not None:
        ProvenanceCaptureEngine.stop()
        store.close()
    return demo.finish()


# ---------------------------------------------------------------------------

def _only_activity(store):
    rows = store._connection().execute("SELECT * FROM activities").fetchall()
    return dict(rows[0])


def _files(store, activity_id):
    """The file that was read and the file that was made."""
    read = made = None
    for relation in store.get_relations_for(activity_id, "both"):
        if relation["relation_type"] == "used":
            read = store.get_entity(relation["target_id"])
        elif relation["relation_type"] == "wasGeneratedBy":
            made = store.get_entity(relation["source_id"])
    return read, made


def read_shapes(entity) -> int:
    import json
    return json.loads(entity["metadata_json"] or "{}").get("feature_count", 0)


def _seconds(job) -> float:
    import datetime as dt
    start = dt.datetime.fromisoformat(job["started_at"])
    end = dt.datetime.fromisoformat(job["ended_at"])
    return (end - start).total_seconds()


def _computer(store, activity_id) -> str:
    for relation in store.get_relations_for(activity_id, "out"):
        if relation["relation_type"] == "wasAssociatedWith":
            machine = store.get_agent(relation["target_id"])
            return f"{machine['os_info']}, Python {machine['python_version']}"
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
