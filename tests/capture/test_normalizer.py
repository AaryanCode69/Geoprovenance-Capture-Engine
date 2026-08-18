"""The event normalizer — RULES.md §5.5-§5.9, §3.3.

No QGIS. Parameter serialisation is "the single biggest source of crashes in
this component" (PERSON_A.md §A4), so it gets real tests rather than hopeful
ones.
"""

from __future__ import annotations

import json
import math
import pathlib

import pytest

from geoprovenance.capture import normalizer as n

from fakes import (
    Explosive,
    FakeAlgorithmDefinitions,
    FakeCrs,
    FakeOutputDefinition,
    FakeProperty,
    FakeRasterLayer,
    FakeSourceDefinition,
    FakeVectorLayer,
    Unreprable,
)


# ===========================================================================
# §5.5 — parameter flattening never raises
# ===========================================================================

def test_primitives_pass_through():
    assert n.flatten_value(500) == 500
    assert n.flatten_value(1.5) == 1.5
    assert n.flatten_value("roads") == "roads"
    assert n.flatten_value(True) is True
    assert n.flatten_value(None) is None


def test_non_finite_floats_become_strings():
    """json.dumps will happily emit NaN, but NaN is not valid JSON and Person B
    parses these with a standard parser."""
    assert isinstance(n.flatten_value(float("nan")), str)
    assert isinstance(n.flatten_value(float("inf")), str)
    assert json.loads(json.dumps(n.flatten_parameters({"x": math.nan})))


def test_nested_containers_are_flattened_throughout():
    value = {"FIELDS": ["a", "b"], "NESTED": {"CRS": FakeCrs("EPSG:3857")}}
    assert n.flatten_value(value) == {"FIELDS": ["a", "b"], "NESTED": {"CRS": "EPSG:3857"}}


def test_tuples_and_sets_become_lists():
    assert n.flatten_value((1, 2)) == [1, 2]
    assert sorted(n.flatten_value({1, 2})) == [1, 2]


def test_a_crs_becomes_its_authid():
    """§5.7 — authid, not WKT, when there is one."""
    assert n.flatten_value(FakeCrs("EPSG:32643")) == "EPSG:32643"


def test_a_custom_crs_falls_back_to_wkt():
    """§5.7 — WKT only when the CRS has no authid."""
    assert n.flatten_value(FakeCrs("", "PROJCS[\"custom\"]")) == 'PROJCS["custom"]'


def test_a_property_holding_an_expression_becomes_the_expression():
    assert n.flatten_value(FakeProperty(expression='"pop" > 100')) == '"pop" > 100'


def test_a_property_holding_a_static_value_becomes_that_value():
    assert n.flatten_value(FakeProperty(static=500)) == 500


def test_a_feature_source_definition_unwraps_to_its_path():
    """This wrapper is the type PERSON_A.md §A4 names first."""
    assert n.flatten_value(FakeSourceDefinition("/data/roads.shp")) == "/data/roads.shp"


def test_an_output_layer_definition_unwraps_to_its_sink():
    assert n.flatten_value(FakeOutputDefinition("/out/buffered.shp")) == "/out/buffered.shp"


def test_an_unknown_object_falls_back_to_repr():
    """§5.5 — repr() rather than raising. The capture layer must never break
    the user's actual processing run."""

    class Mystery:
        def __repr__(self):
            return "<Mystery object>"

    assert n.flatten_value(Mystery()) == "<Mystery object>"


def test_an_object_that_raises_on_every_access_is_survived():
    assert n.flatten_value(Explosive()) == "<Explosive>"


def test_an_object_whose_repr_also_raises_is_survived():
    result = n.flatten_value(Unreprable())
    assert "unserialisable" in result


def test_deep_nesting_is_cut_off_rather_than_overflowing():
    deep = current = {}
    for _ in range(50):
        current["next"] = {}
        current = current["next"]
    assert json.dumps(n.flatten_value(deep))  # terminates and stays serialisable


def test_paths_and_bytes_are_handled():
    assert n.flatten_value(pathlib.Path("/data/roads.shp")) == "/data/roads.shp"
    assert n.flatten_value(b"roads") == "roads"


def test_flatten_parameters_always_returns_a_json_safe_dict():
    """§3.3 — Person B can rely on json.dumps(event) never raising."""
    flattened = n.flatten_parameters({
        "DISTANCE": 500,
        "CRS": FakeCrs("EPSG:4326"),
        "INPUT": FakeSourceDefinition("/data/roads.shp"),
        "BROKEN": Explosive(),
        7: "non-string key",
    })
    assert json.dumps(flattened)
    assert flattened["7"] == "non-string key"


def test_flatten_parameters_survives_not_being_given_a_dict():
    assert "_parameters" in n.flatten_parameters(["not", "a", "dict"])


