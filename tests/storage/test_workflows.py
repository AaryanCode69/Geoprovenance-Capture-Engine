"""Session -> workflow grouping (A6).

No QGIS — RULES.md §6.1, and workflows.py lives under storage/ which imports
none by rule (§4.1).

The claim these tests exist to defend is Review 2's: "a whole 4-step workflow
was captured, in the right order, with nothing missing."
"""

from __future__ import annotations

import pytest

from geoprovenance.storage import workflows as w

SESSION = "11111111-1111-4111-8111-111111111111"


def _link(activity_id, file_path):
    return {"activity_id": activity_id, "file_path": file_path}


def _activity(store, algorithm_id, name, *, minute, session_id=SESSION):
    return store.add_activity(
        algorithm_id=algorithm_id,
        algorithm_name=name,
        session_id=session_id,
        started_at=f"2026-08-08T10:{minute:02d}:00.000000+00:00",
        ended_at=f"2026-08-08T10:{minute:02d}:30.000000+00:00",
    )


def _entity(store, path, *, writing):
    """Resolve a path to an entity the way the engine does.

    Mirrors ProvenanceCaptureEngine._entity_for_path: identity is
    ``(file_path, content_version)`` (Appendix B.1), so the same path cannot
    simply be inserted twice. A job READING a file on record reuses that row;
    a job WRITING one that is already on record mints the next content
    version. Without this a chain — job 2 reads what job 1 wrote — fails the
    entities UNIQUE constraint before the grouping under test even runs.
    """
    existing = store.find_entity_by_path(path)
    if existing is not None and not writing:
        return existing["id"]
    return store.add_entity(
        file_path=path,
        label=path.rsplit("/", 1)[-1],
        content_version=store.next_content_version(path),
    )


def _chain(store, steps, *, session_id=SESSION):
    """Build a linear chain: each step reads what the previous one wrote."""
    ids = []
    for index, (algorithm_id, name, source, written) in enumerate(steps):
        activity_id = _activity(store, algorithm_id, name,
                                minute=index, session_id=session_id)
        for path, relation, role in ((source, "used", "input"),
                                     (written, "wasGeneratedBy", "output")):
            entity = _entity(store, path, writing=relation == "wasGeneratedBy")
            if relation == "used":
                store.add_relation(relation_type=relation, source_id=activity_id,
                                   target_id=entity, role=role)
            else:
                store.add_relation(relation_type=relation, source_id=entity,
                                   target_id=activity_id, role=role)
        ids.append(activity_id)
    return ids


FOUR_STEPS = [
    ("native:buffer", "Buffer", "/d/roads.shp", "/w/buffered.shp"),
    ("native:clip", "Clip", "/w/buffered.shp", "/w/clipped.shp"),
    ("native:dissolve", "Dissolve", "/w/clipped.shp", "/w/dissolved.shp"),
    ("qgis:centroids", "Centroids", "/w/dissolved.shp", "/out/final.shp"),
]


# ===========================================================================
# connected_components — pure, no store
# ===========================================================================

def test_jobs_sharing_a_file_are_one_group():
    groups = w.connected_components(["a", "b"], [_link("a", "/x.shp"), _link("b", "/x.shp")])
    assert groups == [["a", "b"]]


def test_the_link_is_transitive():
    """A shares a file with B, B shares a different file with C — one workflow.
    This is what makes a 4-step chain a chain rather than three pairs."""
    groups = w.connected_components(
        ["a", "b", "c"],
        [_link("a", "/x"), _link("b", "/x"), _link("b", "/y"), _link("c", "/y")],
    )
    assert groups == [["a", "b", "c"]]


def test_jobs_sharing_nothing_stay_separate():
    groups = w.connected_components(["a", "b"], [_link("a", "/x"), _link("b", "/y")])
    assert groups == [["a"], ["b"]]


def test_a_job_touching_no_files_is_its_own_group():
    """The normal case for the history channel, which records that a run
    happened but attaches no datasets (A5). Inventing a link would be a guess."""
    assert w.connected_components(["a"], []) == [["a"]]


def test_group_order_follows_the_order_given():
    """The caller passes activities sorted by started_at, so sequence_order
    comes out right for free (§5.12)."""
    groups = w.connected_components(
        ["first", "second", "third"],
        [_link("first", "/x"), _link("third", "/x")],
    )
    assert groups == [["first", "third"], ["second"]]


def test_links_to_unknown_activities_are_ignored():
    assert w.connected_components(["a"], [_link("ghost", "/x")]) == [["a"]]


