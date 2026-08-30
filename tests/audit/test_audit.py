"""Person C's reproducibility audit.

The cases that matter are the ones where the score should NOT be 100: a file
that moved, a file that was edited, a QGIS that was upgraded, and a check that
could not be run at all.

RULES.md §6.1 — no QGIS anywhere in this file. The two checks that need a
Processing registry are injected, which is why they are testable here.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "fixtures"))

import _minifiles  # noqa: E402

from geoprovenance import audit  # noqa: E402
from geoprovenance.fingerprint import hash as hashing  # noqa: E402

FIELDS = [("NAME", "C", 12), ("KIND", "C", 8)]


def _write_points(base, kinds):
    return _minifiles.write_point_shapefile(
        base,
        [(1.0 + i, 2.0 + i) for i in range(len(kinds))],
        [{"NAME": f"p{i}", "KIND": kind} for i, kind in enumerate(kinds)],
        FIELDS,
    )


@pytest.fixture()
def captured(store, tmp_path):
    """One recorded job: Buffer read points.shp and wrote buffered.shp.

    Both files really exist and both are fingerprinted the way capture would
    fingerprint them, so the audit has something true to compare against.
    """
    source = tmp_path / "points.shp"
    output = tmp_path / "buffered.shp"
    _write_points(source, ["urban", "rural", "urban"])
    _write_points(output, ["urban", "rural", "urban"])

    agent = store.get_or_create_agent(
        qgis_version="3.34.8", os_info="Ubuntu 22.04", python_version="3.10.12"
    )
    with store.transaction():
        points = store.add_entity(label="points.shp", file_path=str(source),
                                  format="Shapefile", crs="EPSG:4326")
        buffered = store.add_entity(label="buffered.shp", file_path=str(output),
                                    format="Shapefile", crs="EPSG:4326")
        activity = store.add_activity(
            algorithm_id="native:buffer", algorithm_name="Buffer",
            started_at="2026-08-08T10:14:22.481903+00:00",
            ended_at="2026-08-08T10:14:23.004117+00:00",
            parameters={"DISTANCE": 500},
        )
        store.add_relation(relation_type="used", source_id=activity,
                           target_id=points, role="input", qgis_param_key="INPUT")
        store.add_relation(relation_type="wasGeneratedBy", source_id=buffered,
                           target_id=activity, role="output")
        store.add_relation(relation_type="wasAssociatedWith", source_id=activity,
                           target_id=agent)
        workflow = store.add_workflow(name="Buffer the points")
        store.set_workflow_activities(workflow_id=workflow, activity_ids=[activity])

    for entity, path in ((points, source), (buffered, output)):
        store.add_fingerprints(
            entity_id=entity, fingerprints=hashing.fingerprint_dataset(path)
        )
    return {"workflow": workflow, "source": source, "points": points}


def _audit(store, workflow, *, installed=True, accepts={"DISTANCE"}, qgis="3.34.8"):
    """Stand in for the Processing registry this machine does not have."""
    return audit.audit_workflow(
        store, workflow,
        algorithm_probe=lambda _: installed,
        parameter_names=lambda _: accepts,
        current_qgis=qgis,
    )


# ---------------------------------------------------------------------------


def test_an_untouched_workflow_scores_full_marks(store, captured):
    result = _audit(store, captured["workflow"])
    assert result.components == {name: 100.0 for name in audit.WEIGHTS}
    assert result.overall == 100.0
    assert result.band == audit.HIGH


def test_a_missing_input_fails_that_check_and_voids_the_contents_check(store, captured):
    """A file that is gone cannot also be compared against what it used to hold.

    So losing an input costs more than its own 30%: the 25% contents check drops
    out of the score entirely rather than being awarded to a file nobody can
    read. 0 out of the 75 points still answerable is 60.
    """
    for path in captured["source"].parent.glob("points.*"):
        path.unlink()

    result = _audit(store, captured["workflow"])
    assert result.components["input_exists"] == 0.0
    assert result.components["input_unchanged"] is None
    assert result.overall == pytest.approx(60.0)
    assert "no longer where we left it" in result.reasons("input_exists")[0]


def test_an_edited_input_is_caught_and_named(store, captured):
    """The audit's whole purpose: the file is still there, and it is different."""
    _write_points(captured["source"], ["urban", "URBAN", "urban"])

    result = _audit(store, captured["workflow"])
    assert result.components["input_exists"] == 100.0
    assert result.components["input_unchanged"] == 0.0
    assert result.overall == pytest.approx(75.0)
    assert "points.shp" in result.reasons("input_unchanged")[0]


def test_a_rewritten_but_identical_file_still_counts_as_unchanged(store, captured):
    """A re-save is not an edit.

    Rewriting the same points produces the same bytes here, but the check that
    matters is that the verdict comes from the whole fingerprint set rather than
    a bare byte comparison — `resaved` scores as unchanged
    (docs/CONTRACT_schema.md, 2026-08-30).
    """
    _write_points(captured["source"], ["urban", "rural", "urban"])
    assert _audit(store, captured["workflow"]).components["input_unchanged"] == 100.0


def test_a_qgis_upgrade_costs_the_environment_component(store, captured):
    result = _audit(store, captured["workflow"], qgis="3.40.0")
    assert result.components["environment_similar"] == 0.0
    assert result.overall == pytest.approx(85.0)
    assert result.reasons("environment_similar") == ["QGIS 3.34.8 then, QGIS 3.40.0 now"]


def test_a_point_release_is_the_same_environment(store, captured):
    """3.34.8 -> 3.34.15 is a patch, not the upgrade §4.3 means by 'major'."""
    result = _audit(store, captured["workflow"], qgis="3.34.15")
    assert result.components["environment_similar"] == 100.0


