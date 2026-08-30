"""PROV mapping, derivation inference, and export.

Owner: Person B (README "Person B — Provenance Modeling, Fingerprinting & Export").
Written by Person A under the explicit written override of RULES.md §1.2 [HARD]
requested on 30 Aug 2026, so that the workflow panel could be demonstrated.
Person B owns this file; A owns nothing in it.

    THIS MODULE IMPORTS NO QGIS and no GDAL, for the same reason
    geoprovenance/fingerprint/ does not: everything here is arithmetic over the
    dicts ProvenanceStore already returns, so it is testable in `make test` and
    usable by a demo running in a room with no QGIS (RULES.md §7.3).

Three jobs, in the order they are needed:

    ProvGraph          one workflow's rows, with the lookups the rest of the
                       project keeps re-deriving by hand.
    write_derivations  "this file came from that file" — the data-flow links
                       Person A's capture engine deliberately does not write
                       (RULES.md §5.12: A's grouping is temporal, B's is
                       data-flow, and they are different jobs).
    to_prov_json       the record in the interchange format, so the claim that
                       this is a standards-based tool is checkable.

Why there is no Entity/Activity/Agent class
    README asks Person B for "custom lightweight PROV model — Entity / Activity
    / Agent classes". `ProvenanceStore` already hands back exactly those three
    row shapes as plain dicts, and `get_workflow_graph()` hands back all of them
    together. Wrapping each in a dataclass that re-states the column names would
    add a second place for the schema to be written down and a translation layer
    to keep in step with it, for no behaviour. The model here is the graph and
    its lookups; the three classes are the dicts that already exist.
"""

from __future__ import annotations

from typing import Any, Iterable

#: PROV-JSON needs qualified names. Nothing dereferences this; it exists so an
#: external reader (ProvStore, PROV-Viewer) can tell our ids apart from its own.
NAMESPACE = "https://github.com/AaryanCode69/GeoProvenance#"
PREFIX = "gp"


class ProvGraph:
    """One workflow's rows, indexed.

    Built from ``ProvenanceStore.get_workflow_graph()``. Read-only — writing is
    ``write_derivations`` below, which goes through the store like everything
    Person B does (RULES.md §1.3: B never executes SQL).
    """

    def __init__(self, graph: dict[str, Any]):
        self.workflow = graph["workflow"]
        self.activities = graph["activities"]
        self.entities = graph["entities"]
        self.agents = graph["agents"]
        self.relations = graph["relations"]
        self._entity = {e["id"]: e for e in self.entities}
        self._agent = {a["id"]: a for a in self.agents}
        self._activity = {a["id"]: a for a in self.activities}

    @classmethod
    def load(cls, store, workflow_id: str) -> "ProvGraph":
        return cls(store.get_workflow_graph(workflow_id))

    # -- lookups -----------------------------------------------------------

    def entity(self, entity_id: str) -> dict[str, Any] | None:
        return self._entity.get(entity_id)

    def activity(self, activity_id: str) -> dict[str, Any] | None:
        return self._activity.get(activity_id)

    def _of_type(self, relation_type: str) -> Iterable[dict[str, Any]]:
        return (r for r in self.relations if r["relation_type"] == relation_type)

    def inputs_of(self, activity_id: str) -> list[dict[str, Any]]:
        """The files this job read, in the order they were recorded."""
        return [
            self._entity[r["target_id"]]
            for r in self._of_type("used")
            if r["source_id"] == activity_id and r["target_id"] in self._entity
        ]

    def outputs_of(self, activity_id: str) -> list[dict[str, Any]]:
        """The files this job created."""
        return [
            self._entity[r["source_id"]]
            for r in self._of_type("wasGeneratedBy")
            if r["target_id"] == activity_id and r["source_id"] in self._entity
        ]

    def agent_for(self, activity_id: str) -> dict[str, Any] | None:
        """The computer and software setup this job ran on."""
        for r in self._of_type("wasAssociatedWith"):
            if r["source_id"] == activity_id:
                return self._agent.get(r["target_id"])
        return None

    def derived_from(self, entity_id: str) -> list[dict[str, Any]]:
        """The files this file came from."""
        return [
            self._entity[r["target_id"]]
            for r in self._of_type("wasDerivedFrom")
            if r["source_id"] == entity_id and r["target_id"] in self._entity
        ]

    def made_by(self, entity_id: str) -> dict[str, Any] | None:
        """The job that created this file, if one did."""
        for r in self._of_type("wasGeneratedBy"):
            if r["source_id"] == entity_id:
                return self._activity.get(r["target_id"])
        return None


# ---------------------------------------------------------------------------
# Derivation inference
# ---------------------------------------------------------------------------


def infer_derivations(graph: ProvGraph) -> list[tuple[str, str]]:
    """``(output_id, input_id)`` pairs the data flow implies, ordered.

    Every output of a job is derived from every input of that job — the full
    cross-product, not just the first input.

    The research doc §7.3 worked example lists only the primary chain
    (``final_roads.shp`` derived from ``buffered_roads.shp``, but not from the
    ``city_boundary.shp`` it was clipped against), which understates the flow: a
    clip's result depends on the overlay just as much as on the layer being
    clipped, and an audit that missed that would report an input as irrelevant
    to a file it in fact shaped. The committed fixture agrees — `native:dissolve`
    reads two files there and carries a derivation row for both.

    Memory and temporary layers (``file_path IS NULL``) take part. They cannot
    be fingerprinted (docs/CONTRACT_event.md) but they are real nodes in the
    flow, and dropping them would break the chain either side of them.
    """
    pairs = []
    for activity in graph.activities:
        inputs = graph.inputs_of(activity["id"])
        for output in graph.outputs_of(activity["id"]):
            for source in inputs:
                if source["id"] != output["id"]:
                    pairs.append((output["id"], source["id"]))
    return pairs


