"""Turn a recorded workflow into map layers. Standard library only, no QGIS.

Owner: Person A.  Demo scaffolding, outside ``geoprovenance/`` on purpose.

    python qgis_demo/export_layers.py [--database PATH]   (or: make qgis-demo-layers)

Reads the record through the public store methods only — no SQL is written
here, the same rule Person B and Person C work under (RULES.md §1.3) — and
writes ``qgis_demo/project/provenance_map.gpkg``.

Why this imports no QGIS
    The same reason ``capture/normalizer.py`` and ``capture/engine.py`` import
    none: it keeps the part with the real logic runnable and testable on any
    machine, and leaves only a thin adapter that needs QGIS. Placing the layers
    is the part that can be wrong; ``build_project.py`` only styles them.

Where the coordinates come from
    Derived, never stored. The record holds file paths, not geometry, and the
    schema is frozen (see ``footprints.py`` for the full reasoning). Every
    rectangle on the map is the extent read out of a file that is really there.
    Files that are not there get no rectangle and are listed, with the reason,
    in a table of their own — a blank space on a map should never be the only
    evidence that something is missing.

What is deliberately NOT here
    No fingerprints, no "which file came from which", no reproducibility score.
    Those are Person B's and Person C's (RULES.md §1.2 [HARD]) and are not
    prototyped here. The one place this touches their territory is that a job
    carries the NAMES of the files it read and created as text in its attribute
    table. That is reading Person A's own relations table (§1.3); it is not
    drawing a family tree, and no line between files is ever drawn.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from geoprovenance.storage.store import ProvenanceStore
from qgis_demo import geopkg, scenario
from qgis_demo.footprints import Footprint, footprint_of

OUTPUT_GPKG = scenario.PROJECT_DIR / "provenance_map.gpkg"

#: Internal values a reviewer should never have to decode (RULES.md §7.5).
CHANNEL_WORDS = {
    "post_hook": "QGIS told us the moment it finished",
    "run_wrapper": "we were wrapped around the command",
    "history_signal": "we spotted it in the QGIS history list",
    None: "not recorded",
}

STATUS_WORDS = {
    "completed": "finished",
    "failed": "failed",
    "cancelled": "stopped by the user",
}

KIND_WORDS = {
    "vector": "shapes (points, lines, areas)",
    "raster": "an image grid",
    "unknown": "not recorded",
    None: "not recorded",
}


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------

def _human_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        moment = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    stamp = moment.strftime("%d %b %Y, %I:%M %p")
    return stamp.replace(" 0", " ").lstrip("0")


def _duration_seconds(started: str | None, ended: str | None) -> float | None:
    if not started or not ended:
        return None
    try:
        a = dt.datetime.fromisoformat(started)
        b = dt.datetime.fromisoformat(ended)
    except ValueError:
        return None
    return round((b - a).total_seconds(), 3)


def _feature_count(entity: dict) -> int | None:
    raw = entity.get("metadata_json")
    if not raw:
        return None
    try:
        return json.loads(raw).get("feature_count")
    except (ValueError, AttributeError):
        return None


def _size_on_disk(path: str | None) -> int | None:
    if not path:
        return None
    candidate = pathlib.Path(path)
    return candidate.stat().st_size if candidate.exists() else None


def _resolve(path: str | None) -> str | None:
    """Make a recorded path absolute the way the plugin's own reader would.

    The record may hold a path relative to the repository — the shared fixtures
    do exactly that on purpose. Resolving against the repository root is what
    turns those into files that can actually be opened.
    """
    if not path:
        return None
    candidate = pathlib.Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str((scenario.REPO_ROOT / candidate).resolve())


def collect(store: ProvenanceStore) -> dict:
    """Everything the map needs, read through public methods only."""
    workflows = store.list_workflows()

    entities: dict[str, dict] = {}
    activities: dict[str, dict] = {}
    agents: dict[str, dict] = {}
    relations: list[dict] = []
    workflow_of_activity: dict[str, dict] = {}

    for workflow in workflows:
        graph = store.get_workflow_graph(workflow["id"])
        for entity in graph["entities"]:
            entities.setdefault(entity["id"], entity)
        for agent in graph["agents"]:
            agents.setdefault(agent["id"], agent)
        for activity in graph["activities"]:
            activities.setdefault(activity["id"], activity)
            workflow_of_activity[activity["id"]] = workflow
        relations.extend(graph["relations"])

    return {
        "workflows": workflows,
        "entities": entities,
        "activities": activities,
        "agents": agents,
        "relations": relations,
        "workflow_of_activity": workflow_of_activity,
    }


def _files_by_job(record: dict) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Which files each job read, and which it created.

    Straight off Person A's own ``relations`` rows: ``used`` points from a job
    to a file it read, ``wasGeneratedBy`` from a file to the job that made it.
    Used as text, never drawn (see the module docstring).
    """
    entities = record["entities"]
    reads: dict[str, list[str]] = {}
    creates: dict[str, list[str]] = {}
    for relation in record["relations"]:
        kind = relation.get("relation_type")
        if kind == "used":
            entity = entities.get(relation.get("target_id"))
            if entity:
                reads.setdefault(relation["source_id"], []).append(
                    entity.get("label") or "")
        elif kind == "wasGeneratedBy":
            entity = entities.get(relation.get("source_id"))
            if entity:
                creates.setdefault(relation["target_id"], []).append(
                    entity.get("label") or "")
    return reads, creates


