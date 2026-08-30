"""Person C's layout: ranks, columns, and the plain-text family tree.

RULES.md §6.1 — no Qt and no QGIS in this file. That is the point of splitting
the arrangement out of the widget.
"""

from __future__ import annotations

import pytest

from geoprovenance import prov
from geoprovenance.ui import layout as L

BRANCHING = "Points analysis (branching)"


@pytest.fixture()
def branching(recorded_store):
    """The fixture's five-step branching workflow, with its derivation links."""
    workflow = next(w for w in recorded_store.list_workflows()
                    if w["name"] == BRANCHING)
    return prov.ProvGraph.load(recorded_store, workflow["id"])


def _label(layout, kind):
    return [n.label for n in sorted(layout.nodes, key=lambda n: (n.rank, n.column))
            if n.kind == kind]


# ---------------------------------------------------------------------------
# Ranks
# ---------------------------------------------------------------------------


def test_files_and_jobs_alternate_down_the_page(branching):
    """A file is always one rank below the job that made it."""
    layout = L.build_layout(branching)
    for edge in layout.edges:
        if edge.kind == L.WROTE:  # job -> file
            assert layout.node(edge.target).rank == layout.node(edge.source).rank + 1


def test_a_file_sits_below_every_job_that_could_have_made_it(branching):
    """The longest-path rule, which is why relaxation is used and not one pass."""
    layout = L.build_layout(branching)
    for edge in layout.edges:
        if edge.kind == L.READ:  # file -> job
            assert layout.node(edge.source).rank < layout.node(edge.target).rank


def test_the_branch_puts_both_children_on_the_same_row_in_different_columns(
    branching,
):
    """One job makes two files that go different ways (RULES.md §6.6)."""
    layout = L.build_layout(branching)
    urban = layout.node(next(n.id for n in layout.nodes if n.label == "urban.shp"))
    not_urban = layout.node(
        next(n.id for n in layout.nodes if n.label == "not_urban.shp")
    )
    assert urban.rank == not_urban.rank
    assert urban.column != not_urban.column


def test_no_two_nodes_share_a_cell(branching):
    layout = L.build_layout(branching)
    cells = [(n.rank, n.column) for n in layout.nodes]
    assert len(cells) == len(set(cells))


def test_every_file_and_job_is_drawn(branching):
    layout = L.build_layout(branching)
    assert len(_label(layout, L.JOB)) == len(branching.activities)
    assert len(_label(layout, L.FILE)) == len(branching.entities)


def test_the_same_record_always_draws_the_same_picture(branching):
    """RULES.md §7.2 — a demo run twice must print the same thing."""
    first = L.build_layout(branching)
    assert first == L.build_layout(branching)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_colours_come_from_the_audit_and_default_to_unknown(branching):
    plain = L.build_layout(branching)
    assert {n.status for n in plain.nodes} == {L.UNKNOWN}

    target = next(n for n in plain.nodes if n.kind == L.FILE)
    graded = L.build_layout(branching, statuses={target.id: "changed"})
    assert graded.node(target.id).status == "changed"


def test_a_memory_layer_says_so_rather_than_showing_an_empty_path(store):
    with store.transaction():
        temp = store.add_entity(label="Clipped (temporary)", file_path=None)
        activity = store.add_activity(algorithm_id="native:clip",
                                      started_at="2026-08-08T10:14:22.481903+00:00",
                                      parameters={})
        store.add_relation(relation_type="wasGeneratedBy", source_id=temp,
                           target_id=activity, role="output")
        workflow = store.add_workflow(name="Into memory")
        store.set_workflow_activities(workflow_id=workflow, activity_ids=[activity])

    layout = L.build_layout(prov.ProvGraph.load(store, workflow))
    assert layout.node(temp).detail == "held in memory, never written to disk"


# ---------------------------------------------------------------------------
# The plain-text tree
# ---------------------------------------------------------------------------


def test_the_text_tree_reads_from_the_starting_file_downwards(branching):
    text = L.as_text(L.build_layout(branching), branching)
    lines = text.splitlines()

    assert lines[0] == "sample_points.shp"          # nothing made it: a root
    assert lines[1] == "   Buffer"                  # the job that read it
    assert lines[2] == "      points_buffered.shp"  # what that job made

    # Both halves of the branch are shown, each under the job that made them.
    assert any(line.strip() == "urban.shp" for line in lines)
    assert any(line.strip() == "not_urban.shp" for line in lines)


def test_a_changed_file_is_marked_in_the_text(branching):
    changed = next(n for n in L.build_layout(branching).nodes
                   if n.label == "sample_points.shp")
    text = L.as_text(
        L.build_layout(branching, statuses={changed.id: "changed"}), branching
    )
    assert text.splitlines()[0] == "sample_points.shp  (changed since)"


def test_a_job_that_touched_no_files_is_still_mentioned(store):
    """RULES.md §4.10 — the history channel records that a job ran even when it
    could not tell us what it ran on. Dropping it from the picture would be the
    one thing a capture record must never do."""
    with store.transaction():
        activity = store.add_activity(algorithm_id="native:buffer",
                                      algorithm_name="Buffer",
                                      started_at="2026-08-08T10:14:22.481903+00:00",
                                      parameters={})
        workflow = store.add_workflow(name="Just a job")
        store.set_workflow_activities(workflow_id=workflow, activity_ids=[activity])

    graph = prov.ProvGraph.load(store, workflow)
    assert L.as_text(L.build_layout(graph), graph) == (
        "Buffer   (we know it ran, but not on what)"
    )


def test_the_text_tree_carries_no_jargon(branching):
    """RULES.md §7.5 — a demo prints this, so it faces the same lint."""
    import pathlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "demos"))
    from _presenter import lint

    assert lint(L.as_text(L.build_layout(branching), branching)) == []