def test_a_null_path_never_links_anything():
    """Memory and temporary layers have path=None (§3.3). Treating them as a
    shared file would merge every unrelated job that used a scratch layer."""
    groups = w.connected_components(["a", "b"], [_link("a", None), _link("b", None)])
    assert groups == [["a"], ["b"]]


def test_a_branch_is_one_workflow():
    """One job writing two outputs, each feeding a different downstream step.
    Person C's layout needs this to be a single non-linear graph."""
    groups = w.connected_components(
        ["split", "left", "right"],
        [_link("split", "/a"), _link("left", "/a"),
         _link("split", "/b"), _link("right", "/b")],
    )
    assert groups == [["split", "left", "right"]]


# ===========================================================================
# suggest_name — reviewer-facing, so plain English (§7.5)
# ===========================================================================

def test_one_step_is_named_for_its_algorithm():
    assert w.suggest_name([{"algorithm_name": "Buffer"}]) == "Buffer"


def test_a_short_chain_lists_its_steps():
    assert w.suggest_name(
        [{"algorithm_name": "Buffer"}, {"algorithm_name": "Clip"}]
    ) == "Buffer, then Clip"


def test_a_long_chain_is_summarised():
    names = [{"algorithm_name": n} for n in ("Buffer", "Clip", "Dissolve", "Centroids")]
    assert w.suggest_name(names) == "Buffer to Centroids (4 steps)"


def test_the_algorithm_id_stands_in_when_there_is_no_name():
    assert w.suggest_name([{"algorithm_id": "native:buffer"}]) == "native:buffer"


def test_a_nameless_workflow_still_gets_something_printable():
    """workflows.name is NOT NULL, and an empty name reads as a bug in
    Person C's panel."""
    assert w.suggest_name([{}]) == w.UNNAMED
    assert w.suggest_name([]) == w.UNNAMED


# ===========================================================================
# group_session — the Review 2 claim
# ===========================================================================

def test_a_four_step_chain_becomes_one_workflow_in_the_right_order(store):
    """Review 2, in one test: all four steps, one workflow, correct order."""
    ids = _chain(store, FOUR_STEPS)
    workflow_ids = w.group_session(store, SESSION)

    assert len(workflow_ids) == 1
    graph = store.get_workflow_graph(workflow_ids[0])
    assert [a["id"] for a in graph["activities"]] == ids
    assert [a["sequence_order"] for a in graph["activities"]] == [0, 1, 2, 3]
    assert [a["algorithm_name"] for a in graph["activities"]] == [
        "Buffer", "Clip", "Dissolve", "Centroids"
    ]


def test_an_unrelated_job_in_the_same_session_is_its_own_workflow(store):
    _chain(store, FOUR_STEPS)
    _chain(store, [("native:reproject", "Reproject", "/o/dem.tif", "/o/dem2.tif")])

    assert len(w.group_session(store, SESSION)) == 2


def test_regrouping_is_idempotent(store):
    """Grouping runs after every capture, so it must be safe to repeat —
    the membership primary key would otherwise fail on the second pass."""
    _chain(store, FOUR_STEPS)
    first = w.group_session(store, SESSION)
    second = w.group_session(store, SESSION)

    assert first == second
    assert len(store.get_workflow_graph(first[0])["activities"]) == 4


def test_a_later_job_can_join_two_groups_that_looked_separate(store):
    """The reason grouping is a recomputation rather than an append: job 3
    writes nothing new but reads from both halves, merging them."""
    _chain(store, [("native:buffer", "Buffer", "/a.shp", "/b.shp")])
    _chain(store, [("native:clip", "Clip", "/c.shp", "/d.shp")])
    assert len(w.group_session(store, SESSION)) == 2

    joiner = _activity(store, "native:merge", "Merge", minute=5)
    for path in ("/b.shp", "/d.shp"):
        entity = store.find_entity_by_path(path)["id"]
        store.add_relation(relation_type="used", source_id=joiner,
                           target_id=entity, role="input")

    merged = w.group_session(store, SESSION)
    assert len(merged) == 1
    assert len(store.get_workflow_graph(merged[0])["activities"]) == 3


