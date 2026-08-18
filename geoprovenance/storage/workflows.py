"""Session -> workflow grouping.

Owner: Person A.  Sub-phase: A6.  RULES.md §4.1 — no QGIS imports.

What this does (§5.12)
    Activities sharing a ``session_id`` AND connected by shared dataset paths
    become one ``workflows`` row, with ``sequence_order`` set by ``started_at``.
    Plus a manual override: the "Start new workflow" / "Name this workflow"
    actions in the plugin menu.

What this does NOT do
    Person B independently infers ``wasDerivedFrom`` from input/output path
    overlap. That is DATA-FLOW based; this is TEMPORAL/SESSION based. Both are
    needed and they are different jobs — do not reimplement B's inference here
    (RULES.md §1.2, §5.12).

    The distinction is not academic, and it is visible in this file: the
    grouper treats a shared path as an UNDIRECTED edge — "these two jobs are
    related" — and never asks which job wrote it and which read it. That
    question is B's, and its answer is a ``wasDerivedFrom`` row. Reaching for
    direction here is the exact shape the boundary violation would take.

Why grouping is a recomputation, not an append
    Activities arrive one at a time, but whether two of them belong together
    can only be known once both exist — job 4 may write the file that job 1
    read, joining two groups that looked separate a moment ago. So grouping
    runs over a whole session and REPLACES what it computed before, rather
    than trying to place each activity as it lands. That is also why it is
    safe to run repeatedly: §5.1 means capture must never block on this, so it
    happens after the write, and possibly more than once.
"""

from __future__ import annotations

from typing import Any, Iterable

#: How a workflow with no better name is described. Kept plain-English
#: because it reaches a reviewer's eyes through the demo (§7.5).
UNNAMED = "Untitled work"

#: Beyond this many steps the auto-name summarises rather than lists.
NAME_STEP_LIMIT = 3


# ---------------------------------------------------------------------------
# connected components (pure — no store, no QGIS)
# ---------------------------------------------------------------------------

def _find(parents: dict[str, str], node: str) -> str:
    """Union-find root, with path compression."""
    root = node
    while parents[root] != root:
        root = parents[root]
    while parents[node] != root:
        parents[node], node = root, parents[node]
    return root


def connected_components(
    activity_ids: Iterable[str], links: Iterable[dict[str, Any]]
) -> list[list[str]]:
    """Group activity ids by shared dataset path.

    ``links`` is ``[{"activity_id": ..., "file_path": ...}, ...]`` — the rows
    ``ProvenanceStore.list_session_datasets`` returns. Two activities touching
    the same path land in the same group, transitively: A shares a file with
    B, B shares a different file with C, so A, B and C are one workflow.

    Groups come back in the order their members were given, and each group
    preserves that order — so a caller that passes activities sorted by
    ``started_at`` gets ``sequence_order`` for free (§5.12).

    An activity touching no files at all is its own group. That is the normal
    case for the history channel, which records that a run happened but
    attaches no datasets to it (A5, docs/capture_coverage.md §1) — such a job
    is genuinely unconnected on the evidence available, and inventing a link
    would be a guess.
    """
    ordered = list(activity_ids)
    parents: dict[str, str] = {aid: aid for aid in ordered}

    first_toucher: dict[str, str] = {}
    for link in links:
        activity_id = link.get("activity_id")
        file_path = link.get("file_path")
        if activity_id not in parents or not file_path:
            continue
        anchor = first_toucher.setdefault(file_path, activity_id)
        left, right = _find(parents, anchor), _find(parents, activity_id)
        if left != right:
            parents[right] = left

    groups: dict[str, list[str]] = {}
    for activity_id in ordered:
        groups.setdefault(_find(parents, activity_id), []).append(activity_id)
    return list(groups.values())


