"""Record the demo workflow through the real capture path, with no QGIS.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

    python qgis_demo/replay.py        (or: make qgis-demo-record)

What this is, and what it is not
    It IS the real write path. Every step goes through
    ``ProvenanceCaptureEngine.record_algorithm_execution`` — the same function
    the QGIS post-execution hook calls — through the real normalizer and the
    real store. Nothing is inserted by hand and no SQL is written here.

    It is NOT QGIS running the algorithms. QGIS is what produces the output
    FILES; this only produces the RECORD of the run. Where the output files are
    missing, the map will say the file is not on this computer, which is the
    truthful thing for it to say.

    ``run_in_qgis.py`` is the other half: it runs the same four steps inside a
    real QGIS, where the plugin captures them for itself. Both read
    ``scenario.py``, so the two cannot describe different workflows.

Determinism
    Timestamps come from a fixed epoch, never ``datetime.now()``, so re-running
    this produces the same record and the demo output is stable (RULES.md §7.2).

Channels
    Step 3 is deliberately recorded twice — once as the post-execution hook
    would see it, once as the history channel would. That exercises the §5.9
    cross-channel dedup for real: the second sighting must not create a second
    job, it must raise the corroboration count on the first. A demo that only
    ever recorded each job once would never show that working.
"""

from __future__ import annotations

import datetime as dt
import platform
import sys

from geoprovenance.capture.engine import ProvenanceCaptureEngine
from geoprovenance.storage.store import ProvenanceStore
from qgis_demo import scenario

#: Fixed, so the record is byte-stable across runs (RULES.md §7.2).
EPOCH = dt.datetime(2026, 8, 24, 10, 0, 0, tzinfo=dt.timezone.utc)
SESSION_ID = "9f1c2d84-0b6a-4e37-9a55-2c7d1b0e4a13"

#: Each step takes a different, plausible number of seconds, so "how long did
#: this take" is a column with something in it rather than a row of zeros.
DURATIONS_S = (2.4, 1.1, 0.8, 3.2)


def _ts(offset_seconds: float) -> str:
    return (EPOCH + dt.timedelta(seconds=offset_seconds)).isoformat(
        timespec="microseconds")


def _agent() -> dict:
    """The computer and software this record was made on.

    Recorded honestly: this replay runs outside QGIS, so there is no QGIS
    version to report and the field says so rather than inventing one.
    """
    return {
        "qgis_version": "not running inside QGIS (offline replay)",
        "os_info": platform.platform(),
        "python_version": platform.python_version(),
        "plugin_versions": {"GeoProvenance": "0.1.0"},
    }


def _definitions(step: dict) -> dict[str, str]:
    """Tell the normalizer which parameters name files.

    Inside QGIS this comes from the algorithm itself, via
    ``hooks.parameter_definitions``. Here it is derived from the scenario, using
    the same vocabulary ``normalizer.INPUT_PARAM_TYPES`` and
    ``OUTPUT_PARAM_TYPES`` recognise.
    """
    definitions = {}
    for key, value in step["parameters"].items():
        if not isinstance(value, str):
            continue
        if value in step["outputs"]:
            definitions[key] = "sink"
        elif value in step["inputs"]:
            definitions[key] = "source"
    return definitions


def record(store: ProvenanceStore) -> ProvenanceCaptureEngine:
    engine = ProvenanceCaptureEngine(store, session_id=SESSION_ID)

    offset = 0.0
    for index, step in enumerate(scenario.STEPS):
        duration = DURATIONS_S[index]
        started, ended = _ts(offset), _ts(offset + duration)

        result = engine.record_algorithm_execution(
            algorithm_id=step["algorithm_id"],
            algorithm_name=step["algorithm_name"],
            provider=step["provider"],
            parameters=step["parameters"],
            parameter_definitions=_definitions(step),
            results={"OUTPUT": step["outputs"][0]},
            started_at=started,
            ended_at=ended,
            status="completed",
            source="post_hook",
            agent=_agent(),
        )
        print(f"  step {index + 1}  {step['algorithm_name']:<20} "
              f"recorded={result.recorded} corroborated={result.corroborated}")

        # The history channel reports the same job a moment later, and reports
        # it less richly: it has no algorithm in hand, so it has no way to tell
        # a file-valued parameter from a number. Everything stays in parameters
        # and nothing is lifted into inputs or outputs. This is the shape a real
        # second sighting has (docs/capture_coverage.md §1), and recording a
        # tidied-up copy of the hook's own event instead is exactly the mistake
        # that once hid a dedup defect behind a green demo.
        if index == 2:
            second = engine.record_algorithm_execution(
                algorithm_id=step["algorithm_id"],
                algorithm_name=step["algorithm_name"],
                provider=step["provider"],
                parameters=step["parameters"],
                parameter_definitions=None,
                results=None,
                started_at=ended,
                ended_at=ended,
                status="completed",
                source="history_signal",
                agent=_agent(),
            )
            print(f"           seen a second time      "
                  f"recorded={second.recorded} corroborated={second.corroborated}")

        offset += duration + 1.5

    engine.group_session(SESSION_ID)
    return engine


def main() -> int:
    scenario.DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = scenario.DB_PATH.with_name(scenario.DB_PATH.name + suffix)
        if candidate.exists():
            candidate.unlink()

    print(f"Recording into {scenario.DB_PATH.relative_to(scenario.REPO_ROOT)}")
    store = ProvenanceStore(scenario.DB_PATH)
    try:
        record(store)
        counts = store.counts()
        channels = store.channel_statistics()
    finally:
        store.close()

    print()
    print(f"  jobs recorded      : {counts['activities']}")
    print(f"  files known about  : {counts['entities']}")
    print(f"  connections drawn  : {counts['relations']}")
    print(f"  groups of work     : {counts['workflows']}")
    print(f"  channels           : {channels}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