def test_a_merge_keeps_the_name_a_person_gave(store):
    """The whole point of the merge policy: a user-given name must survive a
    later regrouping that absorbs another group into it."""
    _chain(store, [("native:buffer", "Buffer", "/a.shp", "/b.shp")])
    _chain(store, [("native:clip", "Clip", "/c.shp", "/d.shp")])
    first, _ = w.group_session(store, SESSION)
    w.name_workflow(store, first, "Flood risk")

    joiner = _activity(store, "native:merge", "Merge", minute=5)
    for path in ("/b.shp", "/d.shp"):
        store.add_relation(relation_type="used", source_id=joiner,
                           target_id=store.find_entity_by_path(path)["id"],
                           role="input")

    merged = w.group_session(store, SESSION)
    assert store.get_workflow(merged[0])["name"] == "Flood risk"


def test_an_auto_named_workflow_is_renamed_as_it_grows(store):
    """A name nobody chose should keep describing what the workflow now is."""
    _chain(store, FOUR_STEPS[:1])
    workflow_id = w.group_session(store, SESSION)[0]
    assert store.get_workflow(workflow_id)["name"] == "Buffer"

    _chain(store, FOUR_STEPS[1:2])
    w.group_session(store, SESSION)
    assert store.get_workflow(workflow_id)["name"] == "Buffer, then Clip"


def test_a_short_user_name_is_not_mistaken_for_a_generated_one(store):
    """The regression test for the heuristic this deliberately does not use:
    'Flood risk' is short and two words, so any shape-based rule would have
    silently overwritten it."""
    _chain(store, FOUR_STEPS[:1])
    workflow_id = w.group_session(store, SESSION)[0]
    w.name_workflow(store, workflow_id, "Flood risk")

    _chain(store, FOUR_STEPS[1:2])
    w.group_session(store, SESSION)
    assert store.get_workflow(workflow_id)["name"] == "Flood risk"


def test_jobs_in_different_sessions_never_group_together(store):
    """Appendix B.5 — session_id is the grouping key, and it is what makes
    'Start new workflow' work at all."""
    _chain(store, FOUR_STEPS[:2], session_id="session-a")
    _chain(store, FOUR_STEPS[2:], session_id="session-b")

    assert len(w.group_session(store, "session-a")) == 1
    assert len(w.group_session(store, "session-b")) == 1


def test_a_rewritten_file_still_links_the_two_jobs(store):
    """Appendix B.1 meeting §5.12: a file overwritten by a later job becomes a
    NEW row — same path, next content version — so the two jobs no longer
    share an entity id. They must still land in one workflow, because grouping
    links on the PATH and not on the row. Get this wrong and re-running a
    workflow over its own outputs silently splits it in two.
    """
    _chain(store, [("native:buffer", "Buffer", "/a.shp", "/b.shp")])
    rewriter = _activity(store, "native:dissolve", "Dissolve", minute=5)
    store.add_relation(
        relation_type="wasGeneratedBy",
        source_id=_entity(store, "/b.shp", writing=True),
        target_id=rewriter,
        role="output",
    )

    versions = store.list_entity_versions("/b.shp")
    assert [e["content_version"] for e in versions] == [1, 2]

    workflow_ids = w.group_session(store, SESSION)
    assert len(workflow_ids) == 1
    assert len(store.get_workflow_graph(workflow_ids[0])["activities"]) == 2


def test_an_empty_session_produces_no_workflows(store):
    assert w.group_session(store, "nothing-here") == []


def test_a_failed_job_is_grouped_like_any_other(store):
    """§4.10 — failed runs are part of the record, and Person C's audit needs
    to see them in the workflow they belong to."""
    activity_id = store.add_activity(
        algorithm_id="gdal:warpreproject", algorithm_name="Warp",
        session_id=SESSION, started_at="2026-08-08T10:00:00.000000+00:00",
        status="failed",
    )
    workflow_id = w.group_session(store, SESSION)[0]
    assert [a["id"] for a in store.get_workflow_graph(workflow_id)["activities"]] == [
        activity_id
    ]


def test_naming_a_workflow_moves_its_updated_at(store):
    _chain(store, FOUR_STEPS[:1])
    workflow_id = w.group_session(store, SESSION)[0]
    before = store.get_workflow(workflow_id)["updated_at"]

    w.name_workflow(store, workflow_id, "Flood risk")
    assert store.get_workflow(workflow_id)["updated_at"] >= before


def test_a_blank_name_is_ignored_rather_than_stored(store):
    _chain(store, FOUR_STEPS[:1])
    workflow_id = w.group_session(store, SESSION)[0]

    w.name_workflow(store, workflow_id, "   ")
    assert store.get_workflow(workflow_id)["name"] == "Buffer"