# ===========================================================================
# §3.3 / §5.6 — paths
# ===========================================================================

@pytest.mark.parametrize("raw", [
    "memory:Buffered", "TEMPORARY_OUTPUT", "/vsimem/tmp.tif", "", "   ", None, "memory",
])
def test_layers_with_no_file_on_disk_resolve_to_none(raw):
    """§3.3 — Person B must not try to fingerprint these."""
    assert n.classify_path(raw) is None


def test_a_real_path_survives():
    assert n.classify_path("/data/roads.shp") == "/data/roads.shp"


def test_gdal_sublayer_selectors_are_stripped():
    """The file is what gets fingerprinted; the layer selector is not part of it."""
    assert n.classify_path("/data/city.gpkg|layername=roads") == "/data/city.gpkg"
    assert n.classify_path("/data/city.gpkg|layerid=0") == "/data/city.gpkg"


def test_an_unresolvable_reference_becomes_none_not_a_guess():
    """§5.6 — a made-up path would put a phantom file into Person C's graph."""
    assert n.classify_path(Explosive()) is None


# ===========================================================================
# describe_layer
# ===========================================================================

def test_a_vector_layer_is_described_from_the_object():
    entry = n.describe_layer("INPUT", FakeVectorLayer("/data/roads.shp", feature_count=1204))
    assert entry["param"] == "INPUT"
    assert entry["path"] == "/data/roads.shp"
    assert entry["crs"] == "EPSG:4326"
    assert entry["feature_count"] == 1204
    assert entry["layer_type"] == "vector"


def test_format_comes_from_the_driver_not_the_extension():
    """§5.8 [HARD] — a .gpkg can hold vector or raster, so the extension tells
    you nothing reliable."""
    raster_in_a_gpkg = FakeRasterLayer("/data/dem.gpkg", storage_type="GPKG")
    entry = n.describe_layer("INPUT", raster_in_a_gpkg)
    assert entry["format"] == "GPKG"
    assert entry["layer_type"] == "raster"


def test_a_memory_layer_keeps_its_type_but_loses_its_path():
    """§3.3 — the rule Person B hits first."""
    entry = n.describe_layer("OUTPUT", FakeVectorLayer("memory:Buffered", feature_count=8))
    assert entry["path"] is None
    assert entry["layer_type"] == "vector"


def test_a_plain_path_string_is_described_too():
    entry = n.describe_layer("OUTPUT", "/out/buffered.shp")
    assert entry["path"] == "/out/buffered.shp"
    assert entry["crs"] is None


def test_the_layer_name_is_never_mistaken_for_the_source():
    """FakeVectorLayer.name() returns a decoy. A layer has both source() and
    name(); picking the wrong one silently records the wrong file."""
    entry = n.describe_layer("INPUT", FakeVectorLayer("/data/roads.shp"))
    assert entry["path"] == "/data/roads.shp"


# ===========================================================================
# §5.9 — the dedup key both channels compute
# ===========================================================================

def test_the_same_execution_seen_milliseconds_apart_gets_one_key():
    """§5.9 — the two channels observe the same run microseconds apart, so an
    exact timestamp match would never fire and everything would double-insert."""
    params = {"DISTANCE": 500}
    first = n.dedup_key("native:buffer", params, "2026-08-08T10:14:22.400000+00:00")
    second = n.dedup_key("native:buffer", params, "2026-08-08T10:14:22.499999+00:00")
    assert first == second


def test_executions_in_different_buckets_get_different_keys():
    params = {"DISTANCE": 500}
    first = n.dedup_key("native:buffer", params, "2026-08-08T10:14:22.400000+00:00")
    second = n.dedup_key("native:buffer", params, "2026-08-08T10:14:22.600000+00:00")
    assert first != second


def test_different_parameters_get_different_keys():
    at = "2026-08-08T10:14:22.400000+00:00"
    assert n.dedup_key("native:buffer", {"DISTANCE": 500}, at) != \
           n.dedup_key("native:buffer", {"DISTANCE": 100}, at)


def test_parameter_order_does_not_change_the_key():
    at = "2026-08-08T10:14:22.400000+00:00"
    assert n.dedup_key("native:buffer", {"A": 1, "B": 2}, at) == \
           n.dedup_key("native:buffer", {"B": 2, "A": 1}, at)


def test_the_key_survives_unserialisable_parameters():
    """A dedup key that raises would take down capture on exactly the awkward
    parameters §5.5 exists to handle."""
    at = "2026-08-08T10:14:22.400000+00:00"
    assert n.dedup_key("native:buffer", {"BROKEN": Explosive()}, at)


def test_a_malformed_timestamp_does_not_break_the_key():
    assert n.dedup_key("native:buffer", {}, "not a timestamp")