# ---------------------------------------------------------------------------
# Building the layers
# ---------------------------------------------------------------------------

FILE_FIELDS = [
    geopkg.Field("file_name"),
    geopkg.Field("where_it_is"),
    geopkg.Field("file_type"),
    geopkg.Field("what_is_in_it"),
    geopkg.Field("coordinate_system"),
    geopkg.Field("version_no", "INTEGER"),
    geopkg.Field("still_on_disk"),
    geopkg.Field("role"),
    geopkg.Field("size_on_disk_bytes", "INTEGER"),
    geopkg.Field("how_many_shapes", "INTEGER"),
    geopkg.Field("part_of"),
]

JOB_FIELDS = [
    geopkg.Field("step_number", "INTEGER"),
    geopkg.Field("what_ran"),
    geopkg.Field("run_by"),
    geopkg.Field("started"),
    geopkg.Field("took_seconds", "REAL"),
    geopkg.Field("outcome"),
    geopkg.Field("how_we_noticed"),
    geopkg.Field("times_confirmed", "INTEGER"),
    geopkg.Field("reads"),
    geopkg.Field("creates"),
    geopkg.Field("part_of"),
]

AREA_FIELDS = [
    geopkg.Field("group_name"),
    geopkg.Field("how_many_steps", "INTEGER"),
    geopkg.Field("started"),
    geopkg.Field("how_many_files", "INTEGER"),
]

NOWHERE_FIELDS = [
    geopkg.Field("file_name"),
    geopkg.Field("where_it_should_be"),
    geopkg.Field("why_it_is_not_on_the_map"),
    geopkg.Field("part_of"),
]

MACHINE_FIELDS = [
    geopkg.Field("qgis_version"),
    geopkg.Field("operating_system"),
    geopkg.Field("python_version"),
    geopkg.Field("software_installed"),
    geopkg.Field("first_seen"),
]