def test_a_missing_tool_costs_its_weight(store, captured):
    result = _audit(store, captured["workflow"], installed=False)
    assert result.components["algorithm_available"] == 0.0
    # Settings cannot be validated against a tool that is not installed.
    assert result.components["parameters_valid"] is None
    assert result.overall == 77.8  # 70 of the 90 points still answerable


# ---------------------------------------------------------------------------
# The honesty rule: an unrun check is never a pass
# ---------------------------------------------------------------------------


def test_checks_that_could_not_run_are_null_and_do_not_inflate_the_score(
    store, captured
):
    """Outside QGIS there is no Processing registry, so two checks are unanswerable.

    Scoring them 100 would report perfect reproducibility for every workflow
    ever audited offline. The score is the weighted mean over the checks that
    actually ran, and the report says so.
    """
    result = audit.audit_workflow(
        store, captured["workflow"], algorithm_probe=lambda _: None,
        current_qgis="3.34.8",
    )
    assert result.components["algorithm_available"] is None
    assert result.components["parameters_valid"] is None
    assert result.overall == 100.0  # over the 70% of weight that could be scored
    assert "needs QGIS" in audit.report(result)


def test_a_workflow_nothing_can_be_checked_on_scores_zero_not_a_crash(store):
    with store.transaction():
        activity = store.add_activity(algorithm_id="native:buffer",
                                      started_at="2026-08-08T10:14:22.481903+00:00",
                                      parameters={})
        workflow = store.add_workflow(name="Nothing to go on")
        store.set_workflow_activities(workflow_id=workflow, activity_ids=[activity])

    result = audit.audit_workflow(store, workflow, algorithm_probe=lambda _: None,
                                  current_qgis="unknown")
    assert set(result.components.values()) == {None}
    assert result.overall == 0.0
    assert result.band == audit.LOW


def test_a_memory_layer_is_not_a_missing_file(store):
    """A temporary layer was never on disk; its absence is not an audit finding."""
    with store.transaction():
        temp = store.add_entity(label="Clipped (temporary)", file_path=None)
        activity = store.add_activity(algorithm_id="native:clip",
                                      started_at="2026-08-08T10:14:22.481903+00:00",
                                      parameters={})
        store.add_relation(relation_type="used", source_id=activity,
                           target_id=temp, role="input")
        workflow = store.add_workflow(name="From memory")
        store.set_workflow_activities(workflow_id=workflow, activity_ids=[activity])

    result = audit.audit_workflow(store, workflow, algorithm_probe=lambda _: True,
                                  current_qgis="3.34.8")
    assert result.components["input_exists"] is None


# ---------------------------------------------------------------------------
# Persistence and reports
# ---------------------------------------------------------------------------


def test_the_score_is_stored_through_person_as_writer(store, captured):
    result = _audit(store, captured["workflow"], qgis="3.40.0")
    audit.persist(store, result)

    stored = store.list_audit_results(captured["workflow"])
    assert len(stored) == 1
    assert stored[0]["overall_score"] == pytest.approx(85.0)
    assert stored[0]["environment_similar_score"] == 0.0
    # 85.0 sits exactly on the HIGH threshold, which is inclusive.
    assert json.loads(stored[0]["details_json"])["band"] == audit.HIGH


def test_an_unrun_check_is_stored_as_null_not_as_a_number(store, captured):
    result = audit.audit_workflow(store, captured["workflow"],
                                  algorithm_probe=lambda _: None,
                                  current_qgis="3.34.8")
    audit.persist(store, result)
    assert store.list_audit_results(captured["workflow"])[0][
        "algorithm_available_score"
    ] is None


def test_the_report_names_the_file_that_changed(store, captured):
    _write_points(captured["source"], ["urban", "URBAN", "urban"])
    result = _audit(store, captured["workflow"])

    text = audit.report(result)
    assert "OVERALL REPRODUCIBILITY SCORE: 75/100 (MODERATE)" in text
    assert "points.shp" in text


def test_the_plain_report_carries_no_jargon(store, captured):
    """RULES.md §7.5 — this is the variant a demo prints, so it must survive
    the same lint the demo output does."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "demos"))
    from _presenter import lint

    _write_points(captured["source"], ["urban", "URBAN", "urban"])
    text = audit.plain_report(_audit(store, captured["workflow"]))
    assert lint(text) == []
    assert "75 out of 100" in text


def test_every_file_gets_a_status_for_the_panel_to_colour(store, captured):
    """Research doc §4.3 Layer 4 colours nodes verified / changed / missing.

    Outputs are graded too even though nothing scores them: a reviewer looking
    at the picture wants to see which of the RESULTS have since been touched,
    not only which of the inputs.
    """
    _write_points(captured["source"], ["urban", "URBAN", "urban"])
    result = _audit(store, captured["workflow"])

    assert result.file_status[captured["points"]] == audit.CHANGED
    assert set(result.file_status.values()) == {audit.CHANGED, audit.VERIFIED}
    assert len(result.file_status) == 2  # the input and the output it made


def test_each_file_is_read_once_however_many_jobs_touch_it(store, captured, monkeypatch):
    """A ten-step chain must not re-hash the same file ten times."""
    calls = []
    real = audit.hashing.fingerprint_dataset
    monkeypatch.setattr(
        audit.hashing, "fingerprint_dataset",
        lambda path, **kw: (calls.append(path), real(path, **kw))[1],
    )
    _audit(store, captured["workflow"])
    assert len(calls) == len(set(calls))