def write_derivations(store, workflow_id: str) -> int:
    """Infer and persist. Returns how many links were NEW.

    Idempotent — it is called after every capture and on every panel refresh,
    and running it twice must not double the record. Existing links are read
    back from the graph rather than trusted from memory, so it is also safe
    across two processes.
    """
    graph = ProvGraph.load(store, workflow_id)
    existing = {
        (r["source_id"], r["target_id"])
        for r in graph.relations
        if r["relation_type"] == "wasDerivedFrom"
    }
    written = 0
    for output_id, source_id in infer_derivations(graph):
        if (output_id, source_id) in existing:
            continue
        store.add_relation(
            relation_type="wasDerivedFrom", source_id=output_id, target_id=source_id
        )
        existing.add((output_id, source_id))
        written += 1
    return written


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def to_record_json(graph: ProvGraph) -> dict[str, Any]:
    """The record in the research doc §7.3 shape — our own, not the standard's.

    Kept because §7.3 is what the project documented and what a reviewer will
    have read. ``to_prov_json`` below is the one an external tool can ingest.
    """
    return {
        "workflow": {
            "id": graph.workflow["id"],
            "name": graph.workflow["name"],
            "created_at": graph.workflow["created_at"],
        },
        "entities": [
            {
                "id": e["id"],
                "label": e["label"],
                "file_path": e["file_path"],
                "format": e["format"],
                "crs": e["crs"],
                "content_version": e["content_version"],
            }
            for e in graph.entities
        ],
        "activities": [
            {
                "id": a["id"],
                "algorithm_id": a["algorithm_id"],
                "algorithm_name": a["algorithm_name"],
                "started_at": a["started_at"],
                "ended_at": a["ended_at"],
                "status": a["status"],
                "parameters": a["parameters_json"],
            }
            for a in graph.activities
        ],
        "agents": [
            {
                "id": g["id"],
                "label": g["label"],
                "qgis_version": g["qgis_version"],
                "os": g["os_info"],
                "python_version": g["python_version"],
            }
            for g in graph.agents
        ],
        "relations": [
            {
                "type": r["relation_type"],
                "source": r["source_id"],
                "target": r["target_id"],
                "role": r["role"],
                "qgis_param_key": r["qgis_param_key"],
            }
            for r in graph.relations
        ],
    }


def _qname(node_id: str) -> str:
    return f"{PREFIX}:{node_id}"


def _without_nulls(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if v is not None}


#: How each relation row maps onto PROV-JSON's own two key names. The `relations`
#: table stores (source, target) in the direction the PROV term is written, so
#: this is a rename, never a swap.
_RELATION_KEYS = {
    "used": ("prov:activity", "prov:entity"),
    "wasGeneratedBy": ("prov:entity", "prov:activity"),
    "wasDerivedFrom": ("prov:generatedEntity", "prov:usedEntity"),
    "wasAssociatedWith": ("prov:activity", "prov:agent"),
    "wasAttributedTo": ("prov:entity", "prov:agent"),
}


def to_prov_json(graph: ProvGraph) -> dict[str, Any]:
    """The record as W3C PROV-JSON, for ingestion by an external PROV tool.

    Note the ``role`` values are LOWERCASE. The research doc §7.3 example writes
    ``"INPUT"`` and ``"OVERLAY"``, but RULES.md §3.2 decision 2 froze the
    vocabulary as lowercase with the original QGIS key kept beside it in its own
    column, and the schema has a CHECK constraint that enforces it. Copying §7.3
    verbatim would emit something the database it came from would refuse.
    """
    document: dict[str, Any] = {
        "prefix": {PREFIX: NAMESPACE, "prov": "http://www.w3.org/ns/prov#"},
        "entity": {
            _qname(e["id"]): _without_nulls(
                {
                    "prov:label": e["label"],
                    f"{PREFIX}:filePath": e["file_path"],
                    f"{PREFIX}:format": e["format"],
                    f"{PREFIX}:crs": e["crs"],
                    f"{PREFIX}:contentVersion": e["content_version"],
                }
            )
            for e in graph.entities
        },
        "activity": {
            _qname(a["id"]): _without_nulls(
                {
                    "prov:label": a["algorithm_name"] or a["algorithm_id"],
                    "prov:startTime": a["started_at"],
                    "prov:endTime": a["ended_at"],
                    f"{PREFIX}:algorithmId": a["algorithm_id"],
                    f"{PREFIX}:status": a["status"],
                }
            )
            for a in graph.activities
        },
        "agent": {
            _qname(g["id"]): _without_nulls(
                {
                    "prov:label": g["label"],
                    f"{PREFIX}:qgisVersion": g["qgis_version"],
                    f"{PREFIX}:os": g["os_info"],
                    f"{PREFIX}:pythonVersion": g["python_version"],
                }
            )
            for g in graph.agents
        },
    }

    for relation in graph.relations:
        keys = _RELATION_KEYS.get(relation["relation_type"])
        if keys is None:  # a relation type added to the schema but not here
            continue
        source_key, target_key = keys
        record = _without_nulls(
            {
                source_key: _qname(relation["source_id"]),
                target_key: _qname(relation["target_id"]),
                f"{PREFIX}:role": relation["role"],
                f"{PREFIX}:qgisParamKey": relation["qgis_param_key"],
            }
        )
        document.setdefault(relation["relation_type"], {})[
            _qname(relation["id"])
        ] = record

    return document