def build_layers(record: dict) -> tuple[list[geopkg.Layer], dict]:
    entities = record["entities"]
    activities = record["activities"]
    workflow_of = record["workflow_of_activity"]
    reads, creates = _files_by_job(record)

    # Which workflow each file belongs to, via the jobs that touched it.
    workflow_of_entity: dict[str, str] = {}
    entity_role: dict[str, str] = {}
    for relation in record["relations"]:
        if relation.get("relation_type") == "used":
            entity_id, activity_id, role = (
                relation.get("target_id"), relation.get("source_id"), "read by a job")
        elif relation.get("relation_type") == "wasGeneratedBy":
            entity_id, activity_id, role = (
                relation.get("source_id"), relation.get("target_id"), "made by a job")
        else:
            continue
        workflow = workflow_of.get(activity_id)
        if workflow and entity_id in entities:
            workflow_of_entity.setdefault(entity_id, workflow["name"])
        # A file that is both read and made is a step's output feeding the next
        # step — the more informative of the two labels.
        if entity_id in entities and entity_role.get(entity_id) != "made by a job":
            entity_role[entity_id] = role

    file_rows = []
    nowhere_rows = []
    footprint_of_entity: dict[str, Footprint] = {}

    for entity in sorted(entities.values(), key=lambda e: (e.get("label") or "")):
        resolved = _resolve(entity.get("file_path"))
        footprint, reason = footprint_of(resolved)
        part_of = workflow_of_entity.get(entity["id"], "")

        if footprint is None:
            nowhere_rows.append((None, {
                "file_name": entity.get("label") or "(unnamed)",
                "where_it_should_be": entity.get("file_path") or "(never on disk)",
                "why_it_is_not_on_the_map": reason,
                "part_of": part_of,
            }))
            continue

        footprint_of_entity[entity["id"]] = footprint
        drawn = footprint.padded()
        file_rows.append((
            geopkg.wkb_box(drawn.xmin, drawn.ymin, drawn.xmax, drawn.ymax),
            {
                "file_name": entity.get("label") or "(unnamed)",
                "where_it_is": entity.get("file_path") or "",
                "file_type": entity.get("format") or "not recorded",
                "what_is_in_it": KIND_WORDS.get(entity.get("layer_type"),
                                                entity.get("layer_type") or ""),
                "coordinate_system": entity.get("crs") or footprint.crs or "not recorded",
                "version_no": entity.get("content_version") or 1,
                "still_on_disk": "yes",
                "role": entity_role.get(entity["id"], "known about"),
                "size_on_disk_bytes": _size_on_disk(resolved),
                "how_many_shapes": _feature_count(entity),
                "part_of": part_of,
            },
        ))

    job_rows = _job_rows(record, footprint_of_entity, reads, creates)
    area_rows = _area_rows(record, footprint_of_entity)
    machine_rows = _machine_rows(record)

    layers = [
        geopkg.Layer("work_areas", "POLYGON", AREA_FIELDS, area_rows,
                     "One box around everything a single piece of work touched"),
        geopkg.Layer("files_we_track", "POLYGON", FILE_FIELDS, file_rows,
                     "Every file the record knows about, drawn where it is on Earth"),
        geopkg.Layer("jobs_qgis_ran", "POINT", JOB_FIELDS, job_rows,
                     "Every job QGIS ran, placed on what it produced"),
        geopkg.Layer("files_with_no_place_on_the_map", None, NOWHERE_FIELDS,
                     nowhere_rows,
                     "Files the record knows about that cannot be drawn, and why"),
        geopkg.Layer("the_computer_it_ran_on", None, MACHINE_FIELDS, machine_rows,
                     "The machine and software each run was made on"),
    ]

    summary = {
        "workflows": len(record["workflows"]),
        "jobs": len(activities),
        "files": len(entities),
        "files_drawn": len(file_rows),
        "files_not_drawn": len(nowhere_rows),
        "machines": len(machine_rows),
    }
    return layers, summary


#: Jobs land on the middle of what they produced. In a workflow where each step
#: feeds the next, those middles are nearly the same point, so without help the
#: four markers stack into one blob and neither the labels nor the channel
#: colours can be read. This fans co-located jobs apart by a fixed step, big
#: enough to separate them at the scale the work covers. It moves a marker off
#: the exact centre of its output — a readability decision, and the reason it is
#: written down here.
_FAN_STEP = 0.017


def _job_rows(record, footprint_of_entity, reads, creates):
    entities = record["entities"]
    workflow_of = record["workflow_of_activity"]
    rows = []
    used_positions: dict[tuple[int, int], int] = {}

    def entity_ids_for(activity_id, relation_type, source_is_activity):
        out = []
        for relation in record["relations"]:
            if relation.get("relation_type") != relation_type:
                continue
            if source_is_activity and relation.get("source_id") == activity_id:
                out.append(relation.get("target_id"))
            elif not source_is_activity and relation.get("target_id") == activity_id:
                out.append(relation.get("source_id"))
        return [e for e in out if e in entities]

    ordered = sorted(record["activities"].values(),
                     key=lambda a: (a.get("sequence_order") or 0,
                                    a.get("started_at") or ""))

    for activity in ordered:
        activity_id = activity["id"]
        made = entity_ids_for(activity_id, "wasGeneratedBy", source_is_activity=False)
        took = entity_ids_for(activity_id, "used", source_is_activity=True)

        anchor = None
        for candidate in made + took:
            if candidate in footprint_of_entity:
                anchor = footprint_of_entity[candidate]
                break
        if anchor is None:
            # Nothing this job touched can be placed. Rather than drop the job
            # from the map, park it on the overall work area so it stays
            # visible and its attributes stay readable.
            all_footprints = list(footprint_of_entity.values())
            if not all_footprints:
                continue
            anchor = _union(all_footprints)

        x, y = anchor.centroid
        key = (round(x, 4), round(y, 4))
        rank = used_positions.get(key, 0)
        used_positions[key] = rank + 1
        x += _FAN_STEP * rank
        y += _FAN_STEP * rank * 0.6

        workflow = workflow_of.get(activity_id)
        rows.append((geopkg.wkb_point(x, y), {
            # sequence_order counts from zero; a reviewer counts from one.
            "step_number": (activity.get("sequence_order") or 0) + 1,
            "what_ran": activity.get("algorithm_name") or activity.get("algorithm_id"),
            "run_by": activity.get("provider") or "",
            "started": _human_time(activity.get("started_at")),
            "took_seconds": _duration_seconds(activity.get("started_at"),
                                              activity.get("ended_at")),
            "outcome": STATUS_WORDS.get(activity.get("status"),
                                        activity.get("status") or ""),
            "how_we_noticed": CHANNEL_WORDS.get(activity.get("capture_channel"),
                                                activity.get("capture_channel")),
            "times_confirmed": activity.get("corroborations") or 0,
            "reads": ", ".join(sorted(set(reads.get(activity_id, [])))),
            "creates": ", ".join(sorted(set(creates.get(activity_id, [])))),
            "part_of": workflow["name"] if workflow else "",
        }))
    return rows