# ===========================================================================
# §3.3 — layer parameters lifted out, scalars left behind
# ===========================================================================

def test_layer_parameters_are_lifted_and_scalars_stay():
    scalars, inputs, outputs = n.split_parameters(
        {"INPUT": "/data/roads.shp", "OUTPUT": "/out/buffered.shp",
         "DISTANCE": 500, "SEGMENTS": 5, "DISSOLVE": False},
        FakeAlgorithmDefinitions.BUFFER,
    )
    assert scalars == {"DISTANCE": 500, "SEGMENTS": 5, "DISSOLVE": False}
    assert [e["param"] for e in inputs] == ["INPUT"]
    assert [e["param"] for e in outputs] == ["OUTPUT"]


def test_an_unknown_parameter_is_treated_as_a_scalar_not_guessed_as_a_layer():
    """Guessing would put a made-up dataset into Person C's graph, which is
    worse than omitting it."""
    scalars, inputs, outputs = n.split_parameters(
        {"MYSTERY": "/looks/like/a/path.shp"}, {}
    )
    assert scalars == {"MYSTERY": "/looks/like/a/path.shp"}
    assert inputs == [] and outputs == []


def test_a_second_layer_input_such_as_overlay_is_lifted_too():
    _, inputs, _ = n.split_parameters(
        {"INPUT": "/data/roads.shp", "OVERLAY": "/data/city.shp"},
        FakeAlgorithmDefinitions.CLIP,
    )
    assert {e["param"] for e in inputs} == {"INPUT", "OVERLAY"}


# ===========================================================================
# §5.6 — results fill in what the parameters could not
# ===========================================================================

def test_the_written_path_beats_the_requested_placeholder():
    """The parameter said TEMPORARY_OUTPUT; results say where it actually went.
    results is the observation, the parameter was only the request."""
    _, _, outputs = n.split_parameters(
        {"OUTPUT": "TEMPORARY_OUTPUT"}, FakeAlgorithmDefinitions.BUFFER
    )
    assert outputs[0]["path"] is None

    merged = n.merge_results(outputs, {"OUTPUT": "/out/buffered.shp"},
                             FakeAlgorithmDefinitions.BUFFER)
    assert merged[0]["path"] == "/out/buffered.shp"


def test_a_layer_object_in_results_is_resolved(agent_block):
    """§5.6 — results may hand back a path, a layer id, or a layer object."""
    _, _, outputs = n.split_parameters({"OUTPUT": "TEMPORARY_OUTPUT"},
                                       FakeAlgorithmDefinitions.BUFFER)
    merged = n.merge_results(
        outputs, {"OUTPUT": FakeVectorLayer("/out/buffered.shp", feature_count=1204)},
        FakeAlgorithmDefinitions.BUFFER,
    )
    assert merged[0]["path"] == "/out/buffered.shp"
    assert merged[0]["feature_count"] == 1204


def test_a_scalar_result_is_not_recorded_as_a_dataset():
    """native:countpointsinpolygon and friends return numbers. A count is not
    a file, and inventing a node for it corrupts Person C's graph."""
    merged = n.merge_results([], {"CLUSTER_COUNT": 7},
                             {"CLUSTER_COUNT": "outputNumber"})
    assert merged == []


def test_an_undeclared_result_that_looks_like_a_file_is_kept():
    merged = n.merge_results([], {"EXTRA": "/out/extra.gpkg"}, {})
    assert [e["path"] for e in merged] == ["/out/extra.gpkg"]


# ===========================================================================
# the whole event
# ===========================================================================

def test_a_built_event_validates_against_the_frozen_schema(agent_block):
    """§3.1 — the normalizer's output is exactly what Person B consumes."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (pathlib.Path(__file__).resolve().parents[2] / "schemas" / "event.schema.json")
        .read_text()
    )

    event = n.build_event(
        algorithm_id="native:buffer",
        algorithm_name="Buffer",
        session_id="11111111-1111-4111-8111-111111111111",
        started_at="2026-08-08T10:14:22.481903+00:00",
        ended_at="2026-08-08T10:14:23.004117+00:00",
        agent=agent_block,
        parameters={"INPUT": FakeVectorLayer("/data/roads.shp", feature_count=1204),
                    "OUTPUT": "TEMPORARY_OUTPUT", "DISTANCE": 500, "DISSOLVE": False},
        parameter_definitions=FakeAlgorithmDefinitions.BUFFER,
        results={"OUTPUT": "/out/buffered.shp"},
    )

    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(event))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors]
    assert json.dumps(event)


def test_the_provider_is_inferred_from_the_algorithm_id(agent_block):
    event = n.build_event(
        algorithm_id="gdal:warpreproject", session_id="s", started_at="t",
        ended_at=None, agent=agent_block,
    )
    assert event["provider"] == "gdal"