def suggest_name(activities: list[dict[str, Any]]) -> str:
    """A plain-English name for an auto-grouped workflow.

    Reaches a reviewer through the demo and the plugin menu, so it says
    "Buffer, then Clip", not "workflow 3f2a" (§7.5). The user can always
    replace it — that is what "Name this workflow" is for.
    """
    steps = [
        (a.get("algorithm_name") or a.get("algorithm_id") or "").strip()
        for a in activities
    ]
    steps = [s for s in steps if s]
    if not steps:
        return UNNAMED
    if len(steps) == 1:
        return steps[0]
    if len(steps) <= NAME_STEP_LIMIT:
        return ", then ".join(steps)
    return f"{steps[0]} to {steps[-1]} ({len(steps)} steps)"


# ---------------------------------------------------------------------------
# grouping one session
# ---------------------------------------------------------------------------

def group_session(store, session_id: str) -> list[str]:
    """Group one session's activities into workflows. Returns the workflow ids.

    Safe to run repeatedly: it reconciles against what is already stored
    rather than appending. Where a computed group overlaps existing
    workflows, the OLDEST of them is kept and the rest are deleted — so a
    name the user gave a workflow survives a later regrouping that merged
    another group into it. Their activities are untouched; only the grouping
    rows move (``delete_workflow`` cascades to membership, never to the
    record itself).

    A workflow whose name was auto-generated is renamed as it grows. One the
    user named is left alone — an explicit name outranks a computed one.
    """
    activities = store.list_activities_for_session(session_id)
    if not activities:
        return []

    by_id = {a["id"]: a for a in activities}
    groups = connected_components(
        [a["id"] for a in activities], store.list_session_datasets(session_id)
    )

    existing = {w["id"]: w for w in store.find_workflows_by_session(session_id)}
    workflow_of_activity: dict[str, str] = {}
    previous_members: dict[str, list[dict[str, Any]]] = {}
    for row in store.list_session_workflow_members(session_id):
        workflow_of_activity[row["activity_id"]] = row["workflow_id"]
        member = by_id.get(row["activity_id"])
        if member is not None:
            previous_members.setdefault(row["workflow_id"], []).append(member)

    workflow_ids: list[str] = []
    claimed: set[str] = set()

    for group in groups:
        # Oldest first, so a user-given name is the one that survives a merge.
        overlapping = [
            wid for wid in existing
            if wid in {workflow_of_activity.get(aid) for aid in group}
            and wid not in claimed
        ]
        members = [by_id[aid] for aid in group]
        name = suggest_name(members)

        if overlapping:
            workflow_id = overlapping[0]
            claimed.add(workflow_id)
            current = existing[workflow_id]
            if _was_auto_named(current, previous_members.get(workflow_id, [])):
                store.update_workflow(workflow_id, name=name)
            for merged in overlapping[1:]:
                store.delete_workflow(merged)
                claimed.add(merged)
        else:
            workflow_id = store.add_workflow(name=name, session_id=session_id)
            claimed.add(workflow_id)

        store.set_workflow_activities(workflow_id=workflow_id, activity_ids=group)
        workflow_ids.append(workflow_id)

    # A workflow left with nothing in it — every activity moved elsewhere —
    # is grouping residue, not a record, so it goes.
    for workflow_id in existing:
        if workflow_id not in claimed:
            store.delete_workflow(workflow_id)

    return workflow_ids


def _was_auto_named(workflow: dict[str, Any], previous: list[dict[str, Any]]) -> bool:
    """Did suggest_name produce this workflow's current name, or did a person?

    Decided by RECOMPUTING the suggestion for the membership the workflow had
    last time and comparing. Exact, where a "does this look auto-generated?"
    heuristic is not: a user who names a workflow "Flood risk" would have it
    silently overwritten on the next regrouping by any rule based on the
    shape of the string.

    Inferred rather than stored because a ``named_by_user`` column would be a
    §3.4 breaking change to two other people's work for a flag only this
    module reads.
    """
    name = (workflow.get("name") or "").strip()
    if not name or name == UNNAMED:
        return True
    return name == suggest_name(previous)


def name_workflow(store, workflow_id: str, name: str) -> None:
    """Give a workflow a name a person chose. Backs the plugin menu action.

    A blank name is ignored rather than stored: ``workflows.name`` is NOT
    NULL, and a workflow with an empty name reads as a bug in Person C's
    panel.
    """
    name = (name or "").strip()
    if not name:
        return
    store.update_workflow(workflow_id, name=name)