def _union(footprints: list[Footprint]) -> Footprint:
    return Footprint(
        min(f.xmin for f in footprints), min(f.ymin for f in footprints),
        max(f.xmax for f in footprints), max(f.ymax for f in footprints),
    )


def _area_rows(record, footprint_of_entity):
    entities = record["entities"]
    workflow_of = record["workflow_of_activity"]
    rows = []
    for workflow in record["workflows"]:
        activity_ids = {aid for aid, wf in workflow_of.items()
                        if wf["id"] == workflow["id"]}
        entity_ids = set()
        for relation in record["relations"]:
            if relation.get("source_id") in activity_ids:
                entity_ids.add(relation.get("target_id"))
            if relation.get("target_id") in activity_ids:
                entity_ids.add(relation.get("source_id"))
        entity_ids &= set(entities)

        footprints = [footprint_of_entity[e] for e in entity_ids
                      if e in footprint_of_entity]
        if not footprints:
            continue
        box = _union(footprints).padded(fraction=0.06, minimum=0.004)
        rows.append((geopkg.wkb_box(box.xmin, box.ymin, box.xmax, box.ymax), {
            "group_name": workflow.get("name") or "",
            "how_many_steps": workflow.get("activity_count") or len(activity_ids),
            "started": _human_time(workflow.get("created_at")),
            "how_many_files": len(entity_ids),
        }))
    return rows


def _machine_rows(record):
    rows = []
    for agent in record["agents"].values():
        installed = agent.get("plugin_versions_json") or ""
        try:
            parsed = json.loads(installed) if installed else {}
            installed = ", ".join(f"{k} {v}" for k, v in sorted(parsed.items()))
        except ValueError:
            pass
        rows.append((None, {
            "qgis_version": agent.get("qgis_version") or "not recorded",
            "operating_system": agent.get("os_info") or "not recorded",
            "python_version": agent.get("python_version") or "not recorded",
            "software_installed": installed,
            "first_seen": _human_time(agent.get("created_at")),
        }))
    return rows


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default=str(scenario.DB_PATH),
                        help="the record to draw (default: the demo's own)")
    parser.add_argument("--output", default=str(OUTPUT_GPKG))
    args = parser.parse_args(argv)

    database = pathlib.Path(args.database)
    if not database.exists():
        print(f"no record at {database} — run 'make qgis-demo-record' first",
              file=sys.stderr)
        return 1

    store = ProvenanceStore(database)
    try:
        record = collect(store)
    finally:
        store.close()

    layers, summary = build_layers(record)
    output = geopkg.write_geopackage(args.output, layers)

    print(f"  wrote {pathlib.Path(output).relative_to(scenario.REPO_ROOT)}")
    for layer in layers:
        shape = layer.geometry_type or "no shape — a table only"
        print(f"    {layer.name:<34} {len(layer.rows):>3} rows   {shape}")
    print()
    print(f"  {summary['jobs']} jobs, {summary['files']} files "
          f"({summary['files_drawn']} drawn, "
          f"{summary['files_not_drawn']} with nowhere to go), "
          f"{summary['workflows']} group(s) of work")
    return 0


if __name__ == "__main__":
    sys.exit(main())
