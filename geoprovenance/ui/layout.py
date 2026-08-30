"""Where every node sits, and the same picture as plain text.

Owner: Person C (README "Person C — Visualization & Reproducibility Audit").
Written by Person A under the explicit written override of RULES.md §1.2 [HARD]
requested on 30 Aug 2026, so that the workflow panel could be demonstrated.
Person C owns this file; A owns nothing in it.

    THIS MODULE IMPORTS NO QT AND NO QGIS. The arrangement of the picture is
    arithmetic, and keeping it out of the widget is what lets `make test` check
    the branching case and what lets a demo print the same family tree it draws
    (RULES.md §6.1, §7.3). `ui/panel.py` is the thin half that needs Qt.

Shape of the picture (research doc §8.3 Week 7): a file is a rectangle, a job is
a circle, and they alternate down the page. Ranks run top to bottom by longest
path, so a file always sits below every job that could have produced it.
Deliberately not force-directed — research doc §12 risk 9 says so in as many
words, and a hand-rolled spring solver is exactly the kind of thing that eats a
week and then jitters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FILE, JOB = "file", "job"

#: Edge kinds, in the vocabulary of the picture rather than of the standard.
READ, WROTE, DERIVED = "read", "wrote", "derived"

#: Mirrors audit.MISSING / CHANGED / VERIFIED / UNKNOWN. Not imported from
#: there, because a layout is drawable with no audit having been run at all.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    label: str
    rank: int
    column: int
    status: str = UNKNOWN
    detail: str = ""


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    label: str = ""


@dataclass(frozen=True)
class Layout:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return max((n.rank for n in self.nodes), default=-1) + 1

    @property
    def width(self) -> int:
        return max((n.column for n in self.nodes), default=-1) + 1

    def node(self, node_id: str) -> Node | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def rows(self) -> list[list[Node]]:
        """Nodes grouped by rank, top row first, each row left to right."""
        rows: list[list[Node]] = [[] for _ in range(self.depth)]
        for node in sorted(self.nodes, key=lambda n: (n.rank, n.column)):
            rows[node.rank].append(node)
        return rows


def _rank_nodes(graph) -> dict[str, int]:
    """Longest path from the sources, by relaxation.

    A single pass in `sequence_order` would be right for anything the capture
    engine writes, since a job cannot read a file a later job made. It would be
    quietly wrong for a record assembled any other way, and the bound below
    costs nothing on graphs this size: fifteen operations is the largest
    workflow the experiments use (RULES.md §8.3).
    """
    rank = {a["id"]: 0 for a in graph.activities}
    rank.update({e["id"]: 0 for e in graph.entities})

    for _ in range(len(graph.activities) + 1):
        settled = True
        for activity in graph.activities:
            inputs = graph.inputs_of(activity["id"])
            want = max((rank[e["id"]] for e in inputs), default=-1) + 1
            if want > rank[activity["id"]]:
                rank[activity["id"]] = want
                settled = False
            for output in graph.outputs_of(activity["id"]):
                if rank[activity["id"]] + 1 > rank[output["id"]]:
                    rank[output["id"]] = rank[activity["id"]] + 1
                    settled = False
        if settled:
            break  # a cycle cannot settle; the bound above stops it anyway
    return rank


def build_layout(graph, statuses: dict[str, str] | None = None) -> Layout:
    """Arrange one workflow's files and jobs.

    ``statuses`` is ``AuditResult.file_status`` when an audit has been run, and
    is what colours the nodes. Absent, every node is `unknown` — which is the
    truth before anyone has checked.
    """
    statuses = statuses or {}
    rank = _rank_nodes(graph)

    #: Columns are assigned in first-appearance order within a rank, so the same
    #: record always draws the same picture. A demo has to be byte-identical run
    #: to run (RULES.md §7.2), and a set iteration here would break that.
    used_columns: dict[int, int] = {}

    def place(node_id: str) -> int:
        column = used_columns.get(rank[node_id], 0)
        used_columns[rank[node_id]] = column + 1
        return column

    nodes: list[Node] = []
    seen: set[str] = set()

    def add_entity(entity: dict[str, Any]) -> None:
        if entity["id"] in seen:
            return
        seen.add(entity["id"])
        nodes.append(Node(
            id=entity["id"], kind=FILE,
            label=entity["label"] or entity["file_path"] or "a temporary layer",
            rank=rank[entity["id"]], column=place(entity["id"]),
            status=statuses.get(entity["id"], UNKNOWN),
            detail=entity["file_path"] or "held in memory, never written to disk",
        ))

    # Walk in rank order so the columns read left-to-right down the page.
    for activity in sorted(graph.activities, key=lambda a: (rank[a["id"]],
                                                            a["started_at"])):
        for entity in graph.inputs_of(activity["id"]):
            add_entity(entity)
        seen.add(activity["id"])
        nodes.append(Node(
            id=activity["id"], kind=JOB,
            label=activity["algorithm_name"] or activity["algorithm_id"],
            rank=rank[activity["id"]], column=place(activity["id"]),
            status=UNKNOWN, detail=activity["algorithm_id"],
        ))
        for entity in graph.outputs_of(activity["id"]):
            add_entity(entity)

    for entity in graph.entities:  # anything nothing touched, so nothing is lost
        add_entity(entity)

    edges = []
    for relation in graph.relations:
        if relation["relation_type"] == "used":
            edges.append(Edge(relation["target_id"], relation["source_id"], READ,
                              relation["role"] or ""))
        elif relation["relation_type"] == "wasGeneratedBy":
            edges.append(Edge(relation["target_id"], relation["source_id"], WROTE))
        elif relation["relation_type"] == "wasDerivedFrom":
            edges.append(Edge(relation["target_id"], relation["source_id"], DERIVED))

    known = {n.id for n in nodes}
    return Layout(nodes=nodes,
                  edges=[e for e in edges if e.source in known and e.target in known])


#: What each status looks like with no colour available. RULES.md §7.5 — these
#: are read aloud, so they are words rather than symbols.
_STATUS_TEXT = {
    "missing": "  (gone)",
    "changed": "  (changed since)",
    "verified": "",
    UNKNOWN: "",
}


def as_text(layout: Layout, graph) -> str:
    """The same picture as an indented family tree, for a demo or a log.

    Walks forwards from each file nothing made, so the reading order is the
    order the work happened in. A file read by two jobs appears under both,
    which is what a family tree does and is more useful here than an
    arbitrary choice of one parent.
    """
    made = {e.target for e in layout.edges if e.kind == WROTE}
    readers: dict[str, list[str]] = {}
    for edge in layout.edges:
        if edge.kind == READ:
            readers.setdefault(edge.source, []).append(edge.target)
    products: dict[str, list[str]] = {}
    for edge in layout.edges:
        if edge.kind == WROTE:
            products.setdefault(edge.source, []).append(edge.target)

    lines: list[str] = []
    visited: set[str] = set()

    def walk(node_id: str, depth: int, path: tuple[str, ...]) -> None:
        node = layout.node(node_id)
        if node is None or node_id in path:
            return  # a record that loops back on itself is not ours to draw
        visited.add(node_id)
        lines.append("   " * depth + node.label + _STATUS_TEXT.get(node.status, ""))
        children = (readers if node.kind == FILE else products).get(node_id, [])
        for child in children:
            walk(child, depth + 1, path + (node_id,))

    for root in sorted(layout.nodes, key=lambda n: (n.rank, n.column)):
        if root.kind == FILE and root.id not in made:
            walk(root.id, 0, ())

    # A job that touched no files still happened, and a capture record that
    # quietly omitted it would be worse than one that says it knows less.
    for node in sorted(layout.nodes, key=lambda n: (n.rank, n.column)):
        if node.kind == JOB and node.id not in visited:
            lines.append(node.label + "   (we know it ran, but not on what)")

    return "\n".join(lines)
